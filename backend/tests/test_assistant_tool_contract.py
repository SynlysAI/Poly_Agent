"""Assistant 工具契约适配器单元测试。"""

from __future__ import annotations

from app.schemas.agent_tools import AgentTool, AgentToolPolicy
from app.schemas.research_engine import AlgorithmAssetSpec, AlgorithmIOSchema
from app.services.assistant_provider_errors import classify_provider_error
from app.services.assistant_tool_contract import (
    build_json_schema,
    missing_inputs,
    normalize_provider_arguments,
    safe_function_name,
    schema_digest,
    validate_arguments,
)


def _tool() -> AgentTool:
    """构造覆盖全部约束类型的算法工具。"""
    policy = AgentToolPolicy(algorithm_id="vertical/tool:a")
    return AgentTool(
        tool_id="algorithm:vertical/tool:a",
        algorithm_id="vertical/tool:a",
        name="Vertical Tool",
        description="预测聚合物性质",
        algorithm_family="vertical_prediction",
        tool_type="predictor",
        source="builtin",
        active_version_id="version-1",
        version="1.0.0",
        input_schema=AlgorithmIOSchema(
            fields={
                "smiles": "string - SMILES",
                "temperature": "number - 温度",
                "count": "integer - 数量",
                "mode": "string - 模式",
                "enabled": "boolean - 是否启用",
                "materials": "list[string] - 物料",
                "meta": "dict - 元数据",
            },
            required=["smiles", "temperature"],
            constraints={
                "temperature": {"minimum": 0, "maximum": 500},
                "smiles": {"min_length": 2, "max_length": 100, "pattern": "[A-Za-z0-9]+"},
            },
            field_defaults={"temperature": 298},
            field_options={"mode": ["fast", "accurate"]},
        ),
        output_schema=AlgorithmIOSchema(),
        input_assets=[AlgorithmAssetSpec(key="structure", label="结构文件", required=True)],
        policy=policy,
        requires_confirmation=True,
        phase="available",
        health_status="healthy",
    )


def test_safe_function_name_is_stable_and_collision_free() -> None:
    first = safe_function_name("algorithm:vertical/tool:a")
    second = safe_function_name("algorithm:vertical/tool:b")
    assert first == safe_function_name("algorithm:vertical/tool:a")
    assert first != second
    assert len(first) <= 64
    assert first.startswith("algorithm_vertical_tool_a_")


def test_build_json_schema_contains_contract_constraints() -> None:
    schema = build_json_schema(_tool())
    properties = schema["properties"]
    assert schema["type"] == "object"
    assert schema["required"] == ["smiles", "temperature"]
    assert schema["additionalProperties"] is False
    assert properties["temperature"] == {
        "type": "number",
        "description": "number - 温度",
        "minimum": 0,
        "maximum": 500,
        "default": 298,
    }
    assert properties["smiles"]["minLength"] == 2
    assert properties["smiles"]["maxLength"] == 100
    assert properties["smiles"]["pattern"] == "[A-Za-z0-9]+"
    assert properties["mode"]["enum"] == ["fast", "accurate"]
    assert properties["materials"]["items"] == {"type": "string"}
    assert properties["meta"]["additionalProperties"] is True


def test_validate_arguments_reports_constraint_errors() -> None:
    missing, errors = validate_arguments(
        _tool(),
        {"smiles": "C", "temperature": 600, "mode": "slow"},
    )
    assert missing == []
    assert errors["temperature"] == "参数不能大于 500"
    assert errors["mode"] == "参数值不在允许范围: fast, accurate"


def test_missing_inputs_combines_fields_and_required_assets() -> None:
    result = missing_inputs(_tool(), {}, {})
    assert result["fields"] == ["smiles", "temperature"]
    assert [item.key for item in result["assets"]] == ["structure"]


def test_normalize_provider_arguments_preserves_malformed_output() -> None:
    parsed = normalize_provider_arguments('{"smiles": "CCO"')
    assert parsed.arguments == {}
    assert parsed.raw_arguments == '{"smiles": "CCO"'
    assert parsed.parse_error

    non_object = normalize_provider_arguments('["CCO"]')
    assert non_object.arguments == {}
    assert non_object.parse_error == "参数必须是 JSON 对象"


def test_schema_digest_is_stable_and_sensitive_to_version() -> None:
    tool = _tool()
    assert schema_digest(tool) == schema_digest(tool)
    changed = tool.model_copy(update={"active_version_id": "version-2"})
    assert schema_digest(tool) != schema_digest(changed)


def test_classify_provider_error_codes() -> None:
    class AuthenticationError(Exception):
        status_code = 401

    class APITimeoutError(Exception):
        pass

    class NotFoundError(Exception):
        status_code = 404

    assert classify_provider_error(AuthenticationError())["code"] == "PROVIDER_AUTH_FAILED"
    assert classify_provider_error(APITimeoutError())["code"] == "PROVIDER_TIMEOUT"
    assert classify_provider_error(NotFoundError())["code"] == "MODEL_NOT_FOUND"
