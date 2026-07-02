"""Service integration config coverage."""

from __future__ import annotations

from pydantic import ValidationError

from app.infra.computation_repositories import AuditEventRepository
from app.infra.computation_repositories import ServiceIntegrationRepository
from app.schemas.integrations import ServiceIntegrationUpsertRequest
from app.services.integration_config_service import IntegrationConfigService

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

    def test_api_upsert_config_returns_sanitized_summary(self) -> None:
        response = self.client.put(
            "/api/v1/integrations/configs/speclabos",
            headers={"X-Request-ID": "req-api"},
            json={
                "display_name": "SpecLabOS",
                "service_type": "experiment",
                "enabled": True,
                "endpoint": "https://speclabos.example/api",
                "config_summary": {"workflow_template": "poly-agent-validation"},
                "secret_refs": {"bearer_token": "SPECLABOS_TOKEN"},
            },
        )

        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"]["service_key"], "speclabos")
        self.assertEqual(payload["data"]["secret_refs"], {"bearer_token": "SPECLABOS_TOKEN"})
        self.assertNotIn("plain-text-secret", response.text)

    def test_api_rejects_plaintext_secret_fields(self) -> None:
        response = self.client.put(
            "/api/v1/integrations/configs/speclabos",
            json={
                "display_name": "SpecLabOS",
                "service_type": "experiment",
                "enabled": True,
                "endpoint": "https://speclabos.example/api",
                "config_summary": {"api_key": "plain-text-secret"},
            },
        )

        self.assertEqual(response.status_code, 422)
