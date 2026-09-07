"""ResearchEngine Plan-first 纯逻辑模块测试。"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.research_engine_plan import (
    build_plan_dependency,
    build_stage_execution_plan,
    find_upstream_output,
    plan_safety_note,
    plan_step_kind,
    planned_input_fields,
    prepare_gate_plan_review,
    stage_blocks_plan_drift,
    stage_requires_plan,
    verify_stage_plan,
)


def stage_run(**overrides) -> dict:
    """构建带计划契约的最小 StageRun 文档。

    Args:
        **overrides: 覆盖默认字段的键值对。

    Returns:
        用于纯函数测试的 StageRun 字典。
    """
    base = {
        "stage_run_id": "sr-current",
        "stage_key": "COMPUTE_PREDICT",
        "status": "running",
        "gate": {
            "required_inputs": ["smiles"],
            "expected_outputs": ["prediction"],
            "plan_policy": {
                "require_plan": True,
                "block_on_drift": True,
            },
            "artifact_policy": {
                "required_artifacts": ["prediction_report"],
            },
        },
    }
    base.update(overrides)
    return base


def research_run_doc() -> dict:
    """构建包含上游阶段与 ProblemSpec 的最小 ResearchRun 文档。"""
    return {
        "run_id": "run-001",
        "problem_spec_id": "ps-001",
        "stage_runs": [
            {
                "stage_run_id": "sr-upstream",
                "status": "completed",
                "gate": {"expected_outputs": ["prediction"]},
            },
            {
                "stage_run_id": "sr-pending",
                "status": "pending",
                "gate": {"expected_outputs": ["prediction"]},
            },
            stage_run(),
        ],
    }


class ResearchEnginePlanPolicyTest(unittest.TestCase):
    """验证计划策略判定与步骤元数据映射。"""

    def test_reads_plan_policy_from_stage_contract(self) -> None:
        self.assertTrue(stage_requires_plan(stage_run()))
        self.assertTrue(stage_blocks_plan_drift(stage_run()))

        no_policy = stage_run(gate={"required_inputs": [], "expected_outputs": []})
        self.assertFalse(stage_requires_plan(no_policy))
        self.assertFalse(stage_blocks_plan_drift(no_policy))

    def test_maps_algorithm_to_restricted_step_kind(self) -> None:
        self.assertEqual(plan_step_kind("weknora_adapter"), "knowledge")
        self.assertEqual(plan_step_kind("mobo_alchemist_adapter"), "computation")
        self.assertEqual(plan_step_kind(None), "manual_review")
        self.assertEqual(plan_step_kind("unknown_adapter"), "manual_review")

    def test_builds_gate_review_safety_note(self) -> None:
        self.assertIn("实验下发", plan_safety_note("EXPERIMENT_EXECUTION", None))
        self.assertIn("不调用外部工具", plan_safety_note("HUMAN_REVIEW", None))
        self.assertIn("mobo_mock", plan_safety_note("COMPUTE_PREDICT", "mobo_mock"))


class ResearchEnginePlanDependencyTest(unittest.TestCase):
    """验证计划输入字段与依赖解析。"""

    def test_planned_input_fields_prefer_algorithm_snapshot_keys(self) -> None:
        algorithm_fields = planned_input_fields(
            stage_run(),
            {"smiles": "CCO", "temperature": 80},
        )
        self.assertEqual(algorithm_fields, ["smiles", "temperature"])

        manual_fields = planned_input_fields(stage_run(), None)
        self.assertEqual(manual_fields, ["smiles"])

    def test_find_upstream_output_only_uses_completed_stages(self) -> None:
        doc = research_run_doc()
        current = doc["stage_runs"][2]

        hit = find_upstream_output(doc, current, "prediction")
        self.assertEqual(hit["stage_run_id"], "sr-upstream")
        self.assertIsNone(find_upstream_output(doc, current, "unknown_field"))

    def test_builds_dependency_by_source_priority(self) -> None:
        doc = research_run_doc()
        current = doc["stage_runs"][2]

        upstream_dep = build_plan_dependency(doc, current, "prediction")
        self.assertEqual(upstream_dep.source_kind, "stage_output")
        self.assertEqual(upstream_dep.source_ref, "sr-upstream")

        problem_dep = build_plan_dependency(doc, current, "smiles")
        self.assertEqual(problem_dep.source_kind, "problem_spec")
        self.assertEqual(problem_dep.source_ref, "ps-001")

        manual_dep = build_plan_dependency(doc, current, "operator_note")
        self.assertEqual(manual_dep.source_kind, "manual")
        self.assertIsNone(manual_dep.source_ref)

    def test_builds_draft_rule_plan_with_single_primary_step(self) -> None:
        doc = research_run_doc()
        current = doc["stage_runs"][2]

        plan = build_stage_execution_plan(
            doc=doc,
            stage_run=current,
            algorithm_id="mobo_mock",
            input_fields=["prediction", "smiles", "operator_note"],
            plan_id="plan-001",
            generated_at=datetime(2026, 9, 7, 12, 0, 0),
        )

        self.assertEqual(plan.plan_id, "plan-001")
        self.assertEqual(plan.review_status, "draft")
        self.assertEqual(plan.generated_by, "rule")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.step_key, "compute_predict:primary")
        self.assertEqual(step.kind, "computation")
        self.assertEqual(step.tool_ref, "mobo_mock")
        self.assertEqual(step.expected_artifacts, ["prediction_report"])
        self.assertEqual(
            [dep.field for dep in step.inputs],
            ["prediction", "smiles", "operator_note"],
        )


class ResearchEnginePlanVerificationTest(unittest.TestCase):
    """验证计划与实际执行的一致性核验。"""

    def test_verify_matched_plan_with_artifact_coverage(self) -> None:
        plan = build_stage_execution_plan(
            doc=research_run_doc(),
            stage_run=stage_run(input_snapshot={"smiles": "CCO"}),
            algorithm_id="mobo_mock",
            input_fields=["smiles"],
            plan_id="plan-001",
            generated_at=datetime(2026, 9, 7, 12, 0, 0),
        )
        current = stage_run(
            plan=plan.model_dump(mode="json"),
            input_snapshot={"smiles": "CCO"},
        )

        result = verify_stage_plan(
            current,
            {"prediction_report": "ok"},
            actual_tool="mobo_mock",
        )

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["planned_tool_ref"], "mobo_mock")
        self.assertEqual(result["actual_tool_ref"], "mobo_mock")
        self.assertEqual(result["missing_input_fields"], [])
        self.assertEqual(result["generated_artifacts"], ["prediction_report"])
        self.assertTrue(result["artifacts_complete"])

    def test_verify_mismatched_tool_and_missing_inputs(self) -> None:
        plan = build_stage_execution_plan(
            doc=research_run_doc(),
            stage_run=stage_run(),
            algorithm_id="mobo_mock",
            input_fields=["smiles", "temperature"],
            plan_id="plan-002",
            generated_at=datetime(2026, 9, 7, 12, 0, 0),
        )
        current = stage_run(
            plan=plan.model_dump(mode="json"),
            input_snapshot={"smiles": "CCO"},
        )

        result = verify_stage_plan(current, {}, actual_tool="weknora_adapter")

        self.assertEqual(result["status"], "mismatched")
        self.assertEqual(result["missing_input_fields"], ["temperature"])
        self.assertEqual(result["input_check"], "algorithm_input_snapshot")
        self.assertEqual(result["generated_artifacts"], [])
        self.assertFalse(result["artifacts_complete"])

    def test_verify_manual_review_skips_input_check(self) -> None:
        plan = build_stage_execution_plan(
            doc=research_run_doc(),
            stage_run=stage_run(stage_key="HUMAN_REVIEW"),
            algorithm_id=None,
            input_fields=["operator_note"],
            plan_id="plan-003",
            generated_at=datetime(2026, 9, 7, 12, 0, 0),
        )
        current = stage_run(
            stage_key="HUMAN_REVIEW",
            plan=plan.model_dump(mode="json"),
        )

        result = verify_stage_plan(current, {}, actual_tool=None)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["input_check"], "not_applicable_manual_review")
        self.assertEqual(result["missing_input_fields"], [])


class ResearchEnginePlanGateReviewTest(unittest.TestCase):
    """验证 Gate 决策的计划审查结果构造。"""

    def test_returns_plan_missing_without_plan(self) -> None:
        review = prepare_gate_plan_review(
            stage_run(),
            decision="approved",
            actual_tool="mobo_mock",
        )

        self.assertEqual(review, {"status": "plan_missing", "decision": "approved"})

    def test_reuses_saved_verification_and_marks_rejected(self) -> None:
        plan = build_stage_execution_plan(
            doc=research_run_doc(),
            stage_run=stage_run(),
            algorithm_id="mobo_mock",
            input_fields=["smiles"],
            plan_id="plan-004",
            generated_at=datetime(2026, 9, 7, 12, 0, 0),
        )
        plan_dict = plan.model_dump(mode="json")
        current = stage_run(
            plan=plan_dict,
            output_summary={},
            checkpoint_data={
                "plan_verification": {"status": "mismatched", "plan_id": "plan-004"}
            },
        )

        review = prepare_gate_plan_review(
            current,
            decision="rejected",
            actual_tool="mobo_mock",
        )

        self.assertEqual(review["status"], "rejected")
        self.assertEqual(review["review_status"], "rejected")
        self.assertEqual(review["plan_id"], "plan-004")
        self.assertEqual(current["plan"]["review_status"], "rejected")

    def test_falls_back_to_live_verification_for_approval(self) -> None:
        plan = build_stage_execution_plan(
            doc=research_run_doc(),
            stage_run=stage_run(input_snapshot={"smiles": "CCO"}),
            algorithm_id="mobo_mock",
            input_fields=["smiles"],
            plan_id="plan-005",
            generated_at=datetime(2026, 9, 7, 12, 0, 0),
        )
        current = stage_run(
            plan=plan.model_dump(mode="json"),
            input_snapshot={"smiles": "CCO"},
            output_summary={},
        )

        review = prepare_gate_plan_review(
            current,
            decision="approved",
            actual_tool="mobo_mock",
        )

        self.assertEqual(review["status"], "matched")
        self.assertEqual(review["decision"], "approved")
        self.assertEqual(current["plan"]["review_status"], "approved")


if __name__ == "__main__":
    unittest.main()
