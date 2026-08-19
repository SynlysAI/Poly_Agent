"""Assistant command lifecycle event tests."""

from __future__ import annotations

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.research_engine_repositories import AssistantChatRepository
from app.main import app


class AssistantCommandEventTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-2", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def test_command_events_increment_once_and_pair_run_done(self) -> None:
        created = self.client.post("/api/v1/assistant/chats", json={"title": "事件会话"})
        self.assertEqual(created.status_code, 200, created.text)
        chat_id = created.json()["data"]["chat_id"]
        executed = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/status"},
        )
        self.assertEqual(executed.status_code, 200, executed.text)
        failed = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/unknown"},
        )
        self.assertEqual(failed.status_code, 200, failed.text)

        response = self.client.get(f"/api/v1/assistant/chats/{chat_id}/command-events")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["total"], 4)
        self.assertEqual(
            [event["type"] for event in data["items"]],
            ["command.run", "command.done", "command.run", "command.done"],
        )
        self.assertEqual(
            [event["seq"] for event in data["items"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(data["next_after_seq"], 4)
        for index in (0, 2):
            run_id = data["items"][index]["data"]["command_id"]
            done_id = data["items"][index + 1]["data"]["command_id"]
            self.assertEqual(run_id, done_id)

        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        self.assertEqual(chat.get("command_event_seq"), 4)
