"""计算智能 MVP smoke tests."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.core.config import settings
from app.infra.demo_store import demo_store
from app.infra.mongo import get_mongo_client
from app.main import app
from app.workers.computation_worker import ComputationWorker


class ComputationMvpSmokeTest(unittest.TestCase):
    """覆盖计算任务、artifact、审计和优化闭环。"""

    def setUp(self) -> None:
        self.runtime_root = Path(tempfile.mkdtemp(prefix="poly-agent-test-"))
        self.original_runtime_root = settings.runtime_root
        self.original_outputs_root = settings.outputs_root
        self.original_auth_enabled = settings.auth_enabled
        self.original_demo_store_path = demo_store.path
        settings.runtime_root = self.runtime_root
        settings.outputs_root = self.runtime_root / "outputs"
        settings.outputs_root.mkdir(parents=True, exist_ok=True)
        settings.auth_enabled = False
        demo_store.path = self.runtime_root / "demo-db.json"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        settings.runtime_root = self.original_runtime_root
        settings.outputs_root = self.original_outputs_root
        settings.auth_enabled = self.original_auth_enabled
        demo_store.path = self.original_demo_store_path
        shutil.rmtree(self.runtime_root, ignore_errors=True)
        get_mongo_client.cache_clear()

    def test_worker_artifact_and_audit_flow(self) -> None:
        response = self.client.post(
            "/api/v1/computations",
            json={
                "workflow_type": "MOCK_LASER",
                "engine": "MOCK",
                "molecule": {"smiles": "CCO", "name": "smoke"},
            },
        )
        self.assertEqual(response.status_code, 200)
        run_id = response.json()["data"]["run_id"]

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        self.assertTrue(result.claimed)
        self.assertEqual(result.status, "completed")

        detail = self.client.get(f"/api/v1/computations/{run_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["status"], "completed")

        artifacts = self.client.get(f"/api/v1/computations/{run_id}/artifacts").json()["data"]["items"]
        self.assertGreaterEqual(len(artifacts), 3)
        structure_id = next(item["artifact_id"] for item in artifacts if item["artifact_type"] == "structure_json")
        result_id = next(item["artifact_id"] for item in artifacts if item["artifact_type"] == "result_json")

        self.assertEqual(self.client.get(f"/api/v1/artifacts/{structure_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/artifacts/{structure_id}/structure").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/artifacts/{result_id}/spectrum").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/artifacts/{result_id}/download").status_code, 200)

        audits = self.client.get(
            "/api/v1/audit-events",
            params={"entity_id": result_id, "page_size": 20},
        ).json()["data"]["items"]
        event_types = {item["event_type"] for item in audits}
        self.assertIn("artifact.registered", event_types)
        self.assertIn("artifact.downloaded", event_types)

    def test_failed_run_can_retry(self) -> None:
        response = self.client.post(
            "/api/v1/computations",
            json={
                "workflow_type": "MOCK_XTB_ONLY",
                "engine": "MOCK",
                "molecule": {"smiles": "CCO", "name": "fail-smoke"},
                "mock_should_fail": True,
            },
        )
        run_id = response.json()["data"]["run_id"]
        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        self.assertEqual(result.status, "failed")

        detail = self.client.get(f"/api/v1/computations/{run_id}").json()["data"]
        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["error"]["error_code"], "MOCK_FAILURE_TRIGGERED")

        retry = self.client.post(f"/api/v1/computations/{run_id}/retry")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["data"]["status"], "queued")

    def test_campaign_chemos_import_to_observation_history(self) -> None:
        campaign = self.client.post(
            "/api/v1/optimization/campaigns",
            json={
                "name": "smoke-campaign",
                "objectives": [{"name": "gain_factor", "direction": "max"}],
            },
        ).json()["data"]
        campaign_id = campaign["campaign_id"]

        imported = self.client.post(
            f"/api/v1/optimization/campaigns/{campaign_id}/candidates:import-chemos-demo"
        )
        self.assertEqual(imported.status_code, 200)
        self.assertGreaterEqual(imported.json()["data"]["imported_count"], 1)
        first_candidate = imported.json()["data"]["items"][0]
        self.assertIn(first_candidate["descriptors"]["status"], {"available", "not_available", "failed"})

        suggestion = self.client.post(
            f"/api/v1/optimization/campaigns/{campaign_id}/suggestions",
            json={"batch_size": 1},
        ).json()["data"]["items"][0]
        submitted = self.client.post(
            f"/api/v1/optimization/suggestions/{suggestion['suggestion_id']}/submit-computation"
        ).json()["data"]

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        self.assertEqual(result.status, "completed")

        observation = self.client.post(
            f"/api/v1/optimization/computations/{submitted['run_id']}/create-observation"
        )
        self.assertEqual(observation.status_code, 200)
        self.assertIn("gain_factor", observation.json()["data"]["observation"]["values"])

        history = self.client.get(f"/api/v1/optimization/campaigns/{campaign_id}/history")
        self.assertEqual(history.status_code, 200)
        event_types = [item["event_type"] for item in history.json()["data"]["items"]]
        self.assertIn("candidate.imported", event_types)
        self.assertIn("suggestion.generated", event_types)
        self.assertIn("observation.created", event_types)


if __name__ == "__main__":
    unittest.main()
