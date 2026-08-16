"""算法版本模型提案解析与兜底生成。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PACKAGE_SAMPLE_SOURCE = "package_sample_input"
CONTRACT_SAMPLE_SOURCE = "contract_sample_input"
SCHEMA_FALLBACK_SOURCE = "schema_fallback"


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """读取 JSON object 文件，失败或类型不匹配时返回 None。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _type_token(field_name: str, description: Any, field_types: dict[str, Any]) -> str:
    """从显式类型或字段描述中提取类型 token。"""
    explicit = str(field_types.get(field_name) or "").strip().lower()
    if explicit:
        return explicit
    return str(description or "string").split(" -", 1)[0].strip().lower()


def _fallback_value(
    field_name: str,
    description: Any,
    field_types: dict[str, Any],
    constraints: dict[str, Any],
) -> Any:
    """按字段类型生成确定性兜底值。"""
    token = _type_token(field_name, description, field_types)
    if token in {"number", "float"}:
        return constraints.get("minimum", 0.0)
    if token in {"integer", "int"}:
        return int(constraints.get("minimum", 0))
    if token in {"boolean", "bool"}:
        return False
    if token in {"array", "list"} or re.match(r"^(?:array|list)(?:\[.*\])?$", token):
        return []
    if token in {"object", "dict", "map"} or re.match(r"^(?:dict|map|object)(?:\[.*\])?$", token):
        return {}
    return "string"


def build_model_proposal_from_schema(input_schema: dict[str, Any] | None) -> dict[str, Any]:
    """根据输入契约生成 model_proposal。"""
    schema = input_schema or {}
    fields = schema.get("fields") or {}
    field_types = schema.get("field_types") or {}
    field_defaults = schema.get("field_defaults") or {}
    field_options = schema.get("field_options") or {}
    constraints = schema.get("constraints") or {}
    proposal: dict[str, Any] = {}
    for field_name, description in fields.items():
        if field_name in field_defaults:
            proposal[field_name] = field_defaults[field_name]
            continue
        options = field_options.get(field_name) or []
        if options:
            proposal[field_name] = options[0]
            continue
        proposal[field_name] = _fallback_value(
            str(field_name),
            description,
            field_types,
            constraints.get(str(field_name)) or {},
        )
    return proposal


def resolve_model_proposal(version_doc: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """解析版本级模型提案。"""
    package_path = version_doc.get("package_path")
    if package_path:
        sample_path = Path(str(package_path)) / "tests" / "sample_input.json"
        package_proposal = _read_json_object(sample_path)
        if package_proposal is not None:
            return package_proposal, PACKAGE_SAMPLE_SOURCE

    contract = version_doc.get("contract") or {}
    contract_proposal = contract.get("sample_input")
    if isinstance(contract_proposal, dict):
        return contract_proposal, CONTRACT_SAMPLE_SOURCE

    return (
        build_model_proposal_from_schema(version_doc.get("input_schema")),
        SCHEMA_FALLBACK_SOURCE,
    )
