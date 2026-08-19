"""Assistant Context Assembler 单元测试。"""

from __future__ import annotations

from app.schemas.agent_tools import AgentTool, AgentToolPolicy
from app.schemas.research_engine import AlgorithmIOSchema
from app.services.assistant_context_assembler import (
    AssistantContextAssembler,
    estimate_tokens,
)


def _tool(*, version: str = "1.0.0") -> AgentTool:
    """构造用于上下文目录测试的算法工具。"""
    return AgentTool(
        tool_id="algorithm:vertical/tool:a",
        algorithm_id="vertical/tool:a",
        name="Vertical Tool",
        description="预测聚合物性质",
        algorithm_family="vertical_prediction",
        tool_type="predictor",
        source="builtin",
        active_version_id="version-1",
        version=version,
        input_schema=AlgorithmIOSchema(fields={"smiles": "string - SMILES"}, required=["smiles"]),
        output_schema=AlgorithmIOSchema(),
        policy=AgentToolPolicy(algorithm_id="vertical/tool:a"),
        requires_confirmation=True,
        phase="available",
        health_status="healthy",
        function_name="algorithm_vertical_tool_a_abc123",
        input_json_schema={"type": "object", "properties": {"smiles": {"type": "string"}}},
        schema_digest="0123456789abcdef",
    )


def test_estimate_tokens_uses_conservative_character_rule() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_assemble_builds_all_builtin_sections_and_stable_digest() -> None:
    assembler = AssistantContextAssembler()
    route = {
        "provider_id": "provider-a",
        "model_id": "model-a",
        "purpose": "qa",
        "route_reason": "user_selected",
        "tool_protocol": "openai_chat_tools",
    }

    first = assembler.assemble(
        request_kind="tool_proposal",
        intent_scope="project",
        deep=False,
        facts={"project": "PolyAgent"},
        route=route,
        selected_tools=[_tool()],
        knowledge_evidence=[{"title": "知识", "source_id": "doc-1", "snippet": "证据", "score": 0.8}],
        web_evidence=[{"title": "网页", "url": "https://example.com", "snippet": "证据", "content": "内容"}],
        prior_tool_messages=[{"role": "tool", "content": '{"status":"completed"}'}],
    )
    second = assembler.assemble(
        request_kind="tool_proposal",
        intent_scope="project",
        deep=False,
        facts={"project": "PolyAgent"},
        route=route,
        selected_tools=[_tool()],
        knowledge_evidence=[{"title": "知识", "source_id": "doc-1", "snippet": "证据", "score": 0.8}],
        web_evidence=[{"title": "网页", "url": "https://example.com", "snippet": "证据", "content": "内容"}],
        prior_tool_messages=[{"role": "tool", "content": '{"status":"completed"}'}],
    )

    section_names = [section.name for section in first.sections]
    assert section_names == [
        "project_facts",
        "llm_route",
        "selected_tools",
        "knowledge_evidence",
        "web_evidence",
        "prior_tool_results",
        "conversation_policy",
    ]
    assert all(section.included for section in first.sections)
    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")
    assert first.token_estimate == sum(section.token_estimate for section in first.sections if section.included)
    assert "algorithm:vertical/tool:a" in first.rendered
    assert "0123456789abcdef" in first.rendered
    assert "input_json_schema" not in first.rendered


def test_budget_omits_sections_with_reason() -> None:
    assembler = AssistantContextAssembler()
    assembly = assembler.assemble(
        request_kind="final_answer",
        intent_scope="project",
        deep=False,
        facts={"facts": "x" * 400},
        route={"provider_id": "provider-a", "model_id": "model-a"},
        total_token_budget=20,
        section_token_budgets={"project_facts": 4, "llm_route": 4, "conversation_policy": 100},
    )

    facts_section = next(section for section in assembly.sections if section.name == "project_facts")
    policy_section = next(section for section in assembly.sections if section.name == "conversation_policy")
    assert facts_section.included is False
    assert facts_section.omitted_reason == "section_budget_exceeded"
    assert policy_section.omitted_reason == "total_budget_exceeded"
    assert assembly.token_estimate <= 20


def test_manifest_records_context_and_tool_digests() -> None:
    assembler = AssistantContextAssembler()
    assembly = assembler.assemble(
        request_kind="tool_proposal",
        intent_scope="project",
        deep=False,
        facts={"project": "PolyAgent"},
        route={
            "provider_id": "provider-a",
            "model_id": "model-a",
            "purpose": "qa",
            "route_reason": "user_selected",
            "tool_protocol": "openai_chat_tools",
        },
    )
    manifest = assembler.build_manifest(
        run_id="asrun_test",
        request_kind="tool_proposal",
        route={
            "provider_id": "provider-a",
            "model_id": "model-a",
            "purpose": "qa",
            "route_reason": "user_selected",
            "tool_protocol": "openai_chat_tools",
        },
        assembly=assembly,
        tools=[_tool(version="2.0.0")],
    )

    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == "asrun_test"
    assert manifest["request_kind"] == "tool_proposal"
    assert manifest["context"]["digest"] == assembly.digest
    assert manifest["context"]["sections"][0]["name"] == "project_facts"
    assert manifest["context"]["sections"][0]["token_estimate"] > 0
    assert manifest["context"]["native_tool_schema_token_estimate"] == 0
    assert manifest["context"]["token_estimation"]["method"] == "char_count"
    assert manifest["tools"] == [
        {
            "tool_id": "algorithm:vertical/tool:a",
            "function_name": "algorithm_vertical_tool_a_abc123",
            "version": "2.0.0",
            "schema_digest": "0123456789abcdef",
        }
    ]


def test_session_state_and_plan_policy_sections_are_budgeted() -> None:
    assembler = AssistantContextAssembler()
    state = {
        "plan_mode": True,
        "permission_mode": "read_only",
        "goal": {"status": "active", "objective": "构建材料实验智能体"},
        "todos": [{"status": "pending", "content": "调研数据"}],
        "compaction": {"summary_digest": "sha256:compact"},
    }
    assembly = assembler.assemble(
        request_kind="final_answer",
        intent_scope="project",
        deep=False,
        facts={"project": "PolyAgent"},
        route={"provider_id": "provider-a", "model_id": "model-a"},
        session_state=state,
    )
    sections = {section.name: section for section in assembly.sections}

    assert sections["session_state"].included is True
    assert "构建材料实验智能体" in sections["session_state"].content
    assert "read_only" in sections["session_state"].content
    assert "sha256:compact" in sections["session_state"].content
    assert sections["plan_policy"].included is True
    assert "不修改文件" in sections["plan_policy"].content


def test_truncation_and_native_tool_schema_tokens_are_recorded() -> None:
    assembler = AssistantContextAssembler()
    assembly = assembler.assemble(
        request_kind="tool_proposal",
        intent_scope="project",
        deep=False,
        facts={"project": "x" * 400},
        route={"provider_id": "provider-a", "model_id": "model-a"},
        selected_tools=[_tool()],
        total_token_budget=80,
        section_token_budgets={"project_facts": 20, "llm_route": 4, "conversation_policy": 100},
        native_tool_schema_tokens=35,
        allow_section_truncation=True,
    )

    facts_section = next(section for section in assembly.sections if section.name == "project_facts")
    assert facts_section.included is True
    assert facts_section.truncated is True
    assert assembly.native_tool_schema_token_estimate == 35
    assert assembly.budget_token_estimate == assembly.token_estimate + 35

    manifest = assembler.build_manifest(
        run_id="asrun_truncation",
        request_kind="tool_proposal",
        route={"provider_id": "provider-a", "model_id": "model-a"},
        assembly=assembly,
        tools=[_tool()],
    )
    assert manifest["context"]["native_tool_schema_token_estimate"] == 35
    assert manifest["context"]["sections"][0]["truncated"] is True
