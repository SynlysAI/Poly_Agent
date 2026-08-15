"""Assistant algorithm tool-call state machine API tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AgentToolPolicyRepository,
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
    AssistantEventRepository,
    AssistantToolCallRepository,
)
from app.schemas.agent_tools import AssistantToolCall
from app.main import app


class AssistantToolCallApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {
            "user_id": "user-1",
            "username": "user",
            "role": "user",
            "status": "active",
        }
        app.dependency_overrides[get_current_user] = lambda: self.user
        now = utc_now()
        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": "vertical-tool",
                "name": "Vertical Tool",
                "description": "Test tool",
                "type": "predictor",
                "algorithm_family": "vertical_prediction",
                "capability_group": "vertical_algorithm",
                "visibility": "public",
                "owner": "owner-1",
                "status": "active",
                "deployment_status": "active",
                "active_version_id": "vertical-tool-v1",
                "trigger_modes": ["human_workflow"],
                "source": "builtin",
                "source_kind": "uploaded_package",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
                "input_assets": [],
                "output_assets": [],
                "created_at": now,
                "updated_at": now,
            },
        )
        AlgorithmVersionRepository.save(
            "version_id",
            {
                "version_id": "vertical-tool-v1",
                "algorithm_id": "vertical-tool",
                "version": "1.0.0",
                "status": "active",
                "source_kind": "uploaded_package",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
                "input_assets": [],
                "output_assets": [],
                "created_by": "owner-1",
                "created_at": now,
                "updated_at": now,
            },
        )

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def test_persisted_extra_fields_do_not_break_tool_call_serialization(self) -> None:
        """历史/未来持久化字段不应导致会话加载或确认响应校验失败。"""
        now = utc_now()
        parsed = AssistantToolCall.model_validate({
            "call_id": "atc-extra-fields",
            "tool_id": "algorithm:vertical-tool",
            "algorithm_id": "vertical-tool",
            "tool_name": "Vertical Tool",
            "phase": "completed",
            "run_status": "completed",
            "future_unknown_field": {"x": 1},
            "arguments": {"smiles": "CCO"},
            "result_summary": {"score": 0.91},
            "artifact_refs": [],
            "error": None,
            "created_by": "user-1",
            "created_at": now,
            "updated_at": now,
        })
        self.assertEqual(parsed.phase, "completed")
        self.assertEqual(parsed.run_status, "completed")
        self.assertNotIn("future_unknown_field", parsed.model_dump())

    def _fake_run(self, payload, *, actor_user_id, is_admin=False, request_id=None, input_asset_uploads=None):
        return type(
            "FakeRun",
            (),
            {
                "run_id": "arun-tool-1",
                "algorithm_id": payload.algorithm_id,
                "algorithm_version_id": payload.algorithm_version_id,
                "status": "completed",
                "output_summary": {"score": 0.91},
                "artifact_refs": [{"artifact_id": "artifact-1", "name": "result.json"}],
                "error": None,
            },
        )()

    def test_pending_call_requires_input_then_confirms_once(self) -> None:
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "chat_id": "chat-1", "arguments": {}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        call = response.json()["data"]
        self.assertEqual(call["phase"], "awaiting_input")
        self.assertEqual(call["missing_fields"], ["smiles"])
        self.assertIsNone(call["run_id"])

        patched = self.client.patch(
            f"/api/v1/assistant/tool-calls/{call['call_id']}/input",
            json={"arguments": {"smiles": "CCO"}},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["data"]["phase"], "awaiting_confirmation")

        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=self._fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call['call_id']}/confirm")
            repeated = self.client.post(f"/api/v1/assistant/tool-calls/{call['call_id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["data"]["phase"], "completed", confirmed.text)
        self.assertEqual(confirmed.json()["data"]["run_id"], "arun-tool-1")
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["data"]["run_id"], "arun-tool-1")
        phases = [event.get("phase") for event in AssistantToolCallRepository.list_events(call["call_id"])]
        self.assertEqual(
            [phase for phase in phases if phase],
            ["requested", "awaiting_input", "awaiting_confirmation", "running", "completed"],
        )
        unified_events, _ = AssistantEventRepository.list_all(
            {"call_id": call["call_id"]},
            sort_field="seq",
            reverse=False,
            page=1,
            page_size=100,
        )
        self.assertIn("tool.confirmed", [event["type"] for event in unified_events])

    def test_invalid_arguments_use_contract_error_code(self) -> None:
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={
                "tool_id": "algorithm:vertical-tool",
                "chat_id": "chat-invalid",
                "arguments": {"smiles": "CCO", "bogus": 1},
            },
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["data"]["detail"]["code"], "TOOL_ARGUMENTS_INVALID")

    def test_cancel_is_terminal_and_confirm_cannot_execute(self) -> None:
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "arguments": {"smiles": "CCO"}},
        )
        self.assertEqual(response.json()["data"]["phase"], "awaiting_confirmation")
        call_id = response.json()["data"]["call_id"]
        canceled = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/cancel")
        self.assertEqual(canceled.status_code, 200, canceled.text)
        self.assertEqual(canceled.json()["data"]["phase"], "canceled")
        confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 409)

    def test_admin_cannot_confirm_another_users_call(self) -> None:
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "arguments": {"smiles": "CCO"}},
        )
        call_id = response.json()["data"]["call_id"]
        self.user = {
            "user_id": "admin-1",
            "username": "admin",
            "role": "admin",
            "status": "active",
        }
        forbidden = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(forbidden.status_code, 403)

    def test_sse_replays_tool_call_status_events(self) -> None:
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "arguments": {"smiles": "CCO"}},
        )
        call_id = response.json()["data"]["call_id"]
        with self.client.stream("GET", f"/api/v1/assistant/tool-calls/{call_id}/events") as stream:
            self.assertEqual(stream.status_code, 200)
            body = "".join(stream.iter_text())
        self.assertIn('"type": "tool_call"', body)
        self.assertIn('"phase": "awaiting_confirmation"', body)

    def test_confirm_rechecks_policy_and_active_version(self) -> None:
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "arguments": {"smiles": "CCO"}},
        )
        call_id = response.json()["data"]["call_id"]
        AlgorithmRegistryRepository.update_fields(
            "vertical-tool",
            {"active_version_id": "vertical-tool-v2"},
        )
        now = datetime.now(timezone.utc)
        AlgorithmVersionRepository.save(
            "version_id",
            {
                "version_id": "vertical-tool-v2",
                "algorithm_id": "vertical-tool",
                "version": "2.0.0",
                "status": "active",
                "source_kind": "uploaded_package",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
                "input_assets": [],
                "output_assets": [],
                "created_by": "owner-1",
                "created_at": now,
                "updated_at": now,
            },
        )
        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=self._fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["data"]["algorithm_version_id"], "vertical-tool-v2")

        second = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "arguments": {"smiles": "CCO"}},
        )
        AgentToolPolicyRepository.update_fields("vertical-tool", {"enabled": False})
        forbidden = self.client.post(f"/api/v1/assistant/tool-calls/{second.json()['data']['call_id']}/confirm")
        self.assertEqual(forbidden.status_code, 403)
        self.assertIsNone(second.json()["data"]["run_id"])

    def test_multipart_input_is_forwarded_without_exposing_storage_path(self) -> None:
        asset_spec = {
            "key": "structure",
            "label": "Structure",
            "required": True,
            "extensions": [".xyz"],
            "max_size_bytes": 1024,
        }
        AlgorithmVersionRepository.update_fields(
            "vertical-tool-v1",
            {"input_assets": [asset_spec]},
        )
        response = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={"tool_id": "algorithm:vertical-tool", "arguments": {"smiles": "CCO"}},
        )
        call = response.json()["data"]
        self.assertEqual(call["phase"], "awaiting_input")
        uploaded = self.client.post(
            f"/api/v1/assistant/tool-calls/{call['call_id']}/input:multipart",
            files={"structure": ("input.xyz", b"1\nexample\nH 0 0 0\n", "chemical/x-xyz")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["data"]["phase"], "awaiting_confirmation")
        self.assertNotIn("_path", uploaded.text)

        received_uploads = {}

        def fake_run(_service, payload, **kwargs):
            received_uploads.update(kwargs.get("input_asset_uploads") or {})
            return self._fake_run(payload, **kwargs)

        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call['call_id']}/confirm")
        self.assertEqual(confirmed.json()["data"]["phase"], "completed")
        self.assertEqual(received_uploads["structure"]["filename"], "input.xyz")
