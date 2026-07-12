"""Report readiness tests."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints.reports import router as reports_router
from app.core.config import settings
from app.services.report_service import ReportService


class ReportReadinessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = Path(tempfile.mkdtemp(prefix="poly-agent-report-readiness-"))
        self.original_reports_enabled = getattr(settings, "reports_enabled", None)
        self.original_report_output_root = getattr(settings, "report_output_root", None)
        self.original_report_llm_provider = getattr(settings, "report_llm_provider", None)
        self.original_report_llm_api_key = getattr(settings, "report_llm_api_key", None)
        self.original_report_llm_model = getattr(settings, "report_llm_model", None)
        self.original_report_skill_pipeline_default = getattr(settings, "report_skill_pipeline_default", None)

        settings.reports_enabled = True
        settings.report_output_root = self.runtime_root / "reports"
        settings.report_llm_provider = "mock"
        settings.report_llm_api_key = "secret-key-for-test"
        settings.report_llm_model = "mock-report-model"
        settings.report_skill_pipeline_default = "nature_research_report_zh"

    def tearDown(self) -> None:
        if self.original_reports_enabled is not None:
            settings.reports_enabled = self.original_reports_enabled
        if self.original_report_output_root is not None:
            settings.report_output_root = self.original_report_output_root
        if self.original_report_llm_provider is not None:
            settings.report_llm_provider = self.original_report_llm_provider
        if self.original_report_llm_api_key is not None:
            settings.report_llm_api_key = self.original_report_llm_api_key
        if self.original_report_llm_model is not None:
            settings.report_llm_model = self.original_report_llm_model
        if self.original_report_skill_pipeline_default is not None:
            settings.report_skill_pipeline_default = self.original_report_skill_pipeline_default
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def test_readiness_creates_output_root_and_hides_secrets(self) -> None:
        readiness = ReportService().get_readiness()
        payload = readiness.model_dump()

        self.assertTrue(readiness.reports_enabled)
        self.assertTrue(readiness.output_root_ready)
        self.assertTrue(readiness.provider_ready)
        self.assertEqual(readiness.provider, "mock")
        self.assertNotIn("secret-key-for-test", str(payload))
        self.assertNotIn(str(self.runtime_root), str(payload))

    def test_readiness_endpoint(self) -> None:
        app = FastAPI()
        app.include_router(reports_router, prefix="/api/v1")
        client = TestClient(app)

        response = client.get("/api/v1/reports/readiness")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["provider"], "mock")
        self.assertTrue(body["data"]["output_root_ready"])
        self.assertNotIn("secret-key-for-test", str(body))
        self.assertNotIn(str(self.runtime_root), str(body))
        client.close()
