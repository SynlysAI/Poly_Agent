"""Computation service unit coverage."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.core.config import settings
from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import build_steps
from app.infra.computation_repositories import ComputationArtifactRepository
from app.infra.computation_repositories import ComputationRunRepository
from app.infra.computation_repositories import utc_now
from app.schemas.computation import ComputationArtifact
from app.schemas.computation import ComputationCreateRequest
from app.services.computation_service import ComputationService
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
    from ._computation_test_utils import computation_payload
except ImportError:
    from _computation_test_utils import ComputationTestCase
    from _computation_test_utils import computation_payload


class ComputationServiceTest(ComputationTestCase):
    """Cover create/cancel/retry/fail and artifact path boundaries."""

    def setUp(self) -> None:
        super().setUp()
        self.service = ComputationService()

    def test_create_run_records_request_id_in_audit(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-service-create",
        )

        audits = self.service.list_audit_events(
            entity_type="computation_run",
            entity_id=created.run_id,
            event_type="computation.created",
            page=1,
            page_size=10,
        )
        self.assertEqual(created.status, "queued")
        self.assertEqual(audits.items[0].request_id, "req-service-create")

    def test_create_run_rejects_unsupported_workflow_engine_pair(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.service.create_run(
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="LOCAL")),
                actor_user_id="tester",
                request_id="req-bad-pair",
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_list_runs_reads_legacy_mock_records(self) -> None:
        now = utc_now()
        ComputationRunRepository.save(
            "run_id",
            {
                "run_id": "comp_legacy_mock",
                "retry_of_run_id": None,
                "workflow_type": "MOCK_LASER",
                "engine": "MOCK",
                "status": "completed",
                "molecule": {"smiles": "CCO", "name": "legacy mock"},
                "parameters": {},
                "resources": {},
                "external_refs": {},
                "steps": [
                    {
                        "step_key": "MOCK_RESULT",
                        "label": "Mock result",
                        "status": "completed",
                        "started_at": now,
                        "finished_at": now,
                    }
                ],
                "artifact_ids": [],
                "result_summary": {},
                "error": None,
                "created_by": "tester",
                "created_at": now,
                "updated_at": now,
                "started_at": now,
                "finished_at": now,
                "source": None,
                "campaign_id": None,
                "suggestion_id": None,
            },
        )

        data = self.service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=20,
            actor_user_id="tester",
            is_admin=False,
        )

        self.assertEqual(data.total, 1)
        self.assertEqual(data.items[0].workflow_type, "MOCK_LASER")
        self.assertEqual(data.items[0].engine, "MOCK")

    def test_retry_legacy_mock_run_reports_clear_unsupported_reason(self) -> None:
        now = utc_now()
        ComputationRunRepository.save(
            "run_id",
            {
                "run_id": "comp_legacy_mock_failed",
                "retry_of_run_id": None,
                "workflow_type": "MOCK_XTB_ONLY",
                "engine": "MOCK",
                "status": "failed",
                "molecule": {"smiles": "CCO", "name": "legacy failed"},
                "parameters": {},
                "resources": {},
                "external_refs": {},
                "steps": [],
                "artifact_ids": [],
                "result_summary": {},
                "error": {"error_code": "MOCK_FAILURE_TRIGGERED", "message": "legacy failure", "retryable": True},
                "created_by": "tester",
                "created_at": now,
                "updated_at": now,
                "started_at": now,
                "finished_at": now,
                "source": None,
                "campaign_id": None,
                "suggestion_id": None,
            },
        )

        with self.assertRaises(HTTPException) as caught:
            self.service.retry_run("comp_legacy_mock_failed", actor_user_id="tester", request_id="req-legacy-retry")

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("已下线的历史 MOCK", str(caught.exception.detail))

    def test_cancel_run_moves_non_terminal_run_to_cancelled(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-cancel",
        )

        cancelled = self.service.cancel_run(
            created.run_id,
            actor_user_id="tester",
            request_id="req-cancel",
        )

        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(cancelled.error["error_code"], "USER_CANCELLED")

    def test_retry_run_creates_new_run_for_cancelled_run(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-retry",
        )
        self.service.cancel_run(created.run_id, actor_user_id="tester", request_id="req-retry")

        retry = self.service.retry_run(created.run_id, actor_user_id="tester", request_id="req-retry")
        retry_detail = self.service.get_run(retry.run_id)

        self.assertNotEqual(retry.run_id, created.run_id)
        self.assertEqual(retry_detail.retry_of_run_id, created.run_id)
        self.assertEqual(retry_detail.status, "queued")

    def test_failed_run_contains_retryable_error(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
            actor_user_id="tester",
            request_id="req-fail",
        )

        with patch("app.computation_adapters.local_xtb.shutil.which", return_value=None):
            result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)

        self.assertTrue(result.claimed)
        self.assertEqual(detail.status, "failed")
        self.assertIn(detail.error["error_code"], {"XTB_NOT_AVAILABLE", "CREST_NOT_AVAILABLE"})
        self.assertTrue(detail.error["retryable"])

    def test_resolve_artifact_path_rejects_path_outside_outputs_root(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-path",
        )
        outside_path = self.runtime_root / "outside.txt"
        outside_path.write_text("outside", encoding="utf-8")
        artifact = ComputationArtifact(
            artifact_id="art_outside",
            run_id=created.run_id,
            step_key="LOCAL_GENERATE_STRUCTURE",
            artifact_type="log_text",
            name="outside.txt",
            storage_uri=str(outside_path),
            mime_type="text/plain",
            size_bytes=outside_path.stat().st_size,
            checksum_sha256="0" * 64,
            created_at=self.service.get_run(created.run_id).created_at,
        )
        ComputationArtifactRepository.save("artifact_id", artifact.model_dump(mode="python"))

        with self.assertRaises(HTTPException) as caught:
            self.service.resolve_artifact_path(artifact)
        self.assertEqual(caught.exception.status_code, 400)

    def test_binary_input_file_preview_reports_unsupported(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-xlsx-preview",
        )
        path = settings.outputs_root / "inputs" / "table.xlsx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"PK\x03\x04binary-xlsx")
        artifact = ComputationArtifact(
            artifact_id="art_xlsx_input",
            run_id=created.run_id,
            owner_type="computation_run",
            owner_id=created.run_id,
            step_key="INPUT",
            artifact_type="input_file",
            name="table.xlsx",
            storage_uri=str(path),
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=path.stat().st_size,
            checksum_sha256="0" * 64,
            created_at=self.service.get_run(created.run_id).created_at,
        )
        ComputationArtifactRepository.save("artifact_id", artifact.model_dump(mode="python"))

        with self.assertRaises(HTTPException) as caught:
            self.service.preview_artifact(artifact.artifact_id)
        self.assertEqual(caught.exception.status_code, 400)

    def test_user_scoped_run_and_artifact_access_denies_other_owner(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="user-a",
            request_id="req-owner",
        )
        ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        artifacts = self.service.list_artifacts(created.run_id, actor_user_id="user-a", is_admin=False)

        runs_for_a = self.service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=20,
            actor_user_id="user-a",
            is_admin=False,
        )
        runs_for_b = self.service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=20,
            actor_user_id="user-b",
            is_admin=False,
        )

        self.assertEqual(runs_for_a.total, 1)
        self.assertEqual(runs_for_b.total, 0)
        with self.assertRaises(HTTPException) as run_denied:
            self.service.get_run(created.run_id, actor_user_id="user-b", is_admin=False)
        with self.assertRaises(HTTPException) as artifact_denied:
            self.service.get_artifact(artifacts[0].artifact_id, actor_user_id="user-b", is_admin=False)
        self.assertEqual(run_denied.exception.status_code, 403)
        self.assertEqual(artifact_denied.exception.status_code, 403)

    def test_admin_can_list_all_user_runs(self) -> None:
        self.service.create_run(
            ComputationCreateRequest(**computation_payload(molecule={"smiles": "CCO", "name": "a"})),
            actor_user_id="user-a",
            request_id="req-a",
        )
        self.service.create_run(
            ComputationCreateRequest(**computation_payload(molecule={"smiles": "CCC", "name": "b"})),
            actor_user_id="user-b",
            request_id="req-b",
        )

        data = self.service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=20,
            actor_user_id="admin",
            is_admin=True,
        )

        self.assertEqual(data.total, 2)

    def test_worker_records_heartbeat_and_does_not_overwrite_cancelled_run(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-worker-cancel",
        )
        original_get_adapter = __import__("app.workers.computation_worker", fromlist=["get_adapter"]).get_adapter

        class CancellingAdapter:
            step_labels = {"FAKE_WAIT": "Fake wait"}

            def validate_input(self, context: AdapterContext) -> None:
                return None

            def run(self, context: AdapterContext) -> AdapterRunResult:
                ComputationService().heartbeat_run(context.run.run_id, worker_id=context.worker_id, now=utc_now())
                ComputationService().cancel_run(
                    context.run.run_id,
                    actor_user_id="tester",
                    request_id="req-worker-cancel",
                )
                return AdapterRunResult(
                    status="completed",
                    steps=build_steps(
                        self.step_labels,
                        status="completed",
                        started_at=context.started_at,
                        finished_at=utc_now(),
                    ),
                    result_summary={"ok": True},
                )

            def collect_artifacts(self, context: AdapterContext, result: AdapterRunResult) -> list:
                return []

            def parse_result(self, context: AdapterContext, result: AdapterRunResult) -> dict:
                return result.result_summary

        import app.workers.computation_worker as worker_module

        worker_module.get_adapter = lambda workflow_type, engine: CancellingAdapter()
        try:
            result = ComputationWorker(worker_id="worker-cancel").acquire_and_run_one()
        finally:
            worker_module.get_adapter = original_get_adapter
        detail = self.service.get_run(created.run_id)

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(detail.status, "cancelled")
        self.assertEqual(detail.error["error_code"], "USER_CANCELLED")
        self.assertEqual(detail.external_refs["worker_id"], "worker-cancel")
        self.assertIsNotNone(detail.external_refs["claimed_at"])
        self.assertIsNotNone(detail.external_refs["heartbeat_at"])

    def test_stale_running_run_can_be_marked_failed(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-stale",
        )
        import datetime as dt
        past = utc_now() - dt.timedelta(seconds=120)
        ComputationRunRepository.update_fields(
            created.run_id,
            {
                "status": "running",
                "external_refs.worker_id": "worker-dead",
                "external_refs.claimed_at": past,
                "external_refs.heartbeat_at": past,
            },
        )

        reclaimed = self.service.fail_stale_running_runs(actor_user_id="worker-monitor")
        detail = self.service.get_run(created.run_id)

        self.assertEqual(reclaimed, [created.run_id])
        self.assertEqual(detail.status, "failed")
        self.assertEqual(detail.error["error_code"], "WORKER_HEARTBEAT_STALE")

    def test_admin_can_force_fail_a_running_run(self) -> None:
        """Admins can force-fail a specific stuck running run."""
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-force-fail",
        )
        now = utc_now()
        ComputationRunRepository.update_fields(
            created.run_id,
            {
                "status": "running",
                "external_refs.worker_id": "worker-stuck",
                "external_refs.claimed_at": now,
                "external_refs.heartbeat_at": now,
            },
        )
        result = self.service.force_fail_run(
            created.run_id,
            actor_user_id="admin",
            is_admin=True,
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["error_code"], "ADMIN_FORCE_FAILED")
        self.assertTrue(result.error["retryable"])

    def test_wallclock_expired_run_marked_failed_by_reaper(self) -> None:
        """Runs exceeding max_wallclock_seconds * safety_factor should be failed."""
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-wallclock",
        )
        import datetime as dt
        past = utc_now() - dt.timedelta(hours=2)
        ComputationRunRepository.update_fields(
            created.run_id,
            {
                "status": "running",
                "started_at": past,
                "external_refs.worker_id": "worker-slow",
                "external_refs.claimed_at": past,
                "external_refs.heartbeat_at": utc_now(),
            },
        )
        failed = self.service.fail_stale_running_runs(actor_user_id="test-reaper")
        detail = self.service.get_run(created.run_id)
        self.assertEqual(detail.status, "failed")
        self.assertIn(created.run_id, failed)

    def test_stale_reaper_fixes_steps(self) -> None:
        """When stale reaper fails a run, 'running'/'queued' steps become 'failed'."""
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload()),
            actor_user_id="tester",
            request_id="req-stale-steps",
        )
        import datetime as dt
        past = utc_now() - dt.timedelta(seconds=120)
        ComputationRunRepository.update_fields(
            created.run_id,
            {
                "status": "running",
                "steps": [
                    {"step_key": "step1", "label": "first", "status": "running", "started_at": str(past)},
                    {"step_key": "step2", "label": "second", "status": "queued"},
                ],
                "external_refs.worker_id": "worker-dead",
                "external_refs.claimed_at": past,
                "external_refs.heartbeat_at": past,
            },
        )
        self.service.fail_stale_running_runs(actor_user_id="test-reaper")
        detail = self.service.get_run(created.run_id)
        self.assertEqual(detail.status, "failed")
        for step in detail.steps:
            self.assertEqual(step.status, "failed", f"Step {step.step_key} should be failed")
