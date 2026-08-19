"""Report artifact storage and download tests."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.endpoints.reports import router as reports_router
from app.core.config import settings
from app.infra import computation_repositories
from app.infra.demo_store import demo_store
from app.infra.report_repositories import ReportJobRepository
from app.services.report_service import ReportService


def _job_doc(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "report_id": "report_artifact_001",
        "subject_type": "algorithm_run",
        "subject_id": "ar_test_001",
        "problem_spec_id": None,
        "campaign_id": None,
        "template_id": "algorithm_run_summary_zh",
        "language": "zh-CN",
        "formats": ["markdown"],
        "status": "running",
        "stage": "persist",
        "progress": 90,
        "input_snapshot": {},
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
        "started_at": now,
        "finished_at": None,
    }
    doc.update(overrides)
    return doc


class ReportArtifactStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = Path(tempfile.mkdtemp(prefix="poly-agent-report-artifact-"))
        self.original_report_output_root = settings.report_output_root
        self.original_require_mongodb = settings.require_mongodb
        self.original_demo_store_path = demo_store.path
        settings.report_output_root = self.runtime_root / "reports"
        settings.require_mongodb = False
        computation_repositories._mongo_unavailable = True
        demo_store.path = self.runtime_root / "demo-db.json"
        ReportJobRepository.save_job(_job_doc())

    def tearDown(self) -> None:
        settings.report_output_root = self.original_report_output_root
        settings.require_mongodb = self.original_require_mongodb
        computation_repositories._mongo_unavailable = False
        demo_store.path = self.original_demo_store_path
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def test_create_artifact_writes_file_and_appends_safe_ref(self) -> None:
        artifact = ReportService().create_artifact(
            report_id="report_artifact_001",
            artifact_type="markdown",
            filename="../report.md",
            content=b"# Report\n",
        )

        self.assertEqual(artifact["filename"], "report.md")
        self.assertEqual(artifact["size_bytes"], 9)
        self.assertTrue((settings.report_output_root / "report_artifact_001" / "report.md").exists())

        job = ReportJobRepository.find_by_report_id("report_artifact_001")
        self.assertEqual(job["artifact_refs"][0]["artifact_id"], artifact["artifact_id"])
        self.assertNotIn("storage_uri", job["artifact_refs"][0])

    def test_download_endpoint_returns_file_without_exposing_storage_uri(self) -> None:
        artifact = ReportService().create_artifact(
            report_id="report_artifact_001",
            artifact_type="markdown",
            filename="report.md",
            content=b"# Report\n",
        )
        app = FastAPI()
        app.include_router(reports_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.get(
            f"/api/v1/reports/report_artifact_001/artifacts/{artifact['artifact_id']}/download"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"# Report\n")
        self.assertNotIn(str(settings.report_output_root), response.text)
        client.close()

    def test_download_filename_includes_report_id_for_default_pdf_name(self) -> None:
        artifact = ReportService().create_artifact(
            report_id="report_artifact_001",
            artifact_type="pdf",
            filename="report.pdf",
            content=b"%PDF-1.4 test",
        )
        app = FastAPI()
        app.include_router(reports_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.get(
            f"/api/v1/reports/report_artifact_001/artifacts/{artifact['artifact_id']}/download"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("report_artifact_001.pdf", response.headers["content-disposition"])
        client.close()

    def test_download_filename_keeps_custom_name_and_appends_report_id(self) -> None:
        artifact = ReportService().create_artifact(
            report_id="report_artifact_001",
            artifact_type="markdown",
            filename="summary.md",
            content=b"# Summary\n",
        )
        app = FastAPI()
        app.include_router(reports_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.get(
            f"/api/v1/reports/report_artifact_001/artifacts/{artifact['artifact_id']}/download"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("summary_report_artifact_001.md", response.headers["content-disposition"])
        client.close()

    def test_build_download_filename_handles_default_and_custom_names(self) -> None:
        build = ReportService.build_download_filename

        self.assertEqual(build("report_abc123", "report.pdf"), "report_abc123.pdf")
        self.assertEqual(build("report_abc123", "report.md"), "report_abc123.md")
        self.assertEqual(build("report_abc123", "summary.pdf"), "summary_report_abc123.pdf")
        self.assertEqual(build("report_abc123", None), "artifact_report_abc123.bin")

    def test_download_rejects_artifact_from_another_report(self) -> None:
        artifact = ReportService().create_artifact(
            report_id="report_artifact_001",
            artifact_type="markdown",
            filename="report.md",
            content=b"# Report\n",
        )
        ReportJobRepository.save_job(_job_doc(report_id="report_other", subject_id="ar_other"))
        app = FastAPI()
        app.include_router(reports_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.get(
            f"/api/v1/reports/report_other/artifacts/{artifact['artifact_id']}/download"
        )

        self.assertEqual(response.status_code, 404)
        client.close()
