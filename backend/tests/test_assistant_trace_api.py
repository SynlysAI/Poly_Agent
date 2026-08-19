"""LUI Execution Trace API 与 SSE 测试。"""

from __future__ import annotations

from datetime import timedelta

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.core.time import utc_now
from app.infra.research_engine_repositories import (
    AssistantEventRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.main import app
from app.services.assistant_run_service import assistant_run_service


class AssistantTraceApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "trace-api-user", "username": "trace", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.now = utc_now()
        run = {
            "run_id": "asrun_trace_api",
            "trace_id": "asrun_trace_api",
            "chat_id": "chat_trace_api",
            "created_by": self.user["user_id"],
            "user_message_id": "msg_trace_api",
            "status": "completed",
            "active": False,
            "stage": "completed",
            "event_seq": 0,
            "events": [],
            "created_at": self.now,
            "updated_at": self.now,
            "started_at": self.now,
            "finished_at": self.now + timedelta(milliseconds=10),
            "request_snapshot": {"context": {}},
        }
        AssistantRunRepository.save("run_id", run)
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "status", "stage": "intent", "message": "正在识别问题范围", "at": self.now},
        )
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "final", "data": {"content": "完成"}, "at": self.now + timedelta(milliseconds=10)},
        )

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def test_trace_snapshot_is_owner_scoped(self) -> None:
        response = self.client.get("/api/v1/assistant/traces/asrun_trace_api")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["trace_id"], "asrun_trace_api")
        self.assertEqual(data["status"], "completed")
        self.assertTrue(data["steps"])
        self.assertTrue(all(step["details"]["source_event_refs"] for step in data["steps"]))

        self.user = {"user_id": "other-user", "username": "other", "role": "admin", "status": "active"}
        forbidden = self.client.get("/api/v1/assistant/traces/asrun_trace_api")
        self.assertEqual(forbidden.status_code, 403)

        missing = self.client.get("/api/v1/assistant/traces/not_exists")
        self.assertEqual(missing.status_code, 404)

    def test_trace_sse_ends_after_terminal_snapshot(self) -> None:
        with self.client.stream("GET", "/api/v1/assistant/traces/asrun_trace_api/events") as stream:
            self.assertEqual(stream.status_code, 200)
            body = b"".join(stream.iter_bytes()).decode("utf-8")
        self.assertIn("trace.step", body)
        self.assertIn("trace.end", body)
        self.assertNotIn("trace.step\\\": {}", body)

    def test_run_creation_and_continuation_context_share_trace_id(self) -> None:
        chat_id = self.client.post(
            "/api/v1/assistant/chats",
            json={"title": "Trace 身份"},
        ).json()["data"]["chat_id"]
        created = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json={"content": "预测 CCO", "messages": [], "context": {"mode": "qa", "trace_id": "should-be-ignored"}},
        )
        self.assertEqual(created.status_code, 200, created.text)
        run = created.json()["data"]
        self.assertEqual(run["trace_id"], run["run_id"])
        events = AssistantEventRepository.list_for_trace(run["trace_id"])
        self.assertTrue(events)
        self.assertTrue(all(event["trace_id"] == run["trace_id"] for event in events))

        continuation_context = assistant_run_service._continuation_context(
            {
                "call_id": "atc_trace_api",
                "trace_id": run["trace_id"],
                "assistant_run_id": run["trace_id"],
                "chat_id": chat_id,
                "tool_id": "algorithm:demo",
            },
            {},
            "message_trace_api",
        )
        self.assertEqual(continuation_context["trace_id"], run["trace_id"])

        AssistantRunRepository.update_fields(
            "run_id",
            run["run_id"],
            {"status": "completed", "active": False},
        )
        AssistantToolCallRepository.save(
            "call_id",
            {
                "call_id": "atc_trace_api",
                "trace_id": run["trace_id"],
                "assistant_run_id": run["trace_id"],
                "chat_id": chat_id,
                "created_by": self.user["user_id"],
                "tool_id": "algorithm:demo",
                "algorithm_id": "demo",
                "tool_name": "Demo",
                "phase": "completed",
                "created_at": self.now,
                "updated_at": self.now,
            },
        )
        continued = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json={
                "content": "继续生成最终回答",
                "messages": [],
                "context": {"mode": "qa", "tool_call_ids": ["atc_trace_api"]},
            },
        )
        self.assertEqual(continued.status_code, 200, continued.text)
        self.assertEqual(continued.json()["data"]["trace_id"], run["trace_id"])

    def test_trace_batch_endpoint_returns_accessible_traces_and_skips_missing(self) -> None:
        response = self.client.get(
            "/api/v1/assistant/traces/batch",
            params=[("trace_ids", "asrun_trace_api"), ("trace_ids", "missing_trace")],
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual([item["trace_id"] for item in data["items"]], ["asrun_trace_api"])
