"""ResearchEngine StageExecutionPlan 编排测试。"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.schemas.research_engine import ExecutionDecisionCreate, ProblemSpecCreate
from app.infra.research_engine_repositories import ResearchRunRepository
from app.services.research_engine_orchestrator import ResearchEngineOrchestrator
from app.services.research_engine_service import ResearchEngineService


class StageExecutionPlanTest(ComputationTestCase):
    """覆盖 Plan-first 阶段计划的生成、审批与核验留痕。"""

    def setUp(self) -> None:
        super().setUp()
        self.service = ResearchEngineService()
        self.orchestrator = ResearchEngineOrchestrator()
        problem_spec = self.service.create_problem_spec(
            ProblemSpecCreate(
                name="ALS Plan-first 测试",
                material_family="fluoropolymer",
                objectives=[
                    {"name": "dielectric_constant", "direction": "maximize"},
                ],
            ),
            actor_user_id="tester",
        )
        self.service.create_execution_decision(
            problem_spec.problem_spec_id,
            ExecutionDecisionCreate(mode="autoresearch", reason="Plan-first 测试"),
            actor_user_id="tester",
        )
        self.run = self.orchestrator.create_research_run(
            problem_spec.problem_spec_id,
            actor_user_id="tester",
        )

    def test_gate_blocks_with_reviewable_execution_plan(self) -> None:
        """Gate 阻塞时必须携带可审查的执行计划。"""
        started = self.orchestrator.start_research_run(
            self.run.run_id,
            actor_user_id="tester",
            reason="启动 Plan-first 测试",
        )
        problem_stage = next(sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC")

        self.assertEqual(problem_stage.status, "blocked_approval")
        self.assertIsNotNone(problem_stage.plan)
        self.assertEqual(problem_stage.plan.review_status, "draft")
        self.assertEqual(problem_stage.plan.generated_by, "rule")
        self.assertTrue(problem_stage.plan.steps)
        self.assertTrue(problem_stage.plan.steps[0].inputs)
        self.assertEqual(
            problem_stage.plan.steps[0].inputs[0].source_kind,
            "problem_spec",
        )

    def test_approve_records_plan_review_and_tool_stage_verification(self) -> None:
        """审批记录计划核验，后续工具阶段执行后保存计划一致性结果。"""
        started = self.orchestrator.start_research_run(
            self.run.run_id,
            actor_user_id="tester",
            reason="启动计划核验测试",
        )
        problem_stage = next(sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC")

        approved = self.orchestrator.approve_stage(
            self.run.run_id,
            problem_stage.stage_run_id,
            actor_user_id="tester",
            reason="批准问题定义计划",
        )
        approved_problem = next(sr for sr in approved.stage_runs if sr.stage_key == "PROBLEM_SPEC")
        knowledge = next(sr for sr in approved.stage_runs if sr.stage_key == "KNOWLEDGE_RETRIEVAL")

        self.assertEqual(approved_problem.plan.review_status, "approved")
        self.assertEqual(approved_problem.decisions[-1].plan_review["status"], "matched")
        self.assertEqual(
            approved_problem.decisions[-1].plan_review["plan_id"],
            approved_problem.plan.plan_id,
        )
        self.assertEqual(knowledge.status, "completed")
        self.assertIsNotNone(knowledge.plan)
        self.assertEqual(
            knowledge.checkpoint_data["plan_verification"]["status"],
            "matched",
        )
        self.assertEqual(
            knowledge.checkpoint_data["plan_verification"]["actual_tool_ref"],
            "weknora_adapter",
        )

    def test_reject_marks_plan_rejected(self) -> None:
        """拒绝 Gate 时计划状态同步留痕。"""
        started = self.orchestrator.start_research_run(
            self.run.run_id,
            actor_user_id="tester",
            reason="启动拒绝计划测试",
        )
        problem_stage = next(sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC")

        rejected = self.orchestrator.reject_stage(
            self.run.run_id,
            problem_stage.stage_run_id,
            actor_user_id="tester",
            reason="计划输入不完整",
        )
        rejected_problem = next(sr for sr in rejected.stage_runs if sr.stage_key == "PROBLEM_SPEC")

        self.assertEqual(rejected.status, "failed")
        self.assertEqual(rejected_problem.plan.review_status, "rejected")
        self.assertEqual(
            rejected_problem.decisions[-1].plan_review["status"],
            "rejected",
        )

    def test_regenerate_after_reject_preserves_history_without_retry(self) -> None:
        """拒绝后可显式重生成计划，且保留历史、不改变失败终态。"""
        started = self.orchestrator.start_research_run(
            self.run.run_id,
            actor_user_id="tester",
            reason="启动重生成计划测试",
        )
        problem_stage = next(sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC")
        rejected = self.orchestrator.reject_stage(
            self.run.run_id,
            problem_stage.stage_run_id,
            actor_user_id="tester",
            reason="计划步骤粒度过粗",
        )
        rejected_problem = next(sr for sr in rejected.stage_runs if sr.stage_key == "PROBLEM_SPEC")
        old_plan_id = rejected_problem.plan.plan_id

        regenerated = self.orchestrator.regenerate_stage_plan(
            self.run.run_id,
            problem_stage.stage_run_id,
            actor_user_id="tester",
            reason="按最新问题定义补齐计划输入",
        )
        current_stage = next(
            sr for sr in regenerated.stage_runs if sr.stage_key == "PROBLEM_SPEC"
        )
        history = current_stage.checkpoint_data["plan_history"]

        self.assertEqual(regenerated.status, "failed")
        self.assertEqual(current_stage.status, "failed")
        self.assertEqual(current_stage.plan.review_status, "draft")
        self.assertNotEqual(current_stage.plan.plan_id, old_plan_id)
        self.assertEqual(history[0]["plan_id"], old_plan_id)
        self.assertEqual(history[0]["review_status"], "rejected")
        self.assertEqual(history[0]["rejected_reason"], "计划步骤粒度过粗")
        self.assertEqual(current_stage.decisions[-1].decision, "rejected")

        with self.assertRaises(HTTPException) as ctx:
            self.orchestrator.regenerate_stage_plan(
                self.run.run_id,
                problem_stage.stage_run_id,
                actor_user_id="tester",
                reason="尝试重复重生成",
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_regenerate_stage_plan_api(self) -> None:
        """重生成计划 API 返回新 draft 计划并保留拒绝历史。"""
        started = self.orchestrator.start_research_run(
            self.run.run_id,
            actor_user_id="tester",
            reason="启动重生成 API 测试",
        )
        problem_stage = next(sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC")
        self.orchestrator.reject_stage(
            self.run.run_id,
            problem_stage.stage_run_id,
            actor_user_id="tester",
            reason="原计划缺少安全约束",
        )

        response = self.client.post(
            f"/api/v1/research-engine/research-runs/{self.run.run_id}"
            f"/stages/{problem_stage.stage_run_id}/regenerate-plan",
            json={
                "stage_key": "PROBLEM_SPEC",
                "reason": "补充安全约束后重新生成",
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        current_stage = next(
            sr for sr in data["stage_runs"] if sr["stage_key"] == "PROBLEM_SPEC"
        )
        self.assertEqual(data["status"], "failed")
        self.assertEqual(current_stage["status"], "failed")
        self.assertEqual(current_stage["plan"]["review_status"], "draft")
        self.assertEqual(len(current_stage["checkpoint_data"]["plan_history"]), 1)

    def test_approve_blocks_plan_drift(self) -> None:
        """计划工具引用与实际执行漂移时禁止审批放行。"""
        started = self.orchestrator.start_research_run(
            self.run.run_id,
            actor_user_id="tester",
            reason="启动计划漂移测试",
        )
        problem_stage = next(sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC")
        doc = ResearchRunRepository.find_one({"run_id": self.run.run_id})
        stage_doc = next(
            sr for sr in doc["stage_runs"] if sr["stage_run_id"] == problem_stage.stage_run_id
        )
        stage_doc["plan"]["steps"][0]["tool_ref"] = "unexpected_tool"
        ResearchRunRepository.update_fields(
            self.run.run_id,
            {"stage_runs": doc["stage_runs"]},
        )

        with self.assertRaises(HTTPException) as ctx:
            self.orchestrator.approve_stage(
                self.run.run_id,
                problem_stage.stage_run_id,
                actor_user_id="tester",
                reason="尝试批准漂移计划",
            )

        self.assertEqual(ctx.exception.status_code, 409)
        current = self.orchestrator.get_research_run(self.run.run_id)
        current_problem = next(sr for sr in current.stage_runs if sr.stage_key == "PROBLEM_SPEC")
        self.assertEqual(current_problem.status, "blocked_approval")
        self.assertEqual(current_problem.plan.review_status, "draft")
