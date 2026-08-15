"""Durable LUI assistant run API tests."""

from __future__ import annotations

from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.main import app
from app.services.assistant_run_service import assistant_run_service
from app.infra.research_engine_repositories import AssistantRunRepository


class AssistantRunsApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "run-user-1", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def _chat(self, title: str) -> str:
        return self.client.post("/api/v1/assistant/chats", json={"title": title}).json()["data"]["chat_id"]

    def _run(self, chat_id: str, content: str = "测试问题"):
        return self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json={"content": content, "messages": [], "context": {"mode": "qa"}},
        )

    def test_user_can_have_only_one_active_run_across_chats(self) -> None:
        first_chat = self._chat("一")
        second_chat = self._chat("二")
        first = self._run(first_chat)
        self.assertEqual(first.status_code, 200, first.text)
        same_chat = self._run(first_chat, "第二问")
        other_chat = self._run(second_chat, "另一个会话")
        self.assertEqual(same_chat.status_code, 409, same_chat.text)
        self.assertEqual(other_chat.status_code, 409, other_chat.text)
        detail = other_chat.json()["data"]["detail"]
        self.assertEqual(detail["run_id"], first.json()["data"]["run_id"])
        self.assertEqual(detail["chat_id"], first_chat)

    def test_different_users_can_create_active_runs(self) -> None:
        first_chat = self._chat("用户一")
        self.assertEqual(self._run(first_chat).status_code, 200)
        self.user = {"user_id": "run-user-2", "username": "other", "role": "user", "status": "active"}
        second_chat = self._chat("用户二")
        self.assertEqual(self._run(second_chat).status_code, 200)

    def test_worker_persists_final_answer_and_replay_cursor(self) -> None:
        chat_id = self._chat("执行")
        created = self._run(chat_id)
        run_id = created.json()["data"]["run_id"]
        events = [
            {"type": "status", "stage": "generation", "message": "生成中"},
            {"type": "answer_delta", "delta": "持久化回答"},
            {"type": "final", "data": {"content": "持久化回答", "answer_mode": "fallback", "answer_scope": "unknown", "retrieval_status": "not_needed"}},
        ]
        with patch("app.services.assistant_run_service.stream_chat_assistant", return_value=iter(events)):
            self.assertEqual(assistant_run_service.execute_next("test-worker"), run_id)
        restored = self.client.get(f"/api/v1/assistant/runs/{run_id}").json()["data"]
        self.assertEqual(restored["status"], "completed")
        self.assertEqual(restored["partial_content"], "持久化回答")
        chat = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        self.assertEqual([item["role"] for item in chat["messages"]], ["user", "assistant"])
        all_events = restored["events"]
        cursor = all_events[1]["seq"]
        replay = list(assistant_run_service.events(run_id, self.user, cursor))
        self.assertTrue(replay)
        self.assertTrue(all(item["seq"] > cursor for item in replay))

    def test_cancel_is_idempotent_and_releases_user_lock(self) -> None:
        chat_id = self._chat("取消")
        run_id = self._run(chat_id).json()["data"]["run_id"]
        first = self.client.post(f"/api/v1/assistant/runs/{run_id}/cancel")
        second = self.client.post(f"/api/v1/assistant/runs/{run_id}/cancel")
        self.assertEqual(first.json()["data"]["status"], "canceled")
        self.assertEqual(second.json()["data"]["status"], "canceled")
        self.assertEqual(self._run(chat_id, "取消后重试").status_code, 200)

    def test_worker_persists_resolved_route_and_message_model_meta(self) -> None:
        """run 区分请求模型与实际解析模型，并把模型信息写入消息元数据。"""
        chat_id = self._chat("模型路由")
        created = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json={
                "content": "路由问题",
                "messages": [],
                "context": {
                    "mode": "qa",
                    "model": {"providerId": "requested-provider", "modelId": "requested-model"},
                },
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        run_id = created.json()["data"]["run_id"]
        route = {
            "purpose": "qa",
            "route_reason": "user_selected",
            "requested_provider_id": "requested-provider",
            "requested_model_id": "requested-model",
            "provider_id": "resolved-provider",
            "model_id": "resolved-model",
            "capabilities": ["chat"],
        }
        context_manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "request_kind": "final_answer",
            "route": route,
            "context": {
                "digest": "sha256:context-digest",
                "sections": [
                    {
                        "name": "project_facts",
                        "source": "ProjectGroundingService",
                        "token_estimate": 8,
                        "included": True,
                        "omitted_reason": None,
                    }
                ],
            },
            "tools": [],
        }
        events = [
            {"type": "route.resolved", "route": route},
            {"type": "context.assembled", "manifest": context_manifest},
            {"type": "answer_delta", "delta": "路由回答"},
            {
                "type": "final",
                "data": {
                    "content": "路由回答",
                    "answer_mode": "fallback",
                    "answer_scope": "unknown",
                    "retrieval_status": "not_needed",
                    "grounding_facts": {
                        "llm_route": route,
                        "context": {"digest": "sha256:context-digest"},
                    },
                },
            },
        ]
        with patch("app.services.assistant_run_service.stream_chat_assistant", return_value=iter(events)):
            self.assertEqual(assistant_run_service.execute_next("route-worker"), run_id)

        restored = self.client.get(f"/api/v1/assistant/runs/{run_id}").json()["data"]
        self.assertEqual(restored["provider_id"], "resolved-provider")
        self.assertEqual(restored["model_id"], "resolved-model")
        self.assertEqual(restored["route"]["route_reason"], "user_selected")
        self.assertEqual(restored["route"]["requested_model_id"], "requested-model")
        self.assertEqual(restored["request_manifests"]["final_answer"], context_manifest)
        self.assertTrue(any(event["type"] == "route.resolved" for event in restored["events"]))
        self.assertTrue(any(event["type"] == "context.assembled" for event in restored["events"]))

        chat = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        assistant_message = next(item for item in chat["messages"] if item["role"] == "assistant")
        self.assertEqual(assistant_message["metadata"]["llm_route"]["model_id"], "resolved-model")
        self.assertEqual(assistant_message["metadata"]["context_digest"], "sha256:context-digest")

    def test_run_access_is_owner_scoped(self) -> None:
        chat_id = self._chat("私有")
        run_id = self._run(chat_id).json()["data"]["run_id"]
        self.user = {"user_id": "run-user-2", "username": "other", "role": "user", "status": "active"}
        self.assertEqual(self.client.get(f"/api/v1/assistant/runs/{run_id}").status_code, 403)

    def test_tool_continuation_reuses_user_message(self) -> None:
        chat_id = self._chat("工具继续")
        first_run = self._run(chat_id)
        first_run_id = first_run.json()["data"]["run_id"]
        self.client.post(f"/api/v1/assistant/runs/{first_run_id}/cancel")
        user_message_id = first_run.json()["data"]["user_message_id"]
        continuation = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json={
                "content": "",
                "user_message_id": user_message_id,
                "messages": [{"role": "user", "content": "测试问题"}],
                "context": {"tool_call_ids": ["call-1"]},
            },
        )
        self.assertEqual(continuation.status_code, 200, continuation.text)
        chat = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        self.assertEqual(len(chat["messages"]), 1)

    def test_existing_run_message_is_not_duplicated_after_recovery(self) -> None:
        chat_id = self._chat("幂等恢复")
        created = self._run(chat_id)
        run_id = created.json()["data"]["run_id"]
        claimed = AssistantRunRepository.claim_next("crashed-worker", assistant_run_service._public(
            AssistantRunRepository.find_one({"run_id": run_id})
        ).created_at)
        message = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/messages",
            json={"role": "assistant", "content": "已落库", "metadata": {"run_id": run_id}},
        ).json()["data"]
        self.assertIsNotNone(claimed)
        AssistantRunRepository.update_if_status(
            run_id, ["running"], {"status": "queued", "worker_id": None, "started_at": None, "heartbeat_at": None}
        )
        events = [
            {"type": "answer_delta", "delta": "已落库"},
            {"type": "final", "data": {"content": "已落库", "answer_mode": "fallback", "answer_scope": "unknown", "retrieval_status": "not_needed"}},
        ]
        with patch("app.services.assistant_run_service.stream_chat_assistant", return_value=iter(events)):
            assistant_run_service.execute_next("recovery-worker")
        restored = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        assistants = [item for item in restored["messages"] if item["role"] == "assistant"]
        self.assertEqual(len(assistants), 1)
        self.assertEqual(assistants[0]["message_id"], message["message_id"])

    def test_metrics_record_conflicts_and_null_token_usage(self) -> None:
        chat_id = self._chat("指标")
        self.assertEqual(self._run(chat_id).status_code, 200)
        self.assertEqual(self._run(chat_id, "冲突").status_code, 409)
        metrics = assistant_run_service.metrics(created_by=self.user["user_id"])
        self.assertEqual(metrics["active"], 1)
        self.assertEqual(metrics["conflicts"], 1)
        self.assertIsNone(metrics["total_tokens"])
