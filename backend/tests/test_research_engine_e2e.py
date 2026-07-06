"""ResearchEngine P0 端到端测试。

覆盖从 ProblemSpec 到 ResearchRun Gate 审批的完整闭环路径，
验证人工通道和 AutoResearch 通道产出均可追溯。

Plan 06 Task 2: P0 E2E 后端测试
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


def problem_spec_payload(**overrides) -> dict:
    """构建最小 ProblemSpec 创建请求。"""
    payload = {
        "name": "氟基高分子 E2E 测试任务",
        "material_family": "fluoropolymer",
        "problem_type": "formulation_process_optimization",
        "execution_mode": "hybrid",
        "objectives": [
            {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
            {"name": "thermal_stability", "direction": "maximize", "unit": "celsius"},
        ],
        "variables": [
            {
                "name": "fluorine_content",
                "type": "continuous",
                "role": "formulation",
                "unit": "percent",
                "bounds": [0, 100],
            },
            {
                "name": "polymerization_temperature",
                "type": "continuous",
                "role": "process",
                "unit": "celsius",
                "bounds": [20, 180],
            },
        ],
        "constraints": [
            {"name": "synthesizable", "type": "hard"},
            {"name": "temp_limit", "type": "hard", "expression": "temperature <= 180"},
        ],
        "description": "E2E 测试：氟基高分子电解质优化",
    }
    payload.update(overrides)
    return payload


class ResearchEngineE2ETest(ComputationTestCase):
    """P0 端到端测试：覆盖完整双通道闭环路径。

    验证场景：
    1. 创建 ProblemSpec（人工定义任务）
    2. 人工运行 mock predictor 生成 AlgorithmRun
    3. 基于同一 ProblemSpec 创建 AutoResearch ResearchRun
    4. 启动 ResearchRun，推进到 gate
    5. 审批 gate 并继续推进
    6. 查看完整追溯链
    7. 暂停-恢复路径
    """

    @classmethod
    def setUpClass(cls) -> None:
        pass

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        self.svc = ResearchEngineService()

        # 填��算法种子数据
        self.svc.seed_default_algorithms()

        # 场景 1：创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        self.assertEqual(resp.status_code, 200)
        self.ps_id = resp.json()["data"]["problem_spec_id"]
        self.assertEqual(resp.json()["data"]["status"], "draft")
        self.assertEqual(resp.json()["data"]["schema_version"], "0.2")

    # =========================================================================
    # 场景 2：人工通道 - mock predictor
    # =========================================================================

    def test_e2e_scenario_02_manual_mock_predictor(self) -> None:
        """E2E 场景 2：人工运行 mock predictor 生成 AlgorithmRun。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {"keywords": "fluoropolymer dielectric"},
                "reason": "E2E 测试：人工文献检索",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["trigger_source"], "human")
        self.assertEqual(data["status"], "completed")
        self.assertIn("knowledge_cards", data["output_summary"])
        self.assertGreater(len(data["artifact_refs"]), 0)

        # 验证追溯链
        trace_resp = self.client.get(
            f"{self.base_url}/algorithm-runs/{data['run_id']}/traceability",
        )
        self.assertEqual(trace_resp.status_code, 200)
        trace_data = trace_resp.json()["data"]
        self.assertEqual(trace_data["algorithm_run"]["run_id"], data["run_id"])
        self.assertGreater(len(trace_data["audit_events"]), 0)
        # 人工运行无关联 computation
        self.assertIsNone(trace_data["linked_computation"])

    def test_e2e_scenario_02b_manual_mock_predictor_multiple(self) -> None:
        """E2E 场景 2b：多次人工运行不同 mock 算法。"""
        algorithms = [
            ("literature_mock", {"keywords": "fluoropolymer"}),
            ("polymer_descriptor_mock", {"smiles": "C=CF", "polymer_type": "homopolymer"}),
        ]

        run_ids = []
        for algo_id, inputs in algorithms:
            resp = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": algo_id,
                    "trigger_source": "human",
                    "problem_spec_id": self.ps_id,
                    "input_snapshot": inputs,
                    "reason": f"E2E 测试：人工运行 {algo_id}",
                },
            )
            self.assertEqual(resp.status_code, 200)
            run_ids.append(resp.json()["data"]["run_id"])

        # 验证所有运行都已完成
        for run_id in run_ids:
            detail = self.client.get(f"{self.base_url}/algorithm-runs/{run_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["data"]["status"], "completed")

    # =========================================================================
    # 场景 3：AutoResearch 通道 - 创建并启动 ResearchRun
    # =========================================================================

    def test_e2e_scenario_03_create_and_start_research_run(self) -> None:
        """E2E 场景 3：创建并启动 ResearchRun。"""
        # 创建
        resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
                "batch_size": 5,
            },
        )
        self.assertEqual(resp.status_code, 200)
        run_id = resp.json()["data"]["run_id"]
        self.assertEqual(resp.json()["data"]["status"], "draft")
        self.assertGreater(len(resp.json()["data"]["stage_runs"]), 0)

        # 验证初始阶段序列包含 P0 所有阶段
        stage_keys = [sr["stage_key"] for sr in resp.json()["data"]["stage_runs"]]
        expected_stages = [
            "PROBLEM_SPEC",
            "KNOWLEDGE_RETRIEVAL",
            "STRUCTURE_FEATURE",
            "COMPUTE_PREDICT",
            "RECOMMENDATION_ASK",
            "HUMAN_REVIEW",
            "EXPERIMENT_EXECUTION",
            "RESULT_TELL",
            "MODEL_UPDATE",
            "ARCHIVE_LEARNING",
        ]
        for stage in expected_stages:
            self.assertIn(stage, stage_keys)

        # 启动
        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "E2E 测试启动"},
        )
        self.assertEqual(start_resp.status_code, 200)
        start_data = start_resp.json()["data"]
        self.assertIn(start_data["status"], ["running", "blocked_approval"])

        if start_data["status"] == "blocked_approval":
            # 验证首个 gate 阶段正确标识
            blocked = [sr for sr in start_data["stage_runs"] if sr["status"] == "blocked_approval"]
            self.assertEqual(len(blocked), 1)

    # =========================================================================
    # 场景 4：完整推进到 gate 并审批
    # =========================================================================

    def test_e2e_scenario_04_advance_to_gate_and_approve(self) -> None:
        """E2E 场景 4：推进到 gate、审批并继续推进。"""
        # 创建并启动
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "E2E 测试启动"},
        )
        self.assertEqual(start_resp.status_code, 200)
        run_status = start_resp.json()["data"]["status"]

        # 如果是 blocked_approval，执行审批
        if run_status == "blocked_approval":
            stage_runs = start_resp.json()["data"]["stage_runs"]
            blocked_sr = next(
                (sr for sr in stage_runs if sr["status"] == "blocked_approval"),
                None,
            )
            self.assertIsNotNone(blocked_sr, "应有阻塞的 gate 阶段")

            # 审批
            approve_resp = self.client.post(
                f"{self.base_url}/research-runs/{run_id}/stages/{blocked_sr['stage_run_id']}/approve",
                json={
                    "stage_key": blocked_sr["stage_key"],
                    "decision": "approved",
                    "reason": "E2E 测试审批通过",
                },
            )
            self.assertEqual(approve_resp.status_code, 200)
            updated_status = approve_resp.json()["data"]["status"]
            self.assertIn(updated_status, ["running", "blocked_approval", "completed"])

            # 如果是 completed，验证所有阶段都完成了
            if updated_status == "completed":
                completed_stages = [
                    sr for sr in approve_resp.json()["data"]["stage_runs"]
                    if sr["status"] == "completed"
                ]
                total_stages = len(approve_resp.json()["data"]["stage_runs"])
                self.assertEqual(len(completed_stages), total_stages)

        # 验证详情可查看
        detail_resp = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        self.assertEqual(detail_resp.status_code, 200)

    def test_e2e_scenario_04b_reject_gate(self) -> None:
        """E2E 场景 4b：拒绝 gate 导致 ResearchRun 失败。"""
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "E2E 测试启动"},
        )
        self.assertEqual(start_resp.status_code, 200)

        if start_resp.json()["data"]["status"] != "blocked_approval":
            # 如果没有 gate 阻塞（可能全部自动完成），跳过拒绝测试
            return

        stage_runs = start_resp.json()["data"]["stage_runs"]
        blocked_sr = next(
            (sr for sr in stage_runs if sr["status"] == "blocked_approval"),
            None,
        )
        self.assertIsNotNone(blocked_sr)

        # 拒绝
        reject_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/stages/{blocked_sr['stage_run_id']}/reject",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "rejected",
                "reason": "E2E 测试拒绝：测试候选不满足约束",
            },
        )
        self.assertEqual(reject_resp.status_code, 200)
        self.assertEqual(reject_resp.json()["data"]["status"], "failed")

        # 验证 gate 审批决策已记录
        detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        rejected_sr = next(
            (sr for sr in detail.json()["data"]["stage_runs"]
             if sr["stage_run_id"] == blocked_sr["stage_run_id"]),
            None,
        )
        self.assertIsNotNone(rejected_sr)
        self.assertEqual(rejected_sr["status"], "failed")
        self.assertGreater(len(rejected_sr["decisions"]), 0)
        self.assertEqual(rejected_sr["decisions"][0]["decision"], "rejected")

    # =========================================================================
    # 场景 5-6：computation 委托和 observation 关联
    # =========================================================================

    def test_e2e_scenario_05_submit_computation_from_algorithm(self) -> None:
        """E2E 场景 5：通过 AlgorithmRun 提交 computation 并关联。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "computation_submit_adapter",
                "trigger_source": "human",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {
                    "workflow_type": "LOCAL_STRUCTURE",
                    "smiles": "CCO",
                    "name": "E2E_test_structure",
                },
                "reason": "E2E 测试：通过 adapter 提交计算任务",
            },
        )
        self.assertEqual(resp.status_code, 200)
        run_data = resp.json()["data"]
        self.assertEqual(run_data["status"], "completed")

        # 验证 linked_computation_run_id 存在
        self.assertIsNotNone(run_data["linked_computation_run_id"])

        # 验证追溯链包含关联的 computation
        trace_resp = self.client.get(
            f"{self.base_url}/algorithm-runs/{run_data['run_id']}/traceability",
        )
        self.assertEqual(trace_resp.status_code, 200)
        trace_data = trace_resp.json()["data"]

        if trace_data["linked_computation"] is not None:
            self.assertEqual(
                trace_data["linked_computation"]["run_id"],
                run_data["linked_computation_run_id"],
            )
            # 验证计算任务不暴露敏感路径
            comp_str = str(trace_data["linked_computation"])
            self.assertNotIn("/home/", comp_str)

    # =========================================================================
    # 场景 7：追溯链验证
    # =========================================================================

    def test_e2e_scenario_07_full_traceability(self) -> None:
        """E2E 场景 7：完整追溯链包含 stage timeline、artifact、audit。"""
        # 先创建人工运行
        arun_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "property_predictor_mock",
                "trigger_source": "human",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {
                    "smiles": "C=C(F)F",
                    "target_properties": ["dielectric_constant", "thermal_stability"],
                    "fluorine_content": 45.0,
                    "polymerization_temperature": 120.0,
                },
                "reason": "E2E 人工预测",
            },
        )
        arun_id = arun_resp.json()["data"]["run_id"]

        # 创建并启动 ResearchRun
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "profile_id": "fluoropolymer",
            },
        )
        rr_id = rr_resp.json()["data"]["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{rr_id}/start",
            json={"target_status": "running", "reason": "追溯链测试"},
        )

        # 获取 ResearchRun 追溯链
        trace_resp = self.client.get(
            f"{self.base_url}/research-runs/{rr_id}/traceability",
        )
        self.assertEqual(trace_resp.status_code, 200)
        trace = trace_resp.json()["data"]

        # 验证 research_run 字段
        self.assertIsNotNone(trace["research_run"])
        self.assertEqual(trace["research_run"]["run_id"], rr_id)

        # 验证 stage_runs 在 research_run 中
        stage_runs = trace["research_run"]["stage_runs"]
        self.assertGreater(len(stage_runs), 0)

        # 验证非 gate 阶段有 output_summary
        non_gate_completed = [
            sr for sr in stage_runs
            if sr["status"] == "completed"
            and sr["stage_key"] not in ("PROBLEM_SPEC", "HUMAN_REVIEW", "EXPERIMENT_EXECUTION")
        ]
        for sr in non_gate_completed:
            self.assertIsNotNone(sr.get("output_summary"))

        # 验证审计事件存在
        self.assertGreater(len(trace["audit_events"]), 0)

        # 验证审计事件按时间倒序排列
        timestamps = [e["created_at"] for e in trace["audit_events"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    # =========================================================================
    # 场景 8-9：暂停-恢复路径
    # =========================================================================

    def test_e2e_scenario_08_pause_and_resume(self) -> None:
        """E2E 场景 8：暂停和恢复 ResearchRun。"""
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "profile_id": "fluoropolymer",
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "暂停恢复测试"},
        )

        # 暂停（running 或 blocked_approval 状态可暂停）
        pause_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "E2E 测试暂停"},
        )
        self.assertEqual(pause_resp.status_code, 200)
        self.assertEqual(pause_resp.json()["data"]["status"], "paused")

        # 恢复
        resume_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/resume",
            json={"target_status": "running", "reason": "E2E 测试恢复"},
        )
        self.assertEqual(resume_resp.status_code, 200)
        self.assertIn(
            resume_resp.json()["data"]["status"],
            ["running", "blocked_approval", "completed"],
        )

        # 验证 checkpoint 已保存
        detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        self.assertIsNotNone(detail.json()["data"].get("checkpoint"))

    def test_e2e_scenario_09_fail_manual_mark(self) -> None:
        """E2E 场景 9：手动标记 ResearchRun 为失败。"""
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "profile_id": "fluoropolymer",
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "失败标记测试"},
        )

        # 标记失败
        fail_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/fail",
            json={"target_status": "failed", "reason": "E2E 测试手动标记失败：模拟外部异常"},
        )
        self.assertEqual(fail_resp.status_code, 200)
        self.assertEqual(fail_resp.json()["data"]["status"], "failed")

        # 验证已终态不可再次标记
        double_fail = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/fail",
            json={"target_status": "failed", "reason": "重复失败不合法"},
        )
        self.assertEqual(double_fail.status_code, 409)

    # =========================================================================
    # 场景 10：ProblemSpec 全生命周期
    # =========================================================================

    def test_e2e_scenario_10_problem_spec_lifecycle(self) -> None:
        """E2E 场景 10：ProblemSpec 完整生命周期（draft -> updated -> frozen）。"""
        # 更新
        update_resp = self.client.patch(
            f"{self.base_url}/problem-specs/{self.ps_id}",
            json=problem_spec_payload(
                name="氟基高分子 E2E 测试任务（已更新）",
                description="更新后的描述",
            ),
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(
            update_resp.json()["data"]["name"],
            "氟基高分子 E2E 测试任务（已更新）",
        )

        # 冻结
        freeze_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/freeze",
        )
        self.assertEqual(freeze_resp.status_code, 200)
        self.assertEqual(freeze_resp.json()["data"]["status"], "frozen")

        # 已冻结不可修改
        update_after_freeze = self.client.patch(
            f"{self.base_url}/problem-specs/{self.ps_id}",
            json=problem_spec_payload(),
        )
        self.assertEqual(update_after_freeze.status_code, 409)

        # 审计事件应记录完整生命周期
        audit_resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "problem_spec", "entity_id": self.ps_id},
        )
        self.assertEqual(audit_resp.status_code, 200)
        event_types = [e["event_type"] for e in audit_resp.json()["data"]["items"]]
        self.assertIn("created", event_types)
        self.assertIn("frozen", event_types)

    # =========================================================================
    # 场景 11：任务中心映射 - ResearchRun/AlgorithmRun 查询
    # =========================================================================

    def test_e2e_scenario_11_task_center_mapping(self) -> None:
        """E2E 场景 11：任务中心可按 ProblemSpec 查询关联的所有运行。"""
        # 创建多个人工运行
        for i in range(3):
            resp = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": "literature_mock",
                    "trigger_source": "human",
                    "problem_spec_id": self.ps_id,
                    "input_snapshot": {"keywords": f"test_query_{i}"},
                    "reason": f"E2E query test {i}",
                },
            )
            self.assertEqual(resp.status_code, 200)

        # 按 problem_spec_id 查询 AlgorithmRun
        list_resp = self.client.get(
            f"{self.base_url}/algorithm-runs",
            params={"problem_spec_id": self.ps_id},
        )
        self.assertEqual(list_resp.status_code, 200)
        list_data = list_resp.json()["data"]
        self.assertGreaterEqual(list_data["total"], 3)
        for item in list_data["items"]:
            self.assertEqual(item["problem_spec_id"], self.ps_id)

        # 按 problem_spec_id 查询 ResearchRun
        rr_list = self.client.get(
            f"{self.base_url}/research-runs",
            params={"problem_spec_id": self.ps_id},
        )
        self.assertEqual(rr_list.status_code, 200)

        # 按状态筛选
        by_status = self.client.get(
            f"{self.base_url}/algorithm-runs",
            params={"problem_spec_id": self.ps_id, "status": "completed"},
        )
        self.assertEqual(by_status.status_code, 200)
        for item in by_status.json()["data"]["items"]:
            self.assertEqual(item["status"], "completed")
