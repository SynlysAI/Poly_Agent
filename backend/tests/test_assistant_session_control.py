"""Assistant session control and tool execution gate tests."""

from __future__ import annotations

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantEventRepository,
    AssistantToolCallRepository,
)
from app.main import app


class AssistantSessionControlTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-3", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user
        created = self.client.post("/api/v1/assistant/chats", json={"title": "权限会话"})
        self.assertEqual(created.status_code, 200, created.text)
        self.chat_id = created.json()["data"]["chat_id"]
        now = utc_now()
        self.call_id = "atc-gate-1"
        AssistantToolCallRepository.save(
            "call_id",
            {
                "call_id": self.call_id,
                "trace_id": "trace-gate-1",
                "assistant_run_id": "asrun-gate-1",
                "chat_id": self.chat_id,
                "tool_id": "algorithm:vertical",
                "algorithm_id": "vertical",
                "tool_name": "Vertical",
                "phase": "awaiting_confirmation",
                "field_schema": {},
                "input_json_schema": {},
                "output_schema": {},
                "arguments": {"smiles": "CCO"},
                "input_asset_refs": {},
                "uploaded_assets": [],
                "requires_confirmation": True,
                "created_by": "user-3",
                "created_at": now,
                "updated_at": now,
            },
        )

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def test_read_only_and_plan_mode_block_confirmation_with_permission_events(self) -> None:
        AssistantChatRepository.update_owned(
            self.chat_id,
            "user-3",
            {"permission_mode": "read_only"},
        )
        read_only = self.client.post(
            f"/api/v1/assistant/tool-calls/{self.call_id}/confirm",
            json={},
        )
        self.assertEqual(read_only.status_code, 403, read_only.text)
        self.assertEqual(read_only.json()["data"]["detail"]["code"], "read_only_blocked")

        AssistantChatRepository.update_owned(
            self.chat_id,
            "user-3",
            {"permission_mode": "workspace_write", "plan_mode": True},
        )
        plan_mode = self.client.post(
            f"/api/v1/assistant/tool-calls/{self.call_id}/confirm",
            json={},
        )
        self.assertEqual(plan_mode.status_code, 403, plan_mode.text)
        self.assertEqual(plan_mode.json()["data"]["detail"]["code"], "plan_mode_blocked")

        events = AssistantEventRepository.list_all(
            {"chat_id": self.chat_id, "type": "permission.decision"},
            page=1,
            page_size=10,
        )[0]
        self.assertEqual([event["data"]["reason"] for event in events], ["read_only_blocked", "plan_mode_blocked"])
        self.assertEqual([event["data"]["decision"] for event in events], ["denied", "denied"])
