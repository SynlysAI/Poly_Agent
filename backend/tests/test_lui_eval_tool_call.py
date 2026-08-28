"""LUI M2 工具调用判定测试。"""

from __future__ import annotations

import unittest

from evaluation.lui.evaluators import evaluate_task
from evaluation.lui.schemas import (
    ExpectedToolCall,
    FixtureRun,
    FixtureToolCall,
    GoldenTask,
    ObservedFacts,
    ToleranceRule,
)
from evaluation.lui.evaluators.tool_call import evaluate_arguments


def _task(expected_calls: list[ExpectedToolCall]) -> GoldenTask:
    """构建最小工具任务。"""
    return GoldenTask.model_validate(
        {
            "id": "LUI-TT-0001",
            "category": "tool_argument",
            "requires_model_capability": "tool_calling",
            "messages": [{"role": "user", "content": "调用工具"}],
            "expected": {"tool_calls": [call.model_dump() for call in expected_calls]},
        }
    )


def _facts(calls: list[FixtureToolCall]) -> ObservedFacts:
    """构建最小观测事实。"""
    return ObservedFacts(
        task_id="LUI-TT-0001",
        run=FixtureRun(run_id="run-1", status="completed"),
        tool_calls=calls,
    )


class LuiEvalToolCallTest(unittest.TestCase):
    def test_exact_match_passes_with_full_metrics(self) -> None:
        """工具、函数名、参数全部正确时应通过并给出三项指标。"""
        expected = ExpectedToolCall(
            tool_id="algorithm:vertical_predictor_adapter",
            function_name="algorithm_vertical_predictor_adapter_66a47bf68bae",
            arguments={
                "smiles": "C=C(F)F",
                "target_properties": ["dielectric_constant", "hydrophobicity"],
            },
        )
        observed = FixtureToolCall(
            call_id="call-1",
            tool_id="algorithm:vertical_predictor_adapter",
            function_name="algorithm_vertical_predictor_adapter_66a47bf68bae",
            arguments={
                "smiles": "C=C(F)F",
                "target_properties": ["hydrophobicity", "dielectric_constant"],
            },
        )
        outcome = evaluate_task(_task([expected]), _facts([observed])).outcomes["m2"]
        self.assertTrue(outcome.passed)
        self.assertEqual(outcome.details["selection_precision"], 1.0)
        self.assertEqual(outcome.details["selection_recall"], 1.0)
        self.assertEqual(outcome.details["argument_accuracy"], 1.0)

    def test_wrong_tool_fails_recall(self) -> None:
        """选错工具时 recall 为 0 且任务级失败。"""
        expected = ExpectedToolCall(tool_id="algorithm:weknora_adapter")
        observed = FixtureToolCall(
            call_id="call-1",
            tool_id="algorithm:vertical_predictor_adapter",
            arguments={},
        )
        outcome = evaluate_task(_task([expected]), _facts([observed])).outcomes["m2"]
        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.details["selection_recall"], 0.0)
        self.assertEqual(outcome.details["unexpected_calls"], 1)

    def test_relative_tolerance(self) -> None:
        """relative 容忍下 10% 内误差应通过。"""
        expected = ExpectedToolCall(
            tool_id="algorithm:mobo_alchemist_adapter",
            arguments={"batch_size": 10},
            argument_tolerance={"batch_size": ToleranceRule(kind="relative", value=0.1)},
        )
        observed = FixtureToolCall(
            call_id="call-1",
            tool_id="algorithm:mobo_alchemist_adapter",
            arguments={"batch_size": 11},
        )
        ok, errors = evaluate_arguments(expected, observed)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_missing_field_and_parse_error_fail(self) -> None:
        """缺必填字段或参数解析失败应判参数错误。"""
        expected = ExpectedToolCall(
            tool_id="algorithm:vertical_predictor_adapter",
            arguments={"smiles": "C=C(F)F", "target_properties": ["dielectric_constant"]},
        )
        observed = FixtureToolCall(
            call_id="call-1",
            tool_id="algorithm:vertical_predictor_adapter",
            arguments={"smiles": "C=C(F)F"},
            missing_fields=["target_properties"],
            arguments_parse_error="invalid json",
        )
        ok, errors = evaluate_arguments(expected, observed)
        self.assertFalse(ok)
        self.assertTrue(any("parse error" in item for item in errors))
        self.assertTrue(any("missing required" in item for item in errors))

    def test_unexpected_extra_call_fails_tool_task(self) -> None:
        """出现期望外工具调用时任务级工具判定失败。"""
        expected = ExpectedToolCall(tool_id="algorithm:weknora_adapter")
        first = FixtureToolCall(
            call_id="call-1",
            tool_id="algorithm:weknora_adapter",
        )
        second = FixtureToolCall(
            call_id="call-2",
            tool_id="algorithm:vertical_predictor_adapter",
        )
        outcome = evaluate_task(_task([expected]), _facts([first, second])).outcomes["m2"]
        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.details["unexpected_calls"], 1)


if __name__ == "__main__":
    unittest.main()
