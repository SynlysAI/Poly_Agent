"""Structured assistant API for dashboard tool guidance."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.llm_client import chat
from app.core.logging import get_logger
from app.schemas.common import ApiResponse
from app.services.integration_status_service import IntegrationStatusService
from app.services.research_engine_defaults import DEFAULT_STAGE_SEQUENCE, P0_GATE_STAGES
from app.services.research_engine_service import ResearchEngineService

logger = get_logger("poly_agent.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantMessage(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    content: str = Field(default="", max_length=8000)


class AssistantChatRequest(BaseModel):
    messages: list[AssistantMessage] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)


class AssistantAction(BaseModel):
    label: str
    type: str = "route"
    target: str
    description: str | None = None


class AssistantReference(BaseModel):
    label: str
    target: str
    type: str = "doc"


class AssistantChatResponse(BaseModel):
    content: str
    actions: list[AssistantAction] = Field(default_factory=list)
    references: list[AssistantReference] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    grounding_facts: dict = Field(default_factory=dict)
    confidence: str = "medium"
    answer_mode: str = "llm_grounded"


SYSTEM_PROMPT = (
    "你是 PolyAgent 的产品内助手。回答要简洁、可操作。"
    "只能基于 FACTS 中的项目事实回答；不要编造算法、页面、按钮或配置状态。"
    "必须区分真实/生产适配器、计算 workflow 适配器、演示 mock 算法和未配置服务。"
)

PRODUCTION_ADAPTER_IDS = {
    "literature_rag_adapter",
    "vertical_predictor_adapter",
    "mobo_alchemist_adapter",
}
COMPUTATION_ADAPTER_IDS = {
    "local_structure_adapter",
    "local_xtb_adapter",
    "orca_compute_engine_laser_adapter",
}
BRIDGE_ADAPTER_IDS = {"computation_submit_adapter"}
FORBIDDEN_UNGROUNDED_ALGORITHM_NAMES = {
    "BayesianOptimizer",
    "RandomSearch",
    "GridSearch",
    "MultiFidelityOptimizer",
}


@dataclass(frozen=True)
class GroundedAnswer:
    content: str
    confidence: str = "high"
    answer_mode: str = "deterministic"


@router.post("/chat", response_model=ApiResponse[AssistantChatResponse])
def assistant_chat(payload: AssistantChatRequest) -> ApiResponse[AssistantChatResponse]:
    """Return assistant content plus structured UI actions."""
    user_text = _latest_user_text(payload.messages)
    actions = _actions_for(user_text)
    references = _references_for(user_text)
    suggested_questions = _suggested_questions_for(user_text)
    facts = _build_grounding_facts()
    grounded_answer = _deterministic_answer(user_text, facts)

    if grounded_answer:
        content = grounded_answer.content
        confidence = grounded_answer.confidence
        answer_mode = grounded_answer.answer_mode
    else:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"FACTS:\n{_facts_for_prompt(facts)}"},
        ]
        messages.extend({"role": msg.role, "content": msg.content} for msg in payload.messages)
        try:
            content = _sanitize_llm_content(chat(messages))
            confidence = "medium"
            answer_mode = "llm_grounded"
        except Exception as exc:
            logger.warning("assistant LLM fallback: %s", exc)
            content = _fallback_content(user_text, facts)
            confidence = "medium"
            answer_mode = "fallback"

    data = AssistantChatResponse(
        content=content,
        actions=actions,
        references=references,
        suggested_questions=suggested_questions,
        grounding_facts=facts,
        confidence=confidence,
        answer_mode=answer_mode,
    )
    return ApiResponse(code=0, message="ok", data=data)


def _latest_user_text(messages: list[AssistantMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content.strip()
    return ""


def _actions_for(text: str) -> list[AssistantAction]:
    lowered = text.lower()
    actions: list[AssistantAction] = []
    if "审批" in text or "待审批" in text or "autoresearch" in lowered:
        actions.append(AssistantAction(
            label="查看待审批任务",
            target="/tasks/center?module_id=research-engine&status=blocked_approval",
            description="筛选 ResearchEngine 中等待 Gate 审批的 AutoResearch 运行。",
        ))
    if any(token in lowered for token in ("research", "autoresearch", "研发", "审批", "workflow")):
        actions.append(AssistantAction(
            label="进入 ResearchEngine",
            target="/research-engine",
            description="定义 ProblemSpec、运行 Workflow 或处理 AutoResearch 审批。",
        ))
    if any(token in lowered for token in ("计算", "xtb", "orca", "dft", "computation")):
        actions.append(AssistantAction(
            label="打开计算任务提交",
            target="/computations/submit",
            description="提交 LOCAL_STRUCTURE、LOCAL_XTB 或 ORCA 计算。",
        ))
    if any(token in lowered for token in ("alchemist", "贝叶斯", "优化", "mobo", "bo")):
        actions.append(AssistantAction(
            label="查看 Alchemist",
            target="/optimization/alchemist",
            description="进入实验设计和贝叶斯优化工具。",
        ))
    if any(token in lowered for token in ("适配器", "算法", "registry", "algorithm")):
        actions.append(AssistantAction(
            label="查看算法清单",
            target="/research-engine",
            description="在 ResearchEngine 的算法能力清单中查看真实注册条目和 Schema。",
        ))
    if not actions:
        actions.append(AssistantAction(
            label="查看任务中心",
            target="/tasks/center",
            description="查看所有计算、优化和 ResearchEngine 任务状态。",
        ))
    return actions


def _references_for(text: str) -> list[AssistantReference]:
    lowered = text.lower()
    refs: list[AssistantReference] = []
    if any(token in lowered for token in ("research", "autoresearch", "研发", "适配器", "算法")):
        refs.append(AssistantReference(label="ResearchEngine 算法清单", target="/research-engine", type="route"))
    if "autoresearch" in lowered or "审批" in text:
        refs.append(AssistantReference(label="AutoResearch 运行说明", target="doc/autoresearch-user-guide.md"))
    if "workflow" in lowered or "计算" in text:
        refs.append(AssistantReference(label="计算 Workflow 使用说明", target="doc/computation-workflows-user-guide.md"))
    return refs


def _suggested_questions_for(text: str) -> list[str]:
    lowered = text.lower()
    if "审批" in text or "autoresearch" in lowered:
        return ["如何批准 blocked_approval 阶段？", "AutoResearch 每个 Gate 会做什么？"]
    if "计算" in text or "xtb" in lowered or "orca" in lowered:
        return ["LOCAL_XTB 需要哪些输入？", "如何从 ResearchEngine 提交计算任务？"]
    return ["如何开始一个 ResearchEngine 示例？", "哪些算法是真实适配器？", "如何查看待审批任务？"]


def _build_grounding_facts() -> dict:
    """Build a compact fact packet from live project sources."""
    algorithms = _safe_list_algorithms()
    integrations = _safe_integration_status()
    production_adapters = []
    computation_adapters = []
    demo_algorithms = []
    bridge_adapters = []
    other_algorithms = []

    for item in algorithms:
        algorithm_id = item.get("algorithm_id", "")
        summary = _algorithm_summary(item)
        if algorithm_id in PRODUCTION_ADAPTER_IDS:
            production_adapters.append(summary)
        elif algorithm_id in COMPUTATION_ADAPTER_IDS:
            computation_adapters.append(summary)
        elif algorithm_id in BRIDGE_ADAPTER_IDS:
            bridge_adapters.append(summary)
        elif _is_demo_algorithm(item):
            demo_algorithms.append(summary)
        else:
            other_algorithms.append(summary)

    return {
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
        },
    }


def _safe_list_algorithms() -> list[dict]:
    try:
        result = ResearchEngineService().list_algorithms(page=1, page_size=100)
        return [item.model_dump(mode="python") for item in result.items]
    except Exception as exc:
        logger.warning("assistant algorithm grounding unavailable: %s", exc)
        return []


def _safe_integration_status() -> dict:
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


def _algorithm_summary(item: dict) -> dict:
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


def _is_demo_algorithm(item: dict) -> bool:
    ui_hints = (item.get("input_schema") or {}).get("ui_hints") or {}
    algorithm_hint = ui_hints.get("_algorithm") or {}
    validation_metric = item.get("validation_metric") or {}
    return bool(
        algorithm_hint.get("hidden_by_default")
        or algorithm_hint.get("is_demo")
        or any(str(value).lower() == "mock" for value in validation_metric.values())
        or str(item.get("algorithm_id", "")).endswith("_mock")
    )


def _deterministic_answer(text: str, facts: dict) -> GroundedAnswer | None:
    lowered = text.lower()
    if _asks_for_real_adapters(text, lowered):
        return GroundedAnswer(_adapter_answer(facts))
    if "审批" in text or "待审批" in text or "blocked_approval" in lowered:
        return GroundedAnswer(_approval_answer(facts))
    if "如何开始" in text and ("researchengine" in lowered or "research engine" in lowered or "研发" in text):
        return GroundedAnswer(_research_engine_start_answer())
    if "计算" in text and any(token in lowered for token in ("workflow", "research", "xtb", "orca", "提交")):
        return GroundedAnswer(_computation_answer(facts))
    return None


def _asks_for_real_adapters(text: str, lowered: str) -> bool:
    return (
        ("真实" in text and ("适配器" in text or "算法" in text))
        or "哪些算法是真实适配器" in text
        or "real adapter" in lowered
        or ("adapter" in lowered and ("research" in lowered or "algorithm" in lowered))
    )


def _adapter_answer(facts: dict) -> str:
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
        *_format_algorithm_lines(production),
        "",
        "计算 workflow 适配器：",
        *_format_algorithm_lines(computation),
        "",
        "桥接适配器：",
        *_format_algorithm_lines(bridge),
        "",
        "演示 mock 算法：",
        *_format_algorithm_lines(demo),
        "",
        "可用性边界：",
        f"- 文献 RAG 取决于本地索引；垂类预测取决于 VERTICAL_PREDICTOR_URL；Alchemist 取决于 alchemist-backend 状态（当前：{_service_status(status, 'alchemist-backend')}）。",
        f"- LOCAL_STRUCTURE 取决于 RDKit/OpenBabel（当前：RDKit {_service_status(status, 'rdkit')}，OpenBabel {_service_status(status, 'openbabel')}）。",
        f"- LOCAL_XTB 取决于 xTB/CREST（当前：xTB {_service_status(status, 'xtb')}，CREST {_service_status(status, 'crest')}）。",
        f"- ORCA DFT 取决于 ORCA 可执行文件和 license（当前：ORCA {_service_status(status, 'orca')}）。",
        "",
        "因此不要把未出现在 AlgorithmRegistry 中的通用优化器名称当成当前 ResearchEngine 已注册的真实适配器。",
    ]
    return "\n".join(lines)


def _approval_answer(facts: dict) -> str:
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


def _research_engine_start_answer() -> str:
    return (
        "开始 ResearchEngine 示例的实际路径是：\n\n"
        "1. 进入 `/research-engine`。\n"
        "2. 创建或实例化一个 ProblemSpec，确认材料体系、目标和约束。\n"
        "3. 创建 ExecutionDecision：选择 `manual_workbench` 或 `autoresearch`。\n"
        "4. 人工模式下选择算法清单形成 Workflow；自动模式下创建 ResearchRun 草稿。\n"
        "5. 启动 ResearchRun 后，遇到 `blocked_approval` 的 Gate 阶段再处理审批。\n\n"
        "如果只是独立提交分子计算，可以直接走 `/computations/submit`；如果要把计算结果纳入研发追溯链，应从 ResearchEngine Workflow 或 ResearchRun 进入。"
    )


def _computation_answer(facts: dict) -> str:
    status = facts.get("integration_status", {})
    return (
        "计算任务有两种入口：\n\n"
        "- 独立探索：进入 `/computations/submit`，直接提交 `LOCAL_STRUCTURE`、`LOCAL_XTB` 或 `ORCA_COMPUTE_ENGINE_LASER`。\n"
        "- 系统性研发：进入 `/research-engine`，在人工 Workflow 中使用计算适配器或 `computation_submit_adapter`，这样结果会关联 ProblemSpec、AlgorithmRun 和追溯链。\n\n"
        "当前依赖状态："
        f"RDKit {_service_status(status, 'rdkit')}，OpenBabel {_service_status(status, 'openbabel')}，"
        f"xTB {_service_status(status, 'xtb')}，CREST {_service_status(status, 'crest')}，ORCA {_service_status(status, 'orca')}。"
    )


def _format_algorithm_lines(items: list[dict]) -> list[str]:
    if not items:
        return ["- 当前 Registry 未返回该类条目。"]
    return [
        f"- `{item.get('algorithm_id')}`：{item.get('name') or '-'}；"
        f"调用方式 {item.get('call_method') or '-'}；状态 {item.get('status') or '-'}；"
        f"依赖：{item.get('runtime_dependency') or '未声明'}。"
        for item in items
    ]


def _service_status(status: dict, service: str) -> str:
    return str((status.get(service) or {}).get("status") or "unknown")


def _facts_for_prompt(facts: dict) -> str:
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
    return "\n".join(sections)


def _sanitize_llm_content(content: str) -> str:
    clean = content or ""
    for name in FORBIDDEN_UNGROUNDED_ALGORITHM_NAMES:
        clean = clean.replace(name, "未在当前 AlgorithmRegistry 中注册的通用优化器")
    return clean


def _fallback_content(text: str, facts: dict | None = None) -> str:
    facts = facts or {}
    if "审批" in text or "autoresearch" in text.lower():
        return _approval_answer(facts)
    if "计算" in text:
        return _computation_answer(facts)
    return "我可以帮你进入 ResearchEngine、提交计算任务、查看 Alchemist，或定位待审批任务。"
