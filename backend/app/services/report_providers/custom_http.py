"""Custom HTTP report provider for internal LLM gateways."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.services.report_providers.base import ReportProviderError, parse_json_payload, validate_required_fields


class CustomHttpReportProvider:
    """Call a configured HTTP endpoint that returns structured report JSON."""

    name = "custom_http"

    def __init__(self, *, endpoint_url: str | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self.endpoint_url = endpoint_url or settings.report_llm_base_url
        self.api_key = api_key if api_key is not None else settings.report_llm_api_key
        self.model = model or settings.report_llm_model

    def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempt_messages = [dict(item) for item in messages]
        max_retries = int(options.get("max_retries", settings.report_llm_max_retries))
        last_error: ReportProviderError | None = None
        with httpx.Client(timeout=options.get("timeout", settings.report_llm_timeout_seconds)) as client:
            for attempt in range(max_retries + 1):
                payload = {
                    "model": self.model,
                    "messages": attempt_messages,
                    "schema": schema,
                    "options": options,
                }
                response = client.post(self.endpoint_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                try:
                    return self._coerce_payload(data, schema=schema)
                except ReportProviderError as exc:
                    last_error = exc
                    if attempt >= max_retries:
                        break
                    attempt_messages = [
                        *attempt_messages,
                        {
                            "role": "user",
                            "content": (
                                "上一轮输出不是符合 schema 的 JSON。"
                                f"错误：{exc}。请只返回一个 JSON object，不要 Markdown。"
                            ),
                        },
                    ]

        raise last_error or ReportProviderError("Custom HTTP provider did not return schema-valid JSON")

    def _coerce_payload(self, data: Any, *, schema: dict[str, Any]) -> dict[str, Any]:
        if isinstance(data, dict):
            for key in ("data", "output", "result", "report"):
                nested = data.get(key)
                if isinstance(nested, dict):
                    validate_required_fields(nested, schema)
                    return nested
            for key in ("content", "text", "output_text"):
                nested_text = data.get(key)
                if isinstance(nested_text, str):
                    return parse_json_payload(nested_text, schema=schema)
            validate_required_fields(data, schema)
            return data

        return parse_json_payload(str(data), schema=schema)
