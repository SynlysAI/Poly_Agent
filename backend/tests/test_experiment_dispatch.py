"""实验方案转发台服务与 API 测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import settings
from app.infra.demo_store import demo_store
from app.infra.experiment_dispatch_repositories import ExperimentDispatchRepository
from app.infra.research_engine_repositories import AlgorithmRunRepository
from app.main import app
from app.schemas.experiment_dispatch import ExperimentDispatchBuildRequest
from app.services.experiment_dispatch_service import experiment_dispatch_service


class ExperimentDispatchTest(TestCase):
    def setUp(self) -> None:
        self.original_require_mongodb = settings.require_mongodb
        self.original_auth_enabled = settings.auth_enabled
        self.original_demo_store_path = demo_store.path
        settings.require_mongodb = False
        settings.auth_enabled = False
        demo_store.path = Path(self.id().replace(".", "_") + ".json").resolve()
        self.mongo_unavailable = patch("app.infra.computation_repositories._mongo_unavailable", True)
        self.mongo_unavailable.start()
        self.run_id = "arun_dispatch_test"
        AlgorithmRunRepository.save(
            "run_id",
            {
                "run_id": self.run_id,
                "algorithm_id": "pi_predictor",
                "algorithm_version_id": "aiv_pi_1",
                "status": "completed",
                "created_by": "demo_user",
                "input_snapshot": {"diamine": "A"},
                "output_summary": {"difficulty_score": 50, "recommended_parameters": {"dianhydride": "B"}},
                "finished_at": None,
            },
        )

    def tearDown(self) -> None:
        self.mongo_unavailable.stop()
        settings.require_mongodb = self.original_require_mongodb
        settings.auth_enabled = self.original_auth_enabled
        demo_store.path.unlink(missing_ok=True)
        demo_store.path = self.original_demo_store_path

    def request(self, **overrides):
        payload = {
            "template_id": "pi_synthesis",
            "experiment_name": "PI test",
            "parameter_overrides": {"solvent": "NMP"},
        }
        payload.update(overrides)
        return ExperimentDispatchBuildRequest(**payload)

    def test_preview_maps_parameters_and_selects_variant(self) -> None:
        manifest = experiment_dispatch_service.preview(self.run_id, self.request(), actor_user_id="demo_user")
        self.assertEqual(manifest.status, "preview")
        self.assertEqual(manifest.template.variant_id, "P05")
        self.assertEqual(manifest.parameters["dianhydride"], "B")
        self.assertEqual(manifest.parameters["solvent"], "NMP")
        self.assertEqual(manifest.execution_inputs["instruction_set_path"], "ChASM/PI-P05.chasm")
        _, total = ExperimentDispatchRepository.list_dispatches(created_by="demo_user")
        self.assertEqual(total, 0)

    def test_score_boundaries_select_expected_variants(self) -> None:
        for score, expected in ((0, "P01"), (11, "P01"), (12, "P02"), (100, "P09")):
            run = AlgorithmRunRepository.find_one({"run_id": self.run_id})
            run["output_summary"]["difficulty_score"] = score
            AlgorithmRunRepository.save("run_id", run)
            manifest = experiment_dispatch_service.preview(self.run_id, self.request(), actor_user_id="demo_user")
            self.assertEqual(manifest.template.variant_id, expected)

    def test_missing_score_is_rejected(self) -> None:
        run = AlgorithmRunRepository.find_one({"run_id": self.run_id})
        run["output_summary"] = {}
        AlgorithmRunRepository.save("run_id", run)
        with self.assertRaises(HTTPException) as ctx:
            experiment_dispatch_service.preview(self.run_id, self.request(), actor_user_id="demo_user")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_unknown_parameter_override_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            experiment_dispatch_service.preview(
                self.run_id,
                self.request(parameter_overrides={"not_in_template": 1}),
                actor_user_id="demo_user",
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_json_pointer_unescapes_reserved_characters(self) -> None:
        value = experiment_dispatch_service.resolve_json_pointer({"a/b": {"x~y": 7}}, "/a~1b/x~0y")
        self.assertEqual(value, 7)

    def test_other_user_cannot_access_run(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            experiment_dispatch_service.preview(self.run_id, self.request(), actor_user_id="user-b")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_non_completed_run_is_rejected(self) -> None:
        run = AlgorithmRunRepository.find_one({"run_id": self.run_id})
        run["status"] = "running"
        AlgorithmRunRepository.save("run_id", run)
        with self.assertRaises(HTTPException) as ctx:
            experiment_dispatch_service.preview(self.run_id, self.request(), actor_user_id="demo_user")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_api_create_detail_and_export(self) -> None:
        with TestClient(app) as client:
            templates = client.get("/api/v1/experiment-templates")
            self.assertEqual(templates.status_code, 200)
            self.assertEqual(templates.json()["data"]["items"][0]["template_id"], "pi_synthesis")

            response = client.post(
                f"/api/v1/algorithm-runs/{self.run_id}/experiment-dispatches",
                json=self.request().model_dump(mode="json"),
            )
            self.assertEqual(response.status_code, 200)
            dispatch_id = response.json()["data"]["dispatch_id"]
            self.assertTrue(dispatch_id.startswith("edsp_"))

            detail = client.get(f"/api/v1/experiment-dispatches/{dispatch_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["data"]["status"], "prepared")

            listing = client.get("/api/v1/experiment-dispatches?page=1&page_size=10")
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json()["data"]["total"], 1)

            exported = client.get(f"/api/v1/experiment-dispatches/{dispatch_id}/export")
            self.assertEqual(exported.status_code, 200)
            self.assertIn("experiment_dispatch.v1", exported.text)
            self.assertIn("Content-Disposition", exported.headers)


if __name__ == "__main__":
    import unittest

    unittest.main()
