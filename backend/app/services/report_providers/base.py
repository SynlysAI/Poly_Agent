"""Base protocol for report generation providers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol


class ReportGenerationProvider(Protocol):
    """Provider contract for structured report generation."""

    name: str
    model: str | None

    def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a JSON-compatible payload that conforms to the requested schema."""
        ...


class ReportProviderError(RuntimeError):
    """Raised when a provider cannot produce valid structured output."""


def parse_json_payload(content: str, *, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse provider text as JSON and validate required top-level fields."""
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.removeprefix("```json").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").strip()
    if cleaned.endswith("```"):
        cleaned = cleaned.removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ReportProviderError(f"Provider returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportProviderError("Provider JSON output must be an object")
    validate_schema(payload, schema or {})
    return payload


def validate_required_fields(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    required = schema.get("required") or []
    missing = [field for field in required if field not in payload]
    if missing:
        raise ReportProviderError(f"Provider JSON output missing required fields: {', '.join(missing)}")


def validate_schema(payload: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate the JSON-schema subset used by structured reports."""
    validate_required_fields(payload, schema)
    properties = schema.get("properties") or {}
    definitions = schema.get("$defs") or {}
    for key, field_schema in properties.items():
        if key not in payload:
            continue
        _validate_value(payload[key], field_schema, definitions, path=key)


def _validate_value(value: Any, schema: dict[str, Any], definitions: dict[str, Any], *, path: str) -> None:
    if "$ref" in schema:
        schema = definitions.get(str(schema["$ref"]).rsplit("/", 1)[-1], {})
    expected = schema.get("type")
    valid = {
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }
    if expected in valid and not valid[expected]:
        raise ReportProviderError(f"Provider JSON field '{path}' must be {expected}")
    if expected == "string" and len(value.strip()) < int(schema.get("minLength", 0)):
        raise ReportProviderError(f"Provider JSON field '{path}' must not be empty")
    if expected == "array":
        if len(value) < int(schema.get("minItems", 0)):
            raise ReportProviderError(f"Provider JSON field '{path}' has too few items")
        item_schema = schema.get("items") or {}
        for index, item in enumerate(value):
            _validate_value(item, item_schema, definitions, path=f"{path}[{index}]")
    if expected == "object":
        validate_required_fields(value, schema)
        for key, field_schema in (schema.get("properties") or {}).items():
            if key in value:
                _validate_value(value[key], field_schema, definitions, path=f"{path}.{key}")


def complete_with_json_retries(
    *,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    options: dict[str, Any],
    max_retries: int,
    generate: Callable[[list[dict[str, Any]]], str],
) -> dict[str, Any]:
    """Call a text provider until it returns schema-valid JSON or retries are exhausted."""
    attempt_messages = [dict(item) for item in messages]
    last_error: ReportProviderError | None = None
    for attempt in range(max_retries + 1):
        try:
            return parse_json_payload(generate(attempt_messages), schema=schema)
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
                        f"必须严格遵守此 JSON Schema：{json.dumps(schema, ensure_ascii=False)[:12000]}"
                    ),
                },
            ]
    raise last_error or ReportProviderError("Provider did not return schema-valid JSON")
