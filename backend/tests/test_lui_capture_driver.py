"""LUI 录制事实驱动器测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from scripts.run_lui_capture import (
    LuiCaptureClient,
    build_run_context,
    execute_task,
    final_tool_call_ids,
    select_tasks,
    should_auto_confirm,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.lui.schemas import GoldenTask  # noqa: E402


def _task(task_id: str = "LUI-PF-0001", category: str = "project_fact") -> GoldenTask:
    """构建最小 Golden 任务。"""
    return GoldenTask.model_validate(
        {
            "id": task_id,
            "category": category,
            "difficulty": "easy",
            "mode": "qa",
            "messages": [{"role": "user", "content": "预测 C=C(F)F 的介电常数。"}],
            "context": {"selected_tool_ids": ["algorithm:demo"]},
            "expected": {"task_success": True},
        }
    )


class SelectTasksTest(unittest.TestCase):
    def test_filters_by_category_and_limit(self) -> None:
        """分类白名单与数量限制应共同生效。"""
        tasks = [_task(f"LUI-PF-{index:04d}") for index in range(1, 6)]
        selected = select_tasks(tasks, categories=["project_fact"], only_task=None, limit=2)
        self.assertEqual([item.id for item in selected], ["LUI-PF-0001", "LUI-PF-0002"])

    def test_only_task_must_exist(self) -> None:
        """指定不存在的任务 ID 应报错。"""
        with self.assertRaisesRegex(ValueError, "task not found"):
            select_tasks([_task()], categories=None, only_task="LUI-XX-9999", limit=None)

    def test_empty_selection_is_rejected(self) -> None:
        """无匹配任务应报错，避免空批次误判成功。"""
        with self.assertRaisesRegex(ValueError, "no golden tasks"):
            select_tasks([_task()], categories=["refusal_boundary"], only_task=None, limit=None)


class RunContextTest(unittest.TestCase):
    def test_context_merges_evaluation_and_model(self) -> None:
        """评测三字段、任务上下文与固定模型应合并进 run context。"""
        context = build_run_context(
            _task(),
            evaluation_id="lui-eval-full-test",
            evaluation_version="2026.08.28",
            provider_id="deepseek",
            model_id="deepseek-chat",
        )
        self.assertEqual(context["evaluation_id"], "lui-eval-full-test")
        self.assertEqual(context["task_id"], "LUI-PF-0001")
        self.assertEqual(context["evaluation_version"], "2026.08.28")
        self.assertEqual(context["mode"], "qa")
        self.assertEqual(context["selected_tool_ids"], ["algorithm:demo"])
        self.assertEqual(context["model"], {"providerId": "deepseek", "modelId": "deepseek-chat"})


class FinalToolCallTest(unittest.TestCase):
    def test_extracts_call_ids_from_last_final_event(self) -> None:
        """应从最后一个 final 事件提取去重后的 call_id。"""
        run = {
            "events": [
                {"type": "status"},
                {
                    "type": "final",
                    "data": {
                        "tool_calls": [
                            {"call_id": "atc_1"},
                            {"call_id": "atc_1"},
                            {"call_id": ""},
                            {"call_id": "atc_2"},
                        ]
                    },
                },
                {
                    "type": "final",
                    "data": {"tool_calls": [{"call_id": "atc_latest"}]},
                },
            ]
        }
        self.assertEqual(final_tool_call_ids(run), ["atc_latest"])

    def test_no_final_event_returns_empty(self) -> None:
        """无 final 事件（纯问答）应返回空列表。"""
        self.assertEqual(final_tool_call_ids({"events": [{"type": "status"}]}), [])


class AutoConfirmPolicyTest(unittest.TestCase):
    def test_only_confirms_complete_proposals(self) -> None:
        """仅 awaiting_confirmation 自动确认；缺参提案保持原样。"""
        self.assertTrue(should_auto_confirm({"phase": "awaiting_confirmation"}))
        self.assertFalse(should_auto_confirm({"phase": "awaiting_input"}))
        self.assertFalse(should_auto_confirm({"phase": "completed"}))
        self.assertFalse(should_auto_confirm({}))


class _StubClient:
    """覆盖提案、缺参与续答链路的桩客户端。"""

    def __init__(self) -> None:
        self.confirmed: list[str] = []
        self.continuation_started = False

    def create_chat(self, task, evaluation_id):
        """返回桩会话。"""
        return {"chat_id": f"chat_{task.id}"}

    def create_run(self, chat_id, task, context):
        """返回携带两类工具提案的桩 run。"""
        return {"run_id": f"asrun_{task.id}"}

    def get_run(self, run_id):
        """返回已完成 run 与 final 事件。"""
        return {
            "run_id": run_id,
            "status": "completed",
            "events": [
                {
                    "type": "final",
                    "data": {
                        "tool_calls": [
                            {"call_id": "atc_confirm"},
                            {"call_id": "atc_missing"},
                        ]
                    },
                }
            ],
        }

    def get_tool_call(self, call_id):
        """返回工具调用状态。"""
        if call_id == "atc_confirm":
            return {
                "call_id": call_id,
                "phase": "awaiting_confirmation",
                "continuation_run_id": (
                    "asrun_continuation" if self.continuation_started else ""
                ),
                "continuation_state": "pending" if not self.continuation_started else "scheduled",
            }
        return {"call_id": call_id, "phase": "awaiting_input"}

    def confirm_tool_call(self, call_id):
        """确认提案并启动续答。"""
        self.confirmed.append(call_id)
        self.continuation_started = True
        return {"call_id": call_id, "phase": "queued"}


class ExecuteTaskTest(unittest.TestCase):
    def test_confirms_complete_proposals_and_waits_continuation(self) -> None:
        """参数齐全提案应自动确认并等待续答完成；缺参提案不确认。"""
        client = _StubClient()
        record = execute_task(
            client,
            _task(),
            evaluation_id="lui-eval-full-test",
            evaluation_version="2026.08.28",
            provider_id=None,
            model_id=None,
            timeout_seconds=5,
            poll_interval=0,
        )
        self.assertTrue(record["ok"], record)
        self.assertEqual(record["confirmed_calls"], ["atc_confirm"])
        self.assertEqual(client.confirmed, ["atc_confirm"])


class ApiErrorDetailTest(unittest.TestCase):
    def test_request_error_includes_backend_detail(self) -> None:
        """HTTP 错误应透出后端 detail，便于定位工具目录/权限缺口。"""
        from unittest.mock import Mock

        client = LuiCaptureClient("http://test")
        response = Mock()
        response.status_code = 403
        response.json.return_value = {"detail": "算法工具不可用或当前用户无权限调用"}
        client.client = Mock()
        client.client.request.return_value = response
        client.token = "token"
        with self.assertRaisesRegex(RuntimeError, "算法工具不可用"):
            client.create_chat(_task(), "lui-eval-full-test")


if __name__ == "__main__":
    unittest.main()


class CleanupOrderTest(unittest.TestCase):
    def test_facts_are_captured_before_cleanup(self) -> None:
        """清理会话前必须先抓取事实，避免消息与工具调用被级联删除。"""
        from unittest.mock import patch

        from scripts.run_lui_capture import main as capture_main

        events: list[str] = []

        class CleanupStubClient:
            def login(self, username: str, password: str) -> None:
                """记录登录桩。"""

            def delete_chat(self, chat_id: str) -> None:
                """记录清理动作。"""
                events.append(f"delete:{chat_id}")

        task = _task()
        record = {
            "task_id": task.id,
            "chat_id": "chat_cleanup",
            "run_id": "run_cleanup",
            "ok": True,
            "confirmed_calls": [],
            "error": "",
        }

        def fake_capture(evaluation_id: str) -> dict:
            events.append("capture")
            return {}

        def fake_write(facts_dir, records, captured) -> list[str]:
            events.append("write")
            return []

        with (
            patch("scripts.run_lui_capture.load_dataset", return_value=[task]),
            patch("scripts.run_lui_capture.LuiCaptureClient", return_value=CleanupStubClient()),
            patch("scripts.run_lui_capture.execute_task", return_value=record),
            patch(
                "scripts.run_lui_capture.capture_facts_by_evaluation",
                side_effect=fake_capture,
            ),
            patch("scripts.run_lui_capture.write_facts", side_effect=fake_write),
        ):
            exit_code = capture_main(
                [
                    "--evaluation-id",
                    "lui-eval-cleanup-test",
                    "--dataset",
                    "unused",
                    "--cleanup-chats",
                    "--username",
                    "admin",
                    "--password",
                    "admin",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, ["capture", "write", "delete:chat_cleanup"])
