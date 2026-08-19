"""Assistant context compaction command tests."""

from __future__ import annotations

from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantMessageRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.main import app
from app.schemas.assistant_chats import AssistantMessageCreate
from app.services.assistant_chat_service import assistant_chat_service
from app.services.assistant_run_service import AssistantRunService
from app.schemas.assistant_runs import AssistantRunCreate


class AssistantCompactionTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-1", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def _chat_id(self) -> str:
        """创建一个包含可压缩历史的会话。"""
        response = self.client.post(
            "/api/v1/assistant/chats",
            json={
                "title": "压缩会话",
                "messages": [
                    {"role": "user", "content": "请围绕聚合物拉伸实验开展工作"},
                    {"role": "assistant", "content": "已记录实验目标，并完成第一轮方案分析。"},
                    {"role": "user", "content": "重复讨论已解决的数据清洗问题"},
                    {"role": "assistant", "content": "数据清洗问题已解决，无需重复处理。"},
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        chat_id = response.json()["data"]["chat_id"]
        AssistantChatRepository.update_owned(
            chat_id,
            "user-1",
            {
                "plan_mode": True,
                "permission_mode": "read_only",
                "goal": {
                    "goal_id": "goal-1",
                    "objective": "建立聚合物拉伸实验闭环",
                    "status": "active",
                    "created_by": "user-1",
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                },
                "todos": [
                    {
                        "todo_id": "todo-1",
                        "content": "整理拉伸实验结论",
                        "status": "in_progress",
                        "created_at": utc_now(),
                        "updated_at": utc_now(),
                    }
                ],
            },
        )
        return chat_id

    def _tool_call(self, chat_id: str) -> None:
        """保存一个带结果摘要的工具调用。"""
        now = utc_now()
        AssistantToolCallRepository.save(
            "call_id",
            {
                "call_id": "call-compact-1",
                "chat_id": chat_id,
                "created_by": "user-1",
                "message_id": "",
                "tool_id": "algorithm:vertical",
                "tool_name": "Vertical Predictor",
                "phase": "completed",
                "status": "completed",
                "arguments": {},
                "result": {"score": 0.92},
                "result_summary": {"message": "预测置信度 0.92"},
                "events": [],
                "created_at": now,
                "updated_at": now,
            },
        )

    def _execute(self, chat_id: str, line: str = "/compact"):
        """执行一条命令并断言 API 成功返回。"""
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": line},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def _events(self, chat_id: str, event_type: str) -> list[dict]:
        """读取指定类型的会话事件。"""
        return [
            event
            for event in AssistantCommandRunRepository.events_after(
                chat_id,
                "user-1",
                event_types={event_type},
            )
            if event.get("type") == event_type
        ]

    def test_compact_uses_compact_route_snapshot_event_and_server_history(self) -> None:
        chat_id = self._chat_id()
        self._tool_call(chat_id)
        messages_before, total_before = AssistantMessageRepository.list_for_chat(
            chat_id, "user-1", page_size=100
        )
        self.assertEqual(total_before, 4)
        route = {
            "purpose": "compact",
            "provider_id": "provider-a",
            "model_id": "model-fast",
            "route_reason": "purpose_default",
        }
        summary = (
            "用户目标：建立聚合物拉伸实验闭环\n"
            "Active Goal：active\n"
            "Todo 状态：整理拉伸实验结论[in_progress]\n"
            "当前权限与模式：read_only / plan\n"
            "已完成任务：第一轮方案分析和数据清洗\n"
            "当前状态：等待下一轮实验设计\n"
            "关键结论：数据清洗已解决\n"
            "重要文件：experiment.xlsx\n"
            "关键配置：温度 25C\n"
            "未完成任务：整理最终结论\n"
            "活跃工具结果：预测置信度 0.92\n"
            "已压缩：重复对话、已解决问题和冗长过程信息"
        )

        with patch(
            "app.services.assistant_compaction_service.LLMModelService.resolve_route",
            return_value=route,
        ) as resolve_route, patch(
            "app.services.assistant_compaction_service.LLMModelService.complete_text",
            return_value=summary,
        ) as complete_text:
            result = self._execute(chat_id)

        resolve_route.assert_called_once_with(purpose="compact")
        self.assertEqual(
            complete_text.call_args.kwargs["purpose"],
            "compact",
        )
        self.assertEqual(result["status"], "success")
        self.assertIn("上下文已压缩", result["message"])

        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        snapshot = chat["compaction"]
        self.assertEqual(snapshot["cutoff_message_id"], messages_before[-1]["message_id"])
        self.assertIn(messages_before[-1]["message_id"], snapshot["retained_message_ids"])
        self.assertEqual(snapshot["summary"], summary)
        self.assertEqual(snapshot["route"]["purpose"], "compact")
        self.assertEqual(snapshot["summary_method"], "llm")
        self.assertGreater(snapshot["original_token_estimate"], snapshot["token_estimate"])
        self.assertGreaterEqual(snapshot["usage"]["total_tokens"], 0)
        self.assertTrue(snapshot["summary_digest"].startswith("sha256:"))
        self.assertEqual(snapshot["created_by"], "user-1")

        events = self._events(chat_id, "context.compacted")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["data"]["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(
            events[0]["data"]["token_reduction"],
            snapshot["original_token_estimate"] - snapshot["token_estimate"],
        )

        messages_after, total_after = AssistantMessageRepository.list_for_chat(
            chat_id, "user-1", page_size=100
        )
        self.assertEqual(total_after, 4)
        self.assertEqual(
            [item["message_id"] for item in messages_after],
            [item["message_id"] for item in messages_before],
        )

        post_cutoff = assistant_chat_service.create_message(
            chat_id,
            AssistantMessageCreate(role="user", content="基于压缩后的状态继续设计实验"),
            self.user,
        )
        run = AssistantRunService().create(
            chat_id,
            AssistantRunCreate(
                content="",
                user_message_id=post_cutoff.message_id,
                messages=[
                    {
                        "role": "user",
                        "content": "客户端伪造的压缩前完整历史，服务端必须忽略",
                    }
                ],
                context={},
            ),
            self.user,
        )
        persisted_run = AssistantRunRepository.find_one({"run_id": run.run_id}) or {}
        history = persisted_run["request_snapshot"]["messages"]
        history_text = "\n".join(item["content"] for item in history)
        self.assertIn("COMPACTION_SUMMARY", history_text)
        self.assertIn(summary, history_text)
        self.assertIn("基于压缩后的状态继续设计实验", history_text)
        self.assertNotIn("客户端伪造的压缩前完整历史", history_text)
        self.assertLess(len(history), 8)

    def test_compact_falls_back_to_deterministic_summary_when_llm_output_invalid(self) -> None:
        chat_id = self._chat_id()
        route = {
            "purpose": "compact",
            "provider_id": "provider-a",
            "model_id": "model-fast",
            "route_reason": "purpose_default",
        }

        with patch(
            "app.services.assistant_compaction_service.LLMModelService.resolve_route",
            return_value=route,
        ), patch(
            "app.services.assistant_compaction_service.LLMModelService.complete_text",
            return_value=" ",
        ):
            result = self._execute(chat_id)

        self.assertEqual(result["status"], "success")
        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        snapshot = chat["compaction"]
        self.assertEqual(snapshot["summary_method"], "deterministic_fallback")
        for section in (
            "用户目标",
            "Active Goal",
            "Todo 状态",
            "当前权限与模式",
            "已完成任务",
            "当前状态",
            "关键结论",
            "重要文件",
            "关键配置",
            "未完成任务",
            "活跃工具结果",
            "已压缩",
        ):
            self.assertIn(section, snapshot["summary"])

    def test_compact_returns_busy_without_partial_snapshot_when_run_is_active(self) -> None:
        chat_id = self._chat_id()
        now = utc_now()
        AssistantRunRepository.save(
            "run_id",
            {
                "run_id": "asrun-active",
                "trace_id": "trace-active",
                "chat_id": chat_id,
                "created_by": "user-1",
                "user_message_id": "",
                "status": "running",
                "active": True,
                "stage": "running",
                "request_snapshot": {"content": "", "messages": [], "context": {}},
                "events": [],
                "created_at": now,
                "updated_at": now,
            },
        )

        result = self._execute(chat_id)

        self.assertEqual(result["status"], "failed")
        self.assertIn("活动回答", result["message"])
        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        self.assertIsNone(chat["compaction"])
        self.assertEqual(self._events(chat_id, "context.compacted"), [])

    def test_compact_event_failure_rolls_back_snapshot_with_stable_error(self) -> None:
        chat_id = self._chat_id()
        route = {
            "purpose": "compact",
            "provider_id": "provider-a",
            "model_id": "model-fast",
            "route_reason": "purpose_default",
        }

        with patch(
            "app.services.assistant_compaction_service.LLMModelService.resolve_route",
            return_value=route,
        ), patch(
            "app.services.assistant_compaction_service.LLMModelService.complete_text",
            return_value="这是一次有效的上下文压缩摘要，保留目标和任务状态。",
        ), patch(
            "app.services.assistant_compaction_service.AssistantCommandRunRepository.append_chat_event",
        ) as append_event:
            def fail_context_event(_chat: dict, event: dict):
                if event.get("type") == "context.compacted":
                    raise RuntimeError("event store unavailable")
                return None

            append_event.side_effect = fail_context_event
            result = self._execute(chat_id)

        self.assertEqual(result["status"], "failed")
        self.assertIn("有效历史未改变", result["message"])
        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        self.assertIsNone(chat["compaction"])
