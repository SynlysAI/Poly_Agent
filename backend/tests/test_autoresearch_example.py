"""
Auto Research 测试示例。

本测试演示完整的 Auto Research 十阶段编排流程，重点是 Gate 审批操作。

运行方式:
    pytest backend/tests/test_autoresearch_example.py -v
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


class AutoResearchExampleTest(ComputationTestCase):
    """Auto Research 示例测试 - 演示完整审批流程。

    演示内容：
    1. 创建 ProblemSpec
    2. 创建 autoresearch ResearchRun
    3. 启动 ResearchRun
    4. 推进到 Gate 阶段
    5. 审批通过 Gate 阶段
    6. 继续推进后续阶段
    """

    def setUp(self):
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        svc = ResearchEngineService()
        svc.seed_default_algorithms()

    # =========================================================================
    # 示例 1：AutoResearch 完整审批流程
    # =========================================================================

    def test_autoresearch_with_gate_approval(self):
        """Auto Research 审批流程示例。

        流程：
        1. 创建 ProblemSpec
        2. 创建 autoresearch ResearchRun
        3. 启动 ResearchRun
        4. 推进到 Gate 阶段（PROBLEM_SPEC）
        5. 审批通过 Gate 阶段
        6. 继续推进完成
        """
        # 步骤 1：创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "AutoResearch 审批示例",
                "material_family": "fluoropolymer",
                "problem_type": "formulation_process_optimization",
                "allowed_execution_modes": ["autoresearch"],
                "decision_status": "pending_execution_decision",
                "variables": [
                    {
                        "name": "monomer_smiles",
                        "type": "categorical",
                        "role": "structure",
                        "categories": ["C=CF", "C=C(F)F", "FC(F)=C(F)F"],
                        "description": "氟基单体 SMILES",
                    },
                    {
                        "name": "fluorine_content",
                        "type": "continuous",
                        "role": "formulation",
                        "unit": "percent",
                        "bounds": [0.0, 100.0],
                    },
                ],
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                    {"name": "thermal_stability", "direction": "maximize"},
                ],
                "description": "演示 AutoResearch 自动编排和 Gate 审批流程",
            },
        )
        self.assertEqual(resp.status_code, 200)
        ps_id = resp.json()["data"]["problem_spec_id"]
        print(f"\n✓ ProblemSpec 创建成功: {ps_id}")

        # 步骤 2：创建 autoresearch 执行决策 和 ResearchRun
        dec_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "AutoResearch 示例测试"},
        )
        self.assertEqual(dec_resp.status_code, 200)
        decision_id = dec_resp.json()["data"]["decision_id"]
        print(f"✓ ExecutionDecision 创建成功: {decision_id}")

        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 1,
                "batch_size": 5,
                "description": "AutoResearch 审批流程示例运行",
            },
        )
        self.assertEqual(rr_resp.status_code, 200)
        rr_data = rr_resp.json()["data"]
        run_id = rr_data["run_id"]
        self.assertEqual(rr_data["status"], "draft")
        self.assertEqual(len(rr_data["stage_runs"]), 10)
        print(f"✓ ResearchRun 创建成功: {run_id}")
        print(f"  共 {len(rr_data['stage_runs'])} 个阶段")

        # 步骤 3：启动 ResearchRun
        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动 AutoResearch 示例"},
        )
        self.assertEqual(start_resp.status_code, 200)
        run_after_start = start_resp.json()["data"]
        self.assertIn(run_after_start["status"], ["running", "blocked_approval"])
        print(f"✓ ResearchRun 已启动, 当前状态: {run_after_start['status']}")

        # 步骤 4：找到 Gate 阶段（PROBLEM_SPEC 需要审批）
        gate_stages = [
            s for s in run_after_start["stage_runs"]
            if s["status"] == "blocked_approval"
        ]
        print(f"  需要审批的阶段数: {len(gate_stages)}")
        for gs in gate_stages:
            print(f"    - {gs['stage_key']}: {gs['status']}")

        # 如果当前阶段在 Gate 且状态为 blocked_approval
        if gate_stages:
            gate = gate_stages[0]

            # 步骤 5：审批通过
            print(f"\n  正在审批阶段: {gate['stage_key']} (stage_run_id: {gate['stage_run_id']})")
            approve_resp = self.client.post(
                f"{self.base_url}/research-runs/{run_id}/stages/{gate['stage_run_id']}/approve",
                json={
                    "stage_key": gate["stage_key"],
                    "decision": "approved",
                    "reason": "问题定义校验通过，材料体系、目标、约束均已明确定义，批准继续推进",
                },
            )
            self.assertEqual(approve_resp.status_code, 200)
            approved_data = approve_resp.json()["data"]
            print(f"  ✓ 审批通过, ResearchRun 状态: {approved_data['status']}")

            # 验证审批决策已记录
            updated_sr = next(
                (s for s in approved_data["stage_runs"]
                 if s["stage_run_id"] == gate["stage_run_id"]),
                None,
            )
            if updated_sr:
                print(f"  ✓ 阶段状态: {updated_sr['status']}")
                self.assertGreater(len(updated_sr.get("decisions", [])), 0,
                                   "审批决策应已记录")
                for d in updated_sr["decisions"]:
                    print(f"    决策: {d['decision']}, 原因: {d['reason']}")

            # 步骤 6：继续推进后续阶段
            print(f"\n  正在推进后续阶段...")
            advance_resp = self.client.post(
                f"{self.base_url}/research-runs/{run_id}/advance",
                json={"target_status": "running", "reason": "审批通过后继续推进后续阶段"},
            )
            self.assertEqual(advance_resp.status_code, 200)
            final_run = advance_resp.json()["data"]

            completed = [
                s for s in final_run["stage_runs"]
                if s["status"] == "completed"
            ]
            failed = [
                s for s in final_run["stage_runs"]
                if s["status"] == "failed"
            ]
            blocked = [
                s for s in final_run["stage_runs"]
                if s["status"] == "blocked_approval"
            ]
            print(f"  已完成阶段数: {len(completed)}")
            print(f"  失败阶段数: {len(failed)}")
            print(f"  等待审批阶段数: {len(blocked)}")

            # 打印阶段状态汇总
            print(f"\n  阶段状态汇总:")
            for sr in final_run["stage_runs"]:
                print(f"    {sr['stage_key']:30s} → {sr['status']}")

    # =========================================================================
    # 示例 2：Gate 拒绝流程
    # =========================================================================

    def test_autoresearch_gate_rejection(self):
        """Auto Research 审批拒绝示例。

        演示如何拒绝一个 Gate 阶段，验证 ResearchRun 变为 failed。
        """
        # 创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "AutoResearch 拒绝审批示例",
                "material_family": "fluoropolymer",
                "problem_type": "formulation_process_optimization",
                "allowed_execution_modes": ["autoresearch"],
                "decision_status": "pending_execution_decision",
                "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                "description": "演示审批拒绝流程",
            },
        )
        self.assertEqual(resp.status_code, 200)
        ps_id = resp.json()["data"]["problem_spec_id"]

        # 创建 ResearchRun
        dec_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "审批拒绝示例"},
        )
        decision_id = dec_resp.json()["data"]["decision_id"]

        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 1,
                "batch_size": 5,
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        # 启动 → 推进到 Gate
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )
        detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        run_data = detail.json()["data"]

        gate_stages = [
            s for s in run_data["stage_runs"]
            if s["status"] == "blocked_approval"
        ]
        if gate_stages:
            gate = gate_stages[0]

            # 拒绝审批
            reject_resp = self.client.post(
                f"{self.base_url}/research-runs/{run_id}/stages/{gate['stage_run_id']}/reject",
                json={
                    "stage_key": gate["stage_key"],
                    "decision": "rejected",
                    "reason": "问题定义不完整：缺少约束条件和测量方法定义",
                },
            )
            self.assertEqual(reject_resp.status_code, 200)
            rejected_data = reject_resp.json()["data"]
            self.assertEqual(rejected_data["status"], "failed")
            print(f"\n✓ ResearchRun 已标记为失败 (拒绝审批)")
            print(f"  拒绝阶段: {gate['stage_key']}")
            print(f"  拒绝原因: 问题定义不完整")

            # 验证被拒绝的阶段状态
            updated_sr = next(
                (s for s in rejected_data["stage_runs"]
                 if s["stage_run_id"] == gate["stage_run_id"]),
                None,
            )
            if updated_sr:
                self.assertEqual(updated_sr["status"], "failed")
                print(f"  ✓ 阶段状态: failed")

    # =========================================================================
    # 示例 3：暂停和恢复
    # =========================================================================

    def test_autoresearch_pause_and_resume(self):
        """Auto Research 暂停和恢复示例。

        演示如何暂停 ResearchRun 并恢复。
        """
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "AutoResearch 暂停恢复示例",
                "material_family": "fluoropolymer",
                "problem_type": "formulation_process_optimization",
                "allowed_execution_modes": ["autoresearch"],
                "decision_status": "pending_execution_decision",
                "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
            },
        )
        ps_id = resp.json()["data"]["problem_spec_id"]

        dec_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "暂停恢复示例"},
        )
        decision_id = dec_resp.json()["data"]["decision_id"]

        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 1,
                "batch_size": 5,
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        # 启动
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )

        # 暂停
        pause_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "暂停检查中间结果"},
        )
        self.assertEqual(pause_resp.status_code, 200)
        self.assertEqual(pause_resp.json()["data"]["status"], "paused")
        print(f"\n✓ ResearchRun 已暂停")

        # 恢复
        resume_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/resume",
            json={"target_status": "running", "reason": "检查完成，继续推进"},
        )
        self.assertEqual(resume_resp.status_code, 200)
        self.assertIn(
            resume_resp.json()["data"]["status"],
            ["running", "blocked_approval", "completed"],
        )
        print(f"✓ ResearchRun 已恢复, 当前状态: {resume_resp.json()['data']['status']}")

        # 验证 checkpoint 已保存
        detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        self.assertIsNotNone(detail.json()["data"].get("checkpoint"))
        print(f"✓ Checkpoint 已保存")
