"""OpenAI-compatible chat completions report provider."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.core.config import settings
from app.services.report_providers.base import complete_with_json_retries


class OpenAICompatibleReportProvider:
    """Use an OpenAI-compatible Chat Completions endpoint for reports."""

    name = "openai_compatible"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.report_llm_api_key
        self.base_url = base_url if base_url is not None else settings.report_llm_base_url
        self.model = model or settings.report_llm_model

    def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        client = OpenAI(api_key=self.api_key or "EMPTY", base_url=self.base_url or None)
        def generate(attempt_messages: list[dict[str, Any]]) -> str:
            response = client.chat.completions.create(
                model=self.model,
                messages=attempt_messages,
                temperature=options.get("temperature", 0.2),
                timeout=options.get("timeout", settings.report_llm_timeout_seconds),
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or ""

        return complete_with_json_retries(
            messages=messages,
            schema=schema,
            options=options,
            max_retries=int(options.get("max_retries", settings.report_llm_max_retries)),
            generate=generate,
        )
