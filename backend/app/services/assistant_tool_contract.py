"""Assistant 算法工具的统一模型契约适配器。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.schemas.agent_tools import AgentTool


SENSITIVE_KEYS = {
    "access-key",
    "api_key",
    "api-key",
    "access_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "secret-key",
    "secret_key",
    "token",
}


@dataclass(frozen=True)
class ProviderArguments:
    """模型原始 arguments 与解析结果。"""

    arguments: dict[str, Any]
    raw_arguments: str
    parse_error: str | None


def safe_function_name(tool_id: str) -> str:
    """生成稳定、短且防冲突的 provider function name。

    Args:
        tool_id: 平台工具 ID，例如 algorithm:xxx。

    Returns:
        不超过 64 字符且带稳定 hash 后缀的安全函数名。
    """
    base = re.sub(r"[^A-Za-z0-9_-]", "_", str(tool_id or ""))
    digest = hashlib.sha256(str(tool_id or "").encode("utf-8")).hexdigest()[:12]
    suffix = f"_{digest}"
    max_base = 64 - len(suffix)
    return f"{base[:max_base]}{suffix}"


def _json_type(description: str) -> dict[str, Any]:
    """从算法字段描述解析 JSON Schema 类型。

    Args:
        description: 形如 `list[string] - 物料列表` 的字段描述。

    Returns:
        JSON Schema 类型节点。
    """
    token = str(description or "").strip().split(" -", 1)[0].strip().lower()
    scalar_types = {
        "string": "string",
        "str": "string",
        "text": "string",
        "number": "number",
        "float": "number",
        "integer": "integer",
        "int": "integer",
        "boolean": "boolean",
        "bool": "boolean",
    }
    list_match = re.match(r"^(?:list|array)(?:\[(.*)\])?$", token)
    dict_match = re.match(r"^(?:dict|map)(?:\[(.*)\])?$", token)
    if list_match:
        result: dict[str, Any] = {"type": "array"}
        inner = (list_match.group(1) or "").strip()
        if inner:
            result["items"] = {"type": scalar_types.get(inner, "string")}
        return result
    if dict_match:
        return {"type": "object", "additionalProperties": True}
    return {"type": scalar_types.get(token, "string")}


def build_json_schema(tool: AgentTool) -> dict[str, Any]:
    """把 AlgorithmIOSchema 转换为模型与服务端共用的 JSON Schema。

    Args:
        tool: 当前可调用的算法工具。

    Returns:
        JSON Schema object schema。
    """
    schema = tool.input_schema
    properties: dict[str, Any] = {}
    for field_name, description in (schema.fields or {}).items():
        prop: dict[str, Any] = {"description": str(description or "").strip()}
        prop.update(_json_type(str(description)))
        options = list((schema.field_options or {}).get(field_name) or [])
        if options:
            prop["enum"] = options
        constraints = (schema.constraints or {}).get(field_name) or {}
        if isinstance(constraints, dict):
            for source, target in (
                ("minimum", "minimum"),
                ("maximum", "maximum"),
                ("min_length", "minLength"),
                ("max_length", "maxLength"),
                ("pattern", "pattern"),
            ):
                if constraints.get(source) is not None:
                    prop[target] = constraints[source]
        if field_name in (schema.field_defaults or {}):
            prop["default"] = schema.field_defaults[field_name]
        properties[field_name] = prop

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if schema.required:
        result["required"] = list(schema.required)
    return result


def build_function_tool(tool: AgentTool) -> dict[str, Any]:
    """生成 OpenAI-compatible chat tools 的 function 定义。

    Args:
        tool: 当前可调用的算法工具。

    Returns:
        `{"type": "function", ...}` 结构。
    """
    description_parts = [str(tool.description or tool.name)]
    if tool.input_assets:
        keys = ", ".join(spec.key for spec in tool.input_assets)
        description_parts.append(f"文件输入由用户在界面补充，不要放入参数: {keys}")
    return {
        "type": "function",
        "function": {
            "name": tool.function_name or safe_function_name(tool.tool_id),
            "description": " ".join(description_parts),
            "parameters": build_json_schema(tool),
        },
    }


def validate_arguments(tool: AgentTool, arguments: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    """按统一 JSON Schema 语义校验模型或用户提交的参数。

    Args:
        tool: 当前工具契约。
        arguments: 待校验参数。

    Returns:
        (缺失必填字段, 字段级错误)。
    """
    schema = tool.input_schema
    fields = schema.fields or {}
    errors: dict[str, str] = {}
    sensitive = sorted(set(arguments) & SENSITIVE_KEYS)
    if sensitive:
        errors["__sensitive__"] = "对话参数不能包含凭据字段: " + ", ".join(sensitive)
    unknown = sorted(set(arguments) - set(fields))
    if unknown:
        errors["__unknown__"] = "参数不在算法契约中: " + ", ".join(unknown)

    missing = [
        field
        for field in schema.required
        if field not in arguments or arguments[field] is None or arguments[field] == ""
    ]
    json_schema = build_json_schema(tool)
    for field, value in arguments.items():
        if field not in fields:
            continue
        expected = json_schema["properties"][field].get("type", "object")
        valid = (
            expected == "string" and isinstance(value, str)
            or expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)
            or expected == "integer" and isinstance(value, int) and not isinstance(value, bool)
            or expected == "boolean" and isinstance(value, bool)
            or expected == "array" and isinstance(value, list)
            or expected == "object" and isinstance(value, dict)
        )
        if not valid:
            errors[field] = f"参数类型不匹配，期望 {expected}"
            continue
        allowed = (schema.field_options or {}).get(field) or []
        if allowed and value not in allowed:
            errors[field] = f"参数值不在允许范围: {', '.join(str(item) for item in allowed)}"
        constraints = (schema.constraints or {}).get(field) or {}
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if constraints.get("minimum") is not None and value < constraints["minimum"]:
                errors[field] = f"参数不能小于 {constraints['minimum']}"
            if constraints.get("maximum") is not None and value > constraints["maximum"]:
                errors[field] = f"参数不能大于 {constraints['maximum']}"
        if isinstance(value, str):
            if constraints.get("min_length") is not None and len(value) < constraints["min_length"]:
                errors[field] = f"参数长度不能小于 {constraints['min_length']}"
            if constraints.get("max_length") is not None and len(value) > constraints["max_length"]:
                errors[field] = f"参数长度不能大于 {constraints['max_length']}"
            if constraints.get("pattern") and not re.fullmatch(str(constraints["pattern"]), value):
                errors[field] = "参数格式不符合约束"
    return missing, errors


def missing_inputs(
    tool: AgentTool,
    arguments: dict[str, Any],
    asset_refs: dict[str, Any],
    uploaded_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """计算待补充参数与待上传资产。

    Args:
        tool: 当前工具契约。
        arguments: 当前参数。
        asset_refs: 已绑定的资产引用。
        uploaded_assets: 本次请求已上传的资产摘要。

    Returns:
        包含 fields 与 assets 的缺失输入描述。
    """
    missing_fields, _errors = validate_arguments(tool, arguments or {})
    uploaded_keys = {str(item.get("asset_key")) for item in (uploaded_assets or [])}
    missing_assets = [
        spec
        for spec in tool.input_assets
        if spec.required and spec.key not in (asset_refs or {}) and spec.key not in uploaded_keys
    ]
    return {"fields": missing_fields, "assets": missing_assets}


def schema_digest(tool: AgentTool) -> str:
    """计算工具输入契约的稳定摘要。

    Args:
        tool: 当前工具。

    Returns:
        16 位十六进制 SHA-256 摘要。
    """
    payload = {
        "tool_id": tool.tool_id,
        "algorithm_id": tool.algorithm_id,
        "active_version_id": tool.active_version_id,
        "version": tool.version,
        "input_schema": tool.input_schema.model_dump(mode="python", by_alias=True, exclude_none=True),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def normalize_provider_arguments(raw_arguments: Any) -> ProviderArguments:
    """保留模型原始 arguments 并安全解析为对象。

    Args:
        raw_arguments: provider 返回的原始字符串或已解析对象。

    Returns:
        包含解析结果、原始输出和解析错误的 ProviderArguments。
    """
    if raw_arguments is None:
        raw_arguments = "{}"
    if isinstance(raw_arguments, dict):
        return ProviderArguments(
            arguments=raw_arguments,
            raw_arguments=json.dumps(raw_arguments, ensure_ascii=False, sort_keys=True),
            parse_error=None,
        )
    raw = str(raw_arguments)
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return ProviderArguments(arguments={}, raw_arguments=raw, parse_error=str(exc))
    if not isinstance(parsed, dict):
        return ProviderArguments(arguments={}, raw_arguments=raw, parse_error="参数必须是 JSON 对象")
    return ProviderArguments(arguments=parsed, raw_arguments=raw, parse_error=None)
