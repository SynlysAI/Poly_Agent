"""LLM provider 配置 schema 目录与文档生成服务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.llm_models import LLMConfigFieldDoc
from app.schemas.llm_models import LLMConfigSchemaData
from app.schemas.llm_models import LLMModelConfigInput
from app.schemas.llm_models import LLMProviderConfigInput


PROVIDER_DEFAULT_OVERRIDES: dict[str, Any] = {
    "provider_type": "openai_compatible",
    "models": [],
    "capabilities": ["chat"],
    "recommended_for": [],
}
"""JSON schema 不包含 default_factory 默认值，这里补充展示用默认值。"""

MODEL_DEFAULT_OVERRIDES: dict[str, Any] = {
    "display_name": None,
    "capabilities": None,
    "recommended_for": None,
    "context_window": None,
    "max_output_tokens": None,
    "tool_protocol": None,
    "supports_parallel_tool_calls": None,
}
"""LLMModelConfigInput 展示用默认值覆盖。"""


def _schema_properties(model: type) -> dict[str, Any]:
    """读取 Pydantic 模型的 JSON Schema 顶层 properties。"""
    return dict(model.model_json_schema().get("properties") or {})


def _type_label(prop: dict[str, Any]) -> str:
    """将 JSON Schema property 转换为 Admin 页可读类型。"""
    any_of = prop.get("anyOf")
    if any_of:
        non_null = [item for item in any_of if item.get("type") != "null"]
        if len(non_null) == 1 and non_null[0].get("type") == "array":
            return _type_label(non_null[0])
        return " | ".join(_type_label(item) for item in non_null if item.get("type") != "null") or "null"
    prop_type = prop.get("type")
    if prop_type == "array":
        items = prop.get("items") or {}
        if "$ref" in items:
            return "array<LLMModelConfigInput>"
        if "anyOf" in items:
            item_types: list[str] = []
            for item in items["anyOf"]:
                if item.get("type") == "null":
                    continue
                if "$ref" in item:
                    item_types.append("LLMModelConfigInput")
                else:
                    item_types.append(item.get("type", "object"))
            return f"array<{' | '.join(item_types) or 'object'}>"
        return f"array<{items.get('type') or 'object'}>"
    return str(prop_type or "object")


def _constraints(prop: dict[str, Any]) -> dict[str, Any]:
    """提取字段约束，供文档和 Admin 页展示。"""
    keys = (
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "pattern",
        "additionalProperties",
    )
    constraints: dict[str, Any] = {}
    for key in keys:
        if key in prop:
            constraints[key] = prop[key]
    items = prop.get("items") or {}
    if isinstance(items, dict) and items.get("enum"):
        constraints["items_enum"] = items["enum"]
    return constraints


def _default_value(
    field_name: str,
    prop: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> Any:
    """返回字段默认值；有手工覆盖时优先使用。"""
    if overrides and field_name in overrides:
        return overrides[field_name]
    return prop.get("default")


def _field_docs(
    properties: dict[str, Any],
    *,
    error_prefix: str,
    overrides: dict[str, Any] | None = None,
) -> list[LLMConfigFieldDoc]:
    """把 schema properties 转换为字段目录。"""
    docs: list[LLMConfigFieldDoc] = []
    for field_name, prop in properties.items():
        docs.append(
            LLMConfigFieldDoc(
                field_name=field_name,
                description=str(prop.get("description") or "").strip(),
                type=_type_label(prop),
                default_value=_default_value(field_name, prop, overrides),
                constraints=_constraints(prop),
                error_path=f"{error_prefix}.{field_name}",
            )
        )
    return docs


def build_config_schema_data() -> LLMConfigSchemaData:
    """从 Pydantic schema 生成 provider 与 per-model 配置字段目录。"""
    provider_properties = _schema_properties(LLMProviderConfigInput)
    model_properties = _schema_properties(LLMModelConfigInput)
    return LLMConfigSchemaData(
        provider_fields=_field_docs(
            provider_properties,
            error_prefix="LLM_PROVIDER_CONFIGS_FILE[].<provider>",
            overrides=PROVIDER_DEFAULT_OVERRIDES,
        ),
        per_model_fields=_field_docs(
            model_properties,
            error_prefix="LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[]",
            overrides=MODEL_DEFAULT_OVERRIDES,
        ),
    )


def _format_default(value: Any) -> str:
    """格式化默认值，避免列表直接拼接。"""
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _format_constraints(constraints: dict[str, Any]) -> str:
    """将约束字典压缩为一行可读文本。"""
    if not constraints:
        return "-"
    return "；".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}"
        for key, value in constraints.items()
    )


def render_config_schema_markdown(data: LLMConfigSchemaData | None = None) -> str:
    """把配置字段目录渲染为 Markdown。"""
    data = data or build_config_schema_data()
    lines = [
        "# LLM Provider 配置 Schema",
        "",
        f"> 生成自 `{data.generated_from}`，schema version：{data.schema_version}。",
        "",
        "本页与 `docs/llm-provider-config-schema.json` 同源。配置错误路径用于定位环境变量 JSON 或 `backend/config/llm.providers.json` 中的具体字段。",
        "",
        "## Provider 字段",
        "",
        "| 字段 | 说明 | 类型 | 默认值 | 约束 | 错误路径 |",
        "|---|---|---|---|---|---|",
    ]
    for field in data.provider_fields:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{field.field_name}`",
                    field.description or "-",
                    field.type,
                    _format_default(field.default_value),
                    _format_constraints(field.constraints),
                    f"`{field.error_path}`",
                ]
            )
            + " |"
        )
    lines.extend(["", "## Per-model 字段", "", "| 字段 | 说明 | 类型 | 默认值 | 约束 | 错误路径 |", "|---|---|---|---|---|---|"])
    for field in data.per_model_fields:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{field.field_name}`",
                    field.description or "-",
                    field.type,
                    _format_default(field.default_value),
                    _format_constraints(field.constraints),
                    f"`{field.error_path}`",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_config_schema_docs(project_root: Path) -> dict[str, Path]:
    """生成 Markdown 与 JSON 配置 schema 文档。"""
    doc_dir = project_root / "docs"
    doc_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = doc_dir / "llm-provider-config-schema.md"
    json_path = doc_dir / "llm-provider-config-schema.json"
    markdown_path.write_text(render_config_schema_markdown(), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            LLMProviderConfigInput.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"markdown": markdown_path, "json": json_path}
