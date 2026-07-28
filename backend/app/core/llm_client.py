"""LLM 客户端 — 基于 OpenAI 兼容接口的统一 LLM 调用模块。"""

from __future__ import annotations

from collections.abc import Iterator

from openai import OpenAI

from app.core.config import settings
from app.services.llm_model_service import LLMModelService


_client: OpenAI | None = None


def get_client() -> OpenAI:
    """获取全局 LLM 客户端实例。"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    return _client


def chat(messages: list[dict], **kwargs) -> str:
    """发送对话请求并返回模型回复文本。

    Args:
        messages: 标准 OpenAI 消息列表。
        **kwargs: 透传给 chat.completions.create 的额外参数。

    Returns:
        模型回复的文本内容。
    """
    provider_id = kwargs.pop("provider_id", None)
    model = kwargs.pop("model", None)
    purpose = kwargs.pop("purpose", "qa")
    if provider_id or model:
        return LLMModelService().complete_text(
            messages=messages,
            purpose=purpose,
            provider_id=provider_id,
            model=model,
            **kwargs,
        )
    return LLMModelService().complete_text(messages=messages, purpose=purpose, **kwargs)


def chat_stream(messages: list[dict], **kwargs) -> Iterator[str]:
    """发送对话请求并逐段返回模型回复文本。"""
    provider_id = kwargs.pop("provider_id", None)
    model = kwargs.pop("model", None)
    purpose = kwargs.pop("purpose", "qa")
    if provider_id or model:
        yield from LLMModelService().stream_text(
            messages=messages,
            purpose=purpose,
            provider_id=provider_id,
            model=model,
            **kwargs,
        )
        return
    yield from LLMModelService().stream_text(messages=messages, purpose=purpose, **kwargs)
