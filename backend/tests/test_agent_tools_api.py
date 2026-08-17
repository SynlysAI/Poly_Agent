"""Agent Tool 派生目录与策略接口测试。"""

from __future__ import annotations

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmRegistryRepository,
    AlgorithmRunRepository,
    AlgorithmVersionRepository,
)
from app.main import app


class AgentToolsApiTest(ComputationTestCase):
    """覆盖算法工具的派生、权限和策略治理。"""

    def setUp(self) -> None:
        super().setUp()
        self.base_url = "/api/v1/agent-tools"
        self._save_algorithm(
            "vertical-demo",
            visibility="public",
            active_version_id="ver-v1",
            version="1.0.0",
            version_status="active",
        )
        self._save_algorithm(
            "private-vertical",
            visibility="private",
            owner="owner-1",
            active_version_id="ver-private",
            version="1.0.0",
            version_status="active",
        )
        self._save_algorithm(
            "frozen-vertical",
            visibility="public",
            active_version_id="ver-frozen",
            version="1.0.0",
            version_status="frozen",
        )

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _save_algorithm(
        algorithm_id: str,
        *,
        visibility: str,
        active_version_id: str,
        version: str,
        version_status: str,
        owner: str | None = None,
    ) -> None:
        now = utc_now()
        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": algorithm_id,
                "name": algorithm_id,
                "type": "predictor",
                "algorithm_family": "vertical_prediction",
                "material_scope": ["universal"],
                "task_scope": ["COMPUTE_PREDICT"],
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"prediction": "number"}, "required": ["prediction"]},
                "input_assets": [],
                "output_assets": [],
                "trigger_modes": ["human_workflow"],
                "version": version,
                "owner": owner,
                "status": "active",
                "description": "test algorithm",
                "active_version_id": active_version_id,
                "source": "uploaded_package",
                "source_kind": "uploaded_package",
                "deployment_status": "active",
                "integration_kind": "real",
                "capability_group": "vertical_algorithm",
                "visibility": visibility,
                "created_at": now,
                "updated_at": now,
            },
        )
        AlgorithmVersionRepository.save(
            "version_id",
            {
                "version_id": active_version_id,
                "algorithm_id": algorithm_id,
                "name": algorithm_id,
                "version": version,
                "status": version_status,
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"prediction": "number"}, "required": ["prediction"]},
                "input_assets": [],
                "output_assets": [],
                "resource_assets": [],
                "deployment": {"backend": "local_sandbox_runtime", "health": "ready"},
                "created_by": owner or "owner-1",
                "created_at": now,
                "updated_at": now,
            },
        )

    def test_lists_only_active_and_authorized_vertical_tools(self) -> None:
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["data"]["items"]
        self.assertEqual(
            [item["tool_id"] for item in items],
            ["algorithm:private-vertical", "algorithm:vertical-demo"],
        )
        self.assertEqual(items[0]["version"], "1.0.0")
        self.assertEqual(items[0]["input_schema"]["required"], ["smiles"])
        demo = next(item for item in items if item["algorithm_id"] == "vertical-demo")
        self.assertTrue(demo["function_name"].startswith("algorithm_vertical"))
        self.assertEqual(demo["input_json_schema"]["additionalProperties"], False)
        self.assertEqual(demo["input_json_schema"]["properties"]["smiles"]["type"], "string")
        self.assertRegex(demo["schema_digest"], r"^[0-9a-f]{16}$")
        self.assertIn("fields", demo["presentation"])
        self.assertIsNone(demo["recent_success_rate"])
        self.assertEqual(demo["recent_run_count"], 0)

    def test_agent_tool_derives_model_proposal_from_active_version(self) -> None:
        AlgorithmVersionRepository.update_fields(
            "ver-v1",
            {
                "model_proposal": {"smiles": "CCC"},
                "contract": {"sample_input": {"smiles": "CCO"}},
            },
        )
        response = self.client.get(self.base_url)
        demo = next(
            item for item in response.json()["data"]["items"]
            if item["algorithm_id"] == "vertical-demo"
        )
        self.assertEqual(demo["model_proposal"], {"smiles": "CCC"})

    def test_agent_tool_does_not_derive_model_proposal_from_sample_input(self) -> None:
        """工具目录只暴露显式参数模板，不能把 sample_input 当作模板。"""
        AlgorithmVersionRepository.update_fields(
            "ver-v1",
            {"contract": {"sample_input": {"smiles": "CCO"}}},
        )
        response = self.client.get(self.base_url)
        demo = next(
            item for item in response.json()["data"]["items"]
            if item["algorithm_id"] == "vertical-demo"
        )
        self.assertIsNone(demo["model_proposal"])

    def test_recent_success_rate_is_derived_from_terminal_algorithm_runs(self) -> None:
        """工具目录应只统计最近的 completed/failed/cancelled 运行。"""
        now = utc_now()
        base = {
            "algorithm_id": "vertical-demo",
            "trigger_source": "human_workflow",
            "input_snapshot": {},
            "output_summary": {},
            "artifact_refs": [],
            "error": None,
            "created_by": "tester",
            "created_at": now,
            "updated_at": now,
        }
        for index, status in enumerate(["completed", "failed", "completed", "cancelled", "queued"]):
            AlgorithmRunRepository.save(
                "run_id",
                {
                    **base,
                    "run_id": f"ar-recent-{index}",
                    "status": status,
                },
            )

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, 200, response.text)
        demo = next(
            item for item in response.json()["data"]["items"]
            if item["algorithm_id"] == "vertical-demo"
        )
        self.assertEqual(demo["recent_run_count"], 4)
        self.assertAlmostEqual(demo["recent_success_rate"], 0.5)

    def test_private_tool_is_visible_to_owner_but_not_other_user(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "owner-1", "username": "owner", "role": "user", "status": "active"
        }
        owner_items = self.client.get(self.base_url).json()["data"]["items"]
        self.assertEqual({item["algorithm_id"] for item in owner_items}, {"vertical-demo", "private-vertical"})

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "other-1", "username": "other", "role": "user", "status": "active"
        }
        other_items = self.client.get(self.base_url).json()["data"]["items"]
        self.assertEqual({item["algorithm_id"] for item in other_items}, {"vertical-demo"})

    def test_admin_can_disable_tool_and_sync_reports_disabled(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin-1", "username": "admin", "role": "admin", "status": "active"
        }
        response = self.client.patch(
            f"{self.base_url}/vertical-demo/policy",
            json={"enabled": False, "allowed_roles": ["admin"], "requires_confirmation": False},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["data"]["policy"]["enabled"])
        self.assertFalse(response.json()["data"]["requires_confirmation"])
        sync = self.client.post(f"{self.base_url}/sync")
        self.assertEqual(sync.status_code, 200, sync.text)
        self.assertGreaterEqual(sync.json()["data"]["disabled"], 1)
        remaining = self.client.get(self.base_url).json()["data"]["items"]
        self.assertEqual([item["algorithm_id"] for item in remaining], ["private-vertical"])

    def test_non_admin_cannot_update_policy_and_registry_exposes_unavailable_reason(self) -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "user-1", "username": "user", "role": "user", "status": "active"
        }
        forbidden = self.client.patch(f"{self.base_url}/vertical-demo/policy", json={"enabled": False})
        self.assertEqual(forbidden.status_code, 403)

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin-1", "username": "admin", "role": "admin", "status": "active"
        }
        registry = self.client.get(f"{self.base_url}/registry")
        self.assertEqual(registry.status_code, 200, registry.text)
        frozen = next(item for item in registry.json()["data"]["items"] if item["algorithm_id"] == "frozen-vertical")
        self.assertEqual(frozen["phase"], "unavailable")
        self.assertIn("版本状态", frozen["unavailable_reason"])
        cannot_enable = self.client.patch(
            f"{self.base_url}/frozen-vertical/policy",
            json={"enabled": True},
        )
        self.assertEqual(cannot_enable.status_code, 409)
