"""跨 LLM 调用边界传递的轻量响应元数据。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


_MESSAGE_METADATA: ContextVar[dict[str, Any] | None] = ContextVar(
    "llm_message_metadata",
    default=None,
)
_LLM_OBSERVATION_SCOPE: ContextVar[dict[str, Any] | None] = ContextVar(
    "llm_observation_scope",
    default=None,
)


def reset_message_metadata() -> None:
    """清除当前上下文的 LLM 响应元数据。"""
    _MESSAGE_METADATA.set(None)


def record_message_metadata(metadata: dict[str, Any] | None) -> None:
    """记录当前上下文最近一次 LLM 响应元数据。

    Args:
        metadata: 包含 finish_reason / usage 等字段的元数据。
    """
    _MESSAGE_METADATA.set(dict(metadata) if metadata else None)


def get_message_metadata() -> dict[str, Any] | None:
    """读取当前上下文最近一次 LLM 响应元数据。"""
    value = _MESSAGE_METADATA.get()
    return dict(value) if value else None


def reset_llm_observation_scope() -> None:
    """清除当前上下文的 LLM 观测作用域。"""
    _LLM_OBSERVATION_SCOPE.set(None)


def record_llm_observation_scope(scope: dict[str, Any] | None) -> None:
    """记录当前上下文要关联到 LLM 生命周期事件的 run/call 信息。

    Args:
        scope: 包含 ``run_id`` / ``call_id`` 等字段的观测作用域。
    """
    _LLM_OBSERVATION_SCOPE.set(dict(scope) if scope else None)


def get_llm_observation_scope() -> dict[str, Any] | None:
    """读取当前上下文的 LLM 观测作用域。"""
    value = _LLM_OBSERVATION_SCOPE.get()
    return dict(value) if value else None
