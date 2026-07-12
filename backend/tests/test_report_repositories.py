"""Report repository tests."""

from __future__ import annotations

import sys
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.infra import computation_repositories
from app.infra.demo_store import demo_store
from app.infra.report_repositories import ReportArtifactRepository, ReportJobRepository
from app.schemas.reports import ReportArtifact, ReportJob, ReportRetryRequest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_doc(**overrides) -> dict:
    now = _now()
    doc = {
        "report_id": "report_test_001",
        "subject_type": "algorithm_run",
        "subject_id": "ar_test_001",
        "problem_spec_id": "ps_test_001",
        "campaign_id": None,
        "template_id": "algorithm_run_summary_zh",
        "language": "zh-CN",
        "formats": ["markdown", "latex", "pdf"],
        "status": "queued",
        "stage": "context",
        "progress": 0,
        "input_snapshot": {"scope": {"include_audit_events": True}},
        "context_ref": None,
        "provider": "mock",
        "model": "mock-report-model",
        "skill_pipeline_id": "nature_research_report_zh",
        "skill_runs": [],
        "artifact_refs": [],
        "error": None,
        "created_by": "tester",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
    doc.update(overrides)
    return doc


def _artifact_doc(**overrides) -> dict:
    now = _now()
    doc = {
        "artifact_id": "rart_test_001",
        "report_id": "report_test_001",
        "artifact_type": "markdown",
        "filename": "report.md",
        "storage_uri": "reports/report_test_001/report.md",
        "size_bytes": 128,
        "sha256": "abc123",
        "created_at": now,
    }
    doc.update(overrides)
    return doc


class ReportRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = Path(tempfile.mkdtemp(prefix="poly-agent-report-test-"))
        self.original_runtime_root = settings.runtime_root
        self.original_require_mongodb = settings.require_mongodb
        self.original_demo_store_path = demo_store.path
        settings.runtime_root = self.runtime_root
        settings.require_mongodb = False
        computation_repositories._mongo_unavailable = True
        demo_store.path = self.runtime_root / "demo-db.json"

    def tearDown(self) -> None:
        settings.runtime_root = self.original_runtime_root
        settings.require_mongodb = self.original_require_mongodb
        computation_repositories._mongo_unavailable = False
        demo_store.path = self.original_demo_store_path
        shutil.rmtree(self.runtime_root, ignore_errors=True)


class ReportSchemaTest(ReportRepositoryTestCase):
    def test_report_job_schema_accepts_planned_statuses_and_provider(self) -> None:
        job = ReportJob(**_job_doc(status="running", stage="draft", provider="mock"))

        self.assertEqual(job.status, "running")
        self.assertEqual(job.stage, "draft")
        self.assertEqual(job.provider, "mock")

    def test_retry_request_records_source_report(self) -> None:
        request = ReportRetryRequest(retry_of="report_failed_001")

        self.assertEqual(request.retry_of, "report_failed_001")

    def test_report_artifact_schema(self) -> None:
        artifact = ReportArtifact(**_artifact_doc(artifact_type="pdf", filename="report.pdf"))

        self.assertEqual(artifact.artifact_type, "pdf")
        self.assertEqual(artifact.report_id, "report_test_001")


class ReportJobRepositoryTest(ReportRepositoryTestCase):
    def test_save_and_find_report_job(self) -> None:
        ReportJobRepository.save_job(_job_doc())

        found = ReportJobRepository.find_by_report_id("report_test_001")

        self.assertIsNotNone(found)
        self.assertEqual(found["subject_type"], "algorithm_run")
        self.assertEqual(found["status"], "queued")

    def test_list_by_subject_filters_and_sorts_newest_first(self) -> None:
        older = _job_doc(report_id="report_old", subject_id="ar_test_001", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        newer = _job_doc(report_id="report_new", subject_id="ar_test_001", created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
        other = _job_doc(report_id="report_other", subject_id="ar_other")
        ReportJobRepository.save_job(older)
        ReportJobRepository.save_job(newer)
        ReportJobRepository.save_job(other)

        items, total = ReportJobRepository.list_jobs(
            subject_type="algorithm_run",
            subject_id="ar_test_001",
            page=1,
            page_size=20,
        )

        self.assertEqual(total, 2)
        self.assertEqual([item["report_id"] for item in items], ["report_new", "report_old"])

    def test_update_status_and_append_artifact_ref(self) -> None:
        ReportJobRepository.save_job(_job_doc())
        updated = ReportJobRepository.update_status(
            "report_test_001",
            status="running",
            stage="draft",
            progress=35,
        )

        self.assertTrue(updated)
        ReportJobRepository.append_artifact_ref(
            "report_test_001",
            {
                "artifact_id": "rart_test_001",
                "artifact_type": "markdown",
                "filename": "report.md",
            },
        )
        found = ReportJobRepository.find_by_report_id("report_test_001")
        self.assertEqual(found["status"], "running")
        self.assertEqual(found["stage"], "draft")
        self.assertEqual(found["progress"], 35)
        self.assertEqual(found["artifact_refs"][0]["artifact_id"], "rart_test_001")

    def test_create_retry_copies_input_snapshot_with_retry_of(self) -> None:
        ReportJobRepository.save_job(_job_doc(report_id="report_failed", status="failed"))

        retry_doc = ReportJobRepository.create_retry_job(
            "report_failed",
            new_report_id="report_retry",
            created_by="tester",
        )

        self.assertEqual(retry_doc["report_id"], "report_retry")
        self.assertEqual(retry_doc["status"], "queued")
        self.assertEqual(retry_doc["input_snapshot"]["retry_of"], "report_failed")
        self.assertEqual(retry_doc["artifact_refs"], [])


class ReportArtifactRepositoryTest(ReportRepositoryTestCase):
    def test_save_find_and_list_artifacts(self) -> None:
        ReportArtifactRepository.save_artifact(_artifact_doc())
        ReportArtifactRepository.save_artifact(
            _artifact_doc(
                artifact_id="rart_test_002",
                artifact_type="pdf",
                filename="report.pdf",
            )
        )

        found = ReportArtifactRepository.find_by_artifact_id("rart_test_001")
        items, total = ReportArtifactRepository.list_by_report_id("report_test_001")

        self.assertIsNotNone(found)
        self.assertEqual(found["filename"], "report.md")
        self.assertEqual(total, 2)
        self.assertEqual({item["artifact_type"] for item in items}, {"markdown", "pdf"})
