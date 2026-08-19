"""Report API tests."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.endpoints.reports import router as reports_router
from app.core.auth import get_current_user
from app.core.config import settings
from app.infra import computation_repositories
from app.infra.demo_store import demo_store
from app.infra.computation_repositories import AuditEventRepository
from app.infra.report_repositories import ReportJobRepository
from app.infra.research_engine_repositories import AlgorithmRunRepository


def _context(subject_type: str = "algorithm_run", subject_id: str = "ar_api_001") -> dict:
    return {
        "subject": {"subject_type": subject_type, "subject_id": subject_id},
        "algorithm_run": {"run_id": subject_id, "output_summary": {"score": 0.9}},
        "artifacts": [],
        "audit_events": [],
        "truncation_notes": [],
    }


def _algorithm_run_doc(run_id: str, created_by: str) -> dict:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return {
        "run_id": run_id,
        "algorithm_id": "test_adapter",
        "trigger_source": "human_workflow",
        "trigger_context_id": None,
        "problem_spec_id": None,
        "problem_spec_version": None,
        "campaign_id": None,
        "workflow_run_id": None,
        "workflow_step_run_id": None,
        "research_run_id": None,
        "stage_run_id": None,
        "linked_computation_run_id": None,
        "linked_suggestion_id": None,
        "linked_observation_id": None,
        "input_snapshot": {},
        "output_summary": {},
        "artifact_refs": [],
        "status": "completed",
        "error": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
        "started_at": now,
        "finished_at": now,
    }


class ReportApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_root = Path(tempfile.mkdtemp(prefix="poly-agent-report-api-"))
        self.original_report_output_root = settings.report_output_root
        self.original_report_llm_provider = settings.report_llm_provider
        self.original_report_llm_fallback_providers = list(settings.report_llm_fallback_providers)
        self.original_report_llm_model = settings.report_llm_model
        self.original_require_mongodb = settings.require_mongodb
        self.original_demo_store_path = demo_store.path
        settings.report_output_root = self.runtime_root / "reports"
        settings.report_llm_provider = "mock"
        settings.report_llm_model = "mock-report-model"
        settings.require_mongodb = False
        computation_repositories._mongo_unavailable = True
        demo_store.path = self.runtime_root / "demo-db.json"

        app = FastAPI()
        app.include_router(reports_router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.app.dependency_overrides.pop(get_current_user, None)
        self.client.close()
        settings.report_output_root = self.original_report_output_root
        settings.report_llm_provider = self.original_report_llm_provider
        settings.report_llm_fallback_providers = self.original_report_llm_fallback_providers
        settings.report_llm_model = self.original_report_llm_model
        settings.require_mongodb = self.original_require_mongodb
        computation_repositories._mongo_unavailable = False
        demo_store.path = self.original_demo_store_path
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def test_create_get_list_and_download_report(self) -> None:
        with patch("app.services.report_service.ReportContextService.collect_context", return_value=_context()):
            create_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_api_001",
                    "template_id": "algorithm_run_summary_zh",
                    "language": "zh-CN",
                    "formats": ["markdown"],
                    "provider": "mock",
                    "skill_pipeline_id": "nature_research_report_zh",
                    "scope": {},
                },
            )

        self.assertEqual(create_resp.status_code, 200)
        created_job = create_resp.json()["data"]
        self.assertEqual(created_job["status"], "queued")
        self.assertEqual(created_job["subject_id"], "ar_api_001")
        self.assertTrue(created_job["created_at"].endswith("Z"))

        get_resp = self.client.get(f"/api/v1/reports/{created_job['report_id']}")
        self.assertEqual(get_resp.status_code, 200)
        job = get_resp.json()["data"]
        self.assertEqual(job["status"], "completed")
        self.assertTrue(job["created_at"].endswith("Z"))
        self.assertTrue(job["started_at"].endswith("Z"))
        self.assertTrue(job["finished_at"].endswith("Z"))
        artifact_types = {item["artifact_type"] for item in job["artifact_refs"]}
        self.assertIn("markdown", artifact_types)
        self.assertNotIn("latex", artifact_types)

        list_resp = self.client.get(
            "/api/v1/reports",
            params={"subject_type": "algorithm_run", "subject_id": "ar_api_001"},
        )
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()["data"]["total"], 1)
        self.assertTrue(list_resp.json()["data"]["items"][0]["created_at"].endswith("Z"))

        markdown_artifact = next(item for item in job["artifact_refs"] if item["artifact_type"] == "markdown")
        download_resp = self.client.get(
            f"/api/v1/reports/{job['report_id']}/artifacts/{markdown_artifact['artifact_id']}/download"
        )
        self.assertEqual(download_resp.status_code, 200)
        self.assertIn(b"#", download_resp.content)

        preview_resp = self.client.get(f"/api/v1/reports/{job['report_id']}/preview")
        self.assertEqual(preview_resp.status_code, 200)
        self.assertIn("# 研发运行报告", preview_resp.json()["data"]["content"])
        self.assertEqual(preview_resp.json()["data"]["model"], "mock-report-model")

        events, total = AuditEventRepository.list_events(
            entity_type="report",
            entity_id=job["report_id"],
            event_type=None,
            page=1,
            page_size=20,
        )
        self.assertGreaterEqual(total, 3)
        event_types = {event["event_type"] for event in events}
        self.assertIn("report.created", event_types)
        self.assertIn("report.context_collected", event_types)
        self.assertIn("report.generated", event_types)
        self.assertIn("report.downloaded", event_types)

    def test_create_report_rejects_latex_format(self) -> None:
        response = self.client.post(
            "/api/v1/reports",
            json={
                "subject_type": "algorithm_run",
                "subject_id": "ar_api_001",
                "formats": ["latex"],
                "provider": "mock",
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_cancel_queued_report(self) -> None:
        with patch("app.services.report_service.ReportService.execute_report_job", return_value=None):
            create_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_cancel_001",
                    "formats": ["markdown"],
                    "provider": "mock",
                },
            )
        report_id = create_resp.json()["data"]["report_id"]

        cancel_resp = self.client.post(f"/api/v1/reports/{report_id}/cancel")

        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["data"]["status"], "cancelled")
        events, _ = AuditEventRepository.list_events(
            entity_type="report",
            entity_id=report_id,
            event_type="report.cancelled",
            page=1,
            page_size=10,
        )
        self.assertEqual(len(events), 1)

    def test_retry_failed_report_creates_new_report(self) -> None:
        with patch(
            "app.services.report_service.ReportContextService.collect_context",
            side_effect=[RuntimeError("context failed"), _context(subject_id="ar_retry_001")],
        ):
            failed_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_retry_001",
                    "formats": ["markdown"],
                    "provider": "mock",
                },
            )
            failed_created_job = failed_resp.json()["data"]
            failed_get_resp = self.client.get(f"/api/v1/reports/{failed_created_job['report_id']}")
            failed_job = failed_get_resp.json()["data"]
            retry_resp = self.client.post(f"/api/v1/reports/{failed_job['report_id']}/retry")
            retry_created_job = retry_resp.json()["data"]
            retry_get_resp = self.client.get(f"/api/v1/reports/{retry_created_job['report_id']}")

        self.assertEqual(failed_job["status"], "failed")
        self.assertIn("log", {item["artifact_type"] for item in failed_job["artifact_refs"]})
        self.assertEqual(retry_resp.status_code, 200)
        self.assertEqual(retry_created_job["status"], "queued")
        retry_job = retry_get_resp.json()["data"]
        self.assertNotEqual(retry_job["report_id"], failed_job["report_id"])
        self.assertEqual(retry_job["status"], "completed")
        self.assertEqual(retry_job["input_snapshot"]["retry_of"], failed_job["report_id"])
        failed_events, _ = AuditEventRepository.list_events(
            entity_type="report",
            entity_id=failed_job["report_id"],
            event_type="report.failed",
            page=1,
            page_size=10,
        )
        retry_events, _ = AuditEventRepository.list_events(
            entity_type="report",
            entity_id=retry_job["report_id"],
            event_type="report.created",
            page=1,
            page_size=10,
        )
        self.assertEqual(len(failed_events), 1)
        self.assertEqual(len(retry_events), 1)

    def test_retry_completed_report_is_rejected(self) -> None:
        with patch("app.services.report_service.ReportContextService.collect_context", return_value=_context(subject_id="ar_done_001")):
            create_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_done_001",
                    "formats": ["markdown"],
                    "provider": "mock",
                },
            )
        report_id = create_resp.json()["data"]["report_id"]

        retry_resp = self.client.post(f"/api/v1/reports/{report_id}/retry")

        self.assertEqual(retry_resp.status_code, 400)
        self.assertIn("失败", retry_resp.json()["detail"])

    def test_retry_failed_auto_report_refreshes_report_model_route(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ReportJobRepository.save_job(
            {
                "report_id": "report_failed_old_route",
                "subject_type": "algorithm_run",
                "subject_id": "ar_retry_route_001",
                "problem_spec_id": None,
                "campaign_id": None,
                "template_id": "algorithm_run_summary_zh",
                "language": "zh-CN",
                "formats": ["markdown"],
                "status": "failed",
                "stage": "persist",
                "progress": 100,
                "input_snapshot": {
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_retry_route_001",
                    "provider": "auto",
                    "retry_of": None,
                    "resolved_model_route": {
                        "provider_id": "default_openai",
                        "provider_type": "openai_compatible",
                        "model_id": "legacy-fast-model",
                    },
                },
                "context_ref": None,
                "provider": "openai_compatible",
                "model": "legacy-fast-model",
                "skill_pipeline_id": "nature_research_report_zh",
                "skill_runs": [],
                "artifact_refs": [],
                "error": {"message": "Error code: 502", "error_type": "InternalServerError"},
                "created_by": "demo_user",
                "created_at": now,
                "updated_at": now,
                "started_at": now,
                "finished_at": now,
            }
        )
        route = {
            "purpose": "report",
            "provider_id": "qwen_reasoning_primary",
            "provider_type": "openai_compatible",
            "model_id": "Qwen3.6-35B-A3B",
            "provider_config": {"base_url": "https://llm.example.test/v1", "api_key": "route-key"},
        }
        settings.report_llm_provider = "openai_compatible"
        with (
            patch("app.services.report_service.ReportService.execute_report_job", return_value=None),
            patch("app.services.report_providers.registry.ReportProviderRegistry.resolve_report_route", return_value=route),
        ):
            retry_resp = self.client.post("/api/v1/reports/report_failed_old_route/retry")

        self.assertEqual(retry_resp.status_code, 200)
        retry_job = retry_resp.json()["data"]
        self.assertEqual(retry_job["model"], "Qwen3.6-35B-A3B")
        self.assertEqual(retry_job["input_snapshot"]["resolved_model_route"]["provider_id"], "qwen_reasoning_primary")

    def test_provider_fallback_completes_report_when_primary_fails(self) -> None:
        from app.services.report_providers.mock import MockReportProvider

        class BrokenProvider:
            name = "openai_responses"
            model = "broken-model"

            def complete_json(self, *, messages, schema, options):
                raise RuntimeError("primary provider failed")

        def fake_get_provider(self, provider_name=None, *, model_route=None):
            if provider_name == "openai_responses":
                return BrokenProvider()
            if provider_name == "mock":
                return MockReportProvider(model="fallback-model")
            raise ValueError(provider_name)

        settings.report_llm_fallback_providers = ["mock"]
        with (
            patch("app.services.report_service.ReportContextService.collect_context", return_value=_context(subject_id="ar_fallback_001")),
            patch("app.services.report_providers.registry.ReportProviderRegistry.get_provider", new=fake_get_provider),
        ):
            create_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_fallback_001",
                    "formats": ["markdown"],
                    "provider": "openai_responses",
                },
            )
        report_id = create_resp.json()["data"]["report_id"]
        job = self.client.get(f"/api/v1/reports/{report_id}").json()["data"]

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["provider"], "mock")
        self.assertEqual(job["model"], "fallback-model")

    def test_auto_report_uses_resolved_report_model_route(self) -> None:
        structured_report = {
            "title": "Routed report",
            "abstract": "Generated with the routed report model.",
            "key_findings": [{"finding": "F", "evidence": ["ar_routed_001"], "confidence": "high"}],
            "methods": ["M"],
            "results": [{"name": "Result", "summary": "S", "evidence": ["ar_routed_001"]}],
            "limitations": ["L"],
            "next_steps": ["N"],
        }
        route = {
            "purpose": "report",
            "provider_id": "qwen_reasoning_primary",
            "provider_type": "openai_compatible",
            "model_id": "Qwen3.6-35B-A3B",
            "provider_config": {
                "base_url": "https://llm.example.test/v1",
                "api_key": "route-key",
            },
        }
        settings.report_llm_provider = "openai_compatible"
        with (
            patch("app.services.report_service.ReportContextService.collect_context", return_value=_context(subject_id="ar_routed_001")),
            patch("app.services.report_providers.registry.ReportProviderRegistry.resolve_report_route", return_value=route),
            patch(
                "app.services.report_providers.openai_compatible.OpenAICompatibleReportProvider.complete_json",
                return_value=structured_report,
            ),
        ):
            create_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_routed_001",
                    "formats": ["markdown"],
                    "provider": "auto",
                },
            )

        report_id = create_resp.json()["data"]["report_id"]
        job = self.client.get(f"/api/v1/reports/{report_id}").json()["data"]

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["provider"], "openai_compatible")
        self.assertEqual(job["model"], "Qwen3.6-35B-A3B")
        self.assertEqual(job["input_snapshot"]["resolved_model_route"]["provider_id"], "qwen_reasoning_primary")

    def test_authenticated_user_cannot_access_another_users_report(self) -> None:
        AlgorithmRunRepository.save("run_id", _algorithm_run_doc("ar_owned_by_a", "user-a"))
        self.client.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "user-a",
            "username": "user-a",
            "role": "user",
            "status": "active",
        }
        with patch("app.services.report_service.ReportContextService.collect_context", return_value=_context(subject_id="ar_owned_by_a")):
            create_resp = self.client.post(
                "/api/v1/reports",
                json={
                    "subject_type": "algorithm_run",
                    "subject_id": "ar_owned_by_a",
                    "formats": ["markdown"],
                    "provider": "mock",
                },
            )
        self.assertEqual(create_resp.status_code, 200)
        created_job = create_resp.json()["data"]
        job = self.client.get(f"/api/v1/reports/{created_job['report_id']}").json()["data"]
        markdown_artifact = next(item for item in job["artifact_refs"] if item["artifact_type"] == "markdown")

        self.client.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "user-b",
            "username": "user-b",
            "role": "user",
            "status": "active",
        }
        list_resp = self.client.get(
            "/api/v1/reports",
            params={"subject_type": "algorithm_run", "subject_id": "ar_owned_by_a"},
        )
        get_resp = self.client.get(f"/api/v1/reports/{job['report_id']}")
        download_resp = self.client.get(
            f"/api/v1/reports/{job['report_id']}/artifacts/{markdown_artifact['artifact_id']}/download"
        )

        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()["data"]["total"], 0)
        self.assertEqual(get_resp.status_code, 403)
        self.assertEqual(download_resp.status_code, 403)

        self.client.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin",
            "username": "admin",
            "role": "admin",
            "status": "active",
        }
        admin_resp = self.client.get(f"/api/v1/reports/{job['report_id']}")
        self.assertEqual(admin_resp.status_code, 200)
