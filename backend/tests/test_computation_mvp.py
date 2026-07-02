"""计算智能 MVP smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.endpoints.computations import get_current_user
from app.core.config import settings
from app.main import app
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class ComputationMvpSmokeTest(ComputationTestCase):
    """覆盖计算任务、artifact、审计和优化闭环。"""

    def _create_completed_run_artifact(self) -> tuple[str, str]:
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
        self.assertEqual(result.status, "completed")
        artifacts = self.client.get(f"/api/v1/computations/{run_id}/artifacts").json()["data"]["items"]
        result_id = next(item["artifact_id"] for item in artifacts if item["artifact_type"] == "result_json")
        return run_id, result_id

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
        response_request_id = response.headers.get("x-request-id")
        self.assertTrue(response_request_id)
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
        download = self.client.get(f"/api/v1/artifacts/{result_id}/download")
        self.assertEqual(download.status_code, 200)
        download_request_id = download.headers.get("x-request-id")
        self.assertTrue(download_request_id)

        audits = self.client.get(
            "/api/v1/audit-events",
            params={"entity_id": result_id, "page_size": 20},
        ).json()["data"]["items"]
        event_types = {item["event_type"] for item in audits}
        self.assertIn("artifact.registered", event_types)
        self.assertIn("artifact.downloaded", event_types)
        download_event = next(item for item in audits if item["event_type"] == "artifact.downloaded")
        self.assertEqual(download_event["actor_user_id"], "demo_user")
        self.assertEqual(download_event["request_id"], download_request_id)
        self.assertEqual(download_event["entity_id"], result_id)
        self.assertEqual(download_event["related_ids"]["run_id"], run_id)

        create_audits = self.client.get(
            "/api/v1/audit-events",
            params={"entity_id": run_id, "event_type": "computation.created", "page_size": 20},
        ).json()["data"]["items"]
        self.assertEqual(create_audits[0]["request_id"], response_request_id)

    def test_artifact_download_works_with_auth_and_records_actor(self) -> None:
        run_id, result_id = self._create_completed_run_artifact()

        settings.auth_enabled = True
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "user_auth_download",
            "username": "auth-download",
            "role": "user",
            "status": "active",
        }
        try:
            download = self.client.get(f"/api/v1/artifacts/{result_id}/download")
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            settings.auth_enabled = False

        self.assertEqual(download.status_code, 200)
        download_request_id = download.headers.get("x-request-id")
        audits = self.client.get(
            "/api/v1/audit-events",
            params={"entity_id": result_id, "event_type": "artifact.downloaded", "page_size": 20},
        ).json()["data"]["items"]
        self.assertEqual(audits[0]["actor_user_id"], "user_auth_download")
        self.assertEqual(audits[0]["request_id"], download_request_id)
        self.assertEqual(audits[0]["related_ids"]["run_id"], run_id)

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
