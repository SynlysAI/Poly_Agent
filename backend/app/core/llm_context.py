"""跨 LLM 调用边界传递的轻量响应元数据。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


_MESSAGE_METADATA: ContextVar[dict[str, Any] | None] = ContextVar(
    "llm_message_metadata",
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
