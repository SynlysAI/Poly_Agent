"""会话级 Execution Trace、收尾命令与控制面回归测试。"""

from __future__ import annotations

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.core.time import utc_now
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.main import app


class AssistantChatTraceResetClearTest(ComputationTestCase):
    """验证 PR-06 的 chat scope 回放与安全收尾命令。"""

    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "chat-trace-user", "username": "trace", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def _chat_id(self) -> str:
        """创建并返回一个当前用户拥有的会话。"""
        response = self.client.post("/api/v1/assistant/chats", json={"title": "PR06 会话"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["chat_id"]

    def _execute(self, chat_id: str, line: str, payload: dict | None = None) -> dict:
        """执行命令并断言 API 成功。"""
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": line, "payload": payload or {}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_chat_trace_merges_commands_control_and_run_events_with_cursor(self) -> None:
        chat_id = self._chat_id()
        self.assertEqual(self._execute(chat_id, "/plan")["status"], "success")
        self.assertEqual(self._execute(chat_id, "/goal 构建可控聚合实验方案")["status"], "success")

        run = {
            "run_id": "asrun_chat_trace",
            "trace_id": "asrun_chat_trace",
            "chat_id": chat_id,
            "created_by": self.user["user_id"],
            "user_message_id": "msg_chat_trace",
            "status": "completed",
            "active": False,
            "stage": "completed",
            "event_seq": 0,
            "events": [],
        }
        AssistantRunRepository.save("run_id", run)
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "final", "data": {"content": "实验方案完成"}, "at": utc_now()},
        )
        AssistantToolCallRepository.save(
            "call_id",
            {
                "call_id": "atc_chat_trace",
                "trace_id": run["trace_id"],
                "assistant_run_id": run["run_id"],
                "chat_id": chat_id,
                "created_by": self.user["user_id"],
                "tool_id": "algorithm:demo",
                "tool_name": "Demo",
                "phase": "completed",
                "event_seq": 0,
                "events": [],
            },
        )
        AssistantToolCallRepository.append_event(
            "atc_chat_trace",
            {"type": "tool_call", "phase": "completed", "tool_name": "Demo", "at": utc_now()},
        )

        response = self.client.get(f"/api/v1/assistant/chats/{chat_id}/trace")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["chat_id"], chat_id)
        self.assertGreater(data["next_after_seq"], 0)
        types = {step["type"] for step in data["steps"]}
        self.assertIn("command", types)
        self.assertIn("control", types)
        tool_step = next(step for step in data["steps"] if step["step_id"] == "tool:atc_chat_trace")
        self.assertEqual(tool_step["status"], "success")
        self.assertFalse(any(
            ref["stream"] == "embedded_event"
            for ref in tool_step["details"]["source_event_refs"]
        ))
        self.assertTrue(all(step["details"]["source_event_refs"] for step in data["steps"]))
        cursor = data["next_after_seq"]

        self.assertEqual(self._execute(chat_id, "/status")["status"], "success")
        incremental = self.client.get(
            f"/api/v1/assistant/chats/{chat_id}/trace",
            params={"after_seq": cursor},
        )
        self.assertEqual(incremental.status_code, 200, incremental.text)
        incremental_data = incremental.json()["data"]
        self.assertTrue(incremental_data["steps"])
        self.assertTrue(all(step["type"] == "command" for step in incremental_data["steps"]))
        self.assertGreater(incremental_data["next_after_seq"], cursor)

        filtered = self.client.get(
            f"/api/v1/assistant/chats/{chat_id}/trace",
            params={"event_types": "goal.changed"},
        )
        self.assertEqual(filtered.status_code, 200, filtered.text)
        filtered_steps = filtered.json()["data"]["steps"]
        self.assertTrue(filtered_steps)
        self.assertTrue(all("goal.changed" in step["details"]["event_types"] for step in filtered_steps))

        other_user = {**self.user, "user_id": "other-chat-trace-user"}
        app.dependency_overrides[get_current_user] = lambda: other_user
        forbidden = self.client.get(f"/api/v1/assistant/chats/{chat_id}/trace")
        self.assertEqual(forbidden.status_code, 403)

    def test_reset_requires_confirmation_and_preserves_audit_history(self) -> None:
        chat_id = self._chat_id()
        self._execute(chat_id, "/plan")
        self._execute(chat_id, "/goal 保留审计的目标")
        self._execute(chat_id, "/permission read-only")

        confirmation = self._execute(chat_id, "/reset", {"canceled": False})
        self.assertEqual(confirmation["status"], "interaction")
        self.assertEqual(confirmation["interaction"]["kind"], "confirmation")

        reset = self._execute(chat_id, "/reset confirm")
        self.assertEqual(reset["status"], "success")
        state = reset["state_after"]
        self.assertFalse(state["plan_mode"])
        self.assertEqual(state["permission_mode"], "workspace_write")
        self.assertIsNone(state["goal"])
        self.assertEqual(state["todos"], [])

        commands, total = AssistantCommandRunRepository.list_runs_for_chat(
            chat_id,
            self.user["user_id"],
        )
        self.assertEqual(total, 5)
        self.assertTrue(all(item.get("status") != "running" for item in commands))
        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        self.assertGreaterEqual(int(chat.get("command_event_seq") or 0), 10)

    def test_clear_creates_new_chat_without_deleting_old_session(self) -> None:
        old_chat_id = self._chat_id()
        self._execute(old_chat_id, "/goal 旧会话目标")

        result = self._execute(old_chat_id, "/clear")
        self.assertEqual(result["status"], "success")
        new_chat = result["chat"]
        self.assertNotEqual(new_chat["chat_id"], old_chat_id)
        self.assertFalse(new_chat["plan_mode"])
        self.assertEqual(new_chat["permission_mode"], "workspace_write")
        self.assertEqual(result["state_after"]["chat_id"], new_chat["chat_id"])
        self.assertIsNone(result["state_after"]["goal"])

        old_chat = AssistantChatRepository.find_one({"chat_id": old_chat_id}) or {}
        self.assertEqual(old_chat.get("goal", {}).get("objective"), "旧会话目标")
        old_commands, old_total = AssistantCommandRunRepository.list_runs_for_chat(
            old_chat_id,
            self.user["user_id"],
        )
        self.assertEqual(old_total, 2)
        self.assertEqual({item["name"] for item in old_commands}, {"goal", "clear"})
