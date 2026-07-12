"""Local Ollama report provider."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings
from app.services.report_providers.base import complete_with_json_retries


class LocalOllamaReportProvider:
    """Use a local Ollama generate endpoint for draft reports."""

    name = "local_ollama"

    def __init__(self, *, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.report_ollama_base_url).rstrip("/")
        self.model = model or settings.report_ollama_model

    def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        with httpx.Client(timeout=options.get("timeout", settings.report_llm_timeout_seconds)) as client:
            def generate(attempt_messages: list[dict[str, Any]]) -> str:
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": self._messages_to_prompt(attempt_messages, schema),
                        "stream": False,
                        "format": "json",
                    },
                )
                response.raise_for_status()
                data = response.json()
                return str(data.get("response") or "")

            return complete_with_json_retries(
                messages=messages,
                schema=schema,
                options=options,
                max_retries=int(options.get("max_retries", settings.report_llm_max_retries)),
                generate=generate,
            )

    def _messages_to_prompt(self, messages: list[dict[str, Any]], schema: dict[str, Any]) -> str:
        body = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in messages)
        return (
            "Return only JSON matching this schema. Do not include markdown fences.\n"
            f"Schema: {json.dumps(schema, ensure_ascii=False)}\n\n"
            f"{body}"
        )
