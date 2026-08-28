"""Assistant orchestration service for project-grounded and web-grounded chat."""

from __future__ import annotations

import html as html_module
import hashlib
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from fastapi import HTTPException

from app.core import llm_client
from app.core.config import settings
from app.core.llm_context import get_message_metadata
from app.core.logging import get_logger
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant import AssistantAction
from app.schemas.assistant import AssistantAnswerMode
from app.schemas.assistant import AssistantAnswerScope
from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant import AssistantChatResponse
from app.schemas.assistant import AssistantReference
from app.schemas.assistant import AssistantRetrievalStatus
from app.schemas.agent_tools import AgentTool, AssistantToolCall, AssistantToolCallCreate
from app.schemas.capabilities import CapabilityRelevanceAssessment
from app.services.agent_tool_service import agent_tool_service
from app.services.assistant_provider_errors import TOOL_ARGUMENTS_INVALID, classify_provider_error
from app.services.assistant_presets import (
    assistant_route_purpose,
    resolve_assistant_runtime,
)
from app.services.assistant_context_assembler import (
    AssistantContextAssembler,
    ContextAssembly,
    estimate_native_tool_schema_tokens,
)
from app.services.assistant_retrieval_telemetry import (
    knowledge_result_entries,
    mark_used_in_answer,
    retrieval_result_event,
    web_result_entries,
)
from app.services.assistant_tool_contract import (
    build_function_tool,
    normalize_provider_arguments,
    safe_function_name,
)
from app.services.assistant_tool_service import assistant_tool_call_service
from app.services.assistant_session_control import control_state
from app.services.capability_relevance_service import CapabilityRelevanceService
from app.services.integration_status_service import IntegrationStatusService
from app.services.knowledge_service import KnowledgeService
from app.services.llm_model_service import LLMModelService
from app.services.research_engine_defaults import DEFAULT_STAGE_SEQUENCE
from app.services.research_engine_defaults import P0_GATE_STAGES
from app.services.research_engine_service import ResearchEngineService


logger = get_logger("poly_agent.assistant")

SYSTEM_PROMPT = (
    "你是 PolyAgent 的产品内助手。优先使用给定 FACTS、KNOWLEDGE_EVIDENCE 和 WEB_EVIDENCE 回答，"
    "所有正常回答都要经过项目配置的 LLM 润色。"
    "项目内问题只依据项目事实；项目外问题必须结合网页证据；混合问题同时结合两者。"
    "当存在 KNOWLEDGE_EVIDENCE 时，应优先把它作为用户所选知识库的依据。"
    "知识库命中只作为回答依据，不要建议用户点击、预览或下载知识库 PDF 原文。"
    "如果事实和网页证据冲突，以项目事实为准，并明确说明冲突。"
    "不要编造算法、按钮、配置状态或外部资料。"
    "回答要简洁、可操作，必要时用要点列出依据。"
)

PROJECT_KEYWORDS = {
    "polyagent",
    "poly agent",
    "researchengine",
    "research engine",
    "autoresearch",
    "task center",
    "任务中心",
    "审批",
    "待审批",
    "blocked_approval",
    "研究引擎",
    "研发引擎",
    "计算",
    "computation",
    "xtb",
    "crest",
    "orca",
    "alchemist",
    "优化",
    "算法",
    "适配器",
    "知识库",
    "文献",
}
MODEL_KEYWORDS = {
    "llm",
    "model",
    "模型",
    "provider",
    "api key",
    "base url",
    "base_url",
    "prompt",
    "responses",
}
WEB_KEYWORDS = {
    "最新",
    "最近",
    "趋势",
    "实践",
    "对比",
    "benchmark",
    "agentic",
    "rag",
    "web search",
    "tool calling",
    "openai",
    "anthropic",
    "langchain",
    "mcp",
    "论文",
    "资料",
}


@dataclass(frozen=True)
class AssistantIntent:
    scope: AssistantAnswerScope
    use_web: bool
    deep: bool


@dataclass(frozen=True)
class WebEvidence:
    title: str
    url: str
    snippet: str
    content: str = ""
    source: str = "bing_rss"
    published_at: str | None = None


@dataclass(frozen=True)
class SearchQueryPlan:
    query: str
    original_query: str
    query_terms: list[str]
    dropped_terms: list[str]


@dataclass(frozen=True)
class SearchOutcome:
    status: AssistantRetrievalStatus
    provider: str
    query: str
    results: list[WebEvidence]
    original_query: str | None = None
    query_terms: list[str] | None = None
    dropped_terms: list[str] | None = None
    raw_result_count: int = 0
    filtered_result_count: int = 0


@dataclass(frozen=True)
class KnowledgeEvidence:
    title: str
    snippet: str
    source_id: str
    score: float = 0.0
    source: str | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class KnowledgeOutcome:
    status: AssistantRetrievalStatus
    provider: str
    system_id: str
    system_name: str
    query: str
    results: list[KnowledgeEvidence]
    error: str | None = None
    system_ids: list[str] = field(default_factory=list)
    system_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SynthesizedAnswer:
    content: str
    reasoning_summary: list[str]


class AssistantIntentRouter:
    """Route user questions to the right answer scope."""

    def route(self, text: str, *, mode: str) -> AssistantIntent:
        normalized = self._normalize(text)
        has_project = self._contains_any(normalized, PROJECT_KEYWORDS)
        has_model = self._contains_any(normalized, MODEL_KEYWORDS)
        has_web = self._contains_any(normalized, WEB_KEYWORDS) or self._looks_current(normalized)
        deep = mode == "deep"

        if has_model and not has_web and not has_project:
            return AssistantIntent(scope="model", use_web=False, deep=deep)
        if has_project and (has_web or self._looks_like_bridge_question(normalized)):
            return AssistantIntent(scope="hybrid", use_web=True, deep=deep)
        if has_project:
            if has_model and not has_web:
                return AssistantIntent(scope="model", use_web=False, deep=deep)
            return AssistantIntent(scope="project", use_web=False, deep=deep)
        if has_model:
            return AssistantIntent(scope="model", use_web=False, deep=deep)
        return AssistantIntent(scope="web", use_web=True, deep=deep)

    def _normalize(self, text: str) -> str:
        return str(text or "").strip().lower()

    def _contains_any(self, text: str, keywords: Iterable[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _looks_current(self, text: str) -> bool:
        return any(token in text for token in ("最新", "最近", "当前", "today", "latest", "recent", "2025", "2026"))

    def _looks_like_bridge_question(self, text: str) -> bool:
        return any(token in text for token in ("结合", "对比", "外部", "互联网", "web search", "agentic", "rag", "最新", "最近"))


class ProjectGroundingService:
    """Collect project facts from live services."""

    def build_facts(self, *, intent: AssistantIntent) -> dict:
        algorithms = self._safe_list_algorithms()
        integrations = self._safe_integration_status()
        model_facts = {
            "chat": {
                "configured": bool(settings.llm_model),
                "model": settings.llm_model or "未配置",
                "base_url_configured": bool(settings.llm_base_url),
                "provider": "LLM_*",
            },
            "report": {
                "provider": settings.report_llm_provider,
                "model": settings.report_llm_model or settings.llm_model or "未配置",
            },
        }
        try:
            llm_catalog = LLMModelService().get_catalog(probe=False).model_dump(mode="python")
        except Exception as exc:
            logger.warning("assistant llm catalog unavailable: %s", exc)
            llm_catalog = {"providers": [], "routing": {}, "warnings": [str(exc)]}

        production_adapters: list[dict] = []
        computation_adapters: list[dict] = []
        bridge_adapters: list[dict] = []
        demo_algorithms: list[dict] = []
        other_algorithms: list[dict] = []

        for item in algorithms:
            algorithm_id = item.get("algorithm_id", "")
            summary = self._algorithm_summary(item)
            if algorithm_id in {"weknora_adapter", "vertical_predictor_adapter", "mobo_alchemist_adapter"}:
                production_adapters.append(summary)
            elif algorithm_id in {"local_structure_adapter", "local_xtb_adapter", "orca_compute_engine_laser_adapter"}:
                computation_adapters.append(summary)
            elif algorithm_id == "computation_submit_adapter":
                bridge_adapters.append(summary)
            elif self._is_demo_algorithm(item):
                demo_algorithms.append(summary)
            else:
                other_algorithms.append(summary)

        return {
            "project": {
                "name": "Poly Agent",
                "assistant": "PolyAgent 产品内助手",
                "research_module": "ResearchEngine",
            },
            "assistant": {
                "intent_scope": intent.scope,
                "deep_mode": intent.deep,
            },
            "algorithm_registry": {
                "total": len(algorithms),
                "production_adapters": production_adapters,
                "computation_workflow_adapters": computation_adapters,
                "bridge_adapters": bridge_adapters,
                "demo_algorithms": demo_algorithms,
                "other_algorithms": other_algorithms,
            },
            "integration_status": integrations,
            "autoresearch": {
                "stage_sequence": list(DEFAULT_STAGE_SEQUENCE),
                "gate_stages": sorted(P0_GATE_STAGES),
                "approval_status": "blocked_approval",
                "approval_route": "/tasks/center?module_id=research-engine&status=blocked_approval",
                "guide": "ResearchRun 阶段时间线中出现 blocked_approval 时点击审批按钮，填写原因后批准或拒绝。",
            },
            "manuals": {
                "autoresearch": "doc/autoresearch-user-guide.md",
                "computation_workflows": "doc/computation-workflows-user-guide.md",
                "knowledge_base": "doc/knowledge-base-rag-kg-upgrade-plan.md",
            },
            "model_management": model_facts,
            "llm_catalog": llm_catalog,
        }

    def build_project_references(self, text: str) -> list[AssistantReference]:
        lowered = text.lower()
        refs: list[AssistantReference] = []
        if any(token in lowered for token in ("research", "autoresearch", "研发", "适配器", "算法")):
            refs.append(AssistantReference(label="ResearchEngine 算法清单", target="/research-engine", type="route"))
        if "autoresearch" in lowered or "审批" in text:
            refs.append(AssistantReference(label="AutoResearch 运行说明", target="doc/autoresearch-user-guide.md"))
        if "workflow" in lowered or "计算" in text:
            refs.append(AssistantReference(label="计算 Workflow 使用说明", target="doc/computation-workflows-user-guide.md"))
        if "知识库" in text or "rag" in lowered:
            refs.append(AssistantReference(label="知识库 RAG/KG 设计", target="doc/knowledge-base-rag-kg-upgrade-plan.md"))
        return refs

    def build_actions(self, text: str) -> list[AssistantAction]:
        lowered = text.lower()
        actions: list[AssistantAction] = []
        if "审批" in text or "待审批" in text or "autoresearch" in lowered:
            actions.append(
                AssistantAction(
                    label="查看待审批任务",
                    target="/tasks/center?module_id=research-engine&status=blocked_approval",
                    description="筛选 ResearchEngine 中等待 Gate 审批的 AutoResearch 运行。",
                )
            )
        if any(token in lowered for token in ("research", "autoresearch", "研发", "审批", "workflow")):
            actions.append(
                AssistantAction(
                    label="进入 ResearchEngine",
                    target="/research-engine",
                    description="定义 ProblemSpec、运行 Workflow 或处理 AutoResearch 审批。",
                )
            )
        if any(token in lowered for token in ("计算", "xtb", "orca", "dft", "computation")):
            actions.append(
                AssistantAction(
                    label="打开计算任务提交",
                    target="/computations/submit",
                    description="提交 LOCAL_STRUCTURE、LOCAL_XTB 或 ORCA 计算。",
                )
            )
        if any(token in lowered for token in ("alchemist", "贝叶斯", "优化", "mobo", "bo")):
            actions.append(
                AssistantAction(
                    label="查看 Alchemist",
                    target="/optimization/alchemist",
                    description="进入实验设计和贝叶斯优化工具。",
                )
            )
        if any(token in lowered for token in ("适配器", "算法", "registry", "algorithm")):
            actions.append(
                AssistantAction(
                    label="查看算法清单",
                    target="/research-engine",
                    description="在 ResearchEngine 的算法能力清单中查看真实注册条目和 Schema。",
                )
            )
        if any(token in lowered for token in ("llm", "模型", "provider", "base url", "api key")):
            actions.append(
                AssistantAction(
                    label="打开 LLM 模型管理",
                    target="/tools?tab=llm-models",
                    description="查看可选模型、能力标签、健康状态和默认路由。",
                )
            )
        if not actions and any(token in lowered for token in ("polyagent", "poly agent", "researchengine", "autoresearch", "任务中心")):
            actions.append(
                AssistantAction(
                    label="查看任务中心",
                    target="/tasks/center",
                    description="查看所有计算、优化和 ResearchEngine 任务状态。",
                )
            )
        return actions

    def build_suggested_questions(self, text: str, intent: AssistantIntent) -> list[str]:
        lowered = text.lower()
        if intent.scope == "model":
            return ["现在问答使用什么模型？", "问答和报告的模型配置有什么区别？", "如何切换 LLM provider？"]
        if "审批" in text or "autoresearch" in lowered:
            return ["如何批准 blocked_approval 阶段？", "AutoResearch 每个 Gate 会做什么？"]
        if "计算" in text or "xtb" in lowered or "orca" in lowered:
            return ["LOCAL_XTB 需要哪些输入？", "如何从 ResearchEngine 提交计算任务？"]
        if intent.scope == "web" or intent.scope == "hybrid":
            return ["给我整理成对比表。", "补充最新实践和局限。", "给出可直接落地的建议。"]
        return ["如何开始一个 ResearchEngine 示例？", "哪些算法是真实适配器？", "如何查看待审批任务？"]

    def _safe_list_algorithms(self) -> list[dict]:
        try:
            result = ResearchEngineService().list_algorithms(page=1, page_size=100)
            return [item.model_dump(mode="python") for item in result.items]
        except Exception as exc:
            logger.warning("assistant algorithm grounding unavailable: %s", exc)
            return []

    def _safe_integration_status(self) -> dict:
        try:
            items = IntegrationStatusService().get_status().get("items", [])
        except Exception as exc:
            logger.warning("assistant integration grounding unavailable: %s", exc)
            items = []
        wanted = {
            "rdkit",
            "openbabel",
            "xtb",
            "crest",
            "orca",
            "alchemist-backend",
            "computation-worker",
        }
        return {
            item.get("service"): {
                "status": item.get("status"),
                "details": item.get("details", {}),
            }
            for item in items
            if item.get("service") in wanted
        }

    def _algorithm_summary(self, item: dict) -> dict:
        return {
            "algorithm_id": item.get("algorithm_id", ""),
            "name": item.get("name", ""),
            "type": item.get("type", ""),
            "algorithm_family": item.get("algorithm_family", ""),
            "call_method": item.get("call_method", ""),
            "runtime_dependency": item.get("runtime_dependency", ""),
            "status": item.get("status", ""),
            "description": item.get("description", ""),
        }

    def _is_demo_algorithm(self, item: dict) -> bool:
        ui_hints = (item.get("input_schema") or {}).get("ui_hints") or {}
        algorithm_hint = ui_hints.get("_algorithm") or {}
        validation_metric = item.get("validation_metric") or {}
        return bool(
            algorithm_hint.get("hidden_by_default")
            or algorithm_hint.get("is_demo")
            or any(str(value).lower() == "mock" for value in validation_metric.values())
            or str(item.get("algorithm_id", "")).endswith("_mock")
        )

    def format_project_facts_for_prompt(self, facts: dict) -> str:
        registry = facts.get("algorithm_registry", {})
        sections = []
        for label, key in [
            ("真实/生产适配器", "production_adapters"),
            ("计算 workflow 适配器", "computation_workflow_adapters"),
            ("桥接适配器", "bridge_adapters"),
            ("演示 mock 算法", "demo_algorithms"),
        ]:
            values = registry.get(key, [])
            ids = ", ".join(item.get("algorithm_id", "") for item in values) or "无"
            sections.append(f"{label}: {ids}")
        sections.append(f"集成状态: {facts.get('integration_status', {})}")
        sections.append(f"AutoResearch: {facts.get('autoresearch', {})}")
        sections.append(f"模型管理: {facts.get('model_management', {})}")
        return "\n".join(sections)


class AssistantSearchQueryBuilder:
    """Build focused web search queries from natural-language questions."""

    CHINESE_DROP_TERMS = (
        "请问",
        "帮我",
        "我要",
        "我想",
        "怎么做",
        "结合",
        "如何",
        "怎么",
        "什么",
        "哪些",
        "一下",
        "一个",
        "一款",
        "一种",
        "这个",
        "那个",
        "问题",
        "搜索",
        "查询",
        "资料",
        "推荐",
        "方法",
        "最近",
        "最新",
        "当前",
        "实践有哪些",
        "有哪些",
        "做",
        "设计",
        "生成",
        "在线",
        "平台",
        "的",
        "了",
        "吗",
        "呢",
        "我",
    )
    ENGLISH_STOPWORDS = {
        "a",
        "an",
        "and",
        "are",
        "best",
        "can",
        "current",
        "design",
        "do",
        "does",
        "find",
        "for",
        "from",
        "help",
        "how",
        "latest",
        "me",
        "method",
        "methods",
        "new",
        "news",
        "of",
        "please",
        "practice",
        "practices",
        "recent",
        "search",
        "the",
        "to",
        "what",
        "which",
        "with",
    }
    CHINESE_DOMAIN_SYNONYMS = {
        "高耐热聚酰亚胺": ["polyimide", "high heat resistant", "high temperature", "synthesis", "preparation"],
        "新材料": ["new materials", "materials design", "materials discovery", "inverse design", "molecular design"],
        "材料设计": ["materials design", "new materials", "materials discovery", "inverse design", "molecular design"],
        "聚酰亚胺": ["polyimide"],
        "高分子": ["polymer", "macromolecule"],
        "分子设计": ["molecular design", "materials discovery"],
        "材料发现": ["materials discovery"],
        "高耐热": ["high heat resistant", "high temperature"],
        "耐热": ["heat resistant", "thermal stability"],
        "制备": ["合成", "synthesis", "preparation"],
        "合成": ["synthesis", "preparation"],
        "配方": ["formulation"],
        "工艺": ["process", "preparation"],
        "材料": ["material"],
    }
    PRESERVED_ENGLISH_PHRASES = (
        "Poly Agent",
        "AI agent",
        "Agentic RAG",
        "web search",
    )

    def build(self, text: str) -> SearchQueryPlan:
        original = str(text or "").strip()
        if not original:
            return SearchQueryPlan(query="", original_query="", query_terms=[], dropped_terms=[])

        dropped_terms = self._dropped_terms(original)
        cleaned = original
        for term in sorted(dropped_terms, key=len, reverse=True):
            cleaned = cleaned.replace(term, " ")
        cleaned = re.sub(r"[?？!！,，。；;：:()（）\[\]{}<>《》\"“”'‘’、]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        terms: list[str] = []
        for term, synonyms in self.CHINESE_DOMAIN_SYNONYMS.items():
            if term in original:
                if term not in self.CHINESE_DROP_TERMS:
                    self._append_unique(terms, term)
                for synonym in synonyms:
                    self._append_unique(terms, synonym)

        covered_english_words: set[str] = set()
        lowered_original = original.lower()
        for phrase in self.PRESERVED_ENGLISH_PHRASES:
            if phrase.lower() in lowered_original:
                self._append_unique(terms, phrase)
                covered_english_words.update(self._english_words(phrase))

        for phrase in self._english_phrases(cleaned):
            if self._english_words(phrase).issubset(covered_english_words):
                continue
            self._append_unique(terms, phrase)
        for phrase in self._english_phrases(original):
            if self._english_words(phrase).issubset(covered_english_words):
                continue
            self._append_unique(terms, phrase)

        for item in re.findall(r"[\u4e00-\u9fff]{2,}", cleaned):
            if item not in self.CHINESE_DROP_TERMS:
                self._append_unique(terms, item)

        query = " ".join(terms).strip() or cleaned or original
        query_terms = self._query_terms_from_values(terms) if terms else self._query_terms(query)
        return SearchQueryPlan(
            query=query,
            original_query=original,
            query_terms=query_terms,
            dropped_terms=dropped_terms,
        )

    def _dropped_terms(self, text: str) -> list[str]:
        return [term for term in self.CHINESE_DROP_TERMS if term in text]

    def _english_phrases(self, text: str) -> list[str]:
        phrases: list[str] = []
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9+.-]*(?:\s+[A-Za-z][A-Za-z0-9+.-]*)*", text):
            words = [word for word in match.group(0).split() if word.lower() not in self.ENGLISH_STOPWORDS]
            if not words:
                continue
            if len(words) == 1:
                phrases.append(words[0])
            else:
                phrases.append(" ".join(words))
                phrases.extend(words)
        return phrases

    def _query_terms(self, text: str) -> list[str]:
        terms: list[str] = []
        for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{1,}", text.lower()):
            if item not in self.ENGLISH_STOPWORDS:
                self._append_unique(terms, item)
        for item in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            if item not in self.CHINESE_DROP_TERMS:
                self._append_unique(terms, item)
        return terms

    def _query_terms_from_values(self, values: list[str]) -> list[str]:
        terms: list[str] = []
        for value in values:
            normalized = re.sub(r"\s+", " ", str(value or "").strip())
            if not normalized:
                continue
            if " " in normalized:
                self._append_unique(terms, normalized.lower())
            for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{1,}", normalized.lower()):
                if item not in self.ENGLISH_STOPWORDS:
                    self._append_unique(terms, item)
            for item in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
                if item not in self.CHINESE_DROP_TERMS:
                    self._append_unique(terms, item)
        return terms

    def _english_words(self, text: str) -> set[str]:
        return {
            item
            for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{1,}", text.lower())
            if item not in self.ENGLISH_STOPWORDS
        }

    def _append_unique(self, values: list[str], value: str) -> None:
        normalized = re.sub(r"\s+", " ", str(value or "").strip())
        if normalized and normalized not in values:
            values.append(normalized)


class AssistantWebSearchService:
    """Search the web using configured HTTP provider or RSS fallback."""

    GENERIC_RELEVANCE_TERMS = {
        "设计",
        "生成",
        "在线",
        "平台",
        "图片",
        "海报",
        "素材",
        "推荐",
        "搜索",
        "查询",
        "资料",
        "方法",
        "问题",
        "实践",
        "最新",
        "最近",
        "当前",
        "new",
        "news",
        "design",
        "method",
        "methods",
        "材料",
        "分子",
        "molecule",
        "material",
        "materials",
        "current",
        "latest",
        "practice",
        "practices",
        "recent",
        "search",
    }

    def search(self, query: str, *, deep: bool) -> SearchOutcome:
        query_plan = AssistantSearchQueryBuilder().build(query)
        focused_query = query_plan.query or query
        if not settings.assistant_web_search_enabled:
            return SearchOutcome(
                status="skipped_disabled",
                provider="disabled",
                query=focused_query,
                results=[],
                original_query=query_plan.original_query,
                query_terms=query_plan.query_terms,
                dropped_terms=query_plan.dropped_terms,
            )

        max_results = settings.assistant_web_search_max_results + (4 if deep else 0)
        max_pages = settings.assistant_web_fetch_max_pages + (2 if deep else 0)
        provider = settings.assistant_web_search_provider

        try:
            if provider == "searxng" and settings.assistant_web_search_endpoint:
                raw_results = self._search_via_searxng(focused_query, max_results=max_results)
                provider_name = "searxng"
            else:
                raw_results = self._search_via_bing_rss(focused_query, max_results=max_results)
                provider_name = "bing_rss"
        except Exception as exc:
            logger.warning("assistant web search failed for provider=%s: %s", provider, exc)
            if provider != "bing_rss":
                try:
                    raw_results = self._search_via_bing_rss(focused_query, max_results=max_results)
                    provider_name = "bing_rss"
                except Exception as fallback_exc:
                    logger.warning("assistant web search fallback failed: %s", fallback_exc)
                    return SearchOutcome(
                        status="failed",
                        provider=provider,
                        query=focused_query,
                        results=[],
                        original_query=query_plan.original_query,
                        query_terms=query_plan.query_terms,
                        dropped_terms=query_plan.dropped_terms,
                    )
            else:
                return SearchOutcome(
                    status="failed",
                    provider=provider,
                    query=focused_query,
                    results=[],
                    original_query=query_plan.original_query,
                    query_terms=query_plan.query_terms,
                    dropped_terms=query_plan.dropped_terms,
                )

        if not raw_results:
            fallback = self._fallback_search(
                query_plan,
                provider=provider,
                max_results=max_results,
            )
            if fallback:
                focused_query, raw_results, provider_name = fallback
            else:
                return SearchOutcome(
                    status="no_results",
                    provider=provider_name,
                    query=focused_query,
                    results=[],
                    original_query=query_plan.original_query,
                    query_terms=query_plan.query_terms,
                    dropped_terms=query_plan.dropped_terms,
                    raw_result_count=0,
                    filtered_result_count=0,
                )

        candidates = self._filter_results(raw_results, query_plan.query_terms, include_content=False)
        if not candidates:
            fallback = self._fallback_search(
                query_plan,
                provider=provider,
                max_results=max_results,
            )
            if fallback:
                fallback_query, fallback_raw_results, fallback_provider_name = fallback
                fallback_candidates = self._filter_results(
                    fallback_raw_results,
                    query_plan.query_terms,
                    include_content=False,
                )
                if fallback_candidates:
                    focused_query = fallback_query
                    raw_results = fallback_raw_results
                    candidates = fallback_candidates
                    provider_name = fallback_provider_name

        if not candidates:
            curated_results = self._curated_fallback_results(query_plan)
            if curated_results:
                focused_query = query_plan.query or focused_query
                raw_results = curated_results
                candidates = curated_results
                provider_name = "curated_material_design"

        if not candidates:
            return SearchOutcome(
                status="no_results",
                provider=provider_name,
                query=focused_query,
                results=[],
                original_query=query_plan.original_query,
                query_terms=query_plan.query_terms,
                dropped_terms=query_plan.dropped_terms,
                raw_result_count=len(raw_results),
                filtered_result_count=0,
            )
        results: list[WebEvidence] = []
        for index, item in enumerate(candidates[:max_results]):
            content = ""
            if index < max_pages:
                content = self._fetch_page_text(item.url)
            results.append(
                WebEvidence(
                    title=item.title,
                    url=item.url,
                    snippet=item.snippet,
                    content=content,
                    source=provider_name,
                    published_at=item.published_at,
                )
            )
        results = self._filter_results(results, query_plan.query_terms, include_content=True)
        if not results:
            return SearchOutcome(
                status="no_results",
                provider=provider_name,
                query=focused_query,
                results=[],
                original_query=query_plan.original_query,
                query_terms=query_plan.query_terms,
                dropped_terms=query_plan.dropped_terms,
                raw_result_count=len(raw_results),
                filtered_result_count=0,
            )
        return SearchOutcome(
            status="searched",
            provider=provider_name,
            query=focused_query,
            results=results,
            original_query=query_plan.original_query,
            query_terms=query_plan.query_terms,
            dropped_terms=query_plan.dropped_terms,
            raw_result_count=len(raw_results),
            filtered_result_count=len(results),
        )

    def _fallback_search(
        self,
        query_plan: SearchQueryPlan,
        *,
        provider: str,
        max_results: int,
    ) -> tuple[str, list[WebEvidence], str] | None:
        for fallback_query in self._fallback_queries(query_plan):
            try:
                if provider == "searxng" and settings.assistant_web_search_endpoint:
                    raw_results = self._search_via_searxng(fallback_query, max_results=max_results)
                    provider_name = "searxng"
                else:
                    raw_results = self._search_via_bing_rss(fallback_query, max_results=max_results)
                    provider_name = "bing_rss"
            except Exception as exc:
                logger.debug("assistant fallback web search failed for query=%s: %s", fallback_query, exc)
                continue
            if raw_results:
                return fallback_query, raw_results, provider_name
        return None

    def _fallback_queries(self, query_plan: SearchQueryPlan) -> list[str]:
        if not self._is_material_design_query(query_plan):
            return []
        return [
            "materials design new materials inverse design materials discovery",
            '"materials design" "new materials" "inverse design"',
            "computational materials design materials discovery review",
        ]

    def _curated_fallback_results(self, query_plan: SearchQueryPlan) -> list[WebEvidence]:
        if not self._is_material_design_query(query_plan):
            return []
        return [
            WebEvidence(
                title="Materials Project",
                url="https://next-gen.materialsproject.org/",
                snippet="Open materials database for exploring computed structures and properties in materials discovery workflows.",
                source="curated_material_design",
            ),
            WebEvidence(
                title="Matminer",
                url="https://hackingmaterials.lbl.gov/matminer/",
                snippet="Python library for data mining and machine learning on materials data, including featurization for materials design.",
                source="curated_material_design",
            ),
            WebEvidence(
                title="Materials Project API documentation",
                url="https://docs.materialsproject.org/",
                snippet="Documentation for programmatic access to Materials Project data for computational materials screening.",
                source="curated_material_design",
            ),
        ]

    def _is_material_design_query(self, query_plan: SearchQueryPlan) -> bool:
        text = f"{query_plan.original_query} {query_plan.query}".lower()
        terms = set(query_plan.query_terms or [])
        return (
            "新材料" in text
            or "材料设计" in text
            or "new materials" in terms
            or "materials design" in terms
            or "materials discovery" in terms
        )

    def _search_via_searxng(self, query: str, *, max_results: int) -> list[WebEvidence]:
        endpoint = settings.assistant_web_search_endpoint.rstrip("/")
        url = f"{endpoint}/search" if not endpoint.endswith("/search") else endpoint
        params = {
            "q": query,
            "format": "json",
            "language": "zh-CN",
            "categories": "general",
        }
        headers = {}
        if settings.assistant_web_search_api_key:
            headers["Authorization"] = f"Bearer {settings.assistant_web_search_api_key}"
        with httpx.Client(timeout=settings.assistant_web_search_timeout_seconds, headers=headers) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
        payload = response.json()
        raw_items = payload.get("results") or payload.get("items") or []
        results: list[WebEvidence] = []
        for item in raw_items[:max_results]:
            title = str(item.get("title") or item.get("name") or query).strip()
            link = str(item.get("url") or item.get("link") or "").strip()
            snippet = str(item.get("content") or item.get("snippet") or item.get("description") or "").strip()
            if title and link:
                results.append(WebEvidence(title=title, url=link, snippet=snippet, source="searxng"))
        return results

    def _search_via_bing_rss(self, query: str, *, max_results: int) -> list[WebEvidence]:
        url = f"https://www.bing.com/search?format=rss&q={quote_plus(query)}"
        with httpx.Client(timeout=settings.assistant_web_search_timeout_seconds, headers=self._search_headers()) as client:
            response = client.get(url)
            response.raise_for_status()
        root = ET.fromstring(response.text)
        results: list[WebEvidence] = []
        for item in root.findall("./channel/item")[:max_results]:
            title = self._xml_text(item, "title")
            link = self._xml_text(item, "link")
            snippet = self._xml_text(item, "description")
            pub_date = self._xml_text(item, "pubDate") or None
            if title and link:
                results.append(
                    WebEvidence(
                        title=title,
                        url=link,
                        snippet=self._clean_snippet(snippet),
                        source="bing_rss",
                        published_at=pub_date,
                    )
                )
        return results

    def _fetch_page_text(self, url: str) -> str:
        if not self._is_safe_http_url(url):
            return ""
        headers = self._search_headers()
        try:
            with httpx.Client(timeout=settings.assistant_web_search_timeout_seconds, headers=headers, follow_redirects=False) as client:
                current_url = url
                for _ in range(3):
                    response = client.get(current_url)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        next_url = response.headers.get("location")
                        if not next_url:
                            break
                        current_url = urljoin(str(response.url), next_url)
                        if not self._is_safe_http_url(current_url):
                            return ""
                        continue
                    if response.status_code >= 400:
                        return ""
                    raw = response.content[: settings.assistant_web_fetch_max_bytes]
                    return self._strip_html(raw.decode(response.encoding or "utf-8", errors="ignore"))
        except httpx.HTTPError as exc:
            logger.debug("assistant web page fetch skipped for %s: %s", url, exc)
        return ""

    def _search_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _is_safe_http_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = parsed.hostname
        if not host:
            return False
        normalized = host.lower()
        if normalized in {"localhost", "127.0.0.1", "::1"} or normalized.endswith(".localhost"):
            return False
        if settings.assistant_web_allowed_domains and not self._host_matches_any(normalized, settings.assistant_web_allowed_domains):
            return False
        if self._host_matches_any(normalized, settings.assistant_web_blocked_domains):
            return False
        return self._host_is_public(normalized)

    def _host_matches_any(self, host: str, patterns: Iterable[str]) -> bool:
        for pattern in patterns:
            normalized = pattern.lower().strip()
            if not normalized:
                continue
            if host == normalized or host.endswith(f".{normalized}"):
                return True
        return False

    @lru_cache(maxsize=256)
    def _host_is_public(self, host: str) -> bool:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        for info in infos:
            ip_text = info[4][0]
            try:
                ip = ipaddress.ip_address(ip_text)
            except ValueError:
                return False
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return False
        return True

    def _strip_html(self, raw_html: str) -> str:
        cleaned = re.sub(r"(?is)<(script|style|noscript|iframe)[^>]*>.*?</\1>", " ", raw_html)
        cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
        cleaned = html_module.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:4000]

    def _xml_text(self, item: ET.Element, tag: str) -> str:
        value = item.findtext(tag) or ""
        return html_module.unescape(value).strip()

    def _clean_snippet(self, text: str) -> str:
        return re.sub(r"\s+", " ", html_module.unescape(text or "")).strip()

    def _filter_results(
        self,
        results: list[WebEvidence],
        query_terms: list[str] | None,
        *,
        include_content: bool,
    ) -> list[WebEvidence]:
        specific_terms = self._specific_query_terms(query_terms or [])
        if not specific_terms:
            return results
        scored = [
            (self._result_relevance_score(item, specific_terms, include_content=include_content), index, item)
            for index, item in enumerate(results)
        ]
        filtered = [(score, index, item) for score, index, item in scored if score > 0]
        filtered.sort(key=lambda value: (-value[0], value[1]))
        return [item for _, _, item in filtered]

    def _result_relevance_score(self, item: WebEvidence, query_terms: list[str], *, include_content: bool) -> int:
        title_snippet = f"{item.title} {item.snippet}"
        text = title_snippet
        if include_content:
            text = f"{text} {item.content}"
        normalized_title_snippet = title_snippet.lower()
        normalized = text.lower()
        score = 0
        for term in query_terms:
            candidate = term.strip().lower()
            if len(candidate) < 2 or candidate in self.GENERIC_RELEVANCE_TERMS:
                continue
            weight = 4 if " " in candidate else 2
            if len(candidate) >= 5:
                weight += 1
            if candidate in normalized_title_snippet:
                score += weight + 2
                continue
            if candidate in normalized:
                score += max(1, weight - 1)
                continue
            if re.search(rf"\b{re.escape(candidate)}\b", normalized):
                score += 1
        return score

    def _specific_query_terms(self, query_terms: list[str]) -> list[str]:
        specific: list[str] = []
        for term in query_terms:
            candidate = re.sub(r"\s+", " ", str(term or "").strip().lower())
            if not candidate or candidate in self.GENERIC_RELEVANCE_TERMS:
                continue
            specific.append(candidate)
        return specific


class AssistantAnswerSynthesizer:
    """Call the project-configured LLM to produce the final answer."""

    def synthesize(
        self,
        *,
        request: AssistantChatRequest,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
        llm_route: dict,
        extra_messages: list[dict] | None = None,
        context_assembly: ContextAssembly | None = None,
    ) -> SynthesizedAnswer:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": self._render_context(
                    context_assembly,
                    intent=intent,
                    facts=facts,
                    knowledge=knowledge,
                    evidence=evidence,
                ),
            },
        ]
        if intent.deep:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "DEEP_RESPONSE_FORMAT: Return only a JSON object with keys "
                        "`answer_markdown` and `reasoning_summary`. "
                        "`answer_markdown` is the final user-facing answer in Markdown. "
                        "`reasoning_summary` is an array of 2-5 short, high-level reasoning steps, "
                        "evidence checks, or decision criteria. Do not reveal hidden chain-of-thought, "
                        "private scratchpad, token-by-token reasoning, or internal deliberation."
                    ),
                }
            )
        if extra_messages:
            messages.extend(extra_messages)
        messages.extend({"role": item.role, "content": item.content} for item in request.messages)
        content = llm_client.chat(
            messages,
            temperature=0.2,
            purpose="deep" if intent.deep else "qa",
            provider_id=llm_route.get("provider_id"),
            model=llm_route.get("model_id"),
        )
        if intent.deep:
            return self._parse_deep_response(content)
        return SynthesizedAnswer(content=content, reasoning_summary=[])

    def stream_answer(
        self,
        *,
        request: AssistantChatRequest,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
        llm_route: dict,
        extra_messages: list[dict] | None = None,
        context_assembly: ContextAssembly | None = None,
    ) -> Iterator[str]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": self._render_context(
                    context_assembly,
                    intent=intent,
                    facts=facts,
                    knowledge=knowledge,
                    evidence=evidence,
                ),
            },
        ]
        if intent.deep:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "DEEP_STREAM_RESPONSE_FORMAT: Return the final user-facing answer directly in Markdown. "
                        "Do not return JSON. The application will show separate high-level reasoning summary events. "
                        "Do not reveal hidden chain-of-thought, private scratchpad, token-by-token reasoning, "
                        "or internal deliberation."
                    ),
                }
            )
        if extra_messages:
            messages.extend(extra_messages)
        messages.extend({"role": item.role, "content": item.content} for item in request.messages)
        yield from llm_client.chat_stream(
            messages,
            temperature=0.2,
            purpose="deep" if intent.deep else "qa",
            provider_id=llm_route.get("provider_id"),
            model=llm_route.get("model_id"),
        )

    def tool_call_messages(
        self,
        *,
        request: AssistantChatRequest,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
        extra_messages: list[dict] | None = None,
        context_assembly: ContextAssembly | None = None,
        max_parallel_tool_calls: int = 1,
    ) -> list[dict]:
        """构建用于工具提议的模型消息，包含项目事实与工具使用规则。"""
        parallel_rule = (
            f"当前产品最多允许提出 {max_parallel_tool_calls} 个最必要的算法调用；"
            "只有多个独立算法都对当前回答有明确收益时才并行提出。"
            if max_parallel_tool_calls > 1
            else "当前产品一次只提出一个最必要的算法调用。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": self._render_context(
                    context_assembly,
                    intent=intent,
                    facts=facts,
                    knowledge=knowledge,
                    evidence=evidence,
                ),
            },
            {
                "role": "system",
                "content": (
                    "TOOL_USE_RULES: 只有用户明确请求运行某个已启用算法、或回答需要算法计算/预测结果时，"
                    f"才发起算法工具调用；其余情况直接回答。{parallel_rule}"
                    "不要把文件路径、密钥或内部字段放入参数。"
                ),
            },
        ]
        if extra_messages:
            messages.extend(extra_messages)
        messages.extend({"role": item.role, "content": item.content} for item in request.messages)
        return messages

    @staticmethod
    def _render_context(
        assembly: ContextAssembly | None,
        *,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
    ) -> str:
        """渲染预算化上下文；旧调用路径保留原有上下文格式。"""
        if assembly is not None:
            return assembly.rendered
        return AssistantAnswerSynthesizer._build_context_block(
            intent=intent,
            facts=facts,
            knowledge=knowledge,
            evidence=evidence,
        )

    def _parse_deep_response(self, raw_content: str) -> SynthesizedAnswer:
        content = str(raw_content or "").strip()
        try:
            payload = json.loads(self._strip_json_fence(content))
        except (TypeError, ValueError, json.JSONDecodeError):
            return SynthesizedAnswer(content=content, reasoning_summary=[])
        if not isinstance(payload, dict):
            return SynthesizedAnswer(content=content, reasoning_summary=[])

        answer = str(payload.get("answer_markdown") or payload.get("content") or "").strip() or content
        raw_summary = payload.get("reasoning_summary") or []
        if not isinstance(raw_summary, list):
            raw_summary = []
        summary = [str(item).strip() for item in raw_summary if str(item).strip()]
        return SynthesizedAnswer(content=answer, reasoning_summary=summary[:5])

    def _strip_json_fence(self, content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _build_context_block(
        self,
        *,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
    ) -> str:
        sections = [
            f"ANSWER_SCOPE: {intent.scope}",
            f"DEEP_MODE: {intent.deep}",
            "FACTS:",
            self._format_facts(facts),
        ]
        if knowledge and knowledge.results:
            sections.append("KNOWLEDGE_EVIDENCE:")
            for index, item in enumerate(knowledge.results, start=1):
                sections.append(
                    f"[K{index}] {item.title}\n"
                    f"SOURCE_ID: {item.source_id}\n"
                    f"SCORE: {item.score:.4f}\n"
                    f"SNIPPET: {item.snippet[:1400]}"
                )
        else:
            sections.append(f"KNOWLEDGE_EVIDENCE: {knowledge.status if knowledge else 'not_needed'}")
        if evidence and evidence.results:
            sections.append("WEB_EVIDENCE:")
            for index, item in enumerate(evidence.results, start=1):
                sections.append(
                    f"[{index}] {item.title}\nURL: {item.url}\nSNIPPET: {item.snippet}\nCONTENT: {item.content[:1200]}"
                )
        else:
            sections.append(f"WEB_EVIDENCE: {evidence.status if evidence else 'not_needed'}")
        sections.append(
            "RESPONSE RULES: 先给结论，再给依据，最后给可执行建议；"
            "知识库证据用 [K1] [K2] 引用，网页证据用 [1] [2] 引用；"
            "不要引导用户点击、预览或下载知识库 PDF。"
        )
        return "\n".join(sections)

    def _format_facts(self, facts: dict) -> str:
        return json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True)


class AssistantService:
    """High-level orchestration for assistant chat."""

    def __init__(self) -> None:
        self.intent_router = AssistantIntentRouter()
        self.project_service = ProjectGroundingService()
        self.search_query_builder = AssistantSearchQueryBuilder()
        self.web_service = AssistantWebSearchService()
        self.knowledge_service = KnowledgeService()
        self.answer_synthesizer = AssistantAnswerSynthesizer()
        self.llm_model_service = LLMModelService()
        self.context_assembler = AssistantContextAssembler()
        self.capability_relevance_service = CapabilityRelevanceService()

    # ── 算法工具编排 ──

    @staticmethod
    def _tool_actor_context(current_user: dict | None) -> tuple[str, str, bool]:
        if current_user is None:
            return "demo_user", "admin", True
        role = current_user.get("role", "user")
        return current_user.get("user_id", ""), role, role == "admin"

    @staticmethod
    def _safe_tool_name(tool_id: str) -> str:
        return safe_function_name(tool_id)

    def _build_function_tools(
        self,
        selected_tool_ids: list[str],
        current_user: dict | None,
    ) -> tuple[list[dict], dict[str, AgentTool]]:
        """把当前用户可调用的已选算法转为 function schema，并记录安全名到 tool_id 的映射。"""
        user_id, role, is_admin = self._tool_actor_context(current_user)
        tools: list[dict] = []
        name_map: dict[str, AgentTool] = {}
        for tool_id in selected_tool_ids or []:
            if not isinstance(tool_id, str) or not tool_id.startswith("algorithm:"):
                continue
            algorithm_id = tool_id.removeprefix("algorithm:")
            tool = agent_tool_service.resolve_callable(
                algorithm_id,
                user_id=user_id,
                role=role,
                is_admin=is_admin,
            )
            if tool is None:
                continue
            function_tool = build_function_tool(tool)
            tools.append(function_tool)
            name_map[function_tool["function"]["name"]] = tool
        return tools, name_map

    @classmethod
    def _function_schema(cls, tool: AgentTool) -> dict:
        """保留旧调用入口，统一委托给 Tool Contract Adapter。"""
        return build_function_tool(tool)

    def _assemble_context(
        self,
        *,
        request_kind: str,
        request: AssistantChatRequest,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
        llm_route: dict,
        selected_tools: list[AgentTool] | None = None,
        prior_tool_messages: list[dict] | None = None,
    ) -> ContextAssembly:
        """构造一次模型请求的预算化上下文。"""
        safe_route = self._safe_llm_route(llm_route)
        native_tool_schema_tokens = 0
        if request_kind == "tool_proposal" and selected_tools:
            native_tool_schema_tokens = estimate_native_tool_schema_tokens(selected_tools)
        session_state = request.context.get("session_state")
        chat_id = str(request.context.get("chat_id") or "")
        if session_state is None and chat_id:
            chat = AssistantChatRepository.find_one({"chat_id": chat_id})
            session_state = control_state(chat or {}).model_dump(mode="python") if chat else None
        return self.context_assembler.assemble(
            request_kind=request_kind,
            intent_scope=intent.scope,
            deep=intent.deep,
            facts=facts,
            route=safe_route,
            selected_tools=selected_tools or [],
            knowledge_evidence=self._knowledge_context_items(knowledge),
            web_evidence=self._web_context_items(evidence),
            prior_tool_messages=prior_tool_messages or [],
            native_tool_schema_tokens=native_tool_schema_tokens,
            chars_per_token=float(safe_route.get("token_estimate_chars_per_token") or 4),
            allow_section_truncation=True,
            session_state=session_state,
        )

    def _context_event(
        self,
        *,
        request: AssistantChatRequest,
        request_kind: str,
        route: dict,
        assembly: ContextAssembly,
        tools: list[AgentTool],
    ) -> dict:
        """构造可持久化的 request manifest 事件。"""
        manifest = self.context_assembler.build_manifest(
            run_id=request.context.get("run_id"),
            request_kind=request_kind,
            route=route,
            assembly=assembly,
            tools=tools,
        )
        return {"type": "context.assembled", "request_kind": request_kind, "manifest": manifest}

    @staticmethod
    def _request_header_event(context_event: dict) -> dict:
        """从 request manifest 构造统一事件流的请求头事件。"""
        return {
            "type": "request.header",
            "request_kind": context_event.get("request_kind"),
            "manifest": context_event.get("manifest"),
        }

    @staticmethod
    def _context_metadata(assembly: ContextAssembly) -> dict:
        """提取响应和消息 metadata 所需的上下文摘要。"""
        return {
            "digest": assembly.digest,
            "token_estimate": assembly.token_estimate,
            "sections": [
                {
                    "name": section.name,
                    "source": section.source,
                    "digest": section.digest,
                    "token_estimate": section.token_estimate,
                    "included": section.included,
                    "omitted_reason": section.omitted_reason,
                }
                for section in assembly.sections
            ],
        }

    def _tool_source_context(
        self,
        *,
        request: AssistantChatRequest,
        llm_route: dict,
        assembly: ContextAssembly,
        selected_tool_ids: list[str],
        capability_relevance: CapabilityRelevanceAssessment | None = None,
    ) -> dict:
        """构造工具调用的可续答来源快照。

        Args:
            request: 触发工具提案的 assistant 请求。
            llm_route: 当前解析后的模型路由。
            assembly: 工具提案请求的上下文装配结果。
            selected_tool_ids: 用户已选择的算法工具。
            capability_relevance: 能力相关性评估结果。

        Returns:
            不包含消息正文与凭据的安全上下文快照。
        """
        context = request.context or {}
        requested_provider_id, requested_model_id = self._requested_model_identifiers(context.get("model"))
        preset_id, _compatibility_mode = resolve_assistant_runtime(
            context.get("preset_id"),
            context.get("mode"),
        )
        return {
            "trace_id": context.get("trace_id") or context.get("run_id"),
            "original_user_message_id": context.get("message_id"),
            "chat_id": context.get("chat_id"),
            "selected_tool_ids": list(selected_tool_ids or []),
            "preset_id": preset_id,
            "mode": context.get("mode") or "qa",
            "model_request": (
                {"providerId": requested_provider_id, "modelId": requested_model_id}
                if requested_provider_id or requested_model_id
                else {}
            ),
            "route_snapshot": self._safe_llm_route(llm_route),
            "context_manifest_digest": assembly.digest,
            "capability_relevance": (
                {
                    "selection_mode": capability_relevance.selection_mode,
                    "selected_capability_ids": capability_relevance.selected_capability_ids,
                    "omitted_capability_ids": capability_relevance.omitted_capability_ids,
                    "token_budget_used": capability_relevance.token_budget_used,
                    "token_budget_limit": capability_relevance.token_budget_limit,
                }
                if capability_relevance
                else {}
            ),
        }

    @staticmethod
    def _short_digest(value: str) -> str:
        """生成可用于事件关联且不保存原文的短摘要。"""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _truncate_result_summary(summary: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
        """压缩超大工具结果，避免续答请求超出上下文预算。"""
        if not isinstance(summary, dict) or not summary:
            return {}
        serialized = json.dumps(summary, ensure_ascii=False, default=str)
        if len(serialized) <= max_chars:
            return summary
        compact: dict[str, Any] = {}
        per_value = max(80, max_chars // max(1, len(summary)))
        for key, value in summary.items():
            if isinstance(value, str):
                compact[key] = value[:per_value]
            elif isinstance(value, (int, float, bool)) or value is None:
                compact[key] = value
            elif isinstance(value, list):
                compact[key] = value[:5]
            else:
                compact[key] = str(value)[:200]
        compact["_truncated"] = True
        return compact

    @classmethod
    def _continuation_tool_payload(cls, call: AssistantToolCall) -> dict[str, Any]:
        """生成续答使用的结构化工具结果，并做字符预算截断。"""
        max_chars = 12_000
        if call.phase == "completed":
            artifact_refs = (call.artifact_refs or [])[:20]
            payload: dict[str, Any] = {
                "status": "completed",
                "run_id": call.run_id,
                "result_summary": cls._truncate_result_summary(
                    call.result_summary or {},
                    max_chars=max_chars // 2,
                ),
                "artifact_refs": artifact_refs,
            }
        else:
            error = call.error or {}
            payload = {
                "status": "failed",
                "error": error,
                "result_summary": {},
                "suggested_next_step": "请根据错误信息调整输入或到算法运行详情页排查后重试。",
            }
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        if len(serialized) <= max_chars:
            return payload
        return {
            "status": payload["status"],
            "run_id": payload.get("run_id"),
            "result_summary": {"_truncated": True, "note": "工具结果过大，请查看算法运行详情"},
            "artifact_refs": (payload.get("artifact_refs") or [])[:5],
            "error": payload.get("error") if isinstance(payload.get("error"), dict) else {},
            "suggested_next_step": payload.get("suggested_next_step"),
        }

    @staticmethod
    def _knowledge_context_items(outcome: KnowledgeOutcome | None) -> list[dict]:
        """把知识库检索结果转换为 assembler provider 输入。"""
        if not outcome:
            return []
        return [
            {
                "title": item.title,
                "source_id": item.source_id,
                "snippet": item.snippet,
                "score": item.score,
            }
            for item in outcome.results
        ]

    @staticmethod
    def _web_context_items(outcome: SearchOutcome | None) -> list[dict]:
        """把网页检索结果转换为 assembler provider 输入。"""
        if not outcome:
            return []
        return [
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "content": item.content,
            }
            for item in outcome.results
        ]

    def _select_relevant_tools(
        self,
        request: AssistantChatRequest,
        current_user: dict | None,
    ) -> tuple[list[str], list[AgentTool], CapabilityRelevanceAssessment | None]:
        """按任务相关性筛选自动选择工具，并保留用户显式选择。

        Args:
            request: 当前助手请求。
            current_user: 当前用户上下文。

        Returns:
            (筛选后的工具 ID, 实际注入工具, 相关性评估结果)。
        """
        requested_ids = [
            str(item)
            for item in (request.context.get("selected_tool_ids") or [])
            if isinstance(item, str) and item.startswith("algorithm:")
        ]
        if not requested_ids:
            return [], [], None
        _candidate_tools, name_map = self._build_function_tools(requested_ids, current_user)
        candidate_tools = list(name_map.values())
        auto_ids = {
            str(item)
            for item in (request.context.get("auto_selected_tool_ids") or [])
            if isinstance(item, str)
        }
        protected_ids = [tool_id for tool_id in requested_ids if tool_id not in auto_ids]
        assessment, selected_tools = self.capability_relevance_service.assess(
            task_summary=self._latest_user_text(request.messages),
            tools=candidate_tools,
            protected_tool_ids=protected_ids,
            token_budget_limit=int(getattr(
                settings,
                "assistant_tool_schema_token_budget",
                6000,
            )),
        )
        return [tool.tool_id for tool in selected_tools], selected_tools, assessment

    def _resolve_selected_tools(
        self,
        selected_tool_ids: list[str],
        current_user: dict | None,
    ) -> list[AgentTool]:
        """解析当前用户可见的已选算法工具目录。"""
        _function_tools, name_map = self._build_function_tools(selected_tool_ids, current_user)
        return list(name_map.values())

    @staticmethod
    def _max_parallel_tool_calls(
        llm_route: dict,
        selected_tools: list[AgentTool],
    ) -> int:
        """计算当前请求允许的最大并行工具调用数。"""
        if not selected_tools or not llm_route.get("supports_parallel_tool_calls"):
            return 1
        return max(1, min(int(settings.assistant_max_parallel_tool_calls), 3))

    def _propose_tool_calls(
        self,
        *,
        request: AssistantChatRequest,
        intent: AssistantIntent,
        facts: dict,
        knowledge: KnowledgeOutcome | None,
        evidence: SearchOutcome | None,
        llm_route: dict,
        current_user: dict | None,
    ) -> tuple[list[dict], list[AssistantToolCall], str | None, list[dict], dict | None]:
        """让模型基于 function schema 提出算法调用。

        Returns:
            (事件列表, pending 调用, 无工具调用时的直接回答, 已构建的 function schema, context 事件)
        """
        selected_tool_ids, _selected_tools, capability_relevance = self._select_relevant_tools(
            request,
            current_user,
        )
        tools, name_map = self._build_function_tools(selected_tool_ids, current_user)
        if not tools:
            return [], [], None, [], None
        selected_tools = list(name_map.values())
        max_parallel_tool_calls = self._max_parallel_tool_calls(llm_route, selected_tools)
        assembly = self._assemble_context(
            request_kind="tool_proposal",
            request=request,
            intent=intent,
            facts=facts,
            knowledge=knowledge,
            evidence=evidence,
            llm_route=llm_route,
            selected_tools=selected_tools,
        )
        tool_source_context = self._tool_source_context(
            request=request,
            llm_route=llm_route,
            assembly=assembly,
            selected_tool_ids=selected_tool_ids,
            capability_relevance=capability_relevance,
        )
        context_event = self._context_event(
            request=request,
            request_kind="tool_proposal",
            route=llm_route,
            assembly=assembly,
            tools=selected_tools,
        )
        if capability_relevance:
            context_event["capability_relevance"] = capability_relevance.model_dump(mode="json")
        facts["context"] = self._context_metadata(assembly)
        if "tool_calling" not in (llm_route.get("capabilities") or []):
            logger.warning(
                "assistant tool calling skipped: model lacks tool_calling capability provider=%s model=%s",
                llm_route.get("provider_id"),
                llm_route.get("model_id"),
            )
            return [], [], None, tools, context_event
        messages = self.answer_synthesizer.tool_call_messages(
            request=request,
            intent=intent,
            facts=facts,
            knowledge=knowledge,
            evidence=evidence,
            context_assembly=assembly,
            max_parallel_tool_calls=max_parallel_tool_calls,
        )
        try:
            message = llm_client.chat_message(
                messages,
                temperature=0.2,
                purpose="deep" if intent.deep else "qa",
                provider_id=llm_route.get("provider_id"),
                model=llm_route.get("model_id"),
                tools=tools,
                tool_choice="auto",
            )
        except Exception as exc:
            provider_error = classify_provider_error(exc)
            logger.warning(
                "assistant tool calling provider error (%s), stop tool proposal: %s",
                provider_error["code"],
                exc,
            )
            return [], [], f"算法工具调用失败：{provider_error['message']}", tools, context_event

        tool_calls = getattr(message, "tool_calls", None) or []
        message_metadata = get_message_metadata() or {}
        if not tool_calls:
            self.llm_model_service.emit_tool_proposal_usage(
                call_id="",
                route=llm_route,
                usage=message_metadata.get("usage"),
                finish_reason=message_metadata.get("finish_reason"),
                request_id=message_metadata.get("request_id"),
            )
            return [], [], getattr(message, "content", "") or "", tools, context_event

        events: list[dict] = []
        pending: list[AssistantToolCall] = []
        proposal_error: str | None = None
        usage_emitted_for_call = False
        call_budget = max_parallel_tool_calls if max_parallel_tool_calls > 1 else 1
        relevance_by_tool = {
            item.capability_id: item
            for item in (capability_relevance.items if capability_relevance else [])
        }
        for call in tool_calls[:call_budget]:
            function = getattr(call, "function", None)
            if function is None:
                continue
            function_name = str(getattr(function, "name", "") or "")
            tool = name_map.get(function_name)
            if tool is None:
                logger.warning("assistant tool proposal references unknown function: %s", function_name)
                continue
            # 显式版本模板是管理端固定的调用载荷；仅未配置模板时才信任
            # provider 根据当前对话自由生成的参数。
            provider_arguments = normalize_provider_arguments(
                tool.model_proposal
                if tool.model_proposal
                else getattr(function, "arguments", None)
            )
            call_source_context = {
                **(tool_source_context or {}),
                "argument_origin": (
                    "version_model_proposal"
                    if tool.model_proposal
                    else "provider"
                ),
            }
            proposal_usage = message_metadata.get("usage")
            relevance_item = relevance_by_tool.get(tool.tool_id)
            try:
                created = assistant_tool_call_service.create(
                    AssistantToolCallCreate(
                        tool_id=tool.tool_id,
                        provider_tool_call_id=getattr(call, "id", None),
                        provider_tool_call_index=getattr(call, "index", 0),
                        chat_id=request.context.get("chat_id"),
                        message_id=request.context.get("message_id"),
                        assistant_run_id=request.context.get("run_id"),
                        trace_id=request.context.get("trace_id") or request.context.get("run_id"),
                        arguments=provider_arguments.arguments,
                        function_name=function_name,
                        raw_arguments=provider_arguments.raw_arguments,
                        arguments_parse_error=provider_arguments.parse_error,
                        finish_reason=message_metadata.get("finish_reason"),
                        proposal_route=self._safe_llm_route(llm_route),
                        proposal_usage=proposal_usage,
                        schema_digest=tool.schema_digest,
                        selection_reason=(
                            relevance_item.reason
                            if relevance_item
                            else f"根据当前 prompt 与已选算法的能力描述匹配：{tool.tool_id}"
                        ),
                        selection_confidence=(
                            relevance_item.confidence if relevance_item else 0.5
                        ),
                        source_context=call_source_context,
                    ),
                    current_user,
                )
                self.llm_model_service.emit_tool_proposal_usage(
                    call_id=created.call_id,
                    route=llm_route,
                    usage=proposal_usage,
                    finish_reason=message_metadata.get("finish_reason"),
                    request_id=message_metadata.get("request_id"),
                )
                usage_emitted_for_call = True
                pending.append(created)
                events.extend(AssistantToolCallRepository.list_events(created.call_id))
            except HTTPException as exc:
                self._rollback_tool_proposal(pending, current_user)
                pending = []
                detail = exc.detail
                if isinstance(detail, dict):
                    code = str(detail.get("code") or "")
                    if code == TOOL_ARGUMENTS_INVALID:
                        details = detail.get("details") or {}
                        rendered = (
                            "；".join(f"{key}: {value}" for key, value in details.items())
                            or str(detail.get("message") or "参数校验失败")
                        )
                        proposal_error = f"未能生成算法调用卡片：{rendered}。请重新描述参数后发送，或到算法页面直接填写参数运行。"
                    else:
                        proposal_error = f"未能生成算法调用卡片：{detail.get('message') or exc.detail}"
                else:
                    proposal_error = f"未能生成算法调用卡片：{exc.detail}"
                logger.warning("assistant tool proposal rejected %s: %s", tool.tool_id, exc)
                break
            except Exception as exc:
                self._rollback_tool_proposal(pending, current_user)
                pending = []
                proposal_error = "生成算法调用卡片时发生异常，请稍后重试。"
                logger.warning("assistant tool proposal skipped call %s: %s", tool.tool_id, exc)
                break
        if not usage_emitted_for_call:
            self.llm_model_service.emit_tool_proposal_usage(
                call_id="",
                route=llm_route,
                usage=message_metadata.get("usage"),
                finish_reason=message_metadata.get("finish_reason"),
                request_id=message_metadata.get("request_id"),
            )
        if proposal_error:
            return [], [], proposal_error, tools, context_event
        return events, pending, None, tools, context_event

    @staticmethod
    def _rollback_tool_proposal(
        pending: list[AssistantToolCall],
        current_user: dict | None,
    ) -> None:
        """并行工具提案失败时，取消同一批次已创建但未执行的调用。"""
        for created in pending:
            try:
                assistant_tool_call_service.cancel(created.call_id, current_user)
            except Exception as exc:
                logger.warning(
                    "assistant tool proposal rollback failed call_id=%s: %s",
                    created.call_id,
                    exc,
                )

    def _continuation_messages(
        self,
        tool_call_ids: list[str],
        current_user: dict | None,
    ) -> tuple[list[dict], list[dict]]:
        """读取已完成/失败的调用，构造 assistant+tool 消息供模型继续生成。"""
        events: list[dict] = []
        continuation_calls: list[AssistantToolCall] = []
        for call_id in tool_call_ids or []:
            try:
                call = assistant_tool_call_service.get(call_id, current_user)
            except Exception as exc:
                logger.warning("assistant continuation skipped call %s: %s", call_id, exc)
                continue
            events.extend(AssistantToolCallRepository.list_events(call_id))
            if call.phase not in {"completed", "failed"}:
                continue
            continuation_calls.append(call)

        if not continuation_calls:
            return events, []

        # OpenAI-compatible providers require each tool result to reference the
        # exact provider-generated tool call ID from the preceding assistant
        # message. Older persisted calls fall back to the local call ID.
        messages: list[dict] = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call.provider_tool_call_id or call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.function_name or self._safe_tool_name(call.tool_id),
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in continuation_calls
                ],
            }
        ]
        for call in continuation_calls:
            provider_tool_call_id = call.provider_tool_call_id or call.call_id
            payload = self._continuation_tool_payload(call)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": provider_tool_call_id,
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                }
            )
        return events, messages

    def chat(self, request: AssistantChatRequest, current_user: dict | None = None) -> AssistantChatResponse:
        user_text = self._latest_user_text(request.messages)
        preset_id, mode = resolve_assistant_runtime(
            request.context.get("preset_id"),
            request.context.get("mode"),
        )
        intent = self.intent_router.route(user_text, mode=mode)
        intent = self._apply_web_search_preference(intent, request.context.get("use_web_search"))
        facts = self.project_service.build_facts(intent=intent)
        project_refs = self.project_service.build_project_references(user_text)
        actions = self.project_service.build_actions(user_text)
        suggested_questions = self.project_service.build_suggested_questions(user_text, intent)
        llm_route = self._resolve_llm_route(mode=mode, request=request, preset_id=preset_id)
        knowledge_outcome = self._retrieve_knowledge(user_text, request)

        if mode == "model":
            response_facts = self._build_response_facts(
                facts=facts,
                knowledge_outcome=knowledge_outcome,
                web_outcome=None,
                request=request,
                search_query_plan=None,
                llm_route=llm_route,
            )
            return AssistantChatResponse(
                content=self._fallback_content(user_text, facts=facts, intent=intent),
                actions=actions,
                references=project_refs,
                suggested_questions=suggested_questions,
                grounding_facts=response_facts,
                confidence="medium",
                answer_mode="fallback",
                answer_scope="model",
                retrieval_status="not_needed",
            )

        web_outcome: SearchOutcome | None = None
        search_query_plan: SearchQueryPlan | None = None
        if intent.use_web:
            search_query_plan = self.search_query_builder.build(user_text)
            web_outcome = self.web_service.search(search_query_plan.query, deep=intent.deep)

        web_refs = self._web_references(web_outcome)
        knowledge_refs = self._knowledge_references(knowledge_outcome)
        references = project_refs + knowledge_refs + web_refs
        retrieval_status = self._combined_retrieval_status(knowledge_outcome, web_outcome)
        answer_mode = self._answer_mode(intent)
        response_facts = self._build_response_facts(
            facts=facts,
            knowledge_outcome=knowledge_outcome,
            web_outcome=web_outcome,
            request=request,
            search_query_plan=search_query_plan,
            llm_route=llm_route,
        )

        continuation_ids = request.context.get("tool_call_ids") or []
        selected_ids = request.context.get("selected_tool_ids") or []
        extra_messages: list[dict] = []
        final_assembly: ContextAssembly | None = None
        if continuation_ids:
            _tool_events, extra_messages = self._continuation_messages(continuation_ids, current_user)
            final_assembly = self._assemble_context(
                request_kind="final_answer",
                request=request,
                intent=intent,
                facts=response_facts,
                knowledge=knowledge_outcome,
                evidence=web_outcome,
                llm_route=llm_route,
                prior_tool_messages=extra_messages,
            )
        elif selected_ids:
            _events, calls, direct_content, _tools, _context_event = self._propose_tool_calls(
                request=request,
                intent=intent,
                facts=response_facts,
                knowledge=knowledge_outcome,
                evidence=web_outcome,
                llm_route=llm_route,
                current_user=current_user,
            )
            if calls:
                return AssistantChatResponse(
                    content="已根据你的请求生成算法调用，请确认参数后执行。",
                    tool_calls=calls,
                    actions=actions,
                    references=references,
                    suggested_questions=suggested_questions,
                    grounding_facts=response_facts,
                    confidence="medium",
                    answer_mode=answer_mode,
                    answer_scope=intent.scope,
                    retrieval_status=retrieval_status,
                )
            if direct_content:
                return AssistantChatResponse(
                    content=direct_content,
                    reasoning_summary=[],
                    actions=actions,
                    references=references,
                    suggested_questions=suggested_questions,
                    grounding_facts=response_facts,
                    confidence="medium",
                    answer_mode=answer_mode,
                    answer_scope=intent.scope,
                    retrieval_status=retrieval_status,
                )

        if final_assembly is None:
            final_assembly = self._assemble_context(
                request_kind="final_answer",
                request=request,
                intent=intent,
                facts=response_facts,
                knowledge=knowledge_outcome,
                evidence=web_outcome,
                llm_route=llm_route,
                selected_tools=self._resolve_selected_tools(selected_ids, current_user),
            )
        response_facts["context"] = self._context_metadata(final_assembly)

        try:
            synthesized = self.answer_synthesizer.synthesize(
                request=request,
                intent=intent,
                facts=response_facts,
                knowledge=knowledge_outcome,
                evidence=web_outcome,
                llm_route=llm_route,
                extra_messages=extra_messages,
                context_assembly=final_assembly,
            )
            content = synthesized.content
            reasoning_summary = synthesized.reasoning_summary
            confidence = "medium"
        except Exception as exc:
            logger.warning("assistant LLM fallback: %s", exc)
            content = self._fallback_content(user_text, facts=facts, intent=intent)
            reasoning_summary = []
            confidence = "medium"
            answer_mode = "fallback"
            if web_outcome and web_outcome.status == "searched":
                retrieval_status = "searched"
            if knowledge_outcome and knowledge_outcome.status == "searched":
                retrieval_status = "searched"

        return AssistantChatResponse(
            content=content,
            reasoning_summary=reasoning_summary,
            actions=actions,
            references=references,
            suggested_questions=suggested_questions,
            grounding_facts=response_facts,
            confidence=confidence,
            answer_mode=answer_mode,
            answer_scope=intent.scope,
            retrieval_status=retrieval_status,
        )

    def stream_chat(self, request: AssistantChatRequest, current_user: dict | None = None) -> Iterator[dict]:
        try:
            yield {"type": "status", "stage": "intent", "message": "正在识别问题范围..."}
            user_text = self._latest_user_text(request.messages)
            preset_id, mode = resolve_assistant_runtime(
                request.context.get("preset_id"),
                request.context.get("mode"),
            )
            intent = self.intent_router.route(user_text, mode=mode)
            intent = self._apply_web_search_preference(intent, request.context.get("use_web_search"))

            yield {"type": "status", "stage": "facts", "message": "正在收集项目事实..."}
            facts = self.project_service.build_facts(intent=intent)
            project_refs = self.project_service.build_project_references(user_text)
            actions = self.project_service.build_actions(user_text)
            suggested_questions = self.project_service.build_suggested_questions(user_text, intent)
            llm_route = self._resolve_llm_route(mode=mode, request=request, preset_id=preset_id)
            logger.info(
                "assistant stream llm route resolved: purpose=%s provider_id=%s model_id=%s",
                llm_route.get("purpose"),
                llm_route.get("provider_id"),
                llm_route.get("model_id"),
            )
            yield {"type": "route.resolved", "route": self._safe_llm_route(llm_route)}

            if mode == "model":
                response_facts = self._build_response_facts(
                    facts=facts,
                    knowledge_outcome=None,
                    web_outcome=None,
                    request=request,
                    search_query_plan=None,
                    llm_route=llm_route,
                )
                content = self._fallback_content(user_text, facts=facts, intent=intent)
                if content:
                    yield {"type": "answer_delta", "delta": content}
                yield {
                    "type": "final",
                    "data": AssistantChatResponse(
                        content=content,
                        actions=actions,
                        references=project_refs,
                        suggested_questions=suggested_questions,
                        grounding_facts=response_facts,
                        confidence="medium",
                        answer_mode="fallback",
                        answer_scope="model",
                        retrieval_status="not_needed",
                    ).model_dump(mode="python"),
                }
                return

            web_outcome: SearchOutcome | None = None
            search_query_plan: SearchQueryPlan | None = None
            if request.context.get("use_knowledge_base"):
                yield {"type": "status", "stage": "knowledge", "message": "正在检索知识库..."}
                yield {
                    "type": "retrieval.started",
                    "source": "knowledge",
                    "query_digest": self._short_digest(user_text),
                }
            knowledge_outcome = self._retrieve_knowledge(user_text, request)
            if knowledge_outcome:
                yield {
                    "type": "evidence",
                    "status": knowledge_outcome.status,
                    "message": self._knowledge_evidence_message(knowledge_outcome),
                    "source": "knowledge",
                    "query_digest": self._short_digest(user_text),
                    "references": [],
                }
            if intent.use_web:
                yield {"type": "status", "stage": "search", "message": "正在检索外部证据..."}
                search_query_plan = self.search_query_builder.build(user_text)
                yield {
                    "type": "retrieval.started",
                    "source": "web",
                    "query_digest": self._short_digest(search_query_plan.query),
                }
                web_outcome = self.web_service.search(search_query_plan.query, deep=intent.deep)

            web_refs = self._web_references(web_outcome)
            knowledge_refs = self._knowledge_references(knowledge_outcome)
            references = project_refs + knowledge_refs + web_refs
            retrieval_status = self._combined_retrieval_status(knowledge_outcome, web_outcome)
            knowledge_entries = mark_used_in_answer(
                knowledge_result_entries(knowledge_outcome),
                references,
            )
            web_entries = mark_used_in_answer(web_result_entries(web_outcome), references)
            if knowledge_outcome:
                yield retrieval_result_event(
                    source="knowledge",
                    query_digest=self._short_digest(user_text),
                    status=knowledge_outcome.status,
                    entries=knowledge_entries,
                )
            if web_outcome:
                yield {
                    "type": "evidence",
                    "status": web_outcome.status,
                    "message": self._evidence_message(web_outcome),
                    "source": "web",
                    "query_digest": self._short_digest(search_query_plan.query),
                    "references": [item.model_dump(mode="python") for item in web_refs],
                }
                yield retrieval_result_event(
                    source="web",
                    query_digest=self._short_digest(search_query_plan.query),
                    status=web_outcome.status,
                    entries=web_entries,
                )

            answer_mode = self._answer_mode(intent)
            response_facts = self._build_response_facts(
                facts=facts,
                knowledge_outcome=knowledge_outcome,
                web_outcome=web_outcome,
                request=request,
                search_query_plan=search_query_plan,
                llm_route=llm_route,
            )

            continuation_ids = request.context.get("tool_call_ids") or []
            selected_ids = request.context.get("selected_tool_ids") or []
            extra_messages: list[dict] = []
            final_assembly: ContextAssembly | None = None
            if continuation_ids:
                tool_events, extra_messages = self._continuation_messages(continuation_ids, current_user)
                for event in tool_events:
                    yield event
                yield {"type": "context.assembly.started", "request_kind": "final_answer"}
                final_assembly = self._assemble_context(
                    request_kind="final_answer",
                    request=request,
                    intent=intent,
                    facts=response_facts,
                    knowledge=knowledge_outcome,
                    evidence=web_outcome,
                    llm_route=llm_route,
                    prior_tool_messages=extra_messages,
                )
                response_facts["context"] = self._context_metadata(final_assembly)
                context_event = self._context_event(
                    request=request,
                    request_kind="final_answer",
                    route=llm_route,
                    assembly=final_assembly,
                    tools=[],
                )
                yield self._request_header_event(context_event)
                yield context_event
            elif selected_ids:
                yield {"type": "status", "stage": "tools", "message": "正在分析算法工具调用..."}
                yield {"type": "context.assembly.started", "request_kind": "tool_proposal"}
                _relevance_filtered_ids, selected_tools, capability_relevance = self._select_relevant_tools(
                    request,
                    current_user,
                )
                if capability_relevance:
                    yield {
                        "type": "tool.relevance.assessed",
                        **capability_relevance.model_dump(mode="json"),
                    }
                if selected_tools:
                    yield {
                        "type": "tool.catalog.resolved",
                        "tools": [{"tool_id": tool.tool_id} for tool in selected_tools],
                    }
                    yield {
                        "type": "tool.schema.rendered",
                        "tools": [
                            {
                                "tool_id": tool.tool_id,
                                "function_name": tool.function_name,
                                "version": tool.version,
                                "schema_digest": tool.schema_digest,
                            }
                            for tool in selected_tools
                        ],
                    }
                tool_events, calls, direct_content, built_tools, context_event = self._propose_tool_calls(
                    request=request,
                    intent=intent,
                    facts=response_facts,
                    knowledge=knowledge_outcome,
                    evidence=web_outcome,
                    llm_route=llm_route,
                    current_user=current_user,
                )
                if context_event:
                    yield self._request_header_event(context_event)
                    yield context_event
                if calls:
                    for event in tool_events:
                        yield event
                    yield {
                        "type": "final",
                        "data": AssistantChatResponse(
                            content="已根据你的请求生成算法调用，请确认参数后执行。",
                            tool_calls=calls,
                            actions=actions,
                            references=references,
                            suggested_questions=suggested_questions,
                            grounding_facts=response_facts,
                            confidence="medium",
                            answer_mode=answer_mode,
                            answer_scope=intent.scope,
                            retrieval_status=retrieval_status,
                        ).model_dump(mode="python"),
                    }
                    return
                if direct_content:
                    yield {"type": "answer_delta", "delta": direct_content}
                    yield {
                        "type": "final",
                        "data": AssistantChatResponse(
                            content=direct_content,
                            reasoning_summary=[],
                            actions=actions,
                            references=references,
                            suggested_questions=suggested_questions,
                            grounding_facts=response_facts,
                            confidence="medium",
                            answer_mode=answer_mode,
                            answer_scope=intent.scope,
                            retrieval_status=retrieval_status,
                        ).model_dump(mode="python"),
                    }
                    return
                if built_tools:
                    yield {
                        "type": "status",
                        "stage": "tools",
                        "message": "当前模型不支持算法工具调用，已按普通问答继续。",
                    }

            reasoning_summary = self._visible_reasoning_summary(
                intent=intent,
                knowledge_outcome=knowledge_outcome,
                web_outcome=web_outcome,
            )
            if final_assembly is None:
                selected_tools = self._resolve_selected_tools(selected_ids, current_user)
                yield {"type": "context.assembly.started", "request_kind": "final_answer"}
                final_assembly = self._assemble_context(
                    request_kind="final_answer",
                    request=request,
                    intent=intent,
                    facts=response_facts,
                    knowledge=knowledge_outcome,
                    evidence=web_outcome,
                    llm_route=llm_route,
                    selected_tools=selected_tools,
                )
                response_facts["context"] = self._context_metadata(final_assembly)
                context_event = self._context_event(
                    request=request,
                    request_kind="final_answer",
                    route=llm_route,
                    assembly=final_assembly,
                    tools=selected_tools,
                )
                yield self._request_header_event(context_event)
                yield context_event
            if intent.deep:
                for item in reasoning_summary:
                    yield {"type": "reasoning_summary_delta", "item": item}

            yield {"type": "status", "stage": "generation", "message": "正在生成回答..."}
            chunks: list[str] = []
            for chunk in self.answer_synthesizer.stream_answer(
                request=request,
                intent=intent,
                facts=response_facts,
                knowledge=knowledge_outcome,
                evidence=web_outcome,
                llm_route=llm_route,
                extra_messages=extra_messages,
                context_assembly=final_assembly,
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                yield {"type": "answer_delta", "delta": chunk}

            content = "".join(chunks).strip()
            if not content:
                content = self._fallback_content(user_text, facts=facts, intent=intent)
                yield {"type": "answer_delta", "delta": content}
                answer_mode = "fallback"
                reasoning_summary = []

            yield {
                "type": "final",
                "data": AssistantChatResponse(
                    content=content,
                    reasoning_summary=reasoning_summary if intent.deep else [],
                    actions=actions,
                    references=references,
                    suggested_questions=suggested_questions,
                    grounding_facts=response_facts,
                    confidence="medium",
                    answer_mode=answer_mode,
                    answer_scope=intent.scope,
                    retrieval_status=retrieval_status,
                ).model_dump(mode="python"),
            }
        except Exception as exc:
            logger.warning("assistant stream failed: %s", exc)
            yield {
                "type": "error",
                "code": "ASSISTANT_STREAM_ERROR",
                "message": str(exc),
            }

    def _build_response_facts(
        self,
        *,
        facts: dict,
        knowledge_outcome: KnowledgeOutcome | None,
        web_outcome: SearchOutcome | None,
        request: AssistantChatRequest,
        search_query_plan: SearchQueryPlan | None = None,
        llm_route: dict | None = None,
    ) -> dict:
        response_facts = dict(facts)
        request_context = dict(request.context)
        if llm_route and llm_route.get("preset_id"):
            request_context["preset_id"] = llm_route.get("preset_id")
        response_facts["request_context"] = request_context
        response_facts["llm_route"] = self._safe_llm_route(llm_route or {})
        if knowledge_outcome:
            response_facts["knowledge_search"] = {
                "status": knowledge_outcome.status,
                "provider": knowledge_outcome.provider,
                "system_id": knowledge_outcome.system_id,
                "system_name": knowledge_outcome.system_name,
                "system_ids": knowledge_outcome.system_ids or [knowledge_outcome.system_id],
                "system_names": knowledge_outcome.system_names or [knowledge_outcome.system_name],
                "query": knowledge_outcome.query,
                "result_count": len(knowledge_outcome.results),
                "error": knowledge_outcome.error,
                "results": [
                    {
                        "title": item.title,
                        "source_id": item.source_id,
                        "snippet": item.snippet,
                        "score": item.score,
                        "source": item.source,
                        "metadata": item.metadata or {},
                    }
                    for item in knowledge_outcome.results
                ],
            }
        else:
            response_facts["knowledge_search"] = {
                "status": "not_needed",
                "provider": None,
                "system_id": None,
                "system_name": None,
                "system_ids": [],
                "system_names": [],
                "query": None,
                "result_count": 0,
                "error": None,
                "results": [],
            }
        if web_outcome:
            raw_count = web_outcome.raw_result_count or len(web_outcome.results)
            filtered_count = web_outcome.filtered_result_count or len(web_outcome.results)
            response_facts["web_search"] = {
                "status": web_outcome.status,
                "provider": web_outcome.provider,
                "query": web_outcome.query,
                "original_query": (
                    search_query_plan.original_query
                    if search_query_plan
                    else web_outcome.original_query or web_outcome.query
                ),
                "query_terms": (
                    search_query_plan.query_terms
                    if search_query_plan
                    else web_outcome.query_terms or []
                ),
                "dropped_terms": (
                    search_query_plan.dropped_terms
                    if search_query_plan
                    else web_outcome.dropped_terms or []
                ),
                "raw_result_count": raw_count,
                "filtered_result_count": filtered_count,
                "result_count": len(web_outcome.results),
                "results": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "snippet": item.snippet,
                        "published_at": item.published_at,
                        "source": item.source,
                    }
                    for item in web_outcome.results
                ],
            }
        else:
            response_facts["web_search"] = {
                "status": "not_needed",
                "provider": None,
                "query": None,
                "original_query": None,
                "query_terms": [],
                "dropped_terms": [],
                "raw_result_count": 0,
                "filtered_result_count": 0,
                "result_count": 0,
                "results": [],
            }
        return response_facts

    def _resolve_llm_route(
        self,
        *,
        mode: str,
        request: AssistantChatRequest,
        preset_id: str | None = None,
    ) -> dict:
        resolved_preset_id, _compatibility_mode = resolve_assistant_runtime(
            preset_id or (request.context or {}).get("preset_id"),
            (request.context or {}).get("mode") or mode,
        )
        purpose = assistant_route_purpose(resolved_preset_id)
        requested_model = (request.context or {}).get("model")
        requested_provider_id, requested_model_id = self._requested_model_identifiers(requested_model)
        if (requested_provider_id or requested_model_id) and not (requested_provider_id and requested_model_id):
            raise ValueError("所选 LLM 模型不可用：providerId 和 modelId 必须同时提供")
        requires_tool_calling = bool((request.context or {}).get("selected_tool_ids"))
        try:
            resolve_method = (
                self.llm_model_service.resolve_tool_capable_route
                if requires_tool_calling
                else self.llm_model_service.resolve_route
            )
            return resolve_method(
                purpose=purpose,
                requested_model=requested_model,
            ) | {"preset_id": resolved_preset_id}
        except Exception as exc:
            if self._has_requested_model(requested_model):
                detail = getattr(exc, "detail", None) or str(exc)
                raise ValueError(f"所选 LLM 模型不可用：{detail}") from exc
            logger.warning("assistant llm route unavailable: %s", exc)
            try:
                return self.llm_model_service.resolve_default_route(purpose=purpose) | {
                    "preset_id": resolved_preset_id
                }
            except Exception as fallback_exc:
                logger.warning("assistant llm default route unavailable: %s", fallback_exc)
                return {
                    "purpose": purpose,
                    "preset_id": resolved_preset_id,
                    "provider_id": None,
                    "model_id": settings.llm_model or None,
                    "capabilities": [],
                    "reasoning_model_available": False,
                }

    def _has_requested_model(self, requested_model) -> bool:
        provider_id, model_id = self._requested_model_identifiers(requested_model)
        return bool(provider_id or model_id)

    def _requested_model_identifiers(self, requested_model) -> tuple[str, str]:
        if not isinstance(requested_model, dict):
            return "", ""
        provider_id = str(requested_model.get("providerId") or requested_model.get("provider_id") or "").strip()
        model_id = str(requested_model.get("modelId") or requested_model.get("model_id") or "").strip()
        return provider_id, model_id

    def _safe_llm_route(self, route: dict) -> dict:
        """Build a serializable route snapshot without provider credentials."""
        return {
            "preset_id": route.get("preset_id"),
            "purpose": route.get("purpose"),
            "route_reason": route.get("route_reason"),
            "requested_provider_id": route.get("requested_provider_id"),
            "requested_model_id": route.get("requested_model_id"),
            "provider_id": route.get("provider_id"),
            "provider_type": route.get("provider_type"),
            "model_id": route.get("model_id"),
            "capabilities": list(route.get("capabilities") or []),
            "capability_source": route.get("capability_source"),
            "tool_protocol": route.get("tool_protocol"),
            "supports_parallel_tool_calls": route.get("supports_parallel_tool_calls"),
            "context_window": route.get("context_window"),
            "max_output_tokens": route.get("max_output_tokens"),
            "reasoning_model_available": bool(route.get("reasoning_model_available")),
        }

    def _web_references(self, outcome: SearchOutcome | None) -> list[AssistantReference]:
        """把联网检索命中转换为可追溯引用。

        Args:
            outcome: 联网检索结果。

        Returns:
            带 source_id 与 rank 的引用列表，便于 Recall@K 判定。
        """
        if not outcome or not outcome.results:
            return []
        return [
            AssistantReference(
                label=item.title,
                target=item.url,
                type="web",
                source="web",
                source_id=item.url,
                rank=index + 1,
            )
            for index, item in enumerate(outcome.results[:3])
        ]

    def _retrieve_knowledge(self, query: str, request: AssistantChatRequest) -> KnowledgeOutcome | None:
        """按前端选择从 WeKnora 检索知识库证据。

        Args:
            query: 用户最新问题。
            request: 当前对话请求。

        Returns:
            检索结果；未启用知识库时返回 ``None``。
        """
        context = request.context or {}
        enabled = self._normalize_bool(context.get("use_knowledge_base"))
        system_ids = self._selected_knowledge_base_ids(context)
        if not enabled or not system_ids:
            return None
        system_names = self._selected_knowledge_base_names(context, system_ids)
        system_id = system_ids[0]
        system_name = "、".join(system_names[:3])
        if len(system_names) > 3:
            system_name = f"{system_name} 等 {len(system_names)} 个知识库"
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return KnowledgeOutcome(
                status="no_results",
                provider="weknora",
                system_id=system_id,
                system_name=system_name,
                query="",
                results=[],
                system_ids=system_ids,
                system_names=system_names,
            )
        try:
            hits = self.knowledge_service.search_hits_many(system_ids, normalized_query, limit=5)
        except Exception as exc:
            logger.warning("assistant knowledge retrieval failed: %s", exc)
            return KnowledgeOutcome(
                status="failed",
                provider="weknora",
                system_id=system_id,
                system_name=system_name,
                query=normalized_query,
                results=[],
                error=f"{type(exc).__name__}: {exc}",
                system_ids=system_ids,
                system_names=system_names,
            )
        results = [
            KnowledgeEvidence(
                title=hit.title,
                snippet=hit.snippet,
                source_id=hit.source_id,
                score=hit.score,
                source=hit.source,
                metadata=hit.metadata,
            )
            for hit in hits
        ]
        return KnowledgeOutcome(
            status="searched" if results else "no_results",
            provider="weknora",
            system_id=system_id,
            system_name=system_name,
            query=normalized_query,
            results=results,
            system_ids=system_ids,
            system_names=system_names,
        )

    def _knowledge_references(self, outcome: KnowledgeOutcome | None) -> list[AssistantReference]:
        """将 WeKnora 命中转换为工作台引用入口。

        Args:
            outcome: 知识库检索结果。

        Returns:
            可在前端展示的引用列表。
        """
        if not outcome or not outcome.results:
            return []
        target = (
            f"/knowledge?system_id={quote_plus(outcome.system_id)}"
            if len(outcome.system_ids or []) <= 1
            else "/knowledge"
        )
        refs: list[AssistantReference] = []
        seen: set[str] = set()
        for item in outcome.results:
            key = item.source_id or item.title
            if key in seen:
                continue
            seen.add(key)
            label = item.title or outcome.system_name
            refs.append(
                AssistantReference(
                    label=label,
                    target=target,
                    type="knowledge",
                    source="knowledge",
                    source_id=key,
                    rank=len(refs) + 1,
                    score=item.score,
                )
            )
            if len(refs) >= 5:
                break
        return refs

    def _evidence_message(self, outcome: SearchOutcome) -> str:
        if outcome.status == "searched":
            return f"已检索到 {len(outcome.results)} 条可用证据"
        if outcome.status == "no_results":
            return "未检索到可用证据"
        if outcome.status == "failed":
            return "外部检索失败，继续使用可用项目事实"
        if outcome.status == "skipped_disabled":
            return "外部检索未启用"
        return "无需外部检索"

    def _knowledge_evidence_message(self, outcome: KnowledgeOutcome) -> str:
        """生成知识库检索状态文案。

        Args:
            outcome: 知识库检索结果。

        Returns:
            面向前端展示的检索状态。
        """
        if outcome.status == "searched":
            return f"已从 {outcome.system_name} 检索到 {len(outcome.results)} 条证据"
        if outcome.status == "no_results":
            return f"{outcome.system_name} 未检索到可用证据"
        if outcome.status == "failed":
            return f"{outcome.system_name} 检索失败，继续使用可用上下文"
        return "知识库检索未启用"

    def _selected_knowledge_base_ids(self, context: dict) -> list[str]:
        """从对话上下文中读取知识库 ID 列表。

        Args:
            context: 前端传入的对话上下文。

        Returns:
            去重后的知识库 ID 列表。
        """
        values = self._normalize_context_string_list(context.get("knowledge_base_ids"))
        if not values:
            values = self._normalize_context_string_list(context.get("knowledge_base_id") or context.get("system_id"))
        return values

    def _selected_knowledge_base_names(self, context: dict, system_ids: list[str]) -> list[str]:
        """从对话上下文中读取知识库名称列表。

        Args:
            context: 前端传入的对话上下文。
            system_ids: 已选择的知识库 ID 列表。

        Returns:
            与知识库 ID 顺序对应的名称列表。
        """
        names = self._normalize_context_string_list(context.get("knowledge_base_names"))
        if not names:
            names = self._normalize_context_string_list(context.get("knowledge_base_name"))
        padded = names[: len(system_ids)]
        while len(padded) < len(system_ids):
            padded.append(system_ids[len(padded)])
        return padded

    @staticmethod
    def _normalize_context_string_list(value: object) -> list[str]:
        """规范化上下文中的字符串或字符串数组。

        Args:
            value: 前端传入的单个字符串、字符串数组或逗号分隔字符串。

        Returns:
            去重后的字符串列表。
        """
        raw_values = value if isinstance(value, list) else [value]
        normalized: list[str] = []
        for item in raw_values:
            if item is None:
                continue
            parts = [item] if not isinstance(item, str) else re.split(r"[,，]", item)
            for part in parts:
                text = str(part or "").strip()
                if text and text not in normalized:
                    normalized.append(text)
        return normalized

    def _combined_retrieval_status(
        self,
        knowledge_outcome: KnowledgeOutcome | None,
        web_outcome: SearchOutcome | None,
    ) -> AssistantRetrievalStatus:
        """合并网页和知识库检索状态。

        Args:
            knowledge_outcome: 知识库检索结果。
            web_outcome: 网页检索结果。

        Returns:
            面向前端展示的综合检索状态。
        """
        statuses = [item.status for item in (knowledge_outcome, web_outcome) if item]
        if not statuses:
            return "not_needed"
        if "searched" in statuses:
            return "searched"
        if "failed" in statuses:
            return "failed"
        if "no_results" in statuses:
            return "no_results"
        if "skipped_disabled" in statuses:
            return "skipped_disabled"
        return "not_needed"

    def _visible_reasoning_summary(
        self,
        *,
        intent: AssistantIntent,
        knowledge_outcome: KnowledgeOutcome | None,
        web_outcome: SearchOutcome | None,
    ) -> list[str]:
        summary = [
            f"识别回答范围为 {intent.scope}，确认是否需要项目事实或外部证据。",
            "整合项目配置、算法清单、任务入口和模型路由等可核查事实。",
        ]
        if knowledge_outcome:
            summary.append(f"检查知识库检索状态为 {knowledge_outcome.status}，筛选 WeKnora 命中证据。")
        if web_outcome:
            summary.append(f"检查外部检索状态为 {web_outcome.status}，筛选可引用证据。")
        summary.append("基于已验证事实组织结论、依据和可执行建议。")
        return summary[:5]

    def _answer_mode(self, intent: AssistantIntent) -> AssistantAnswerMode:
        if intent.scope == "web":
            return "web_grounded"
        if intent.scope == "hybrid":
            return "hybrid_grounded"
        return "llm_project_grounded"

    def _normalize_mode(self, mode: str | None) -> str:
        normalized = str(mode or "qa").strip().lower()
        if normalized not in {"qa", "deep", "model"}:
            return "qa"
        return normalized

    def _apply_web_search_preference(
        self,
        intent: AssistantIntent,
        use_web_search: object,
    ) -> AssistantIntent:
        """根据前端联网开关调整回答范围。

        Args:
            intent: 路由器根据问题意图生成的回答意图。
            use_web_search: 前端传入的联网开关，支持布尔值与字符串。

        Returns:
            调整后的回答意图。
        """
        preference = self._normalize_web_search_preference(use_web_search)
        if preference is None:
            return intent
        if preference:
            if intent.scope == "model":
                return intent
            if intent.scope == "project":
                return AssistantIntent(scope="hybrid", use_web=True, deep=intent.deep)
            return AssistantIntent(scope=intent.scope, use_web=True, deep=intent.deep)
        if intent.scope == "model":
            return intent
        return AssistantIntent(scope="project", use_web=False, deep=intent.deep)

    def _normalize_bool(self, value: object) -> bool:
        """规范化前端布尔开关。

        Args:
            value: 前端传入的开关值。

        Returns:
            解析后的布尔值。
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _normalize_web_search_preference(self, use_web_search: object) -> bool | None:
        """规范化联网搜索开关。

        Args:
            use_web_search: 前端传入的联网搜索开关。

        Returns:
            解析后的布尔值；未提供时返回 ``None``。
        """
        if use_web_search is None:
            return None
        if isinstance(use_web_search, bool):
            return use_web_search
        if isinstance(use_web_search, (int, float)):
            return bool(use_web_search)
        if isinstance(use_web_search, str):
            normalized = use_web_search.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return None

    def _latest_user_text(self, messages) -> str:
        for msg in reversed(messages):
            if msg.role == "user":
                return msg.content.strip()
        return ""

    def _fallback_content(self, text: str, *, facts: dict, intent: AssistantIntent) -> str:
        lowered = text.lower()
        if intent.scope == "model":
            llm_catalog = facts.get("llm_catalog", {})
            routing = llm_catalog.get("routing") or {}
            model_facts = facts.get("model_management", {})
            chat_model = (model_facts.get("chat") or {}).get("model", "未配置")
            report_provider = (model_facts.get("report") or {}).get("provider", "unknown")
            return (
                "模型管理已迁移为 LLM 模型选择与路由管理。\n\n"
                f"- 科研问答默认模型：`{(routing.get('qa') or {}).get('model_id') or chat_model}`。\n"
                f"- 深度思考默认模型：`{(routing.get('deep') or {}).get('model_id') or '未配置'}`。\n"
                f"- 报告链路 provider：`{report_provider}`。\n\n"
                "请进入 `/tools?tab=llm-models` 查看可选模型、能力标签、健康状态并设置默认路由。"
            )
        if "审批" in text or "autoresearch" in lowered or "blocked_approval" in lowered:
            return self._approval_answer(facts)
        if "如何开始" in text and ("researchengine" in lowered or "research engine" in lowered or "研发" in text):
            return self._research_engine_start_answer()
        if "计算" in text and any(token in lowered for token in ("workflow", "research", "xtb", "orca", "提交")):
            return self._computation_answer(facts)
        if "真实适配器" in text or ("adapter" in lowered and ("research" in lowered or "algorithm" in lowered)):
            return self._adapter_answer(facts)
        if intent.scope == "web":
            return "我暂时没有拿到外部网页证据，但可以先基于通用经验给出保守建议：请补充更具体的主题、技术栈或对比对象。"
        return "我可以帮你进入 ResearchEngine、提交计算任务、查看 Alchemist，或定位待审批任务。"

    def _adapter_answer(self, facts: dict) -> str:
        registry = facts.get("algorithm_registry", {})
        production = registry.get("production_adapters", [])
        computation = registry.get("computation_workflow_adapters", [])
        bridge = registry.get("bridge_adapters", [])
        demo = registry.get("demo_algorithms", [])
        status = facts.get("integration_status", {})

        lines = [
            "当前 ResearchEngine 的算法事实应按 Registry 分类理解：",
            "",
            "真实/生产适配器：",
            *self._format_algorithm_lines(production),
            "",
            "计算 workflow 适配器：",
            *self._format_algorithm_lines(computation),
            "",
            "桥接适配器：",
            *self._format_algorithm_lines(bridge),
            "",
            "演示 mock 算法：",
            *self._format_algorithm_lines(demo),
            "",
            "可用性边界：",
            f"- 知识库问答取决于 WeKnora 服务；垂类预测取决于 VERTICAL_PREDICTOR_URL；Alchemist 取决于 alchemist-backend 状态（当前：{self._service_status(status, 'alchemist-backend')}）。",
            f"- LOCAL_STRUCTURE 取决于 RDKit/OpenBabel（当前：RDKit {self._service_status(status, 'rdkit')}，OpenBabel {self._service_status(status, 'openbabel')}）。",
            f"- LOCAL_XTB 取决于 xTB/CREST（当前：xTB {self._service_status(status, 'xtb')}，CREST {self._service_status(status, 'crest')}）。",
            f"- ORCA DFT 取决于 ORCA 可执行文件和 license（当前：ORCA {self._service_status(status, 'orca')}）。",
            "",
            "因此不要把未出现在 AlgorithmRegistry 中的通用优化器名称当成当前 ResearchEngine 已注册的真实适配器。",
        ]
        return "\n".join(lines)

    def _approval_answer(self, facts: dict) -> str:
        autoresearch = facts.get("autoresearch", {})
        gate_stages = autoresearch.get("gate_stages", [])
        route = autoresearch.get("approval_route", "/tasks/center?module_id=research-engine&status=blocked_approval")
        return (
            "AutoResearch 进入 `blocked_approval` 时才需要人工审批。\n\n"
            f"待审批入口：`{route}`。\n\n"
            f"当前 P0 Gate 阶段：{', '.join(gate_stages)}。\n\n"
            "操作路径：任务中心筛选 ResearchEngine + blocked_approval，或进入 ResearchEngine 的 ResearchRun 面板；"
            "在阶段时间线中点击“审批”，填写原因后选择批准或拒绝。批准后流程继续推进，拒绝后该 ResearchRun 会失败。"
        )

    def _research_engine_start_answer(self) -> str:
        return (
            "开始 ResearchEngine 示例的实际路径是：\n\n"
            "1. 进入 `/research-engine`。\n"
            "2. 创建或实例化一个 ProblemSpec，确认材料体系、目标和约束。\n"
            "3. 创建 ExecutionDecision：选择 `manual_workbench` 或 `autoresearch`。\n"
            "4. 人工模式下选择算法清单形成 Workflow；自动模式下创建 ResearchRun 草稿。\n"
            "5. 启动 ResearchRun 后，遇到 `blocked_approval` 的 Gate 阶段再处理审批。\n\n"
            "如果只是独立提交分子计算，可以直接走 `/computations/submit`；如果要把计算结果纳入研发追溯链，应从 ResearchEngine Workflow 或 ResearchRun 进入。"
        )

    def _computation_answer(self, facts: dict) -> str:
        status = facts.get("integration_status", {})
        return (
            "计算任务有两种入口：\n\n"
            "- 独立探索：进入 `/computations/submit`，直接提交 `LOCAL_STRUCTURE`、`LOCAL_XTB` 或 `ORCA_COMPUTE_ENGINE_LASER`。\n"
            "- 系统性研发：进入 `/research-engine`，在人工 Workflow 中使用计算适配器或 `computation_submit_adapter`，这样结果会关联 ProblemSpec、AlgorithmRun 和追溯链。\n\n"
            "当前依赖状态："
            f"RDKit {self._service_status(status, 'rdkit')}，OpenBabel {self._service_status(status, 'openbabel')}，"
            f"xTB {self._service_status(status, 'xtb')}，CREST {self._service_status(status, 'crest')}，ORCA {self._service_status(status, 'orca')}。"
        )

    def _format_algorithm_lines(self, items: list[dict]) -> list[str]:
        if not items:
            return ["- 当前 Registry 未返回该类条目。"]
        return [
            f"- `{item.get('algorithm_id')}`：{item.get('name') or '-'}；"
            f"调用方式 {item.get('call_method') or '-'}；状态 {item.get('status') or '-'}；"
            f"依赖：{item.get('runtime_dependency') or '未声明'}。"
            for item in items
        ]

    def _service_status(self, status: dict, service: str) -> str:
        return str((status.get(service) or {}).get("status") or "unknown")


_assistant_service = AssistantService()


def chat_assistant(request: AssistantChatRequest, current_user: dict | None = None) -> AssistantChatResponse:
    return _assistant_service.chat(request, current_user=current_user)


def stream_chat_assistant(request: AssistantChatRequest, current_user: dict | None = None) -> Iterator[dict]:
    yield from _assistant_service.stream_chat(request, current_user=current_user)
