"""ResearchEngine API 集成测试。

覆盖 ProblemSpec API 和 AlgorithmRegistry API 的所有端点。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.services.research_engine_service import ResearchEngineService
from app.core.auth import get_current_user
from app.main import app


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
# ProblemSpec API 测试
# =============================================================================


class ProblemSpecApiTest(ComputationTestCase):
    """覆盖 ProblemSpec REST API。"""

    @classmethod
    def setUpClass(cls) -> None:
        """填充算法种子数据。"""
        # 不在此处初始化，由 setUp 处理
        pass

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"

    def test_create_problem_spec(self) -> None:
        """POST /problem-specs 创建 ProblemSpec 成功。"""
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertTrue(data["data"]["problem_spec_id"].startswith("ps_"))
        self.assertEqual(data["data"]["status"], "draft")
        self.assertEqual(data["data"]["schema_version"], "0.4")
        self.assertEqual(data["data"]["decision_status"], "pending_execution_decision")
        self.assertEqual(data["data"]["allowed_execution_modes"], ["manual_workbench", "autoresearch"])

    def test_create_with_full_fields(self) -> None:
        """包含完整字段的 ProblemSpec 创建成功。"""
        payload = problem_spec_payload(
            variables=[
                {"name": "fluorine_content", "type": "continuous", "role": "formulation", "unit": "percent", "bounds": [0, 100]},
                {"name": "monomer_smiles", "type": "categorical", "role": "structure", "categories": ["C=CF", "C=C(F)F"]},
            ],
            constraints=[
                {"name": "synthesizable", "type": "hard"},
                {"name": "temp_limit", "type": "hard", "expression": "temperature <= 180"},
            ],
            measurements=[
                {"name": "dielectric_constant", "condition": "room_temperature", "method": "impedance"},
            ],
            description="氟基高分子电解质优化演示",
        )
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(len(data["data"]["variables"]), 2)
        self.assertEqual(len(data["data"]["constraints"]), 2)
        self.assertEqual(len(data["data"]["measurements"]), 1)

    def test_create_rejects_empty_name(self) -> None:
        """空名称被拒绝（422 校验错误）。"""
        payload = problem_spec_payload(name="   ")
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_create_rejects_empty_objectives(self) -> None:
        """空目标列表被拒绝（422 校验错误）。"""
        payload = problem_spec_payload(objectives=[])
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 422)

    def test_list_problem_specs(self) -> None:
        """GET /problem-specs 查询列表成功。"""
        # 先创建几条数据
        for i in range(3):
            self.client.post(
                f"{self.base_url}/problem-specs",
                json=problem_spec_payload(name=f"任务{i}"),
            )

        resp = self.client.get(f"{self.base_url}/problem-specs?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)
        self.assertGreaterEqual(data["data"]["total"], 3)

    def test_archive_problem_spec_hides_from_default_list(self) -> None:
        """归档 ProblemSpec 后默认列表隐藏，按 archived 状态可查。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(name="待归档研发任务"),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        archive_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}:archive",
            json={"reason": "API 测试归档"},
        )
        self.assertEqual(archive_resp.status_code, 200)
        self.assertEqual(archive_resp.json()["data"]["status"], "archived")

        default_resp = self.client.get(f"{self.base_url}/problem-specs")
        default_ids = [item["problem_spec_id"] for item in default_resp.json()["data"]["items"]]
        self.assertNotIn(ps_id, default_ids)

        archived_resp = self.client.get(f"{self.base_url}/problem-specs?status=archived")
        archived_ids = [item["problem_spec_id"] for item in archived_resp.json()["data"]["items"]]
        self.assertIn(ps_id, archived_ids)

    def test_readiness_reports_optional_demo_fallbacks_before_start(self) -> None:
        """AutoResearch 启动前可见 RAG/Alchemist 等集成可用性。"""
        with patch("app.services.integration_status_service.IntegrationStatusService._can_connect", return_value=False):
            resp = self.client.get(f"{self.base_url}/readiness")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        by_service = {item["service"]: item for item in data["items"]}

        self.assertFalse(data["ready"])
        self.assertTrue(data["can_start"])
        self.assertEqual(by_service["literature-rag"]["status"], "warning")
        self.assertTrue(by_service["literature-rag"]["demo_fallback"])
        self.assertFalse(by_service["literature-rag"]["blocking"])
        self.assertEqual(by_service["artifact-store"]["status"], "ready")
        self.assertEqual(by_service["computation-engine"]["status"], "ready")
        self.assertEqual(by_service["alchemist-backend"]["status"], "warning")


class ResearchEngineAccessControlApiTest(ComputationTestCase):
    """覆盖 ResearchEngine ID 直连访问的所有权校验。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        ResearchEngineService().seed_default_algorithms()

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _login_as(user_id: str, role: str = "user") -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "username": user_id,
            "role": role,
            "status": "active",
        }

    def _create_owned_research_run(self) -> tuple[str, str, str]:
        self._login_as("user-a")
        ps_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(
                name="用户 A 的 AutoResearch",
                allowed_execution_modes=["autoresearch"],
            ),
        )
        self.assertEqual(ps_resp.status_code, 200)
        ps_id = ps_resp.json()["data"]["problem_spec_id"]

        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "访问控制测试"},
        )
        self.assertEqual(decision_resp.status_code, 200)
        decision_id = decision_resp.json()["data"]["decision_id"]

        run_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": ps_id,
                "execution_decision_id": decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 1,
                "batch_size": 5,
            },
        )
        self.assertEqual(run_resp.status_code, 200)
        run_id = run_resp.json()["data"]["run_id"]
        return ps_id, decision_id, run_id

    def test_id_based_operations_require_owner_or_admin(self) -> None:
        ps_id, _decision_id, run_id = self._create_owned_research_run()

        self._login_as("user-b")
        forbidden_requests = [
            self.client.get(f"{self.base_url}/problem-specs/{ps_id}"),
            self.client.post(f"{self.base_url}/problem-specs/{ps_id}:archive", json={"reason": "try"}),
            self.client.get(f"{self.base_url}/research-runs/{run_id}"),
            self.client.post(f"{self.base_url}/research-runs/{run_id}:archive", json={"reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/start", json={"target_status": "running", "reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/advance", json={"target_status": "running", "reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/pause", json={"target_status": "paused", "reason": "try"}),
            self.client.post(f"{self.base_url}/research-runs/{run_id}/fail", json={"target_status": "failed", "reason": "try"}),
            self.client.get(f"{self.base_url}/research-runs/{run_id}/traceability"),
        ]
        for response in forbidden_requests:
            self.assertEqual(response.status_code, 403, response.text)

        audit_resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "research_run", "entity_id": run_id},
        )
        self.assertEqual(audit_resp.status_code, 200)
        self.assertEqual(audit_resp.json()["data"]["total"], 0)

        self._login_as("user-a")
        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "owner start"},
        )
        self.assertEqual(start_resp.status_code, 200)
        gate = next(
            stage
            for stage in start_resp.json()["data"]["stage_runs"]
            if stage["status"] == "blocked_approval"
        )

        self._login_as("user-b")
        approve_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/stages/{gate['stage_run_id']}/approve",
            json={"stage_key": gate["stage_key"], "decision": "approved", "reason": "try"},
        )
        reject_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/stages/{gate['stage_run_id']}/reject",
            json={"stage_key": gate["stage_key"], "decision": "rejected", "reason": "try"},
        )
        self.assertEqual(approve_resp.status_code, 403)
        self.assertEqual(reject_resp.status_code, 403)

        self._login_as("admin", role="admin")
        admin_detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        self.assertEqual(admin_detail.status_code, 200)

    def test_list_with_filters(self) -> None:
        """按状态和材料体系过滤。"""
        # 创建一条数据
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(material_family="fluoropolymer"),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        # 查询 fluoropolymer
        resp = self.client.get(f"{self.base_url}/problem-specs?material_family=fluoropolymer")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.json()["data"]["total"], 1)

    def test_get_problem_spec(self) -> None:
        """GET /problem-specs/{id} 获取详情成功。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        resp = self.client.get(f"{self.base_url}/problem-specs/{ps_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["problem_spec_id"], ps_id)

    def test_get_nonexistent_returns_404(self) -> None:
        """不存在的 ProblemSpec 返回 404。"""
        resp = self.client.get(f"{self.base_url}/problem-specs/ps_nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_update_problem_spec(self) -> None:
        """PATCH /problem-specs/{id} 更新草稿成功。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        update_payload = problem_spec_payload(
            name="更新后的任务名",
            allowed_execution_modes=["manual_workbench"],
        )
        resp = self.client.patch(
            f"{self.base_url}/problem-specs/{ps_id}",
            json=update_payload,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["name"], "更新后的任务名")
        self.assertEqual(data["data"]["allowed_execution_modes"], ["manual_workbench"])

    def test_freeze_problem_spec(self) -> None:
        """POST /problem-specs/{id}/freeze 冻结成功。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        resp = self.client.post(f"{self.base_url}/problem-specs/{ps_id}/freeze")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "frozen")
        self.assertEqual(data["data"]["frozen_version"], 1)

    def test_freeze_nonexistent_returns_404(self) -> None:
        """冻结不存在的 ProblemSpec 返回 404。"""
        resp = self.client.post(f"{self.base_url}/problem-specs/ps_nonexistent/freeze")
        self.assertEqual(resp.status_code, 404)

    def test_update_frozen_returns_409(self) -> None:
        """已冻结的 ProblemSpec 不可修改（409）。"""
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        ps_id = create_resp.json()["data"]["problem_spec_id"]

        # 冻结
        self.client.post(f"{self.base_url}/problem-specs/{ps_id}/freeze")

        # 尝试更新
        update_payload = problem_spec_payload(name="尝试更新")
        resp = self.client.patch(
            f"{self.base_url}/problem-specs/{ps_id}",
            json=update_payload,
        )
        self.assertEqual(resp.status_code, 409)

    def test_create_with_campaign_id(self) -> None:
        """创建时可关联已有 campaign_id。"""
        payload = problem_spec_payload(campaign_id="camp_001")
        resp = self.client.post(f"{self.base_url}/problem-specs", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["campaign_id"], "camp_001")

    def test_execution_mode_field_is_rejected(self) -> None:
        """v0.4 不再接受旧 execution_mode 字段。"""
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(execution_mode="hybrid", name="旧字段"),
        )
        self.assertEqual(resp.status_code, 422)


# =============================================================================
# AlgorithmRegistry API 测试
# =============================================================================


class AlgorithmRegistryAutoSeedApiTest(ComputationTestCase):
    """覆盖算法清单 API 的默认种子化行为。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"

    def test_list_algorithms_auto_seeds_empty_registry_with_family(self) -> None:
        """空库首次请求算法清单时自动返回默认算法族。"""
        resp = self.client.get(f"{self.base_url}/algorithms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 8)
        families = {item.get("algorithm_family") for item in data["data"]["items"]}
        self.assertIn("computation", families)
        self.assertIn("wetlab_optimization", families)
        self.assertIn("vertical_prediction", families)

        filtered = self.client.get(f"{self.base_url}/algorithms?algorithm_family=computation")
        self.assertEqual(filtered.status_code, 200)
        filtered_items = filtered.json()["data"]["items"]
        self.assertGreaterEqual(len(filtered_items), 1)
        self.assertTrue(all(item.get("algorithm_family") == "computation" for item in filtered_items))


class AlgorithmRegistryApiTest(ComputationTestCase):
    """覆盖 AlgorithmRegistry REST API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        # 写入种子数据
        service = ResearchEngineService()
        service.seed_default_algorithms()

    def test_list_algorithms(self) -> None:
        """GET /algorithms 查询列表成功。"""
        resp = self.client.get(f"{self.base_url}/algorithms")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 8)
        self.assertEqual(data["data"]["page"], 1)

    def test_list_with_type_filter(self) -> None:
        """按类型过滤算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?type=simulator")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        for item in data["data"]["items"]:
            self.assertEqual(item["type"], "simulator")

    def test_list_with_trigger_mode_filter(self) -> None:
        """按触发方式过滤算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?trigger_mode=human_workflow")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for item in data["data"]["items"]:
            self.assertIn("human_workflow", item["trigger_modes"])

    def test_list_with_status_filter(self) -> None:
        """按状态过滤算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?status=active")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for item in data["data"]["items"]:
            self.assertEqual(item["status"], "active")

    def test_list_with_pagination(self) -> None:
        """分页查询算法。"""
        resp = self.client.get(f"{self.base_url}/algorithms?page=1&page_size=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertLessEqual(len(data["data"]["items"]), 5)

    def test_get_algorithm_detail(self) -> None:
        """GET /algorithms/{id} 获取详情成功。"""
        resp = self.client.get(f"{self.base_url}/algorithms/literature_mock")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["algorithm_id"], "literature_mock")
        self.assertEqual(data["data"]["type"], "retriever")
        self.assertEqual(data["data"]["name"], "文献检索")
        # 必须有 input_schema 和 output_schema
        self.assertIn("fields", data["data"]["input_schema"])
        self.assertIn("required", data["data"]["input_schema"])
        self.assertIn("fields", data["data"]["output_schema"])

    def test_get_nonexistent_algorithm_returns_404(self) -> None:
        """不存在的算法返回 404。"""
        resp = self.client.get(f"{self.base_url}/algorithms/nonexistent_algo")
        self.assertEqual(resp.status_code, 404)

    def test_all_mock_algorithms_returned(self) -> None:
        """所有 5 个 mock 算法均被返回。"""
        mock_ids = [
            "literature_mock",
            "polymer_descriptor_mock",
            "property_predictor_mock",
            "mobo_mock",
            "computation_submit_adapter",
        ]
        for algo_id in mock_ids:
            resp = self.client.get(f"{self.base_url}/algorithms/{algo_id}")
            self.assertEqual(resp.status_code, 200, f"算法 {algo_id} 未找到")
            self.assertEqual(resp.json()["data"]["algorithm_id"], algo_id)

    def test_all_adapter_algorithms_returned(self) -> None:
        """所有 3 个计算 adapter 算法均被返回。"""
        adapter_ids = [
            "local_structure_adapter",
            "local_xtb_adapter",
            "orca_compute_engine_laser_adapter",
        ]
        for algo_id in adapter_ids:
            resp = self.client.get(f"{self.base_url}/algorithms/{algo_id}")
            self.assertEqual(resp.status_code, 200, f"算法 {algo_id} 未找到")
            self.assertEqual(resp.json()["data"]["algorithm_id"], algo_id)

    def test_algorithm_has_required_display_fields(self) -> None:
        """算法响应包含前端渲染算法卡所需的字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/property_predictor_mock")
        data = resp.json()["data"]

        required_fields = [
            "algorithm_id", "name", "type", "material_scope",
            "task_scope", "trigger_modes", "status", "version",
            "description", "input_schema", "output_schema",
        ]
        for field in required_fields:
            self.assertIn(field, data, f"缺少字段: {field}")

    def test_literature_mock_schema(self) -> None:
        """文献检索 mock 的 input_schema 包含 keywords 必填字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/literature_mock")
        data = resp.json()["data"]
        self.assertIn("keywords", data["input_schema"]["required"])
        self.assertIn("knowledge_cards", data["output_schema"]["required"])

    def test_mobo_mock_schema(self) -> None:
        """BO/MOBO mock 的 input_schema 包含 problem_spec_id 必填字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/mobo_mock")
        data = resp.json()["data"]
        self.assertIn("problem_spec_id", data["input_schema"]["required"])
        self.assertIn("top_k_candidates", data["output_schema"]["required"])

    def test_computation_submit_adapter_schema(self) -> None:
        """计算提交 adapter 的 input_schema 包含 workflow_type 必填字段。"""
        resp = self.client.get(f"{self.base_url}/algorithms/computation_submit_adapter")
        data = resp.json()["data"]
        self.assertIn("workflow_type", data["input_schema"]["required"])
        self.assertIn("computation_run_id", data["output_schema"]["required"])


# =============================================================================
# ExecutionDecision / ManualWorkflow API 测试
# =============================================================================


class ManualWorkflowApiTest(ComputationTestCase):
    """覆盖 v0.4 执行决策和人工 Workflow API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        service = ResearchEngineService()
        service.seed_default_algorithms()
        ps_resp = self.client.post(f"{self.base_url}/problem-specs", json=problem_spec_payload())
        self.assertEqual(ps_resp.status_code, 200)
        self.ps_id = ps_resp.json()["data"]["problem_spec_id"]

    def test_create_and_get_active_execution_decision(self) -> None:
        """ProblemSpec 可显式选择 manual_workbench。"""
        resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "API 测试人工编排"},
        )
        self.assertEqual(resp.status_code, 200)
        decision = resp.json()["data"]
        self.assertEqual(decision["mode"], "manual_workbench")

        active = self.client.get(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions/active"
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["data"]["decision_id"], decision["decision_id"])

    def test_manual_workflow_run_creates_algorithm_run(self) -> None:
        """单节点人工 WorkflowRun 会创建关联 AlgorithmRun。"""
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "API 测试单节点 workflow"},
        )
        decision_id = decision_resp.json()["data"]["decision_id"]

        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": decision_id,
                "name": "API 单节点文献检索",
                "steps": [
                    {
                        "step_id": "s1",
                        "algorithm_id": "literature_mock",
                        "input_bindings": {
                            "keywords": {
                                "source": "manual_input",
                                "value": "氟基高分子 介电常数",
                            }
                        },
                    }
                ],
            },
        )
        self.assertEqual(workflow_resp.status_code, 200)
        workflow_id = workflow_resp.json()["data"]["workflow_id"]

        run_resp = self.client.post(f"{self.base_url}/manual-workflows/{workflow_id}/runs")
        self.assertEqual(run_resp.status_code, 200)
        workflow_run = run_resp.json()["data"]
        self.assertEqual(workflow_run["status"], "completed")
        self.assertEqual(len(workflow_run["step_runs"]), 1)

        aruns = self.client.get(
            f"{self.base_url}/algorithm-runs",
            params={"workflow_run_id": workflow_run["workflow_run_id"]},
        )
        self.assertEqual(aruns.status_code, 200)
        self.assertEqual(aruns.json()["data"]["total"], 1)
        self.assertEqual(aruns.json()["data"]["items"][0]["trigger_source"], "human_workflow")

    def test_archive_manual_workflow_hides_from_default_list(self) -> None:
        """归档人工 Workflow 后默认列表隐藏，按 archived 状态可查。"""
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "manual_workbench", "reason": "API 测试归档 workflow"},
        )
        workflow_resp = self.client.post(
            f"{self.base_url}/manual-workflows",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": decision_resp.json()["data"]["decision_id"],
                "name": "待归档 Workflow",
                "steps": [
                    {
                        "step_id": "s1",
                        "algorithm_id": "literature_mock",
                        "input_bindings": {
                            "keywords": {"source": "manual_input", "value": "polymer"}
                        },
                    }
                ],
            },
        )
        workflow_id = workflow_resp.json()["data"]["workflow_id"]

        archive_resp = self.client.post(
            f"{self.base_url}/manual-workflows/{workflow_id}:archive",
            json={"reason": "API 测试归档"},
        )
        self.assertEqual(archive_resp.status_code, 200)
        self.assertEqual(archive_resp.json()["data"]["status"], "archived")

        default_resp = self.client.get(f"{self.base_url}/manual-workflows")
        default_ids = [item["workflow_id"] for item in default_resp.json()["data"]["items"]]
        self.assertNotIn(workflow_id, default_ids)

        archived_resp = self.client.get(f"{self.base_url}/manual-workflows?status=archived")
        archived_ids = [item["workflow_id"] for item in archived_resp.json()["data"]["items"]]
        self.assertIn(workflow_id, archived_ids)


# =============================================================================
# 现有路由不受影响测试
# =============================================================================


class ExistingRoutesUnaffectedTest(ComputationTestCase):
    """确保新增 ResearchEngine 路由不影响现有 API 端点。"""

    def test_health_endpoint_still_works(self) -> None:
        """Health 端点仍正常响应。"""
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)

    def test_optimization_campaigns_endpoint_still_works(self) -> None:
        """优化 campaign 端点仍正常响应。"""
        resp = self.client.get("/api/v1/optimization/campaigns?page=1&page_size=5")
        self.assertEqual(resp.status_code, 200)

    def test_computations_endpoint_still_works(self) -> None:
        """计算任务端点仍正常响应。"""
        resp = self.client.get("/api/v1/computations?page=1&page_size=5")
        self.assertEqual(resp.status_code, 200)

    def test_integrations_endpoint_still_works(self) -> None:
        """集成配置端点仍正常响应。"""
        resp = self.client.get("/api/v1/integrations/status")
        self.assertEqual(resp.status_code, 200)


# =============================================================================
# AlgorithmRun API 测试
# =============================================================================


class AlgorithmRunApiTest(ComputationTestCase):
    """覆盖 AlgorithmRun REST API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        # 写入算法种子数据
        service = ResearchEngineService()
        service.seed_default_algorithms()

    def test_create_algorithm_run(self) -> None:
        """POST /algorithm-runs 创建 AlgorithmRun 成功。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "氟基高分子 介电常数"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "completed")
        self.assertTrue(data["data"]["run_id"].startswith("arun_"))
        self.assertIn("knowledge_cards", data["data"]["output_summary"])

    def test_create_all_five_mock_runs(self) -> None:
        """所有 5 个 mock 算法均可通过 API 创建运行。"""
        test_cases = [
            {
                "algorithm_id": "literature_mock",
                "input_snapshot": {"keywords": "氟基高分子"},
            },
            {
                "algorithm_id": "polymer_descriptor_mock",
                "input_snapshot": {"smiles": "C=CF"},
            },
            {
                "algorithm_id": "property_predictor_mock",
                "input_snapshot": {
                    "smiles": "C=C(F)F",
                    "target_properties": ["dielectric_constant", "thermal_stability"],
                },
            },
            {
                "algorithm_id": "mobo_mock",
                "input_snapshot": {
                    "problem_spec_id": "ps_test_001",
                    "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                },
            },
            {
                "algorithm_id": "computation_submit_adapter",
                "input_snapshot": {
                    "workflow_type": "LOCAL_STRUCTURE",
                    "smiles": "CCO",
                    "name": "ethanol",
                },
            },
        ]

        for tc in test_cases:
            resp = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": tc["algorithm_id"],
                    "trigger_source": "human_workflow",
                    "input_snapshot": tc["input_snapshot"],
                },
            )
            self.assertEqual(
                resp.status_code, 200,
                f"算法 {tc['algorithm_id']} 创建失败: {resp.json()}",
            )
            data = resp.json()
            self.assertEqual(data["code"], 0)
            self.assertEqual(data["data"]["algorithm_id"], tc["algorithm_id"])
            self.assertEqual(data["data"]["status"], "completed")

    def test_create_with_problem_spec_and_campaign(self) -> None:
        """创建 AlgorithmRun 时关联 problem_spec_id 和 campaign_id。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "problem_spec_id": "ps_demo_001",
                "campaign_id": "camp_demo_001",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["problem_spec_id"], "ps_demo_001")
        self.assertEqual(data["data"]["campaign_id"], "camp_demo_001")

    def test_create_with_reason(self) -> None:
        """创建 AlgorithmRun 时提供操作原因。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
                "reason": "验证人工算法通道闭环",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["data"]["status"], "completed")

    def test_create_nonexistent_algorithm_returns_404(self) -> None:
        """不存在的 algorithm_id 返回 404。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "nonexistent_algo",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_create_unsupported_trigger_returns_400(self) -> None:
        """不支持的 trigger_source 返回 400。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "system",  # 不支持
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_missing_required_input_returns_error(self) -> None:
        """缺少必填输入字段时返回错误（500 或 422，取决于校验时机）。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"material_family": "fluoropolymer"},  # 缺少 keywords
            },
        )
        self.assertIn(resp.status_code, [400, 422, 500])

    def test_list_algorithm_runs(self) -> None:
        """GET /algorithm-runs 查询列表成功。"""
        # 创建几条数据
        for i in range(3):
            self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": "literature_mock",
                    "trigger_source": "human_workflow",
                    "input_snapshot": {"keywords": f"test{i}"},
                },
            )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)
        self.assertGreaterEqual(data["data"]["total"], 3)

    def test_list_by_algorithm_id(self) -> None:
        """按 algorithm_id 过滤列表。"""
        # 创建不同类型的数据
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "polymer_descriptor_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "C=CF"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?algorithm_id=polymer_descriptor_mock")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["algorithm_id"], "polymer_descriptor_mock")

    def test_list_by_status(self) -> None:
        """按 status 过滤列表。"""
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?status=completed")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["status"], "completed")

    def test_list_by_trigger_source(self) -> None:
        """按 trigger_source 过滤列表。"""
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs?trigger_source=human_workflow")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["trigger_source"], "human_workflow")

    def test_list_with_empty_filters(self) -> None:
        """无过滤条件时返回所有记录。"""
        self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )

        resp = self.client.get(f"{self.base_url}/algorithm-runs")
        self.assertEqual(resp.status_code, 200)

    def test_get_algorithm_run_detail(self) -> None:
        """GET /algorithm-runs/{run_id} 获取详情成功。"""
        # 先创建
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "property_predictor_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {
                    "smiles": "C=C(F)F",
                    "target_properties": ["dielectric_constant"],
                },
            },
        )
        run_id = create_resp.json()["data"]["run_id"]

        # 查询详情
        resp = self.client.get(f"{self.base_url}/algorithm-runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["run_id"], run_id)
        self.assertEqual(data["data"]["algorithm_id"], "property_predictor_mock")
        self.assertEqual(data["data"]["trigger_source"], "human_workflow")
        self.assertIn("predictions", data["data"]["output_summary"])
        self.assertIn("input_snapshot", data["data"])
        self.assertIsInstance(data["data"]["artifact_refs"], list)

    def test_get_algorithm_run_has_required_fields(self) -> None:
        """AlgorithmRun 详情包含所有必要字段。"""
        create_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "mobo_mock",
                "trigger_source": "human_workflow",
                "input_snapshot": {
                    "problem_spec_id": "ps_test_001",
                    "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                },
            },
        )
        run_id = create_resp.json()["data"]["run_id"]

        resp = self.client.get(f"{self.base_url}/algorithm-runs/{run_id}")
        data = resp.json()["data"]

        required_fields = [
            "run_id", "algorithm_id", "trigger_source", "status",
            "input_snapshot", "output_summary", "artifact_refs",
            "created_by", "created_at", "updated_at",
        ]
        for field in required_fields:
            self.assertIn(field, data, f"缺少字段: {field}")

    def test_get_nonexistent_run_returns_404(self) -> None:
        """不存在的 AlgorithmRun 返回 404。"""
        resp = self.client.get(f"{self.base_url}/algorithm-runs/arun_nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_create_empty_algorithm_id_returns_422(self) -> None:
        """空的 algorithm_id 被拒绝（422）。"""
        resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "   ",
                "trigger_source": "human_workflow",
                "input_snapshot": {"keywords": "test"},
            },
        )
        self.assertEqual(resp.status_code, 422)


# =============================================================================
# ResearchRun API 测试 (Plan 04)
# =============================================================================


class ResearchRunApiTest(ComputationTestCase):
    """覆盖 ResearchRun REST API 的创建、启动、推进、暂停、恢复。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        # 写入算法种子数据，并创建 ProblemSpec
        from app.services.research_engine_service import ResearchEngineService
        svc = ResearchEngineService()
        svc.seed_default_algorithms()

        # 创建 ProblemSpec
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "ResearchRun API 测试",
                "material_family": "fluoropolymer",
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                ],
            },
        )
        self.assertEqual(create_resp.status_code, 200)
        self.ps_id = create_resp.json()["data"]["problem_spec_id"]
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "API 测试进入 AutoResearch"},
        )
        self.assertEqual(decision_resp.status_code, 200)
        self.execution_decision_id = decision_resp.json()["data"]["decision_id"]

    def _create_research_run(self, **overrides) -> dict:
        """创建 ResearchRun 草稿的辅助方法。"""
        payload = {
            "problem_spec_id": self.ps_id,
            "execution_decision_id": self.execution_decision_id,
            "profile_id": "fluoropolymer",
        }
        payload.update(overrides)
        resp = self.client.post(f"{self.base_url}/research-runs", json=payload)
        self.assertEqual(resp.status_code, 200)
        return resp.json()["data"]

    def test_create_research_run(self) -> None:
        """POST /research-runs 创建 ResearchRun 成功。"""
        data = self._create_research_run()
        self.assertEqual(data["status"], "draft")
        self.assertTrue(data["run_id"].startswith("rr_"))
        self.assertEqual(data["problem_spec_id"], self.ps_id)
        self.assertEqual(len(data["stage_runs"]), 10)

    def test_create_with_campaign(self) -> None:
        """创建 ResearchRun 时关联 campaign。"""
        data = self._create_research_run(campaign_id="camp_001")
        self.assertEqual(data["campaign_id"], "camp_001")

    def test_create_with_profile(self) -> None:
        """创建时使用指定 profile。"""
        data = self._create_research_run(profile_id="carbon_polymer")
        self.assertEqual(data["profile_id"], "carbon_polymer")

    def test_get_research_run(self) -> None:
        """GET /research-runs/{id} 获取详情成功。"""
        created = self._create_research_run()
        resp = self.client.get(f"{self.base_url}/research-runs/{created['run_id']}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["run_id"], created["run_id"])
        self.assertIn("stage_runs", data["data"])

    def test_get_nonexistent_research_run_returns_404(self) -> None:
        """不存在的 ResearchRun 返回 404。"""
        resp = self.client.get(f"{self.base_url}/research-runs/rr_nonexistent")
        self.assertEqual(resp.status_code, 404)

    def test_list_research_runs(self) -> None:
        """GET /research-runs 查询列表成功。"""
        for i in range(3):
            self._create_research_run()

        resp = self.client.get(f"{self.base_url}/research-runs?page=1&page_size=2")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertLessEqual(len(data["data"]["items"]), 2)
        self.assertGreaterEqual(data["data"]["total"], 3)

    def test_archive_research_run_hides_from_default_list(self) -> None:
        """归档 ResearchRun 后默认列表隐藏，按 archived 状态可查。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        archive_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}:archive",
            json={"reason": "API 测试归档"},
        )
        self.assertEqual(archive_resp.status_code, 200)
        self.assertEqual(archive_resp.json()["data"]["status"], "archived")

        default_resp = self.client.get(f"{self.base_url}/research-runs")
        default_ids = [item["run_id"] for item in default_resp.json()["data"]["items"]]
        self.assertNotIn(run_id, default_ids)

        archived_resp = self.client.get(f"{self.base_url}/research-runs?status=archived")
        archived_ids = [item["run_id"] for item in archived_resp.json()["data"]["items"]]
        self.assertIn(run_id, archived_ids)

    def test_list_by_status(self) -> None:
        """按状态过滤 ResearchRun。"""
        self._create_research_run()
        resp = self.client.get(f"{self.base_url}/research-runs?status=draft")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["data"]["total"], 1)

    def test_start_research_run(self) -> None:
        """POST /research-runs/{id}/start 启动并推进到 gate。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动测试"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "blocked_approval")
        problem_stage = next(
            sr for sr in data["data"]["stage_runs"]
            if sr["stage_key"] == "PROBLEM_SPEC"
        )
        self.assertEqual(problem_stage["status"], "blocked_approval")

    def test_start_requires_reason(self) -> None:
        """启动时缺少 reason 返回 422。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": ""},
        )
        self.assertEqual(resp.status_code, 422)

    def test_start_nonexistent_run_returns_404(self) -> None:
        """启动不存在的 ResearchRun 返回 404。"""
        resp = self.client.post(
            f"{self.base_url}/research-runs/rr_nonexistent/start",
            json={"target_status": "running", "reason": "启动"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_pause_research_run(self) -> None:
        """POST /research-runs/{id}/pause 暂停成功。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        # 先启动
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )

        # 暂停
        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "测试暂停"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "paused")

    def test_resume_research_run(self) -> None:
        """POST /research-runs/{id}/resume 恢复成功。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        # 启动 → 暂停
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "暂停"},
        )

        # 恢复
        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/resume",
            json={"target_status": "running", "reason": "测试恢复"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "running")

    def test_fail_research_run(self) -> None:
        """POST /research-runs/{id}/fail 标记失败。"""
        created = self._create_research_run()
        run_id = created["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "启动"},
        )

        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/fail",
            json={"target_status": "failed", "reason": "手动标记失败"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "failed")


# =============================================================================
# Stage/Gate 审批 API 测试 (Plan 04 Task 3)
# =============================================================================


class StageGateApiTest(ComputationTestCase):
    """覆盖 Stage/Gate 审批 REST API。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        from app.services.research_engine_service import ResearchEngineService
        svc = ResearchEngineService()
        svc.seed_default_algorithms()

        # 创建 ProblemSpec
        create_resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json={
                "name": "Gate 审批测试",
                "material_family": "fluoropolymer",
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                ],
            },
        )
        self.ps_id = create_resp.json()["data"]["problem_spec_id"]
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "Gate API 测试进入 AutoResearch"},
        )
        self.execution_decision_id = decision_resp.json()["data"]["decision_id"]

        # 创建 ResearchRun 并启动以到达 gate
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={"problem_spec_id": self.ps_id, "execution_decision_id": self.execution_decision_id},
        )
        self.run_id = rr_resp.json()["data"]["run_id"]

        start_resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/start",
            json={"target_status": "running", "reason": "启动以到达 gate"},
        )
        self.started_data = start_resp.json()["data"]

    def test_approve_gate(self) -> None:
        """POST .../stages/{stage_run_id}/approve 批准 gate。"""
        # 找到 PROBLEM_SPEC gate（第一个 blocked_approval）
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr, "应有 blocked_approval 阶段")

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/approve",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "approved",
                "reason": "审批通过测试",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "blocked_approval")
        knowledge_stage = next(
            sr for sr in data["data"]["stage_runs"]
            if sr["stage_key"] == "KNOWLEDGE_RETRIEVAL"
        )
        self.assertEqual(knowledge_stage["status"], "completed")
        self.assertGreater(len(knowledge_stage["linked_algorithm_runs"]), 0)

    def test_reject_gate(self) -> None:
        """POST .../stages/{stage_run_id}/reject 拒绝 gate。"""
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr)

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/reject",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "rejected",
                "reason": "拒绝测试-不满足需求",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertEqual(data["data"]["status"], "failed")

    def test_approve_requires_reason(self) -> None:
        """审批缺少 reason 返回 422。"""
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr)

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/approve",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "approved",
                "reason": "   ",  # 空白被拒绝
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_reject_requires_reason(self) -> None:
        """拒绝缺少 reason 返回 422。"""
        blocked_sr = None
        for sr in self.started_data["stage_runs"]:
            if sr["status"] == "blocked_approval":
                blocked_sr = sr
                break
        self.assertIsNotNone(blocked_sr)

        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/{blocked_sr['stage_run_id']}/reject",
            json={
                "stage_key": blocked_sr["stage_key"],
                "decision": "rejected",
                "reason": "",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_approve_nonexistent_stage_returns_404(self) -> None:
        """审批不存在的 StageRun 返回 404。"""
        resp = self.client.post(
            f"{self.base_url}/research-runs/{self.run_id}/stages/srun_nonexistent/approve",
            json={
                "stage_key": "PROBLEM_SPEC",
                "decision": "approved",
                "reason": "审批不存在的 stage",
            },
        )
        self.assertEqual(resp.status_code, 404)

    def test_full_approve_flow(self) -> None:
        """完整审批流程：逐个审批所有 gate。"""
        run_id = self.run_id

        # 获取初始状态
        rr_resp = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        run_data = rr_resp.json()["data"]

        max_loops = 10
        while run_data["status"] in ("blocked_approval",) and max_loops > 0:
            max_loops -= 1
            blocked_sr = None
            for sr in run_data["stage_runs"]:
                if sr["status"] == "blocked_approval":
                    blocked_sr = sr
                    break
            if blocked_sr is None:
                break

            approve_resp = self.client.post(
                f"{self.base_url}/research-runs/{run_id}/stages/{blocked_sr['stage_run_id']}/approve",
                json={
                    "stage_key": blocked_sr["stage_key"],
                    "decision": "approved",
                    "reason": f"审批 {blocked_sr['stage_key']}",
                },
            )
            self.assertEqual(approve_resp.status_code, 200)
            run_data = approve_resp.json()["data"]

        self.assertIn(run_data["status"], ["completed", "blocked_approval", "failed"])

    def test_full_pause_resume_flow(self) -> None:
        """完整暂停-恢复流程 API 测试。"""
        run_id = self.run_id

        # 暂停
        pause_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/pause",
            json={"target_status": "paused", "reason": "API 测试暂停"},
        )
        self.assertEqual(pause_resp.status_code, 200)
        self.assertEqual(pause_resp.json()["data"]["status"], "paused")

        # 恢复
        resume_resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/resume",
            json={"target_status": "running", "reason": "API 测试恢复"},
        )
        self.assertEqual(resume_resp.status_code, 200)
        self.assertIn(
            resume_resp.json()["data"]["status"],
            ["running", "blocked_approval"],
        )

    def test_advance_endpoint(self) -> None:
        """POST /research-runs/{id}/advance 推进阶段。"""
        run_id = self.run_id

        # advance 要求 status 为 running 或 blocked_approval
        # 从 running 或 blocked_approval 直接调用 advance
        resp = self.client.post(
            f"{self.base_url}/research-runs/{run_id}/advance",
            json={"target_status": "running", "reason": "手动继续推进"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertIn(data["data"]["status"], ["running", "blocked_approval", "completed"])


# =============================================================================
# Traceability API 测试（Plan 06 Task 1）
# =============================================================================


class TraceabilityApiTest(ComputationTestCase):
    """覆盖追溯聚合 API。"""

    @classmethod
    def setUpClass(cls) -> None:
        pass

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        self.svc = ResearchEngineService()

        # 创建 ProblemSpec
        resp = self.client.post(
            f"{self.base_url}/problem-specs",
            json=problem_spec_payload(),
        )
        self.ps_id = resp.json()["data"]["problem_spec_id"]

        # 填充算法种子
        self.svc.seed_default_algorithms()
        decision_resp = self.client.post(
            f"{self.base_url}/problem-specs/{self.ps_id}/execution-decisions",
            json={"mode": "autoresearch", "reason": "Traceability 测试进入 AutoResearch"},
        )
        self.autoresearch_decision_id = decision_resp.json()["data"]["decision_id"]

    def test_query_audit_by_entity(self) -> None:
        """按 entity_type 和 entity_id 查询审计事件。"""
        resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_type": "problem_spec", "entity_id": self.ps_id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 1)
        # 确认有 "created" 事件
        event_types = [e["event_type"] for e in data["data"]["items"]]
        self.assertIn("created", event_types)

    def test_query_audit_filter_by_event_type(self) -> None:
        """按事件类型过滤审计事件。"""
        resp = self.client.get(
            f"{self.base_url}/audit",
            params={
                "entity_type": "problem_spec",
                "entity_id": self.ps_id,
                "event_type": "created",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["code"], 0)
        self.assertGreaterEqual(data["data"]["total"], 1)
        for item in data["data"]["items"]:
            self.assertEqual(item["event_type"], "created")

    def test_audit_returns_sanitized_data(self) -> None:
        """审计事件不暴露敏感路径。"""
        resp = self.client.get(
            f"{self.base_url}/audit",
            params={"entity_id": self.ps_id},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for item in data["data"]["items"]:
            item_str = str(item)
            # 不暴露本地文件系统路径
            self.assertNotIn("/home/", item_str)
            self.assertNotIn("storage_uri", item_str)

    def test_algorithm_run_traceability_without_computation(self) -> None:
        """AlgorithmRun 追溯链：无关联 computation 的情况。"""
        # 运行 mock predictor
        arun_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "literature_mock",
                "trigger_source": "human_workflow",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {"keywords": "fluoropolymer"},
                "reason": "测试追溯链",
            },
        )
        self.assertEqual(arun_resp.status_code, 200)
        run_id = arun_resp.json()["data"]["run_id"]

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/algorithm-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证 algorithm_run 字段存在
        self.assertIsNotNone(data["algorithm_run"])
        self.assertEqual(data["algorithm_run"]["run_id"], run_id)
        self.assertEqual(data["algorithm_run"]["trigger_source"], "human_workflow")

        # 无关联 computation 时应为 None
        self.assertIsNone(data["linked_computation"])

        # 应有审计事件
        self.assertGreater(len(data["audit_events"]), 0)
        event_types = [e["event_type"] for e in data["audit_events"]]
        self.assertIn("created", event_types)

    def test_algorithm_run_traceability_with_computation(self) -> None:
        """AlgorithmRun 追溯链：关联 computation 的情况。"""
        # 运行 computation adapter
        arun_resp = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": "computation_submit_adapter",
                "trigger_source": "human_workflow",
                "problem_spec_id": self.ps_id,
                "input_snapshot": {
                    "workflow_type": "LOCAL_STRUCTURE",
                    "smiles": "CCO",
                    "name": "test_structure",
                },
                "reason": "测试 computation 追溯链",
            },
        )
        self.assertEqual(arun_resp.status_code, 200)
        run_id = arun_resp.json()["data"]["run_id"]

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/algorithm-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证关联 computation
        if data["linked_computation"] is not None:
            self.assertIsNotNone(data["linked_computation"]["run_id"])
            self.assertIsNotNone(data["linked_computation"]["workflow_type"])
            # 验证不暴露本地路径
            comp_str = str(data["linked_computation"])
            self.assertNotIn("/home/", comp_str)

    def test_research_run_traceability(self) -> None:
        """ResearchRun 追溯链：完整聚合。"""
        # 创建 ResearchRun
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": self.autoresearch_decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
                "batch_size": 5,
            },
        )
        self.assertEqual(rr_resp.status_code, 200)
        run_id = rr_resp.json()["data"]["run_id"]

        # 启动以生成审计事件
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "追溯链测试启动"},
        )

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/research-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证 research_run 字段
        self.assertIsNotNone(data["research_run"])
        self.assertEqual(data["research_run"]["run_id"], run_id)

        # 验证 stage_runs 在 research_run 中
        self.assertGreater(len(data["research_run"]["stage_runs"]), 0)

        # 验证审计事件（至少包含 created）
        self.assertGreater(len(data["audit_events"]), 0)
        event_types = [e["event_type"] for e in data["audit_events"]]
        self.assertIn("created", event_types)

    def test_stage_run_traceability(self) -> None:
        """StageRun 追溯链：单个阶段聚合。"""
        # 创建并启动 ResearchRun
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": self.autoresearch_decision_id,
                "profile_id": "fluoropolymer",
                "max_iterations": 3,
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]

        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "StageRun 追溯链测试"},
        )

        # 获取 stage_run_id
        rr_detail = self.client.get(f"{self.base_url}/research-runs/{run_id}")
        stage_runs = rr_detail.json()["data"]["stage_runs"]
        self.assertGreater(len(stage_runs), 0)

        stage_run_id = stage_runs[0]["stage_run_id"]

        # 获取阶段追溯链
        resp = self.client.get(
            f"{self.base_url}/research-runs/{run_id}/stages/{stage_run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]

        # 验证 stage_run 字段
        self.assertIsNotNone(data["stage_run"])
        self.assertEqual(data["stage_run"]["stage_run_id"], stage_run_id)

        # 验证审计事件（至少包含 blocked_approval 或 completed）
        stage_status = data["stage_run"]["status"]
        if stage_status == "completed":
            event_types = [e["event_type"] for e in data["audit_events"]]
            self.assertIn("completed", event_types)

    def test_traceability_no_sensitive_paths(self) -> None:
        """追溯链不暴露敏感路径。"""
        # 创建 ResearchRun 并启动
        rr_resp = self.client.post(
            f"{self.base_url}/research-runs",
            json={
                "problem_spec_id": self.ps_id,
                "execution_decision_id": self.autoresearch_decision_id,
                "profile_id": "fluoropolymer",
            },
        )
        run_id = rr_resp.json()["data"]["run_id"]
        self.client.post(
            f"{self.base_url}/research-runs/{run_id}/start",
            json={"target_status": "running", "reason": "测试"},
        )

        # 获取追溯链
        resp = self.client.get(
            f"{self.base_url}/research-runs/{run_id}/traceability",
        )
        self.assertEqual(resp.status_code, 200)
        response_text = resp.text

        # 不暴露本地文件路径
        self.assertNotIn("/home/", response_text)
        self.assertNotIn("storage_uri", response_text)
        self.assertNotIn("/tmp/", response_text)
        self.assertNotIn("password", response_text.lower())
        self.assertNotIn("secret", response_text.lower())
