"""LLM 客户端 — 基于 OpenAI 兼容接口的统一 LLM 调用模块。"""

from __future__ import annotations

from openai import OpenAI

from app.core.config import settings


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
    client = get_client()
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        **kwargs,
    )
    return response.choices[0].message.content
