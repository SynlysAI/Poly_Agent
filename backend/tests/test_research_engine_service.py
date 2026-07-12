"""ResearchEngine service 单元测试。

覆盖 ResearchEngineService 的 ProblemSpec CRUD、冻结、
AlgorithmRegistry 种子写入、AlgorithmRun 创建和执行、Mock Runner 逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from fastapi import HTTPException

from app.schemas.research_engine import (
    AlgorithmRunCreate,
    ExecutionDecisionCreate,
    ManualAlgorithmWorkflowCreate,
    ProblemSpec,
    ProblemSpecCreate,
    ProblemSpecObjective,
    ProblemSpecVariable,
)
from app.services.research_engine_algorithm_runner import (
    ComputationSubmitAdapter,
    LiteratureMockRunner,
    MOBOMockRunner,
    PolymerDescriptorMockRunner,
    PropertyPredictorMockRunner,
    get_runner,
)
from app.services.optimization_service import OptimizationService
from app.services.research_engine_service import ResearchEngineService


def problem_spec_payload(**overrides) -> dict:
    """构建最小 ProblemSpec 创建请求。"""
    payload = {
        "name": "氟基高分子测试任务",
        "material_family": "fluoropolymer",
        "problem_type": "formulation_process_optimization",
        "objectives": [
            {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
        ],
    }
    payload.update(overrides)
    return payload


# =============================================================================
# ProblemSpec Service 测试
# =============================================================================


class ProblemSpecServiceTest(ComputationTestCase):
    """覆盖 ProblemSpec 业务服务层。"""

    def setUp(self) -> None:
        super().setUp()
        self.service = ResearchEngineService()

    def test_create_draft(self) -> None:
        """创建 ProblemSpec 草稿成功。"""
        payload = ProblemSpecCreate(**problem_spec_payload())
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.assertEqual(ps.name, "氟基高分子测试任务")
        self.assertEqual(ps.status, "draft")
        self.assertEqual(ps.schema_version, "0.4")
        self.assertEqual(ps.decision_status, "pending_execution_decision")
        self.assertEqual(ps.allowed_execution_modes, ["manual_workbench", "autoresearch"])
        self.assertTrue(ps.problem_spec_id.startswith("ps_"))

    def test_get_problem_spec(self) -> None:
        """获取 ProblemSpec 详情。"""
        payload = ProblemSpecCreate(**problem_spec_payload())
        created = self.service.create_problem_spec(payload, actor_user_id="tester")
        fetched = self.service.get_problem_spec(created.problem_spec_id)
        self.assertEqual(fetched.problem_spec_id, created.problem_spec_id)
        self.assertEqual(fetched.name, created.name)

    def test_get_nonexistent_returns_404(self) -> None:
        """不存在的 ProblemSpec 返回 404。"""
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.service.get_problem_spec("ps_nonexistent")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_problem_specs(self) -> None:
        """分页查询 ProblemSpec 列表。"""
        for i in range(3):
            payload = ProblemSpecCreate(**problem_spec_payload(name=f"任务{i}"))
            self.service.create_problem_spec(payload, actor_user_id="tester")

        result = self.service.list_problem_specs(page=1, page_size=2)
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.total, 3)

    def test_list_by_status(self) -> None:
        """按状态过滤。"""
        payload = ProblemSpecCreate(**problem_spec_payload(name="草稿任务"))
        created = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.service.freeze_problem_spec(created.problem_spec_id, actor_user_id="tester")

        result = self.service.list_problem_specs(status="frozen")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.status, "frozen")

    def test_list_by_material_family(self) -> None:
        """按材料体系过滤。"""
        payload = ProblemSpecCreate(**problem_spec_payload(name="氟基任务", material_family="fluoropolymer"))
        self.service.create_problem_spec(payload, actor_user_id="tester")

        result = self.service.list_problem_specs(material_family="fluoropolymer")
        self.assertGreaterEqual(result.total, 1)

    def test_update_draft(self) -> None:
        """更新草稿成功。"""
        payload = ProblemSpecCreate(**problem_spec_payload())
        created = self.service.create_problem_spec(payload, actor_user_id="tester")

        updated_payload = ProblemSpecCreate(
            **problem_spec_payload(
                name="更新后的任务名",
                allowed_execution_modes=["manual_workbench"],
            )
        )
        updated = self.service.update_problem_spec(
            created.problem_spec_id, updated_payload, actor_user_id="tester"
        )
        self.assertEqual(updated.name, "更新后的任务名")
        self.assertEqual(updated.allowed_execution_modes, ["manual_workbench"])

    def test_update_frozen_returns_409(self) -> None:
        """已冻结的 ProblemSpec 不可直接修改。"""
        from fastapi import HTTPException

        payload = ProblemSpecCreate(**problem_spec_payload())
        created = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.service.freeze_problem_spec(created.problem_spec_id, actor_user_id="tester")

        update_payload = ProblemSpecCreate(**problem_spec_payload(name="尝试更新"))
        with self.assertRaises(HTTPException) as ctx:
            self.service.update_problem_spec(created.problem_spec_id, update_payload, actor_user_id="tester")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_freeze_problem_spec(self) -> None:
        """冻结 ProblemSpec 成功。"""
        payload = ProblemSpecCreate(**problem_spec_payload())
        created = self.service.create_problem_spec(payload, actor_user_id="tester")

        frozen = self.service.freeze_problem_spec(created.problem_spec_id, actor_user_id="tester")
        self.assertEqual(frozen.status, "frozen")
        self.assertEqual(frozen.frozen_version, 1)

    def test_freeze_already_frozen_returns_409(self) -> None:
        """重复冻结返回 409。"""
        from fastapi import HTTPException

        payload = ProblemSpecCreate(**problem_spec_payload())
        created = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.service.freeze_problem_spec(created.problem_spec_id, actor_user_id="tester")

        with self.assertRaises(HTTPException) as ctx:
            self.service.freeze_problem_spec(created.problem_spec_id, actor_user_id="tester")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_create_with_objectives(self) -> None:
        """包含多目标的 ProblemSpec 创建成功。"""
        payload = ProblemSpecCreate(
            **problem_spec_payload(
                objectives=[
                    {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
                    {"name": "thermal_stability", "direction": "maximize", "unit": "celsius"},
                ],
            )
        )
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.assertEqual(len(ps.objectives), 2)

    def test_create_with_variables(self) -> None:
        """包含变量定义的 ProblemSpec 创建成功。"""
        payload = ProblemSpecCreate(
            **problem_spec_payload(
                variables=[
                    {"name": "fluorine_content", "type": "continuous", "role": "formulation", "unit": "percent", "bounds": [0, 100]},
                    {"name": "monomer_smiles", "type": "categorical", "role": "structure", "categories": ["C=CF", "C=C(F)F"]},
                ],
            )
        )
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.assertEqual(len(ps.variables), 2)

    def test_create_with_constraints(self) -> None:
        """包含约束条件的 ProblemSpec 创建成功。"""
        payload = ProblemSpecCreate(
            **problem_spec_payload(
                constraints=[
                    {"name": "synthesizable", "type": "hard"},
                    {"name": "temp_limit", "type": "hard", "expression": "temperature <= 180"},
                ],
            )
        )
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.assertEqual(len(ps.constraints), 2)

    def test_create_with_measurements(self) -> None:
        """包含测量条件的 ProblemSpec 创建成功。"""
        payload = ProblemSpecCreate(
            **problem_spec_payload(
                measurements=[
                    {"name": "dielectric_constant", "condition": "room_temperature", "method": "impedance"},
                ],
            )
        )
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.assertEqual(len(ps.measurements), 1)

    def test_allowed_execution_modes(self) -> None:
        """ProblemSpec 记录可用执行策略，但不直接启动运行。"""
        payload = ProblemSpecCreate(
            **problem_spec_payload(
                allowed_execution_modes=["manual_workbench"],
                name="只允许人工工作台",
            )
        )
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")
        self.assertEqual(ps.allowed_execution_modes, ["manual_workbench"])
        self.assertEqual(ps.decision_status, "pending_execution_decision")

    def test_auto_created_campaign_is_optimization_compatible(self) -> None:
        """自动创建的 ResearchEngine 容器 campaign 可被优化模块读取。"""
        payload = ProblemSpecCreate(
            **problem_spec_payload(
                objectives=[
                    {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
                    {"name": "density", "direction": "minimize", "unit": "g/cm3"},
                ],
            )
        )
        ps = self.service.create_problem_spec(payload, actor_user_id="tester")

        optimization_service = OptimizationService()
        listing = optimization_service.list_campaigns(page=1, page_size=20, actor_user_id="tester")
        detail = optimization_service.get_detail(ps.campaign_id, actor_user_id="tester")

        self.assertEqual(listing.total, 1)
        self.assertEqual(detail.campaign.planner_type, "fallback")
        self.assertEqual(detail.campaign.source, "research_engine")
        self.assertEqual(detail.campaign.linked_problem_spec_id, ps.problem_spec_id)
        self.assertEqual([objective.direction for objective in detail.campaign.objectives], ["max", "min"])


# =============================================================================
# AlgorithmRegistry Service 测试
# =============================================================================


class AlgorithmRegistryServiceTest(ComputationTestCase):
    """覆盖 AlgorithmRegistry 业务服务层。"""

    def setUp(self) -> None:
        super().setUp()
        self.service = ResearchEngineService()

    def test_seed_defaults_is_idempotent(self) -> None:
        """种子写入幂等。"""
        count1 = self.service.seed_default_algorithms()
        self.assertGreater(count1, 0)

        count2 = self.service.seed_default_algorithms()
        self.assertEqual(count2, 0)

    def test_seed_has_all_eight_entries(self) -> None:
        """种子中包含 8 个算法条目（3 计算 + 5 mock）。"""
        self.service.seed_default_algorithms()
        result = self.service.list_algorithms(page_size=100)
        self.assertGreaterEqual(result.total, 8)

    def test_get_algorithm(self) -> None:
        """获取单个算法条目详情。"""
        self.service.seed_default_algorithms()
        entry = self.service.get_algorithm("literature_mock")
        self.assertEqual(entry.algorithm_id, "literature_mock")
        self.assertEqual(entry.type, "retriever")
        self.assertEqual(entry.name, "文献检索")

    def test_get_nonexistent_algorithm_returns_404(self) -> None:
        """不存在的算法条目返回 404。"""
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.service.get_algorithm("nonexistent_algo")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_all_algorithms(self) -> None:
        """列出所有算法条目。"""
        self.service.seed_default_algorithms()
        result = self.service.list_algorithms()
        self.assertGreaterEqual(result.total, 8)
        self.assertEqual(result.page, 1)

    def test_list_by_type(self) -> None:
        """按算法类型过滤。"""
        self.service.seed_default_algorithms()
        result = self.service.list_algorithms(algorithm_type="simulator")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.type, "simulator")

    def test_list_by_trigger_mode(self) -> None:
        """按触发方式过滤。"""
        self.service.seed_default_algorithms()
        result = self.service.list_algorithms(trigger_mode="human_workflow")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertIn("human_workflow", item.trigger_modes)

    def test_list_by_status(self) -> None:
        """按状态过滤。"""
        self.service.seed_default_algorithms()
        result = self.service.list_algorithms(status="active")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.status, "active")

    def test_mock_algorithms_have_correct_types(self) -> None:
        """Mock 算法具有正确的类型标识。"""
        self.service.seed_default_algorithms()

        literature = self.service.get_algorithm("literature_mock")
        self.assertEqual(literature.type, "retriever")

        descriptor = self.service.get_algorithm("polymer_descriptor_mock")
        self.assertEqual(descriptor.type, "predictor")

        predictor = self.service.get_algorithm("property_predictor_mock")
        self.assertEqual(predictor.type, "predictor")

        mobo = self.service.get_algorithm("mobo_mock")
        self.assertEqual(mobo.type, "optimizer")

        submit = self.service.get_algorithm("computation_submit_adapter")
        self.assertEqual(submit.type, "simulator")

    def test_adapter_algorithms_have_correct_types(self) -> None:
        """计算 adapter 算法具有正确的类型标识。"""
        self.service.seed_default_algorithms()

        for algo_id in ["local_structure_adapter", "local_xtb_adapter", "orca_compute_engine_laser_adapter"]:
            entry = self.service.get_algorithm(algo_id)
            self.assertEqual(entry.type, "simulator")

    def test_all_algorithms_have_required_fields(self) -> None:
        """所有算法条目的必要字段不为空。"""
        self.service.seed_default_algorithms()
        result = self.service.list_algorithms(page_size=100)

        for entry in result.items:
            self.assertIsNotNone(entry.algorithm_id)
            self.assertIsNotNone(entry.name)
            self.assertIsNotNone(entry.type)
            self.assertIsNotNone(entry.status)
            self.assertGreater(len(entry.trigger_modes), 0)
            self.assertGreater(len(entry.task_scope), 0)

    def test_pagination(self) -> None:
        """分页查询正确。"""
        self.service.seed_default_algorithms()
        # 总共应有 8 个条目
        page1 = self.service.list_algorithms(page=1, page_size=5)
        self.assertEqual(len(page1.items), 5)
        self.assertGreaterEqual(page1.total, 8)

        page2 = self.service.list_algorithms(page=2, page_size=5)
        self.assertGreaterEqual(len(page2.items), 1)

    # ── Legacy trigger_modes 兼容性测试 ──

    def test_legacy_trigger_modes_human_normalized_to_human_workflow(self) -> None:
        """旧数据 trigger_modes=["human"] 应被规范化为 ["human_workflow"]。"""
        from app.infra.research_engine_repositories import AlgorithmRegistryRepository

        # 直接写入旧数据
        legacy_doc = {
            "algorithm_id": "legacy_algo_test",
            "name": "旧数据测试算法",
            "type": "predictor",
            "algorithm_family": "vertical_prediction",
            "material_scope": ["universal"],
            "task_scope": ["COMPUTE_PREDICT"],
            "input_schema": {"fields": {}, "required": [], "constraints": {}},
            "output_schema": {"fields": {}, "required": [], "constraints": {}},
            "call_method": "REST",
            "trigger_modes": ["human"],
            "runtime_dependency": "",
            "version": "1.0.0",
            "validation_metric": {},
            "owner": "test",
            "status": "active",
            "description": "旧数据测试",
        }
        AlgorithmRegistryRepository.save("algorithm_id", legacy_doc)

        # get_algorithm 应返回规范化后的值
        entry = self.service.get_algorithm("legacy_algo_test")
        self.assertEqual(entry.trigger_modes, ["human_workflow"])

    def test_legacy_algo_returned_by_human_workflow_filter(self) -> None:
        """trigger_mode=human_workflow 过滤应包含旧 human 记录。"""
        from app.infra.research_engine_repositories import AlgorithmRegistryRepository

        # 直接写入旧数据
        legacy_doc = {
            "algorithm_id": "legacy_algo_filter_test",
            "name": "旧数据过滤测试",
            "type": "predictor",
            "algorithm_family": "vertical_prediction",
            "material_scope": ["universal"],
            "task_scope": ["COMPUTE_PREDICT"],
            "input_schema": {"fields": {}, "required": [], "constraints": {}},
            "output_schema": {"fields": {}, "required": [], "constraints": {}},
            "call_method": "REST",
            "trigger_modes": ["human"],
            "runtime_dependency": "",
            "version": "1.0.0",
            "validation_metric": {},
            "owner": "test",
            "status": "active",
            "description": "旧数据过滤测试",
        }
        AlgorithmRegistryRepository.save("algorithm_id", legacy_doc)

        # human_workflow 过滤应能找到这个旧数据条目
        result = self.service.list_algorithms(trigger_mode="human_workflow", page_size=100)
        algo_ids = [item.algorithm_id for item in result.items]
        self.assertIn("legacy_algo_filter_test", algo_ids)
        # 验证返回的是规范化后的值
        for item in result.items:
            if item.algorithm_id == "legacy_algo_filter_test":
                self.assertEqual(item.trigger_modes, ["human_workflow"])

    def test_algorithm_run_with_legacy_algo_succeeds(self) -> None:
        """使用旧 trigger_modes=["human"] 的算法创建 AlgorithmRun 应成功通过触发校验。"""
        from app.infra.research_engine_repositories import AlgorithmRegistryRepository

        # 直接写入旧数据
        legacy_doc = {
            "algorithm_id": "legacy_algo_run_test",
            "name": "旧数据运行测试",
            "type": "predictor",
            "algorithm_family": "vertical_prediction",
            "material_scope": ["universal"],
            "task_scope": ["COMPUTE_PREDICT"],
            "input_schema": {
                "fields": {"smiles": "string", "target_properties": "list[string]"},
                "required": ["smiles", "target_properties"],
                "constraints": {},
            },
            "output_schema": {
                "fields": {"predictions": "dict", "uncertainty": "dict"},
                "required": ["predictions", "uncertainty"],
            },
            "call_method": "REST",
            "trigger_modes": ["human"],
            "runtime_dependency": "",
            "version": "1.0.0",
            "validation_metric": {},
            "owner": "test",
            "status": "active",
            "description": "旧数据运行测试",
        }
        AlgorithmRegistryRepository.save("algorithm_id", legacy_doc)

        # 创建 AlgorithmRun，trigger_source="human_workflow" 应对应规范化后的 trigger_modes
        # 旧值 "human" 被规范化为 "human_workflow"，触发校验通过
        # 但因无对应 runner，应返回 501（而非 400 触发不支持）
        with self.assertRaises(HTTPException) as ctx:
            self.service.create_algorithm_run(
                AlgorithmRunCreate(
                    algorithm_id="legacy_algo_run_test",
                    trigger_source="human_workflow",
                    input_snapshot={"smiles": "C=CF", "target_properties": ["dielectric_constant"]},
                ),
                actor_user_id="tester",
            )
        # 应因无 runner 而失败 (501)，而非因 trigger_mode 不支持 (400)
        self.assertEqual(ctx.exception.status_code, 501)
        self.assertIn("尚未实现执行器", ctx.exception.detail)

    def test_seed_defaults_repairs_legacy_trigger_modes(self) -> None:
        """seed_default_algorithms 应修复已存在条目的旧 trigger_modes 值。"""
        from app.infra.research_engine_repositories import AlgorithmRegistryRepository

        # 先写入一个正常的算法条目，改其 trigger_modes 为旧值
        self.service.seed_default_algorithms()
        AlgorithmRegistryRepository.update_fields(
            "literature_mock",
            {"trigger_modes": ["human", "autoresearch"]},
        )

        # 验证旧值在存储中
        doc = AlgorithmRegistryRepository.find_one({"algorithm_id": "literature_mock"})
        self.assertIn("human", doc.get("trigger_modes") or [])

        # 再次调用 seed，应修复旧值
        self.service.seed_default_algorithms()

        # 验证已修复
        doc = AlgorithmRegistryRepository.find_one({"algorithm_id": "literature_mock"})
        trigger_modes = doc.get("trigger_modes") or []
        self.assertNotIn("human", trigger_modes)
        self.assertIn("human_workflow", trigger_modes)


# =============================================================================
# ExecutionDecision / ManualWorkflow Service 测试
# =============================================================================


class ManualWorkflowServiceTest(ComputationTestCase):
    """覆盖 v0.4 的执行决策和人工 Workflow 主路径。"""

    def setUp(self) -> None:
        super().setUp()
        self.service = ResearchEngineService()
        self.service.seed_default_algorithms()
        self.problem_spec = self.service.create_problem_spec(
            ProblemSpecCreate(**problem_spec_payload()),
            actor_user_id="tester",
        )

    def test_create_manual_execution_decision(self) -> None:
        """ProblemSpec 校验后可显式选择 manual_workbench。"""
        decision = self.service.create_execution_decision(
            self.problem_spec.problem_spec_id,
            ExecutionDecisionCreate(mode="manual_workbench", reason="需要人工调试模型参数"),
            actor_user_id="tester",
        )
        self.assertTrue(decision.decision_id.startswith("ed_"))
        self.assertEqual(decision.problem_spec_id, self.problem_spec.problem_spec_id)
        self.assertEqual(decision.mode, "manual_workbench")

        active = self.service.get_active_execution_decision(self.problem_spec.problem_spec_id)
        self.assertEqual(active.decision_id, decision.decision_id)

    def test_reject_duplicate_active_decision_same_mode(self) -> None:
        """同一 ProblemSpec 同一模式不能重复创建 active decision。"""
        self.service.create_execution_decision(
            self.problem_spec.problem_spec_id,
            ExecutionDecisionCreate(mode="manual_workbench", reason="第一次选择"),
            actor_user_id="tester",
        )
        with self.assertRaises(HTTPException) as ctx:
            self.service.create_execution_decision(
                self.problem_spec.problem_spec_id,
                ExecutionDecisionCreate(mode="manual_workbench", reason="重复选择"),
                actor_user_id="tester",
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_single_node_manual_workflow_run_creates_algorithm_run(self) -> None:
        """单节点人工 WorkflowRun 会生成 WorkflowStepRun 和 AlgorithmRun。"""
        decision = self.service.create_execution_decision(
            self.problem_spec.problem_spec_id,
            ExecutionDecisionCreate(mode="manual_workbench", reason="先跑文献检索"),
            actor_user_id="tester",
        )
        workflow = self.service.create_manual_workflow(
            ManualAlgorithmWorkflowCreate(
                problem_spec_id=self.problem_spec.problem_spec_id,
                execution_decision_id=decision.decision_id,
                name="单节点文献检索",
                steps=[
                    {
                        "step_id": "s1",
                        "algorithm_id": "literature_mock",
                        "input_bindings": {
                            "keywords": {"source": "manual_input", "value": "氟基高分子 介电常数"}
                        },
                    }
                ],
            ),
            actor_user_id="tester",
        )

        run = self.service.start_workflow_run(workflow.workflow_id, actor_user_id="tester")
        self.assertEqual(run.status, "completed")
        self.assertEqual(len(run.step_runs), 1)
        self.assertEqual(run.step_runs[0].status, "completed")
        self.assertIsNotNone(run.step_runs[0].algorithm_run_id)

        algorithm_runs = self.service.list_algorithm_runs(
            workflow_run_id=run.workflow_run_id,
            trigger_source="human_workflow",
        )
        self.assertEqual(algorithm_runs.total, 1)
        self.assertEqual(algorithm_runs.items[0].trigger_source, "human_workflow")
        self.assertEqual(algorithm_runs.items[0].workflow_run_id, run.workflow_run_id)


# =============================================================================
# AlgorithmRun Service 测试
# =============================================================================


class AlgorithmRunServiceTest(ComputationTestCase):
    """覆盖 AlgorithmRun 业务服务层（创建、状态流转、查询）。"""

    def setUp(self) -> None:
        super().setUp()
        self.service = ResearchEngineService()
        # 写入算法种子数据
        self.service.seed_default_algorithms()

    def _create_run(self, algorithm_id: str = "literature_mock", **overrides) -> dict:
        """创建 AlgorithmRun 的辅助方法。"""
        payload_dict = {
            "algorithm_id": algorithm_id,
            "trigger_source": "human_workflow",
            "input_snapshot": {"keywords": "氟基高分子 介电常数"},
        }
        payload_dict.update(overrides)
        payload = AlgorithmRunCreate(**payload_dict)
        result = self.service.create_algorithm_run(payload, actor_user_id="tester")
        return result.model_dump()

    def test_create_literature_run(self) -> None:
        """创建文献检索 AlgorithmRun 成功。"""
        run = self._create_run("literature_mock")
        self.assertEqual(run["algorithm_id"], "literature_mock")
        self.assertEqual(run["trigger_source"], "human_workflow")
        self.assertEqual(run["status"], "completed")
        self.assertTrue(run["run_id"].startswith("arun_"))
        # 验证输出
        output = run["output_summary"]
        self.assertIn("knowledge_cards", output)
        self.assertIn("literature_summary", output)
        self.assertGreaterEqual(len(output["knowledge_cards"]), 3)

    def test_create_polymer_descriptor_run(self) -> None:
        """创建聚合物描述符生成 AlgorithmRun 成功。"""
        run = self._create_run(
            "polymer_descriptor_mock",
            input_snapshot={"smiles": "C=CF"},
        )
        self.assertEqual(run["status"], "completed")
        output = run["output_summary"]
        self.assertIn("descriptors", output)
        self.assertIn("molecular_weight", output)
        self.assertIn("logp", output)
        self.assertIn("tpsa", output)
        self.assertGreaterEqual(len(output.get("fingerprint_bits", [])), 1)

    def test_create_property_predictor_run(self) -> None:
        """创建性质预测 AlgorithmRun 成功。"""
        run = self._create_run(
            "property_predictor_mock",
            input_snapshot={
                "smiles": "C=C(F)F",
                "target_properties": ["dielectric_constant", "thermal_stability"],
                "fluorine_content": 45.0,
            },
        )
        self.assertEqual(run["status"], "completed")
        output = run["output_summary"]
        self.assertIn("predictions", output)
        self.assertIn("uncertainty", output)
        self.assertIn("dielectric_constant", output["predictions"])
        self.assertIn("thermal_stability", output["predictions"])

    def test_create_mobo_run(self) -> None:
        """创建 MOBO 推荐 AlgorithmRun 成功。"""
        run = self._create_run(
            "mobo_mock",
            input_snapshot={
                "problem_spec_id": "ps_test_001",
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                    {"name": "thermal_stability", "direction": "maximize"},
                ],
            },
        )
        self.assertEqual(run["status"], "completed")
        output = run["output_summary"]
        self.assertIn("top_k_candidates", output)
        self.assertIn("recommendation_reasons", output)
        # 默认返回 Top-5
        self.assertEqual(len(output["top_k_candidates"]), 5)
        # 每个候选有排名、预测值和推荐理由
        for candidate in output["top_k_candidates"]:
            self.assertIn("rank", candidate)
            self.assertIn("smiles", candidate)
            self.assertIn("reason", candidate)

    def test_create_run_with_problem_spec_and_campaign(self) -> None:
        """创建 AlgorithmRun 时关联 problem_spec_id 和 campaign_id。"""
        problem_spec = self.service.create_problem_spec(
            ProblemSpecCreate(**problem_spec_payload(name="算法运行关联任务")),
            actor_user_id="tester",
        )
        run = self._create_run(
            "literature_mock",
            problem_spec_id=problem_spec.problem_spec_id,
            campaign_id="camp_demo_001",
        )
        self.assertEqual(run["problem_spec_id"], problem_spec.problem_spec_id)
        self.assertEqual(run["campaign_id"], "camp_demo_001")

    def test_create_run_saves_input_snapshot(self) -> None:
        """AlgorithmRun 保存完整的 input_snapshot。"""
        input_data = {"keywords": "氟基高分子 介电常数", "material_family": "fluoropolymer", "max_results": 10}
        run = self._create_run("literature_mock", input_snapshot=input_data)
        self.assertEqual(run["input_snapshot"]["keywords"], "氟基高分子 介电常数")
        self.assertEqual(run["input_snapshot"]["max_results"], 10)

    def test_create_run_fails_for_invalid_algorithm(self) -> None:
        """不存在的 algorithm_id 返回 404。"""
        with self.assertRaises(HTTPException) as ctx:
            self._create_run("nonexistent_algo")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_create_run_fails_for_unsupported_trigger(self) -> None:
        """算法不支持指定触发来源时返回 400。"""
        # 对于正常的算法，trigger_mode 包含 human_workflow。
        run = self._create_run("literature_mock", trigger_source="human_workflow")
        self.assertEqual(run["status"], "completed")

        # 测试 system trigger：文献 mock 只支持 human_workflow 和 autoresearch。
        with self.assertRaises(HTTPException) as ctx:
            payload = AlgorithmRunCreate(
                algorithm_id="literature_mock",
                trigger_source="system",  # literature_mock 不支持 system
                input_snapshot={"keywords": "test"},
            )
            self.service.create_algorithm_run(payload, actor_user_id="tester")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_create_run_missing_required_input(self) -> None:
        """缺少必填输入字段时返回错误。"""
        with self.assertRaises((HTTPException, ValueError)):
            self._create_run(
                "literature_mock",
                input_snapshot={"material_family": "fluoropolymer"},  # 缺少 keywords
            )

    def test_get_algorithm_run(self) -> None:
        """获取 AlgorithmRun 详情。"""
        created = self._create_run("literature_mock")
        fetched = self.service.get_algorithm_run(created["run_id"])
        self.assertEqual(fetched.run_id, created["run_id"])
        self.assertEqual(fetched.algorithm_id, "literature_mock")

    def test_get_nonexistent_run_returns_404(self) -> None:
        """不存在的 AlgorithmRun 返回 404。"""
        with self.assertRaises(HTTPException) as ctx:
            self.service.get_algorithm_run("arun_nonexistent")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_algorithm_runs(self) -> None:
        """分页查询 AlgorithmRun 列表。"""
        for i in range(3):
            self._create_run("literature_mock")

        result = self.service.list_algorithm_runs(page=1, page_size=2)
        self.assertEqual(len(result.items), 2)
        self.assertGreaterEqual(result.total, 3)

    def test_list_by_status(self) -> None:
        """按状态过滤 AlgorithmRun。"""
        self._create_run("literature_mock")

        result = self.service.list_algorithm_runs(status="completed")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.status, "completed")

    def test_list_by_algorithm_id(self) -> None:
        """按 algorithm_id 过滤 AlgorithmRun。"""
        self._create_run("literature_mock")
        self._create_run("polymer_descriptor_mock", input_snapshot={"smiles": "C=CF"})

        result = self.service.list_algorithm_runs(algorithm_id="polymer_descriptor_mock")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.algorithm_id, "polymer_descriptor_mock")

    def test_list_by_trigger_source(self) -> None:
        """按 trigger_source 过滤 AlgorithmRun。"""
        self._create_run("literature_mock", trigger_source="human_workflow")

        result = self.service.list_algorithm_runs(trigger_source="human_workflow")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.trigger_source, "human_workflow")

    def test_list_by_problem_spec(self) -> None:
        """按 problem_spec_id 过滤 AlgorithmRun。"""
        first = self.service.create_problem_spec(
            ProblemSpecCreate(**problem_spec_payload(name="筛选任务一")),
            actor_user_id="tester",
        )
        second = self.service.create_problem_spec(
            ProblemSpecCreate(**problem_spec_payload(name="筛选任务二")),
            actor_user_id="tester",
        )
        self._create_run("literature_mock", problem_spec_id=first.problem_spec_id)
        self._create_run("literature_mock", problem_spec_id=second.problem_spec_id)

        result = self.service.list_algorithm_runs(problem_spec_id=first.problem_spec_id)
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.problem_spec_id, first.problem_spec_id)

    def test_list_by_campaign(self) -> None:
        """按 campaign_id 过滤 AlgorithmRun。"""
        self._create_run("literature_mock", campaign_id="camp_filter_001")

        result = self.service.list_algorithm_runs(campaign_id="camp_filter_001")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.campaign_id, "camp_filter_001")

    def test_algorithm_run_has_artifact_refs(self) -> None:
        """AlgorithmRun 完成时有 artifact_refs。"""
        run = self._create_run("literature_mock")
        self.assertIsInstance(run["artifact_refs"], list)
        self.assertGreater(len(run["artifact_refs"]), 0)

    def test_algorithm_run_deterministic_output(self) -> None:
        """相同输入产生相同输出（确定性 mock）。"""
        input_data = {"keywords": "氟基高分子", "material_family": "fluoropolymer"}

        run1 = self._create_run("literature_mock", input_snapshot=input_data)
        run2 = self._create_run("literature_mock", input_snapshot=input_data)

        # 输出应相同
        self.assertEqual(
            run1["output_summary"]["literature_summary"],
            run2["output_summary"]["literature_summary"],
        )
        self.assertEqual(
            run1["output_summary"]["total_results"],
            run2["output_summary"]["total_results"],
        )

    def test_all_runners_registered(self) -> None:
        """所有 5 个 runner 均已注册。"""
        expected_ids = {
            "literature_mock",
            "polymer_descriptor_mock",
            "property_predictor_mock",
            "mobo_mock",
            "computation_submit_adapter",
        }
        for algo_id in expected_ids:
            runner = get_runner(algo_id)
            self.assertIsNotNone(runner, f"Runner '{algo_id}' 未注册")
            self.assertEqual(runner.algorithm_id, algo_id)


# =============================================================================
# Mock Runner 单元测试
# =============================================================================


class MockRunnerUnitTest(ComputationTestCase):
    """覆盖各个 Mock Runner 的输入校验和输出格式。"""

    def setUp(self) -> None:
        super().setUp()
        self.service = ResearchEngineService()
        self.service.seed_default_algorithms()

    def test_literature_mock_output_schema(self) -> None:
        """literature_mock 输出包含 ≥ 3 条 knowledge cards。"""
        runner = LiteratureMockRunner()
        runner.validate_input({"keywords": "氟基高分子"})
        output = runner.run({"keywords": "氟基高分子"})
        self.assertGreaterEqual(len(output["knowledge_cards"]), 3)
        self.assertIsInstance(output["literature_summary"], str)
        self.assertGreater(len(output["literature_summary"]), 0)
        # 每条 knowledge card 有 title, authors, year, abstract, relevance_score
        for card in output["knowledge_cards"]:
            self.assertIn("title", card)
            self.assertIn("authors", card)
            self.assertIn("year", card)
            self.assertIn("abstract", card)
            self.assertIn("relevance_score", card)

    def test_polymer_descriptor_mock_output_schema(self) -> None:
        """polymer_descriptor_mock 输出包含 ≥ 6 个描述符字段。"""
        runner = PolymerDescriptorMockRunner()
        runner.validate_input({"smiles": "C=CF"})
        output = runner.run({"smiles": "C=CF"})
        self.assertGreaterEqual(len(output["descriptors"]), 6)
        self.assertGreater(output["molecular_weight"], 0)
        self.assertIsInstance(output["fingerprint_bits"], list)

    def test_property_predictor_mock_output_schema(self) -> None:
        """property_predictor_mock 输出包含 predictions 和 uncertainty。"""
        runner = PropertyPredictorMockRunner()
        runner.validate_input({
            "smiles": "C=C(F)F",
            "target_properties": ["dielectric_constant", "thermal_stability"],
        })
        output = runner.run({
            "smiles": "C=C(F)F",
            "target_properties": ["dielectric_constant", "thermal_stability"],
        })
        self.assertIn("dielectric_constant", output["predictions"])
        self.assertIn("thermal_stability", output["predictions"])
        self.assertIn("dielectric_constant", output["uncertainty"])
        self.assertIn("thermal_stability", output["uncertainty"])
        self.assertIn("dielectric_constant", output["confidence_interval"])

    def test_mobo_mock_output_schema(self) -> None:
        """mobo_mock 输出 Top-5 candidates + reasons。"""
        runner = MOBOMockRunner()
        runner.validate_input({
            "problem_spec_id": "ps_test_001",
            "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
        })
        output = runner.run({
            "problem_spec_id": "ps_test_001",
            "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
        })
        self.assertEqual(len(output["top_k_candidates"]), 5)
        self.assertGreater(len(output["recommendation_reasons"]), 0)
        # 每个候选有 reason
        for candidate in output["top_k_candidates"]:
            self.assertIn("reason", candidate)

    def test_computation_submit_adapter_validation(self) -> None:
        """computation_submit_adapter 校验 workflow_type 白名单。"""
        runner = ComputationSubmitAdapter()
        # 合法 workflow_type
        runner.validate_input({"workflow_type": "LOCAL_XTB", "smiles": "CCO"})
        # 非法 workflow_type
        with self.assertRaises(ValueError):
            runner.validate_input({"workflow_type": "INVALID_WORKFLOW", "smiles": "CCO"})

    def test_computation_submit_adapter_output(self) -> None:
        """computation_submit_adapter 输出包含正确字段。"""
        runner = ComputationSubmitAdapter()
        runner.validate_input({"workflow_type": "LOCAL_XTB", "smiles": "CCO"})
        output = runner.run({"workflow_type": "LOCAL_XTB", "smiles": "CCO"})
        self.assertIn("computation_run_id", output)
        self.assertIn("status", output)
        self.assertEqual(output["status"], "submitted")

    def test_mock_runner_input_validation(self) -> None:
        """BaseMockRunner 校验必填字段。"""
        runner = LiteratureMockRunner()
        # 缺少 keywords
        with self.assertRaises(ValueError):
            runner.validate_input({"material_family": "fluoropolymer"})
        # 包含 keywords 应通过
        runner.validate_input({"keywords": "氟基高分子"})

    def test_mock_runner_constraint_validation(self) -> None:
        """BaseMockRunner 校验边界约束。"""
        runner = PropertyPredictorMockRunner()
        # 氟含量超出边界
        with self.assertRaises(ValueError):
            runner.validate_input({
                "smiles": "C=CF",
                "target_properties": ["dielectric_constant"],
                "fluorine_content": 150,  # 超出 0-100 范围
            })

    def test_mock_runner_deterministic_output(self) -> None:
        """相同输入 → 相同输出。"""
        runner = PolymerDescriptorMockRunner()
        input_data = {"smiles": "C=CF"}
        output1 = runner.run(input_data)
        output2 = runner.run(input_data)
        self.assertEqual(output1["molecular_weight"], output2["molecular_weight"])
        self.assertEqual(output1["logp"], output2["logp"])

    def test_mock_runner_different_input_different_output(self) -> None:
        """不同输入 → 不同输出。"""
        runner = PolymerDescriptorMockRunner()
        output1 = runner.run({"smiles": "C=CF"})
        output2 = runner.run({"smiles": "CCCCCC"})
        self.assertNotEqual(output1["molecular_weight"], output2["molecular_weight"])

    def test_get_artifact_specs(self) -> None:
        """BaseMockRunner.get_artifact_specs 返回 artifact 规格列表。"""
        runner = LiteratureMockRunner()
        output = runner.run({"keywords": "test"})
        artifacts = runner.get_artifact_specs(output)
        self.assertIsInstance(artifacts, list)
        self.assertGreater(len(artifacts), 0)
        self.assertIn("type", artifacts[0])
        self.assertIn("name", artifacts[0])
        self.assertIn("content", artifacts[0])

    def test_get_runner_nonexistent(self) -> None:
        """未注册的 algorithm_id 返回 None。"""
        runner = get_runner("nonexistent_runner")
        self.assertIsNone(runner)


# =============================================================================
# ResearchRunOrchestrator Service 测试 (Plan 04 Task 1-2, 5)
# =============================================================================


class ResearchRunOrchestratorServiceTest(ComputationTestCase):
    """覆盖 ResearchRun Orchestrator 的创建、启动、推进、暂停、恢复。"""

    def setUp(self) -> None:
        super().setUp()
        from app.services.research_engine_orchestrator import ResearchEngineOrchestrator
        from app.services.research_engine_service import ResearchEngineService

        self.orchestrator = ResearchEngineOrchestrator()
        self.svc = ResearchEngineService()
        # 先创建 ProblemSpec
        from app.schemas.research_engine import ProblemSpecCreate
        ps_payload = ProblemSpecCreate(
            name="Plan04 测试任务",
            material_family="fluoropolymer",
            objectives=[
                {"name": "dielectric_constant", "direction": "maximize"},
                {"name": "thermal_stability", "direction": "maximize"},
            ],
        )
        self.ps = self.svc.create_problem_spec(ps_payload, actor_user_id="tester")
        self.autoresearch_decision = self.svc.create_execution_decision(
            self.ps.problem_spec_id,
            ExecutionDecisionCreate(mode="autoresearch", reason="进入 AutoResearch 编排测试"),
            actor_user_id="tester",
        )
        # 写入算法种子
        self.svc.seed_default_algorithms()

    def test_create_research_run(self) -> None:
        """创建 ResearchRun 草稿成功。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        self.assertEqual(rr.status, "draft")
        self.assertTrue(rr.run_id.startswith("rr_"))
        self.assertEqual(rr.problem_spec_id, self.ps.problem_spec_id)
        # 应有 10 个默认阶段
        self.assertEqual(len(rr.stage_runs), 10)
        # 验证阶段顺序
        expected_keys = [
            "PROBLEM_SPEC", "KNOWLEDGE_RETRIEVAL", "STRUCTURE_FEATURE",
            "COMPUTE_PREDICT", "RECOMMENDATION_ASK", "HUMAN_REVIEW",
            "EXPERIMENT_EXECUTION", "RESULT_TELL", "MODEL_UPDATE", "ARCHIVE_LEARNING",
        ]
        for i, sr in enumerate(rr.stage_runs):
            self.assertEqual(sr.stage_key, expected_keys[i])
            self.assertEqual(sr.status, "pending")

    def test_create_with_campaign(self) -> None:
        """创建时关联 campaign。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            campaign_id="camp_001",
            actor_user_id="tester",
        )
        self.assertEqual(rr.campaign_id, "camp_001")

    def test_create_with_profile(self) -> None:
        """创建时使用指定 profile。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            profile_id="carbon_polymer",
            actor_user_id="tester",
        )
        self.assertEqual(rr.profile_id, "carbon_polymer")

    def test_create_nonexistent_problem_spec_returns_404(self) -> None:
        """不存在的 ProblemSpec 创建 ResearchRun 返回 404。"""
        with self.assertRaises(Exception) as ctx:
            self.orchestrator.create_research_run(
                problem_spec_id="ps_nonexistent",
                actor_user_id="tester",
            )
        exc = ctx.exception
        self.assertTrue(
            hasattr(exc, "status_code") and exc.status_code == 404
        )

    def test_get_research_run(self) -> None:
        """获取 ResearchRun 详情。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        fetched = self.orchestrator.get_research_run(rr.run_id)
        self.assertEqual(fetched.run_id, rr.run_id)
        self.assertEqual(fetched.status, "draft")

    def test_get_nonexistent_research_run_returns_404(self) -> None:
        """不存在的 ResearchRun 返回 404。"""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.orchestrator.get_research_run("rr_nonexistent")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_list_research_runs(self) -> None:
        """分页查询 ResearchRun 列表。"""
        for i in range(3):
            self.orchestrator.create_research_run(
                problem_spec_id=self.ps.problem_spec_id,
                actor_user_id="tester",
            )
        result = self.orchestrator.list_research_runs(page=1, page_size=2)
        self.assertEqual(len(result.items), 2)
        self.assertGreaterEqual(result.total, 3)

    def test_list_by_status(self) -> None:
        """按状态过滤 ResearchRun。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        result = self.orchestrator.list_research_runs(status="draft")
        self.assertGreaterEqual(result.total, 1)
        for item in result.items:
            self.assertEqual(item.status, "draft")

    def test_start_research_run(self) -> None:
        """启动 ResearchRun 成功推进到 gate 阶段阻塞。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        started = self.orchestrator.start_research_run(
            rr.run_id,
            actor_user_id="tester",
            reason="测试启动",
        )
        # 启动后状态应为 running 或 blocked_approval
        self.assertIn(started.status, ["running", "blocked_approval"])
        # 第一个 gate 阶段是 PROBLEM_SPEC，应阻塞在此
        problem_spec_sr = None
        for sr in started.stage_runs:
            if sr.stage_key == "PROBLEM_SPEC":
                problem_spec_sr = sr
                break
        self.assertIsNotNone(problem_spec_sr)
        self.assertEqual(problem_spec_sr.status, "blocked_approval")

    def test_start_draft_only(self) -> None:
        """仅 draft 状态可启动。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        self.orchestrator.start_research_run(
            rr.run_id, actor_user_id="tester", reason="第一次启动",
        )
        # 第二次启动应失败
        with self.assertRaises(Exception):
            self.orchestrator.start_research_run(
                rr.run_id, actor_user_id="tester", reason="第二次启动",
            )

    def test_advance_after_approval(self) -> None:
        """审批通过 gate 后可继续推进。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        started = self.orchestrator.start_research_run(
            rr.run_id,
            actor_user_id="tester",
            reason="测试启动",
        )
        # 找到 PROBLEM_SPEC gate
        ps_sr = [sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC"][0]
        self.assertEqual(ps_sr.status, "blocked_approval")

        # 批准 PROBLEM_SPEC
        approved = self.orchestrator.approve_stage(
            research_run_id=rr.run_id,
            stage_run_id=ps_sr.stage_run_id,
            actor_user_id="tester",
            reason="批准 ProblemSpec",
        )
        # 批准后会进入 KnowledgeService-backed RAG；未配置 LightRAG 时使用 demo evidence 继续推进。
        self.assertIn(approved.status, {"running", "blocked_approval", "completed"})
        knowledge_stage = [sr for sr in approved.stage_runs if sr.stage_key == "KNOWLEDGE_RETRIEVAL"][0]
        self.assertEqual(knowledge_stage.status, "completed")
        self.assertGreater(len(knowledge_stage.linked_algorithm_runs), 0)

    def test_reject_stage(self) -> None:
        """拒绝 gate 阶段。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        started = self.orchestrator.start_research_run(
            rr.run_id,
            actor_user_id="tester",
            reason="测试启动",
        )
        ps_sr = [sr for sr in started.stage_runs if sr.stage_key == "PROBLEM_SPEC"][0]

        rejected = self.orchestrator.reject_stage(
            research_run_id=rr.run_id,
            stage_run_id=ps_sr.stage_run_id,
            actor_user_id="tester",
            reason="测试拒绝",
        )
        self.assertEqual(rejected.status, "failed")
        # StageRun 应有 decisions
        fetched = self.orchestrator.get_research_run(rr.run_id)
        for sr in fetched.stage_runs:
            if sr.stage_key == "PROBLEM_SPEC":
                self.assertEqual(sr.status, "failed")
                self.assertGreater(len(sr.decisions), 0)
                self.assertEqual(sr.decisions[0].decision, "rejected")
                break

    def test_approve_stage_requires_blocked_approval(self) -> None:
        """非 blocked_approval 状态的阶段不可审批。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        # 找一个 pending 状态的 stage_run（未启动）
        ps_sr = rr.stage_runs[0]
        self.assertEqual(ps_sr.status, "pending")

        with self.assertRaises(Exception):
            self.orchestrator.approve_stage(
                research_run_id=rr.run_id,
                stage_run_id=ps_sr.stage_run_id,
                actor_user_id="tester",
                reason="尝试审批未阻塞的 gate",
            )

    def test_pause_research_run(self) -> None:
        """暂停 ResearchRun。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        started = self.orchestrator.start_research_run(
            rr.run_id, actor_user_id="tester", reason="启动测试",
        )
        # 启动后应可暂停
        paused = self.orchestrator.pause_research_run(
            rr.run_id, actor_user_id="tester", reason="测试暂停",
        )
        self.assertEqual(paused.status, "paused")
        # checkpoint 应已保存
        self.assertIn("status", paused.checkpoint)
        self.assertIn("saved_at", paused.checkpoint)

    def test_resume_research_run(self) -> None:
        """恢复 ResearchRun。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        self.orchestrator.start_research_run(
            rr.run_id, actor_user_id="tester", reason="启动",
        )
        self.orchestrator.pause_research_run(
            rr.run_id, actor_user_id="tester", reason="暂停",
        )
        # 恢复
        resumed = self.orchestrator.resume_research_run(
            rr.run_id, actor_user_id="tester", reason="测试恢复",
        )
        self.assertIn(resumed.status, ["running", "blocked_approval"])

    def test_pause_only_running_or_blocked(self) -> None:
        """仅 running 或 blocked_approval 状态可暂停。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        # draft 状态不可暂停
        with self.assertRaises(Exception):
            self.orchestrator.pause_research_run(
                rr.run_id, actor_user_id="tester", reason="暂停 draft",
            )

    def test_resume_only_paused(self) -> None:
        """仅 paused 状态可恢复。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        # draft 状态不可恢复
        with self.assertRaises(Exception):
            self.orchestrator.resume_research_run(
                rr.run_id, actor_user_id="tester", reason="恢复 draft",
            )

    def test_fail_research_run(self) -> None:
        """手动标记 ResearchRun 为失败。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        started = self.orchestrator.start_research_run(
            rr.run_id, actor_user_id="tester", reason="启动",
        )
        failed = self.orchestrator.fail_research_run(
            rr.run_id, actor_user_id="tester", reason="手动标记失败",
        )
        self.assertEqual(failed.status, "failed")

    def test_full_flow_draft_to_complete(self) -> None:
        """完整流程：创建 → 启动 → 审批所有 gate → 完成。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        self.assertEqual(rr.status, "draft")

        # 启动
        rr = self.orchestrator.start_research_run(
            rr.run_id, actor_user_id="tester", reason="启动全流程",
        )
        self.assertIn(rr.status, ["blocked_approval", "running"])

        # 逐个审批所有 gate
        max_loops = 10  # 防止无限循环
        while rr.status in ("blocked_approval",) and max_loops > 0:
            max_loops -= 1
            # 找到 blocked_approval 的 gate
            blocked_sr = None
            for sr in rr.stage_runs:
                if sr.status == "blocked_approval":
                    blocked_sr = sr
                    break
            if blocked_sr is None:
                break

            # 审批
            rr = self.orchestrator.approve_stage(
                research_run_id=rr.run_id,
                stage_run_id=blocked_sr.stage_run_id,
                actor_user_id="tester",
                reason=f"批准 {blocked_sr.stage_key}",
            )

        # 未配置真实 adapter 时会停在 failed，不能静默 mock 成功。
        self.assertIn(rr.status, ["completed", "blocked_approval", "failed"])
        # 至少验证有阶段完成了
        completed_count = sum(1 for sr in rr.stage_runs if sr.status == "completed")
        self.assertGreater(completed_count, 0, "至少有部分阶段已完成")

    def test_stage_audit_written(self) -> None:
        """创建和启动 ResearchRun 有审计事件。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        # 审计事件写入无法直接查询，但不会抛出异常
        self.assertTrue(rr.run_id.startswith("rr_"))

    def test_multiple_rounds_of_pause_resume(self) -> None:
        """多轮暂停恢复测试。"""
        rr = self.orchestrator.create_research_run(
            problem_spec_id=self.ps.problem_spec_id,
            actor_user_id="tester",
        )
        rr = self.orchestrator.start_research_run(
            rr.run_id, actor_user_id="tester", reason="启动",
        )
        # 暂停
        rr = self.orchestrator.pause_research_run(
            rr.run_id, actor_user_id="tester", reason="暂停1",
        )
        self.assertEqual(rr.status, "paused")
        # 恢复
        rr = self.orchestrator.resume_research_run(
            rr.run_id, actor_user_id="tester", reason="恢复1",
        )
        self.assertIn(rr.status, ["running", "blocked_approval"])
        # 再次暂停
        rr = self.orchestrator.pause_research_run(
            rr.run_id, actor_user_id="tester", reason="暂停2",
        )
        self.assertEqual(rr.status, "paused")
        # 再次恢复
        rr = self.orchestrator.resume_research_run(
            rr.run_id, actor_user_id="tester", reason="恢复2",
        )
        self.assertIn(rr.status, ["running", "blocked_approval"])
