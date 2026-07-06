"""Service integration config coverage."""

from __future__ import annotations

from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import settings
from app.infra.computation_repositories import AuditEventRepository
from app.infra.computation_repositories import ServiceIntegrationRepository
from app.schemas.integrations import ServiceIntegrationUpsertRequest
from app.services.integration_config_service import IntegrationConfigService
from app.services.integration_status_service import IntegrationStatusService

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class IntegrationConfigServiceTest(ComputationTestCase):
    """Cover persisted integration config summaries."""

    def setUp(self) -> None:
        super().setUp()
        self.service = IntegrationConfigService()

    def test_upsert_rejects_plaintext_secret_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceIntegrationUpsertRequest(
                display_name="SpecLabOS",
                service_type="experiment",
                enabled=True,
                endpoint="https://speclabos.example/api",
                config_summary={"api_key": "plain-text-secret"},
            )

    def test_upsert_persists_summary_without_plaintext_secrets_and_audits(self) -> None:
        config = self.service.upsert_config(
            "speclabos",
            ServiceIntegrationUpsertRequest(
                display_name="SpecLabOS",
                service_type="experiment",
                enabled=True,
                endpoint="https://speclabos.example/api",
                config_summary={"workflow_template": "poly-agent-validation", "timeout_seconds": 30},
                secret_refs={"bearer_token": "SPECLABOS_TOKEN"},
            ),
            actor_user_id="admin-user",
            request_id="req-upsert",
        )

        saved = ServiceIntegrationRepository.find_one({"service_key": "speclabos"})
        audits, total = AuditEventRepository.list_events(
            entity_type="service_integration",
            entity_id="speclabos",
            event_type="integration_config.updated",
            page=1,
            page_size=10,
        )

        self.assertEqual(config.service_key, "speclabos")
        self.assertEqual(config.endpoint, "https://speclabos.example/api")
        self.assertEqual(config.secret_refs, {"bearer_token": "SPECLABOS_TOKEN"})
        self.assertIsNotNone(saved)
        self.assertNotIn("plain-text-secret", str(saved))
        self.assertEqual(total, 1)
        self.assertEqual(audits[0]["request_id"], "req-upsert")
        self.assertNotIn("plain-text-secret", str(audits[0]))

    def test_upsert_config_returns_sanitized_summary(self) -> None:
        config = self.service.upsert_config(
            "speclabos",
            ServiceIntegrationUpsertRequest(
                display_name="SpecLabOS",
                service_type="experiment",
                enabled=True,
                endpoint="https://speclabos.example/api",
                config_summary={"workflow_template": "poly-agent-validation"},
                secret_refs={"bearer_token": "SPECLABOS_TOKEN"},
            ),
            actor_user_id="demo_user",
            request_id="req-api",
        )
        audits, total = AuditEventRepository.list_events(
            entity_type="service_integration",
            entity_id="speclabos",
            event_type="integration_config.updated",
            page=1,
            page_size=10,
        )

        self.assertEqual(config.service_key, "speclabos")
        self.assertEqual(config.secret_refs, {"bearer_token": "SPECLABOS_TOKEN"})
        self.assertNotIn("plain-text-secret", config.model_dump_json())
        self.assertEqual(total, 1)
        self.assertEqual(audits[0]["request_id"], "req-api")

    def test_alchemist_backend_can_be_persisted_and_merged_into_status(self) -> None:
        self.service.upsert_config(
            "alchemist-backend",
            ServiceIntegrationUpsertRequest(
                display_name="ALchemist backend",
                service_type="optimizer",
                enabled=True,
                endpoint="http://127.0.0.1:8004/api/v1",
                config_summary={"mode": "external_optimizer", "purpose": "bayesian_design"},
            ),
            actor_user_id="demo_user",
            request_id="req-alchemist-config",
        )

        with patch.object(IntegrationStatusService, "_can_connect", return_value=False):
            items = IntegrationStatusService().get_status()["items"]

        by_service = {item["service"]: item for item in items}

        self.assertEqual(by_service["alchemist-backend"]["status"], "down")
        self.assertTrue(by_service["alchemist-backend"]["details"]["configured"])
        self.assertTrue(by_service["alchemist-backend"]["details"]["enabled"])

    def test_disabled_persisted_config_marks_status_disabled(self) -> None:
        self.service.upsert_config(
            "speclabos",
            ServiceIntegrationUpsertRequest(
                display_name="SpecLabOS",
                service_type="experiment",
                enabled=False,
                config_summary={"boundary": "not used in local demo"},
            ),
            actor_user_id="demo_user",
            request_id="req-speclabos-disabled",
        )

        items = IntegrationStatusService().get_status()["items"]

        by_service = {item["service"]: item for item in items}

        self.assertEqual(by_service["speclabos"]["status"], "disabled")
        self.assertTrue(by_service["speclabos"]["details"]["configured"])
        self.assertFalse(by_service["speclabos"]["details"]["enabled"])

    def test_request_rejects_plaintext_secret_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ServiceIntegrationUpsertRequest(
                display_name="SpecLabOS",
                service_type="experiment",
                enabled=True,
                endpoint="https://speclabos.example/api",
                config_summary={"api_key": "plain-text-secret"},
            )

    def test_local_dependency_status_includes_path_capabilities_and_failure_reason(self) -> None:
        with patch("app.services.integration_status_service.importlib.util.find_spec", return_value=None), patch(
            "app.services.integration_status_service.shutil.which",
            return_value=None,
        ):
            items = IntegrationStatusService().get_status()["items"]

        by_service = {item["service"]: item for item in items}

        self.assertEqual(by_service["rdkit"]["details"]["reason"], "python package rdkit is not importable")
        self.assertEqual(by_service["openbabel"]["details"]["reason"], "obabel executable not found on PATH")
        self.assertEqual(by_service["xtb"]["details"]["reason"], "xtb executable not found on PATH")
        self.assertEqual(by_service["openbabel"]["details"]["path"], None)
        self.assertEqual(by_service["xtb"]["details"]["path"], None)

    def test_status_includes_alchemist_backend_without_requiring_service(self) -> None:
        original_url = settings.alchemist_backend_url
        settings.alchemist_backend_url = "http://127.0.0.1:8004/api/v1"
        try:
            with patch.object(IntegrationStatusService, "_can_connect", return_value=False):
                items = IntegrationStatusService().get_status()["items"]
        finally:
            settings.alchemist_backend_url = original_url

        by_service = {item["service"]: item for item in items}

        self.assertIn("alchemist-backend", by_service)
        self.assertEqual(by_service["alchemist-backend"]["status"], "not_configured")
        self.assertEqual(by_service["alchemist-backend"]["details"]["host"], "127.0.0.1")
        self.assertEqual(by_service["alchemist-backend"]["details"]["port"], 8004)
