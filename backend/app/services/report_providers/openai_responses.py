"""OpenAI Responses API report provider."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.core.config import settings
from app.services.report_providers.base import complete_with_json_retries


class OpenAIResponsesReportProvider:
    """Use OpenAI Responses API with structured JSON output."""

    name = "openai_responses"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.report_llm_api_key
        self.model = model or settings.report_llm_model

    def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        client = OpenAI(
            api_key=self.api_key,
            max_retries=int(options.get("transport_max_retries", settings.report_llm_max_retries)),
        )
        def generate(attempt_messages: list[dict[str, Any]]) -> str:
            response = client.responses.create(
                model=self.model,
                input=attempt_messages,
                temperature=options.get("temperature", 0.2),
                timeout=options.get("timeout", settings.report_llm_timeout_seconds),
                store=bool(options.get("store", settings.report_llm_store)),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "structured_report",
                        "schema": schema,
                        "strict": False,
                    }
                },
            )
            output_text = getattr(response, "output_text", None)
            if output_text is None:
                output_text = self._extract_output_text(response)
            return output_text or ""

        return complete_with_json_retries(
            messages=messages,
            schema=schema,
            options=options,
            max_retries=int(options.get("max_retries", settings.report_llm_max_retries)),
            generate=generate,
        )

    def _extract_output_text(self, response: Any) -> str:
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks)
