"""助手能力相关性评估与工具注入预算控制。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.time import utc_now
from app.schemas.agent_tools import AgentTool
from app.schemas.capabilities import (
    CapabilityRelevanceAssessment,
    CapabilityRelevanceItem,
)
from app.services.assistant_context_assembler import estimate_native_tool_schema_tokens


LATIN_TERM_PATTERN = re.compile(r"[a-z0-9][a-z0-9_+.-]{1,}", re.IGNORECASE)
CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
GENERIC_TERMS = {"预测", "生成", "计算", "分析", "返回", "结果"}


class CapabilityRelevanceService:
    """按当前任务评估候选能力，并输出可审计的注入决策。"""

    @staticmethod
    def estimate_tool_schema_tokens(tool: AgentTool) -> int:
        """估算单个工具原生 schema 的 token 占用。

        Args:
            tool: 算法工具目录项。

        Returns:
            保守估算的 schema token 数。
        """
        return estimate_native_tool_schema_tokens([tool])

    @staticmethod
    def _terms(text: str) -> set[str]:
        """抽取中英文轻量检索词，用于规则兜底相关性评估。"""
        normalized = str(text or "").lower()
        terms = {
            match.group(0).strip(".-")
            for match in LATIN_TERM_PATTERN.finditer(normalized)
            if match.group(0).strip(".-")
        }
        for block in CJK_PATTERN.findall(normalized):
            if len(block) == 1:
                terms.add(block)
            else:
                terms.update(block[index : index + 2] for index in range(len(block) - 1))
        return terms

    @staticmethod
    def _tool_text(tool: AgentTool) -> str:
        """汇总工具元数据和输入 schema 中可公开检索的文本。"""
        input_fields = " ".join(
            str(field) for field in (tool.input_schema.fields or {}).keys()
        )
        return " ".join(
            [
                tool.algorithm_id,
                tool.name,
                tool.description or "",
                tool.algorithm_family,
                tool.capability_group or "",
                tool.tool_type,
                " ".join(tool.material_scope or []),
                input_fields,
            ]
        )

    @staticmethod
    def _score(task_terms: set[str], tool: AgentTool) -> tuple[float, str]:
        """计算任务词与工具文本的加权匹配得分。"""
        if not task_terms:
            return 0, "任务摘要为空，暂不自动注入"
        tool_terms = CapabilityRelevanceService._terms(
            CapabilityRelevanceService._tool_text(tool)
        )
        overlaps = sorted(task_terms & tool_terms)
        score = sum(0.25 if term in GENERIC_TERMS else 1.0 for term in overlaps)
        return score, "、".join(overlaps[:8])

    def assess(
        self,
        *,
        task_summary: str,
        tools: Sequence[AgentTool],
        protected_tool_ids: Sequence[str] = (),
        token_budget_limit: int = 0,
    ) -> tuple[CapabilityRelevanceAssessment, list[AgentTool]]:
        """评估候选工具并返回注入决策。

        Args:
            task_summary: 当前任务摘要，来自最新用户消息。
            tools: 当前用户可见且待筛选的算法工具。
            protected_tool_ids: 用户显式选择的工具 ID，不参与相关性裁剪。
            token_budget_limit: 原生工具 schema token 预算；小于等于 0 表示不限制。

        Returns:
            (相关性评估结果, 实际注入的工具列表)。
        """
        protected = set(protected_tool_ids or [])
        task_terms = self._terms(task_summary)
        ranked: list[tuple[float, int, AgentTool, float, str]] = []
        for index, tool in enumerate(tools):
            overlap, evidence = self._score(task_terms, tool)
            is_protected = tool.tool_id in protected
            relevant = is_protected or overlap >= 1.0
            confidence = 1.0 if is_protected else min(0.95, 0.55 + overlap * 0.2)
            reason = (
                "用户显式选择，保留注入"
                if is_protected
                else f"任务与工具元数据命中：{evidence}"
                if relevant
                else "任务与工具元数据无稳定匹配"
            )
            ranked.append((confidence, index, tool, overlap, reason))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected_keys: set[str] = set()
        token_used = 0
        budget_trimmed = False
        has_auto_candidate = any(tool.tool_id not in protected for tool in tools)
        for _confidence, _index, tool, overlap, _reason in ranked:
            is_protected = tool.tool_id in protected
            if not is_protected and overlap < 1.0:
                continue
            schema_tokens = self.estimate_tool_schema_tokens(tool)
            within_budget = token_budget_limit <= 0 or token_used + schema_tokens <= token_budget_limit
            if is_protected or within_budget:
                selected_keys.add(tool.tool_id)
                token_used += schema_tokens
            else:
                budget_trimmed = True

        selected_tools = [tool for tool in tools if tool.tool_id in selected_keys]
        selected_ids = [tool.tool_id for tool in selected_tools]
        omitted_ids = [tool.tool_id for tool in tools if tool.tool_id not in selected_keys]
        if not has_auto_candidate:
            selection_mode = "explicit_only"
        elif budget_trimmed:
            selection_mode = "budget_trimmed"
        else:
            selection_mode = "dynamic_with_explicit_priority"

        token_estimates = {
            tool.tool_id: self.estimate_tool_schema_tokens(tool) for tool in tools
        }
        confidence_map = {item[2].tool_id: item[0] for item in ranked}
        reason_map = {item[2].tool_id: item[4] for item in ranked}
        relevant_map = {item[2].tool_id: item[0] == 1.0 or item[3] >= 1.0 for item in ranked}
        items = [
            CapabilityRelevanceItem(
                capability_id=tool.tool_id,
                capability_kind="computation_adapter",
                relevant=relevant_map[tool.tool_id],
                confidence=round(confidence_map[tool.tool_id], 4),
                reason=reason_map[tool.tool_id],
                selected=tool.tool_id in selected_keys,
                schema_token_estimate=token_estimates[tool.tool_id],
            )
            for tool in tools
        ]
        assessment = CapabilityRelevanceAssessment(
            task_summary=task_summary[:4000],
            items=items,
            assessed_at=utc_now(),
            selection_mode=selection_mode,
            selected_capability_ids=selected_ids,
            omitted_capability_ids=omitted_ids,
            token_budget_used=token_used,
            token_budget_limit=max(0, int(token_budget_limit)),
        )
        return assessment, selected_tools
