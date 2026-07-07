"""
人工 Workflow 测试示例。

本测试演示如何在 Poly Agent 中通过人工 Workflow 运行算法：
1. 创建 ProblemSpec
2. 选择 execution mode
3. 创建包含多个算法的 Workflow（串联执行）
4. 启动并验证结果

用户可直接复制本文件中的方法，替换算法 ID 和输入参数来运行自己的 Workflow。

运行方式:
    pytest backend/tests/test_manual_workflow_example.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.services.research_engine_service import ResearchEngineService


class ManualWorkflowExampleTest(ComputationTestCase):
    """人工 Workflow 示例测试 - 可复用的模板。

    演示两种使用模式：
    1. 单算法快速运行（快速验证）
    2. 多步骤串联流水线（结构生成 → xTB 计算）
    """

    def setUp(self):
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        svc = ResearchEngineService()
        svc.seed_default_algorithms()

    # =========================================================================
    # 示例 1：单算法快速运行
    # =========================================================================

    def test_single_algorithm_run(self):
        """示例：选择单个算法（文献检索）运行。

        流程：
        1. 创建 ProblemSpec
        2. 选择 manual_workbench 执行模式
        3. 创建单步骤 Workflow（文献检索）
        4. 启动 WorkflowRun 并验证
        """
        # 步骤 1：创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "人工 Workflow 单算法示例",
                "material_family": "fluoropolymer",
                "problem_type": "formulation_process_optimization",
                "allowed_execution_modes": ["manual_workbench"],
                "decision_status": "pending_execution_decision",
                "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                "description": "演示单算法快速运行",
            },
        )
        self.assertEqual(resp.status_code, 200)
        ps_id = resp.json()["data"]["problem_spec_id"]
        print(f"✓ ProblemSpec 创建成功: {ps_id}")

        # 步骤 2：选择人工工作台执行模式
        resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "人工 Workflow 单算法示例"},
        )
        self.assertEqual(resp.status_code, 200)
        decision_id = resp.json()["data"]["decision_id"]
        print(f"✓ ExecutionDecision 创建成功: {decision_id}")

        # 步骤 3：创建单步骤 Workflow（文献检索 mock）
        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "name": "文献检索 - 氟基高分子",
                "description": "检索氟基高分子相关文献",
                "steps": [
                    {
                        "step_id": "step_1",
                        "algorithm_id": "literature_mock",
                        "input_bindings": {
                            "keywords": {"source": "literal", "value": "氟基高分子"},
                            "material_family": {"source": "literal", "value": "fluoropolymer"},
                        },
                        "depends_on": [],
                    },
                ],
            },
        )
        self.assertEqual(workflow_resp.status_code, 200)
        workflow_id = workflow_resp.json()["data"]["workflow_id"]
        print(f"✓ ManualWorkflow 创建成功: {workflow_id}")

        # 步骤 4：启动 WorkflowRun
        run_resp = self.client.post(
            f"{self.base_url}/manual-workflows/{workflow_id}/runs"
        )
        self.assertEqual(run_resp.status_code, 200)
        run_data = run_resp.json()["data"]

        # 验证结果
        self.assertEqual(run_data["status"], "completed")
        self.assertEqual(len(run_data["step_runs"]), 1)
        self.assertEqual(run_data["step_runs"][0]["status"], "completed")
        print(f"✓ WorkflowRun 完成: {run_data['workflow_run_id']}")
        print(f"  AlgorithmRun ID: {run_data['step_runs'][0]['algorithm_run_id']}")

    # =========================================================================
    # 示例 2：多步骤串联流水线
    # =========================================================================

    def test_serial_pipeline_example(self):
        """示例：串联运行结构生成 + 性质预测。

        流程：
        1. 创建 ProblemSpec
        2. 选择 manual_workbench 执行模式
        3. 创建两步 Workflow: 聚合物描述符 → 性质预测
        4. 启动 WorkflowRun
        5. 验证两个步骤都完成
        """
        # 步骤 1：创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "人工 Workflow 串联示例",
                "material_family": "fluoropolymer",
                "problem_type": "formulation_process_optimization",
                "allowed_execution_modes": ["manual_workbench"],
                "decision_status": "pending_execution_decision",
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                    {"name": "thermal_stability", "direction": "maximize"},
                ],
                "description": "演示如何通过人工 Workflow 串联运行多个算法",
            },
        )
        self.assertEqual(resp.status_code, 200)
        ps_id = resp.json()["data"]["problem_spec_id"]
        print(f"✓ ProblemSpec 创建成功: {ps_id}")

        # 步骤 2：选择人工工作台执行模式
        resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "人工 Workflow 串联示例"},
        )
        decision_id = resp.json()["data"]["decision_id"]
        print(f"✓ ExecutionDecision 创建成功: {decision_id}")

        # 步骤 3：创建两步串联 Workflow
        # step_1: 聚合物描述符生成（输入 SMILES）
        # step_2: 性质预测（依赖 step_1 完成，输入描述符和 SMILES）
        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "name": "描述符生成 → 性质预测 示例",
                "description": "演示串联执行：先生成描述符，再预测性质",
                "steps": [
                    {
                        "step_id": "step_1",
                        "algorithm_id": "polymer_descriptor_mock",
                        "input_bindings": {
                            "smiles": {"source": "literal", "value": "C=C(F)F"},
                        },
                        "depends_on": [],
                    },
                    {
                        "step_id": "step_2",
                        "algorithm_id": "property_predictor_mock",
                        "input_bindings": {
                            "smiles": {"source": "literal", "value": "C=C(F)F"},
                            "target_properties": {
                                "source": "literal",
                                "value": ["dielectric_constant", "thermal_stability"],
                            },
                            "fluorine_content": {"source": "literal", "value": 45.0},
                        },
                        "depends_on": ["step_1"],
                    },
                ],
            },
        )
        self.assertEqual(workflow_resp.status_code, 200)
        workflow_id = workflow_resp.json()["data"]["workflow_id"]
        print(f"✓ ManualWorkflow 创建成功: {workflow_id}")

        # 步骤 4：启动 WorkflowRun 并验证结果
        run_resp = self.client.post(
            f"{self.base_url}/manual-workflows/{workflow_id}/runs"
        )
        self.assertEqual(run_resp.status_code, 200)
        run_data = run_resp.json()["data"]

        # 验证两个步骤都已完成
        self.assertEqual(run_data["status"], "completed")
        self.assertEqual(len(run_data["step_runs"]), 2)
        self.assertEqual(run_data["step_runs"][0]["status"], "completed")
        self.assertEqual(run_data["step_runs"][1]["status"], "completed")
        print(f"✓ WorkflowRun 完成: {run_data['workflow_run_id']}")
        print(f"  Step 1 AlgorithmRun ID: {run_data['step_runs'][0]['algorithm_run_id']}")
        print(f"  Step 2 AlgorithmRun ID: {run_data['step_runs'][1]['algorithm_run_id']}")

        # 步骤 5：获取每个步骤的 AlgorithmRun 详情验证输出
        for i, step_run in enumerate(run_data["step_runs"]):
            arun_resp = self.client.get(
                f"{self.base_url}/algorithm-runs/{step_run['algorithm_run_id']}"
            )
            self.assertEqual(arun_resp.status_code, 200)
            arun_data = arun_resp.json()["data"]
            self.assertEqual(arun_data["status"], "completed")
            self.assertIsNotNone(arun_data["output_summary"])
            print(f"  Step {i + 1} ({step_run['algorithm_run_id']}): output keys = {list(arun_data['output_summary'].keys())}")

    # =========================================================================
    # 示例 3：计算任务提交（使用下拉选项值）
    # =========================================================================

    def test_computation_submit_workflow(self):
        """示例：使用 computation_submit_adapter 提交计算任务。

        演示使用 field_options 中的有效值（workflow_type 从下拉列表选择）。
        """
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "计算任务提交示例",
                "material_family": "universal",
                "problem_type": "formulation_process_optimization",
                "allowed_execution_modes": ["manual_workbench"],
                "decision_status": "pending_execution_decision",
                "objectives": [{"name": "energy", "direction": "minimize"}],
            },
        )
        self.assertEqual(resp.status_code, 200)
        ps_id = resp.json()["data"]["problem_spec_id"]

        resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "计算任务提交示例"},
        )
        decision_id = resp.json()["data"]["decision_id"]

        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "name": "xTB 计算 - 乙醇",
                "description": "使用有效的 workflow_type 值提交计算任务",
                "steps": [
                    {
                        "step_id": "step_1",
                        "algorithm_id": "computation_submit_adapter",
                        "input_bindings": {
                            "workflow_type": {"source": "literal", "value": "LOCAL_XTB"},
                            "smiles": {"source": "literal", "value": "CCO"},
                        },
                        "depends_on": [],
                    },
                ],
            },
        )
        self.assertEqual(workflow_resp.status_code, 200)
        workflow_id = workflow_resp.json()["data"]["workflow_id"]

        run_resp = self.client.post(
            f"{self.base_url}/manual-workflows/{workflow_id}/runs"
        )
        self.assertEqual(run_resp.status_code, 200)
        run_data = run_resp.json()["data"]
        self.assertEqual(run_data["status"], "completed")
        print(f"✓ 计算任务提交成功: {run_data['workflow_run_id']}")
