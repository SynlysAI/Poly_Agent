"""Lightweight preset identifiers for the LUI research assistant."""

from __future__ import annotations

RESEARCH_QA_PRESET_ID = "research_qa"
RESEARCH_DEEP_PRESET_ID = "research_deep"
ASSISTANT_PRESET_IDS = frozenset(
    {RESEARCH_QA_PRESET_ID, RESEARCH_DEEP_PRESET_ID},
)


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
    return RESEARCH_DEEP_PRESET_ID if normalize_assistant_mode(mode) == "deep" else RESEARCH_QA_PRESET_ID


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
