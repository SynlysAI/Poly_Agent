"""Lightweight preset identifiers for the LUI research assistant."""

from __future__ import annotations

from app.schemas.assistant_budget import (
    AssistantPreset,
    BudgetPolicy,
    ClassificationPolicy,
    ExecutionPolicy,
)


RESEARCH_QA_PRESET_ID = "research_qa"
RESEARCH_DEEP_PRESET_ID = "research_deep"
ASSISTANT_PRESET_IDS = frozenset(
    {RESEARCH_QA_PRESET_ID, RESEARCH_DEEP_PRESET_ID},
)
CLASSIFICATION_POLICY = ClassificationPolicy(
    simple_keywords=("入口", "在哪里", "怎么打开", "是什么", "列表", "状态"),
    complex_keywords=("比较", "对比", "综合", "分析", "推导", "方案", "评估", "多来源", "冲突"),
    high_risk_keywords=("执行算法", "运行算法", "提交", "删除", "覆盖", "正式报告", "发布"),
    explainability_keywords=("解释", "依据", "来源", "可解释", "为什么"),
)
BUDGET_POLICY = BudgetPolicy(
    default_mode="shadow",
    model_purposes={"simple": "qa", "complex": "deep", "high_risk": "deep"},
    retrieval_tiers={
        "simple": "vector",
        "complex": "hybrid_reranker",
        "high_risk": "hybrid_reranker",
    },
    execution_tiers={
        "simple": "one_shot",
        "complex": "planning",
        "high_risk": "planning_verification_human",
    },
    allow_deep_simple_downgrade=True,
)
EXECUTION_POLICY = ExecutionPolicy()
ASSISTANT_PRESETS: dict[str, AssistantPreset] = {
    RESEARCH_QA_PRESET_ID: AssistantPreset(
        preset_id=RESEARCH_QA_PRESET_ID,
        mode="qa",
        route_purpose="qa",
        display_name="科研问答",
        classification_policy=CLASSIFICATION_POLICY,
        budget_policy=BUDGET_POLICY,
        execution_policy=EXECUTION_POLICY,
    ),
    RESEARCH_DEEP_PRESET_ID: AssistantPreset(
        preset_id=RESEARCH_DEEP_PRESET_ID,
        mode="deep",
        route_purpose="deep",
        display_name="深度科研",
        classification_policy=CLASSIFICATION_POLICY,
        budget_policy=BUDGET_POLICY,
        execution_policy=EXECUTION_POLICY,
    ),
}


def normalize_assistant_mode(mode: str | None) -> str:
    """归一化旧版助手模式，并保留内部模型说明回退模式。"""
    normalized = str(mode or "qa").strip().lower()
    if normalized not in {"qa", "deep", "model"}:
        return "qa"
    return normalized


def assistant_preset_from_mode(mode: str | None) -> str:
    """将旧版助手模式映射到两个科研 Preset 之一。

    Args:
        mode: 旧版 `qa` / `deep` / `model` 模式值。

    Returns:
        权威科研 Preset ID；无效值和旧版兜底值回落到 `research_qa`。
    """
    normalized = normalize_assistant_mode(mode)
    return (
        RESEARCH_DEEP_PRESET_ID
        if normalized == "deep"
        else RESEARCH_QA_PRESET_ID
    )


def assistant_mode_from_preset(preset_id: str | None) -> str:
    """将科研 Preset 映射为兼容模式。

    Args:
        preset_id: 科研 Preset ID。

    Returns:
        `research_deep` 返回 `deep`，其余返回 `qa`。
    """
    return "deep" if str(preset_id or "").strip().lower() == RESEARCH_DEEP_PRESET_ID else "qa"


def resolve_assistant_runtime(preset_id: str | None, mode: str | None) -> tuple[str, str]:
    """解析权威 Preset 及其兼容模式。

    Args:
        preset_id: 新客户端或持久化会话提供的 Preset ID。
        mode: 旧客户端或历史文档提供的兼容模式。

    Returns:
        `(preset_id, mode)` 二元组。有效 Preset 优先；没有 Preset 时保留旧模式
        （包括内部 `model` 回退）并映射到默认 Preset。
    """
    candidate = str(preset_id or "").strip().lower()
    if candidate in ASSISTANT_PRESET_IDS:
        return candidate, assistant_mode_from_preset(candidate)
    normalized_mode = normalize_assistant_mode(mode)
    return assistant_preset_from_mode(normalized_mode), normalized_mode


def assistant_route_purpose(preset_id: str | None) -> str:
    """返回科研 Preset 的静态模型路由用途。

    Args:
        preset_id: 科研 Preset ID。

    Returns:
        `research_deep` 返回 `deep`，其余返回 `qa`。
    """
    return "deep" if assistant_mode_from_preset(preset_id) == "deep" else "qa"


def get_assistant_preset(preset_id: str | None) -> AssistantPreset:
    """返回权威科研 Preset 契约。

    Args:
        preset_id: 科研 Preset ID。

    Returns:
        有效 Preset 契约；无效值回退到 `research_qa`。
    """
    return ASSISTANT_PRESETS.get(
        str(preset_id or "").strip().lower(),
        ASSISTANT_PRESETS[RESEARCH_QA_PRESET_ID],
    )
