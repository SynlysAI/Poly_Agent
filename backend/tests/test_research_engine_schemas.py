"""ResearchEngine schema 单元测试。

覆盖 ProblemSpec、AlgorithmRegistry、AlgorithmRun、ResearchRun、
StageGate 等 Pydantic schema 的校验逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

from app.schemas.attribution import AttributionItem
from app.schemas.research_engine import (
    AlgorithmIOSchema,
    AlgorithmRegistryEntry,
    AlgorithmRun,
    AlgorithmRunCreate,
    AlgorithmRunListData,
    ExecutionDecisionMode,
    ProblemSpec,
    ProblemSpecConstraint,
    ProblemSpecCreate,
    ProblemSpecListData,
    ProblemSpecMeasurement,
    ProblemSpecObjective,
    ProblemSpecVariable,
    ResearchRun,
    ResearchRunCreate,
    ResearchRunListData,
    ResearchRunStatus,
    ResearchStageKey,
    ResearchStageRun,
    ResearchStageStatus,
    StageGate,
    StageGateDecision,
    StageApprovalRequest,
    ResearchRunStatusChangeRequest,
    TriggerSource,
    validate_research_run_transition,
    validate_stage_transition,
)

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


# =============================================================================
# 辅助 payload 构建函数
# =============================================================================


def problem_spec_payload(**overrides: object) -> dict:
    """构建最小 ProblemSpec 创建请求。"""
    payload = {
        "name": "氟基高分子测试任务",
        "material_family": "fluoropolymer",
        "problem_type": "formulation_process_optimization",
        "allowed_execution_modes": ["manual_workbench", "autoresearch"],
        "objectives": [
            {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
        ],
    }
    payload.update(overrides)
    return payload


def algorithm_run_payload(**overrides: object) -> dict:
    """构建最小 AlgorithmRun 创建请求。"""
    payload = {
        "algorithm_id": "local_xtb_adapter",
        "trigger_source": "human_workflow",
    }
    payload.update(overrides)
    return payload


def research_run_payload(**overrides: object) -> dict:
    """构建最小 ResearchRun 创建请求。"""
    payload = {
        "problem_spec_id": "ps_demo_001",
        "execution_decision_id": "ed_demo_001",
    }
    payload.update(overrides)
    return payload


# =============================================================================
# ProblemSpec Schema 测试
# =============================================================================


class ProblemSpecSchemaTest(ComputationTestCase):
    """覆盖 ProblemSpec 创建、校验和错误路径。"""

    def test_create_valid_minimal_problem_spec(self) -> None:
        """最简 ProblemSpec 创建成功。"""
        ps = ProblemSpecCreate(**problem_spec_payload())
        self.assertEqual(ps.name, "氟基高分子测试任务")
        self.assertEqual(ps.material_family, "fluoropolymer")
        self.assertEqual(ps.allowed_execution_modes, ["manual_workbench", "autoresearch"])
        self.assertEqual(ps.decision_status, "pending_execution_decision")

    def test_create_normalizes_cross_module_material_family_aliases(self) -> None:
        """跨模块材料语料别名归一为通用材料体系。"""
        ps = ProblemSpecCreate(**problem_spec_payload(material_family="welding"))
        self.assertEqual(ps.material_family, "universal")

        ps = ProblemSpecCreate(**problem_spec_payload(material_family="welding_materials"))
        self.assertEqual(ps.material_family, "universal")

    def test_create_rejects_empty_name(self) -> None:
        """空名称被拒绝。"""
        with self.assertRaises(ValueError):
            ProblemSpecCreate(**problem_spec_payload(name="   "))

    def test_create_with_full_variables(self) -> None:
        """包含变量定义的 ProblemSpec 创建成功。"""
        ps = ProblemSpecCreate(
            **problem_spec_payload(
                variables=[
                    {
                        "name": "fluorine_content",
                        "type": "continuous",
                        "role": "formulation",
                        "unit": "percent",
                        "bounds": [0.0, 100.0],
                    },
                    {
                        "name": "monomer_smiles",
                        "type": "categorical",
                        "role": "structure",
                        "categories": ["C=CF", "C=C(F)F"],
                    },
                ],
            )
        )
        self.assertEqual(len(ps.variables), 2)
        self.assertEqual(ps.variables[0].name, "fluorine_content")
        self.assertEqual(ps.variables[1].type, "categorical")

    def test_variable_bounds_validation(self) -> None:
        """变量边界校验。"""
        # 边界顺序错误
        with self.assertRaises(ValueError):
            ProblemSpecVariable(
                name="test",
                type="continuous",
                bounds=[100.0, 0.0],
            )

    def test_variable_categories_min_length(self) -> None:
        """分类变量至少需要两个候选项。"""
        with self.assertRaises(ValueError):
            ProblemSpecVariable(
                name="test",
                type="categorical",
                categories=["only_one"],
            )

    def test_create_with_objectives(self) -> None:
        """多目标 ProblemSpec 创建成功。"""
        ps = ProblemSpecCreate(
            **problem_spec_payload(
                objectives=[
                    {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
                    {"name": "thermal_stability", "direction": "maximize", "unit": "celsius"},
                    {"name": "cost", "direction": "minimize", "unit": "CNY_per_kg"},
                ],
            )
        )
        self.assertEqual(len(ps.objectives), 3)

    def test_create_rejects_empty_objectives(self) -> None:
        """空目标列表被拒绝。"""
        with self.assertRaises(ValueError):
            ProblemSpecCreate(**problem_spec_payload(objectives=[]))

    def test_create_with_constraints(self) -> None:
        """包含约束条件的 ProblemSpec 创建成功。"""
        ps = ProblemSpecCreate(
            **problem_spec_payload(
                constraints=[
                    {"name": "synthesizable", "type": "hard"},
                    {"name": "temp_limit", "type": "hard", "expression": "temperature <= 180"},
                ],
            )
        )
        self.assertEqual(len(ps.constraints), 2)

    def test_create_with_measurements(self) -> None:
        """包含测量条件的 ProblemSpec 创建成功。"""
        ps = ProblemSpecCreate(
            **problem_spec_payload(
                measurements=[
                    {"name": "dielectric_constant", "condition": "room_temperature", "method": "impedance"},
                ],
            )
        )
        self.assertEqual(len(ps.measurements), 1)

    def test_allowed_execution_modes_literal(self) -> None:
        """allowed_execution_modes 仅接受 v0.4 合法值。"""
        for mode in ["manual_workbench", "autoresearch"]:
            ps = ProblemSpecCreate(**problem_spec_payload(allowed_execution_modes=[mode]))
            self.assertEqual(ps.allowed_execution_modes, [mode])

    def test_rejects_legacy_execution_mode_field(self) -> None:
        """v0.4 不再接受旧 execution_mode 字段。"""
        with self.assertRaises(ValueError):
            ProblemSpecCreate(**problem_spec_payload(execution_mode="hybrid"))

    def test_create_with_campaign_id(self) -> None:
        """可关联已有 campaign。"""
        ps = ProblemSpecCreate(**problem_spec_payload(campaign_id="campaign_001"))
        self.assertEqual(ps.campaign_id, "campaign_001")

    def test_full_problem_spec_record(self) -> None:
        """ProblemSpec 完整记录包含系统字段。"""
        now = datetime.now(timezone.utc)
        ps = ProblemSpec(
            problem_spec_id="ps_test_001",
            created_by="tester",
            created_at=now,
            updated_at=now,
            **problem_spec_payload(),
        )
        self.assertEqual(ps.problem_spec_id, "ps_test_001")
        self.assertEqual(ps.schema_version, "0.4")
        self.assertEqual(ps.status, "draft")
        self.assertEqual(ps.frozen_version, 0)


# =============================================================================
# AlgorithmRegistry Schema 测试
# =============================================================================


class AlgorithmRegistrySchemaTest(ComputationTestCase):
    """覆盖 AlgorithmRegistry 条目的校验和构建。"""

    def test_valid_algorithm_entry(self) -> None:
        """合法算法条目创建成功。"""
        entry = AlgorithmRegistryEntry(
            algorithm_id="test_adapter",
            name="测试算法",
            type="simulator",
            material_scope=["fluoropolymer", "universal"],
            task_scope=["COMPUTE_PREDICT"],
            input_schema=AlgorithmIOSchema(
                fields={"smiles": "string"},
                required=["smiles"],
            ),
            output_schema=AlgorithmIOSchema(
                fields={"energy": "float"},
                required=["energy"],
            ),
            trigger_modes=["human_workflow", "autoresearch"],
            developer_attribution=AttributionItem(
                name="测试团队",
                role="developer",
                organization="测试机构",
                visibility="prominent",
            ),
        )
        self.assertEqual(entry.algorithm_id, "test_adapter")
        self.assertEqual(entry.name, "测试算法")
        self.assertEqual(entry.type, "simulator")
        self.assertIn("human_workflow", entry.trigger_modes)
        self.assertEqual(entry.developer_attribution.organization, "测试机构")

    def test_rejects_empty_algorithm_id(self) -> None:
        """空算法 ID 被拒绝。"""
        with self.assertRaises(ValueError):
            AlgorithmRegistryEntry(
                algorithm_id="   ",
                name="测试算法",
            )

    def test_rejects_empty_name(self) -> None:
        """空算法名称被拒绝。"""
        with self.assertRaises(ValueError):
            AlgorithmRegistryEntry(
                algorithm_id="test",
                name="   ",
            )

    def test_default_values(self) -> None:
        """默认值正确填充。"""
        entry = AlgorithmRegistryEntry(
            algorithm_id="test_defaults",
            name="默认值测试",
        )
        self.assertEqual(entry.type, "predictor")
        self.assertEqual(entry.material_scope, ["universal"])
        self.assertEqual(entry.status, "active")
        self.assertEqual(entry.version, "1.0.0")
        self.assertEqual(entry.call_method, "REST")


# =============================================================================
# AlgorithmRun Schema 测试
# =============================================================================


class AlgorithmRunSchemaTest(ComputationTestCase):
    """覆盖 AlgorithmRun 的创建、触发来源区分和关联字段。"""

    def test_create_human_workflow_trigger_run(self) -> None:
        """人工 Workflow 触发的 AlgorithmRun 创建成功。"""
        ar = AlgorithmRunCreate(**algorithm_run_payload())
        self.assertEqual(ar.algorithm_id, "local_xtb_adapter")
        self.assertEqual(ar.trigger_source, "human_workflow")

    def test_create_autoresearch_trigger_run(self) -> None:
        """AutoResearch 触发的 AlgorithmRun 创建成功。"""
        ar = AlgorithmRunCreate(
            **algorithm_run_payload(trigger_source="autoresearch")
        )
        self.assertEqual(ar.trigger_source, "autoresearch")

    def test_create_with_all_cross_references(self) -> None:
        """包含完整交叉引用的 AlgorithmRun 创建成功。"""
        ar = AlgorithmRunCreate(
            **algorithm_run_payload(
                problem_spec_id="ps_001",
                campaign_id="camp_001",
                research_run_id="rr_001",
                stage_run_id="sr_001",
                trigger_context_id="ctx_001",
                input_snapshot={"smiles": "C=CF", "charge": 0},
                reason="人工验证氟基单体计算",
            )
        )
        self.assertEqual(ar.problem_spec_id, "ps_001")
        self.assertEqual(ar.campaign_id, "camp_001")
        self.assertEqual(ar.research_run_id, "rr_001")

    def test_full_algorithm_run_record(self) -> None:
        """AlgorithmRun 完整记录包含所有系统字段。"""
        now = datetime.now(timezone.utc)
        ar = AlgorithmRun(
            run_id="ar_test_001",
            algorithm_id="local_xtb_adapter",
            trigger_source="human_workflow",
            created_by="tester",
            created_at=now,
            updated_at=now,
        )
        self.assertEqual(ar.run_id, "ar_test_001")
        self.assertEqual(ar.status, "queued")
        self.assertIsNone(ar.linked_computation_run_id)
        self.assertIsNone(ar.linked_suggestion_id)

    def test_algorithm_run_with_computation_link(self) -> None:
        """AlgorithmRun 可关联 ComputationRun。"""
        now = datetime.now(timezone.utc)
        ar = AlgorithmRun(
            run_id="ar_with_comp",
            algorithm_id="local_xtb_adapter",
            trigger_source="autoresearch",
            linked_computation_run_id="comp_run_001",
            created_by="system",
            created_at=now,
            updated_at=now,
        )
        self.assertEqual(ar.linked_computation_run_id, "comp_run_001")

    def test_rejects_empty_algorithm_id(self) -> None:
        """空 algorithm_id 被拒绝。"""
        with self.assertRaises(ValueError):
            AlgorithmRunCreate(**algorithm_run_payload(algorithm_id="   "))


# =============================================================================
# ResearchRun / StageGate Schema 测试
# =============================================================================


class ResearchRunSchemaTest(ComputationTestCase):
    """覆盖 ResearchRun、ResearchStageRun、StageGate 的校验。"""

    def test_create_valid_research_run(self) -> None:
        """合法 ResearchRun 创建成功。"""
        rr = ResearchRunCreate(**research_run_payload())
        self.assertEqual(rr.problem_spec_id, "ps_demo_001")
        self.assertEqual(rr.execution_decision_id, "ed_demo_001")
        self.assertEqual(rr.profile_id, "fluoropolymer")
        self.assertEqual(rr.max_iterations, 5)

    def test_create_with_campaign(self) -> None:
        """ResearchRun 可关联 campaign。"""
        rr = ResearchRunCreate(
            **research_run_payload(campaign_id="camp_001")
        )
        self.assertEqual(rr.campaign_id, "camp_001")

    def test_rejects_empty_problem_spec_id(self) -> None:
        """空 problem_spec_id 被拒绝。"""
        with self.assertRaises(ValueError):
            ResearchRunCreate(**research_run_payload(problem_spec_id="   "))

    def test_full_research_run_record(self) -> None:
        """ResearchRun 完整记录包含系统字段。"""
        now = datetime.now(timezone.utc)
        rr = ResearchRun(
            run_id="rr_test_001",
            problem_spec_id="ps_demo_001",
            created_by="tester",
            created_at=now,
            updated_at=now,
        )
        self.assertEqual(rr.run_id, "rr_test_001")
        self.assertEqual(rr.status, "draft")
        self.assertIsNone(rr.current_stage)
        self.assertEqual(len(rr.stage_runs), 0)

    def test_stage_gate_definition(self) -> None:
        """StageGate 定义创建成功。"""
        gate = StageGate(
            stage_key="RECOMMENDATION_ASK",
            required_inputs=["prediction_results"],
            expected_outputs=["top_k_candidates"],
            definition_of_done="Top-K 候选已生成",
            gate_policy={"require_approval": True},
            retry_policy={"max_retries": 3},
        )
        self.assertEqual(gate.stage_key, "RECOMMENDATION_ASK")
        self.assertTrue(gate.gate_policy["require_approval"])

    def test_stage_gate_decision(self) -> None:
        """审批决策记录创建成功。"""
        now = datetime.now(timezone.utc)
        decision = StageGateDecision(
            stage_key="RECOMMENDATION_ASK",
            decision="approved",
            actor_user_id="expert_001",
            reason="候选分子合成可行，同意提交计算",
            decided_at=now,
        )
        self.assertEqual(decision.decision, "approved")
        self.assertEqual(decision.actor_user_id, "expert_001")

    def test_stage_gate_decision_requires_reason(self) -> None:
        """审批决策必须有原因。"""
        with self.assertRaises(ValueError):
            StageGateDecision(
                stage_key="RECOMMENDATION_ASK",
                decision="rejected",
                actor_user_id="expert_001",
                reason="   ",
                decided_at=datetime.now(timezone.utc),
            )

    def test_stage_run_record(self) -> None:
        """ResearchStageRun 记录创建成功。"""
        now = datetime.now(timezone.utc)
        sr = ResearchStageRun(
            stage_run_id="sr_test_001",
            research_run_id="rr_test_001",
            stage_key="COMPUTE_PREDICT",
            status="running",
            created_at=now,
            updated_at=now,
        )
        self.assertEqual(sr.stage_key, "COMPUTE_PREDICT")
        self.assertEqual(sr.status, "running")

    def test_approval_request_validation(self) -> None:
        """审批请求校验。"""
        req = StageApprovalRequest(
            stage_key="RECOMMENDATION_ASK",
            decision="approved",
            reason="同意推荐候选",
        )
        self.assertEqual(req.decision, "approved")

    def test_approval_request_requires_reason(self) -> None:
        """审批请求必须有原因。"""
        with self.assertRaises(ValueError):
            StageApprovalRequest(
                stage_key="RECOMMENDATION_ASK",
                decision="approved",
                reason="   ",
            )

    def test_status_change_request_validation(self) -> None:
        """状态变更请求校验。"""
        req = ResearchRunStatusChangeRequest(
            target_status="running",
            reason="启动 AutoResearch 运行",
        )
        self.assertEqual(req.target_status, "running")

    def test_status_change_request_requires_reason(self) -> None:
        """状态变更必须有原因。"""
        with self.assertRaises(ValueError):
            ResearchRunStatusChangeRequest(
                target_status="running",
                reason="   ",
            )


# =============================================================================
# 状态转移规则测试
# =============================================================================


class StatusTransitionTest(ComputationTestCase):
    """覆盖 ResearchRun 和 ResearchStageRun 的状态转移规则。"""

    def test_research_run_valid_transitions(self) -> None:
        """合法状态转移返回 True。"""
        self.assertTrue(validate_research_run_transition("draft", "running"))
        self.assertTrue(validate_research_run_transition("running", "blocked_approval"))
        self.assertTrue(validate_research_run_transition("running", "paused"))
        self.assertTrue(validate_research_run_transition("running", "completed"))
        self.assertTrue(validate_research_run_transition("running", "failed"))
        self.assertTrue(validate_research_run_transition("blocked_approval", "running"))
        self.assertTrue(validate_research_run_transition("paused", "running"))
        self.assertTrue(validate_research_run_transition("completed", "archived"))

    def test_research_run_invalid_transitions(self) -> None:
        """非法状态转移返回 False。"""
        self.assertFalse(validate_research_run_transition("draft", "completed"))
        self.assertFalse(validate_research_run_transition("completed", "running"))
        self.assertFalse(validate_research_run_transition("failed", "running"))
        self.assertFalse(validate_research_run_transition("archived", "running"))

    def test_stage_valid_transitions(self) -> None:
        """合法阶段状态转移返回 True。"""
        self.assertTrue(validate_stage_transition("pending", "running"))
        self.assertTrue(validate_stage_transition("running", "completed"))
        self.assertTrue(validate_stage_transition("running", "failed"))
        self.assertTrue(validate_stage_transition("running", "blocked_approval"))
        self.assertTrue(validate_stage_transition("blocked_approval", "completed"))
        self.assertTrue(validate_stage_transition("blocked_approval", "failed"))

    def test_stage_invalid_transitions(self) -> None:
        """非法阶段状态转移返回 False。"""
        self.assertFalse(validate_stage_transition("completed", "running"))
        self.assertFalse(validate_stage_transition("failed", "running"))
        self.assertFalse(validate_stage_transition("pending", "completed"))


# =============================================================================
# 中文错误消息测试
# =============================================================================


class ChineseErrorMessageTest(ComputationTestCase):
    """确保所有 field_validator 使用中文错误消息。"""

    def test_problem_spec_name_error_in_chinese(self) -> None:
        """ProblemSpec 名称错误消息为中文。"""
        with self.assertRaises(ValueError) as ctx:
            ProblemSpecCreate(**problem_spec_payload(name="   "))
        self.assertIn("不能为空", str(ctx.exception))

    def test_variable_bounds_error_in_chinese(self) -> None:
        """变量边界错误消息为中文。"""
        with self.assertRaises(ValueError) as ctx:
            ProblemSpecVariable(name="test", type="continuous", bounds=[100, 0])
        self.assertIn("最小值", str(ctx.exception))

    def test_algorithm_id_error_in_chinese(self) -> None:
        """算法 ID 错误消息为中文。"""
        with self.assertRaises(ValueError) as ctx:
            AlgorithmRegistryEntry(algorithm_id="   ", name="test")
        self.assertIn("不能为空", str(ctx.exception))

    def test_approval_reason_error_in_chinese(self) -> None:
        """审批原因错误消息为中文（空白字符被 strip 后为空）。"""
        with self.assertRaises(ValueError) as ctx:
            StageGateDecision(
                stage_key="RECOMMENDATION_ASK",
                decision="approved",
                actor_user_id="tester",
                reason="   ",
                decided_at=datetime.now(timezone.utc),
            )
        self.assertIn("不能为空", str(ctx.exception))


# =============================================================================
# Literal 类型测试
# =============================================================================


class LiteralTypeTest(ComputationTestCase):
    """确保所有 Literal 类型值正确。"""

    def test_execution_decision_mode_values(self) -> None:
        """ExecutionDecisionMode 包含两种 v0.4 执行路径。"""
        self.assertIn("manual_workbench", ExecutionDecisionMode.__args__)
        self.assertIn("autoresearch", ExecutionDecisionMode.__args__)

    def test_trigger_source_values(self) -> None:
        """TriggerSource 包含三种来源。"""
        self.assertIn("human_workflow", TriggerSource.__args__)
        self.assertIn("autoresearch", TriggerSource.__args__)
        self.assertIn("system", TriggerSource.__args__)

    def test_research_run_status_values(self) -> None:
        """ResearchRunStatus 包含七种状态。"""
        for status in ["draft", "running", "paused", "blocked_approval", "completed", "failed", "archived"]:
            self.assertIn(status, ResearchRunStatus.__args__)

    def test_research_stage_status_values(self) -> None:
        """ResearchStageStatus 包含五种状态。"""
        for status in ["pending", "running", "blocked_approval", "completed", "failed"]:
            self.assertIn(status, ResearchStageStatus.__args__)

    def test_research_stage_keys(self) -> None:
        """ResearchStageKey 包含十个阶段。"""
        expected_stages = [
            "PROBLEM_SPEC", "KNOWLEDGE_RETRIEVAL", "STRUCTURE_FEATURE",
            "COMPUTE_PREDICT", "RECOMMENDATION_ASK", "HUMAN_REVIEW",
            "EXPERIMENT_EXECUTION", "RESULT_TELL", "MODEL_UPDATE", "ARCHIVE_LEARNING",
        ]
        for stage in expected_stages:
            self.assertIn(stage, ResearchStageKey.__args__)


# =============================================================================
# 列表响应模型测试
# =============================================================================


class ListDataSchemaTest(ComputationTestCase):
    """覆盖列表响应 wrapper 模型。"""

    def test_problem_spec_list_data(self) -> None:
        """ProblemSpecListData 构建正确。"""
        now = datetime.now(timezone.utc)
        items = [
            ProblemSpec(
                problem_spec_id="ps_001",
                created_by="tester",
                created_at=now,
                updated_at=now,
                **problem_spec_payload(),
            ),
        ]
        ld = ProblemSpecListData(items=items, page=1, page_size=20, total=1)
        self.assertEqual(len(ld.items), 1)
        self.assertEqual(ld.total, 1)

    def test_algorithm_run_list_data(self) -> None:
        """AlgorithmRunListData 构建正确。"""
        now = datetime.now(timezone.utc)
        items = [
            AlgorithmRun(
                run_id="ar_001",
                algorithm_id="test_adapter",
                trigger_source="human_workflow",
                created_by="tester",
                created_at=now,
                updated_at=now,
            ),
        ]
        ld = AlgorithmRunListData(items=items, page=1, page_size=20, total=1)
        self.assertEqual(len(ld.items), 1)

    def test_research_run_list_data(self) -> None:
        """ResearchRunListData 构建正确。"""
        now = datetime.now(timezone.utc)
        items = [
            ResearchRun(
                run_id="rr_001",
                problem_spec_id="ps_001",
                created_by="tester",
                created_at=now,
                updated_at=now,
            ),
        ]
        ld = ResearchRunListData(items=items, page=1, page_size=20, total=1)
        self.assertEqual(len(ld.items), 1)
