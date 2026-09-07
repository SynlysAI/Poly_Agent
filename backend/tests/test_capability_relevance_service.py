"""动态能力相关性筛选测试。"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.agent_tools import AgentTool, AgentToolPolicy
from app.services.capability_relevance_service import CapabilityRelevanceService


def tool(algorithm_id: str, name: str, description: str) -> AgentTool:
    """构建用于相关性评估的最小算法工具。"""
    return AgentTool(
        tool_id=f"algorithm:{algorithm_id}",
        algorithm_id=algorithm_id,
        name=name,
        description=description,
        algorithm_family="vertical_prediction",
        tool_type="predictor",
        source="test",
        policy=AgentToolPolicy(algorithm_id=algorithm_id),
        requires_confirmation=True,
        phase="available",
        health_status="healthy",
    )


class CapabilityRelevanceServiceTest(unittest.TestCase):
    """以纯函数方式验证相关性、显式选择优先和预算裁剪。"""

    def test_selects_relevant_tool_and_filters_irrelevant_tool(self) -> None:
        property_tool = tool("property", "Property Predictor", "预测分子属性")
        formulation_tool = tool("formulation", "Formulation Tool", "接收配方列表")

        assessment, selected = CapabilityRelevanceService().assess(
            task_summary="预测 CCO 的属性",
            tools=[property_tool, formulation_tool],
            protected_tool_ids=[],
        )

        selected_ids = [item.tool_id for item in selected]
        self.assertIn("algorithm:property", selected_ids)
        self.assertNotIn("algorithm:formulation", selected_ids)
        self.assertTrue(assessment.token_budget_used > 0)

    def test_protects_explicitly_selected_tool_from_relevance_filtering(self) -> None:
        formulation_tool = tool("formulation", "Formulation Tool", "接收配方列表")

        _assessment, selected = CapabilityRelevanceService().assess(
            task_summary="预测分子属性",
            tools=[formulation_tool],
            protected_tool_ids=["algorithm:formulation"],
        )

        self.assertEqual([item.tool_id for item in selected], ["algorithm:formulation"])

    def test_budget_trims_low_confidence_auto_tools(self) -> None:
        property_tool = tool("property", "Property Predictor", "预测分子属性")
        structure_tool = tool("structure", "Structure Generator", "预测分子结构")
        service = CapabilityRelevanceService()
        single_tool_budget = service.estimate_tool_schema_tokens(property_tool)

        _assessment, selected = service.assess(
            task_summary="预测 CCO 的属性和结构",
            tools=[property_tool, structure_tool],
            protected_tool_ids=[],
            token_budget_limit=single_tool_budget,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].tool_id, "algorithm:property")
