"""计算智能 MVP smoke tests."""

from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.core.config import settings
from app.schemas.computation import ComputationCreateRequest
from app.schemas.optimization import CampaignCreateRequest
from app.schemas.optimization import CandidateImportRequest
from app.schemas.optimization import ObservationCreateRequest
from app.schemas.optimization import SuggestionCreateRequest
from app.services.computation_service import ComputationService
from app.services.optimization_service import OptimizationService
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class ComputationMvpSmokeTest(ComputationTestCase):
    """覆盖计算任务、artifact、审计和优化闭环。"""

    def _run_local_structure_worker(self) -> object:
        fake_bin = self.runtime_root / "bin"
        fake_bin.mkdir(exist_ok=True)
        fake_obabel = fake_bin / "obabel"
        self._write_fake_obabel(fake_obabel)
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                return ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

    def test_worker_artifact_and_audit_flow(self) -> None:
        service = ComputationService()
        created = service.create_run(
            ComputationCreateRequest(
                workflow_type="LOCAL_STRUCTURE",
                engine="LOCAL",
                molecule={"smiles": "CCO", "name": "smoke"},
            ),
            actor_user_id="demo_user",
            request_id="req-service-create",
        )
        run_id = created.run_id

        result = self._run_local_structure_worker()
        self.assertTrue(result.claimed)
        self.assertEqual(result.status, "completed")

        detail = service.get_run(run_id)
        self.assertEqual(detail.status, "completed")

        artifacts = service.list_artifacts(run_id)
        self.assertGreaterEqual(len(artifacts), 3)
        structure = next(item for item in artifacts if item.artifact_type == "structure_json")

        self.assertEqual(service.get_artifact(structure.artifact_id).artifact_id, structure.artifact_id)
        self.assertEqual(service.get_artifact_structure(structure.artifact_id).structure["source"], "openbabel")
        self.assertEqual(service.preview_artifact(structure.artifact_id).preview["source"], "openbabel")
        service.audit_artifact_download(structure, actor_user_id="demo_user", request_id="req-download")

        audits = service.list_audit_events(
            entity_type=None,
            entity_id=structure.artifact_id,
            event_type=None,
            page=1,
            page_size=20,
        ).items
        event_types = {item.event_type for item in audits}
        self.assertIn("artifact.registered", event_types)
        self.assertIn("artifact.downloaded", event_types)
        download_event = next(item for item in audits if item.event_type == "artifact.downloaded")
        self.assertEqual(download_event.actor_user_id, "demo_user")
        self.assertEqual(download_event.request_id, "req-download")
        self.assertEqual(download_event.entity_id, structure.artifact_id)
        self.assertEqual(download_event.related_ids["run_id"], run_id)

        create_audits = service.list_audit_events(
            entity_type=None,
            entity_id=run_id,
            event_type="computation.created",
            page=1,
            page_size=20,
        ).items
        self.assertEqual(create_audits[0].request_id, "req-service-create")

    def test_artifact_download_works_with_auth_and_records_actor(self) -> None:
        service = ComputationService()
        created = service.create_run(
            ComputationCreateRequest(
                workflow_type="LOCAL_STRUCTURE",
                engine="LOCAL",
                molecule={"smiles": "CCO", "name": "auth-owned"},
            ),
            actor_user_id="user_auth_download",
            request_id="req-auth-create",
        )
        self._run_local_structure_worker()
        artifacts = service.list_artifacts(created.run_id, actor_user_id="user_auth_download", is_admin=False)
        result_artifact = next(item for item in artifacts if item.artifact_type == "structure_json")
        service.audit_artifact_download(
            result_artifact,
            actor_user_id="user_auth_download",
            request_id="req-auth-download",
        )

        audits = service.list_audit_events(
            entity_type=None,
            entity_id=result_artifact.artifact_id,
            event_type="artifact.downloaded",
            page=1,
            page_size=20,
        ).items
        self.assertEqual(audits[0].actor_user_id, "user_auth_download")
        self.assertEqual(audits[0].request_id, "req-auth-download")
        self.assertEqual(audits[0].related_ids["run_id"], created.run_id)

    def test_artifact_api_does_not_expose_storage_uri_or_static_file(self) -> None:
        service = ComputationService()
        created = service.create_run(
            ComputationCreateRequest(
                workflow_type="LOCAL_STRUCTURE",
                engine="LOCAL",
                molecule={"smiles": "CCO", "name": "public-artifact"},
            ),
            actor_user_id="artifact_owner",
            request_id="req-artifact-public",
        )
        self._run_local_structure_worker()
        artifacts = service.list_artifacts(created.run_id, actor_user_id="artifact_owner", is_admin=False)
        artifact = next(item for item in artifacts if item.artifact_type == "structure_json")

        list_resp = self.client.get(f"/api/v1/computations/{created.run_id}/artifacts")
        detail_resp = self.client.get(f"/api/v1/artifacts/{artifact.artifact_id}")
        preview_resp = self.client.get(f"/api/v1/artifacts/{artifact.artifact_id}/preview")

        for response in (list_resp, detail_resp, preview_resp):
            self.assertEqual(response.status_code, 200)
            response_text = response.text
            self.assertNotIn("storage_uri", response_text)
            self.assertNotIn(str(settings.outputs_root), response_text)
            self.assertIn("/api/v1/artifacts/", response_text)
            self.assertIn("/download", response_text)

        artifact_path = service.resolve_artifact_path(artifact)
        relative_path = artifact_path.relative_to(settings.outputs_root)
        static_resp = self.client.get(f"/static/outputs/{relative_path.as_posix()}")
        self.assertEqual(static_resp.status_code, 404)

    def test_auth_enabled_scopes_runs_artifacts_campaigns_and_audit(self) -> None:
        computation_service = ComputationService()
        optimization_service = OptimizationService()
        created = computation_service.create_run(
            ComputationCreateRequest(
                workflow_type="LOCAL_STRUCTURE",
                engine="LOCAL",
                molecule={"smiles": "CCO", "name": "owned"},
            ),
            actor_user_id="user-a",
            request_id="req-owned-run",
        )
        campaign = optimization_service.create_campaign(
            CampaignCreateRequest(
                name="owned-campaign",
                objectives=[{"name": "gain_factor", "direction": "max"}],
            ),
            actor_user_id="user-a",
            request_id="req-owned-campaign",
        )
        run_id = created.run_id
        campaign_id = campaign.campaign_id
        self._run_local_structure_worker()

        artifacts = computation_service.list_artifacts(run_id, actor_user_id="user-a", is_admin=False)
        artifact_id = artifacts[0].artifact_id

        list_runs = computation_service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=20,
            actor_user_id="user-b",
            is_admin=False,
        )
        list_campaigns = optimization_service.list_campaigns(
            page=1,
            page_size=20,
            actor_user_id="user-b",
            is_admin=False,
        )
        audits = computation_service.list_audit_events(
            entity_type=None,
            entity_id=None,
            event_type=None,
            page=1,
            page_size=50,
            actor_user_id="user-b",
            is_admin=False,
        )

        self.assertEqual(list_runs.total, 0)
        with self.assertRaises(HTTPException) as run_denied:
            computation_service.get_run(run_id, actor_user_id="user-b", is_admin=False)
        with self.assertRaises(HTTPException) as artifact_denied:
            computation_service.get_artifact(artifact_id, actor_user_id="user-b", is_admin=False)
        with self.assertRaises(HTTPException) as campaign_denied:
            optimization_service.get_detail(campaign_id, actor_user_id="user-b", is_admin=False)
        self.assertEqual(run_denied.exception.status_code, 403)
        self.assertEqual(artifact_denied.exception.status_code, 403)
        self.assertEqual(campaign_denied.exception.status_code, 403)
        self.assertEqual(list_campaigns.total, 0)
        self.assertEqual(audits.items, [])

        admin_runs = computation_service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=20,
            actor_user_id="admin",
            is_admin=True,
        )
        admin_campaign = optimization_service.get_detail(campaign_id, actor_user_id="admin", is_admin=True)
        admin_audits = computation_service.list_audit_events(
            entity_type=None,
            entity_id=None,
            event_type=None,
            page=1,
            page_size=50,
            actor_user_id="admin",
            is_admin=True,
        )
        self.assertEqual(admin_runs.total, 1)
        self.assertEqual(admin_campaign.campaign.campaign_id, campaign_id)
        self.assertGreater(len(admin_audits.items), 0)

    def test_failed_run_can_retry(self) -> None:
        service = ComputationService()
        created = service.create_run(
            ComputationCreateRequest(
                workflow_type="LOCAL_XTB",
                engine="XTB",
                molecule={"smiles": "CCO", "name": "fail-smoke"},
            ),
            actor_user_id="demo_user",
            request_id="req-failed-run",
        )
        run_id = created.run_id
        with patch("app.computation_adapters.local_xtb.shutil.which", return_value=None):
            result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        self.assertEqual(result.status, "failed")

        detail = service.get_run(run_id)
        self.assertEqual(detail.status, "failed")
        self.assertIn(detail.error["error_code"], {"XTB_NOT_AVAILABLE", "CREST_NOT_AVAILABLE"})

        retry = service.retry_run(run_id, actor_user_id="demo_user", request_id="req-retry")
        self.assertEqual(retry.status, "queued")

    def test_campaign_candidate_import_to_observation_history(self) -> None:
        service = OptimizationService()
        campaign = service.create_campaign(
            CampaignCreateRequest(
                name="smoke-campaign",
                objectives=[{"name": "gain_factor", "direction": "max"}],
            ),
            actor_user_id="demo_user",
            request_id="req-campaign-create",
        )
        campaign_id = campaign.campaign_id

        imported = service.import_candidates(
            campaign_id,
            CandidateImportRequest(
                candidates=[
                    {
                        "candidate_key": "cand-ethanol",
                        "smiles": "CCO",
                        "parameters": {"solvent": "ETHANOL"},
                        "metadata": {"source": "smoke-test"},
                    }
                ]
            ),
            actor_user_id="demo_user",
            request_id="req-candidate-import",
        )
        self.assertGreaterEqual(imported.imported_count, 1)
        first_candidate = imported.items[0]
        self.assertEqual(first_candidate.candidate_key, "cand-ethanol")

        suggestion = service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="demo_user",
            request_id="req-suggestion-create",
        ).items[0]

        observation = service.create_observation(
            campaign_id,
            ObservationCreateRequest(
                candidate_id=suggestion.candidate_id,
                suggestion_id=suggestion.suggestion_id,
                values={"gain_factor": 1.25},
                source_type="manual",
            ),
            actor_user_id="demo_user",
            request_id="req-observation-create",
        )
        self.assertIn("gain_factor", observation.values)

        history = service.get_history(campaign_id, actor_user_id="demo_user", is_admin=False)
        event_types = [item.event_type for item in history.items]
        self.assertIn("candidate.imported", event_types)
        self.assertIn("suggestion.generated", event_types)
        self.assertIn("observation.created", event_types)

    def _write_fake_obabel(self, path: Path) -> None:
        path.write_text(
            """#!/usr/bin/env python3
import sys
from pathlib import Path

out = Path(sys.argv[sys.argv.index("-O") + 1])
if out.suffix == ".xyz":
    out.write_text("2\\nfake openbabel\\nC 0.0 0.0 0.0\\nO 1.2 0.0 0.0\\n", encoding="utf-8")
elif out.suffix == ".sdf":
    out.write_text("fake sdf\\n  OpenBabel\\n\\nM  END\\n$$$$\\n", encoding="utf-8")
else:
    out.write_text("", encoding="utf-8")
sys.stdout.write("fake obabel ok\\n")
""",
            encoding="utf-8",
        )
        path.chmod(0o755)
