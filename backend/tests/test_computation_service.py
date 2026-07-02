"""Computation service unit coverage."""

from __future__ import annotations

from fastapi import HTTPException

from app.infra.computation_repositories import ComputationArtifactRepository
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
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="MOCK")),
                actor_user_id="tester",
                request_id="req-bad-pair",
            )
        self.assertEqual(caught.exception.status_code, 400)

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
            ComputationCreateRequest(**computation_payload(mock_should_fail=True)),
            actor_user_id="tester",
            request_id="req-fail",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)

        self.assertTrue(result.claimed)
        self.assertEqual(detail.status, "failed")
        self.assertEqual(detail.error["error_code"], "MOCK_FAILURE_TRIGGERED")
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
            step_key="MOCK_RESULT",
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
