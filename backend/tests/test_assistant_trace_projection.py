"""LUI Execution Trace 投影服务测试。"""

from __future__ import annotations

from datetime import timedelta

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.time import utc_now
from app.infra.research_engine_repositories import (
    AssistantEventRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.services.assistant_trace_service import assistant_trace_service


class AssistantTraceProjectionTest(ComputationTestCase):
    """验证 Trace 只从真实事件投影，并能串起工具与续答链路。"""

    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "trace-user", "username": "trace", "role": "user", "status": "active"}
        self.now = utc_now()

    def _run(self, run_id: str, *, status: str = "completed", offset_seconds: int = 0) -> dict:
        """构造属于同一条 Trace 的 AssistantRun 文档。"""
        timestamp = self.now + timedelta(seconds=offset_seconds)
        document = {
            "run_id": run_id,
            "trace_id": "asrun_trace_root",
            "chat_id": "chat_trace",
            "created_by": self.user["user_id"],
            "user_message_id": "msg_trace_user",
            "status": status,
            "active": False,
            "stage": status,
            "event_seq": 0,
            "events": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "started_at": timestamp,
            "finished_at": timestamp if status in {"completed", "failed", "canceled"} else None,
            "request_snapshot": {"context": {}},
        }
        AssistantRunRepository.save("run_id", document)
        return document

    def _tool_call(self, phase: str = "awaiting_confirmation") -> dict:
        """构造同一条 Trace 下的算法工具调用。"""
        document = {
            "call_id": "atc_trace_tool",
            "trace_id": "asrun_trace_root",
            "assistant_run_id": "asrun_trace_root",
            "chat_id": "chat_trace",
            "created_by": self.user["user_id"],
            "tool_id": "algorithm:vertical",
            "algorithm_id": "vertical",
            "tool_name": "Vertical Predictor",
            "phase": phase,
            "arguments": {"smiles": "CCO", "api_key": "secret-value"},
            "artifact_refs": [{"artifact_id": "artifact-1", "name": "result.json"}],
            "result_summary": {"score": 0.8},
            "event_seq": 0,
            "events": [],
            "created_at": self.now,
            "updated_at": self.now,
        }
        AssistantToolCallRepository.save("call_id", document)
        return document

    def test_projection_creates_safe_steps_from_real_events(self) -> None:
        root = self._run("asrun_trace_root", status="running")
        base = self.now
        events = [
            {"type": "status", "stage": "intent", "message": "正在识别问题范围", "at": base},
            {"type": "context.assembly.started", "request_kind": "final_answer", "at": base + timedelta(milliseconds=100)},
            {
                "type": "context.assembled",
                "request_kind": "final_answer",
                "manifest": {
                    "context": {"digest": "sha256:context", "token_estimate": 100},
                    "sections": [{"name": "project", "source": "project_facts", "included": True, "token_estimate": 80}],
                },
                "at": base + timedelta(milliseconds=600),
            },
            {"type": "llm.request.started", "request_id": "req-1", "provider_id": "openai", "model_id": "gpt-test", "request_kind": "final_answer", "at": base + timedelta(milliseconds=700)},
            {"type": "llm.usage.recorded", "request_id": "req-1", "usage": {"total_tokens": 20}, "at": base + timedelta(milliseconds=1200)},
            {"type": "final", "data": {"content": "完成"}, "at": base + timedelta(milliseconds=1300)},
        ]
        for event in events:
            self.assertTrue(AssistantRunRepository.append_event(root["run_id"], event))

        trace = assistant_trace_service.get("asrun_trace_root", self.user)

        self.assertEqual(trace.trace_id, "asrun_trace_root")
        self.assertEqual(trace.status, "completed")
        self.assertTrue(trace.steps)
        self.assertTrue(all(step.details.source_event_refs for step in trace.steps))
        self.assertIn("think", [step.type for step in trace.steps])
        self.assertIn("context", [step.type for step in trace.steps])
        self.assertIn("tool_call", [step.type for step in trace.steps])
        self.assertIn("final", [step.type for step in trace.steps])

        context = next(step for step in trace.steps if step.type == "context")
        self.assertEqual(context.status, "success")
        self.assertTrue(context.details.duration_known)
        self.assertEqual(context.duration_ms, 500)
        llm = next(step for step in trace.steps if step.tool_type == "llm")
        self.assertEqual(llm.tool_name, "openai / gpt-test")
        self.assertEqual(llm.details.provider_id, "openai")
        final = next(step for step in trace.steps if step.type == "final")
        self.assertEqual(final.status, "success")
        self.assertGreaterEqual(trace.summary.total_steps, 4)
        self.assertEqual(trace.summary.llm_calls, 1)
        self.assertEqual(trace.summary.duration_known, True)

    def test_tool_approval_result_artifact_and_continuation_are_linked(self) -> None:
        root = self._run("asrun_trace_root", status="completed")
        continuation = self._run("asrun_trace_continuation", status="completed", offset_seconds=5)
        call = self._tool_call(phase="completed")
        base = self.now + timedelta(seconds=1)
        run_events = [
            {"type": "route.resolved", "route": {"provider_id": "p", "model_id": "m"}, "at": base},
            {"type": "final", "data": {"content": "已生成算法调用，请确认参数后执行。", "tool_calls": []}, "at": base + timedelta(milliseconds=10)},
        ]
        for event in run_events:
            AssistantRunRepository.append_event(root["run_id"], event)
        AssistantRunRepository.append_event(
            continuation["run_id"],
            {"type": "final", "data": {"content": "最终回答"}, "at": base + timedelta(seconds=2)},
        )
        tool_events = [
            {"type": "tool_call", "phase": "requested", "call_id": call["call_id"], "tool_name": call["tool_name"], "arguments": call["arguments"], "at": base + timedelta(milliseconds=20)},
            {"type": "tool_call", "phase": "awaiting_confirmation", "call_id": call["call_id"], "tool_name": call["tool_name"], "at": base + timedelta(milliseconds=30)},
            {"type": "tool.confirmed", "call_id": call["call_id"], "arguments": {"smiles": "CCC"}, "at": base + timedelta(milliseconds=40)},
            {"type": "tool_call", "phase": "running", "call_id": call["call_id"], "tool_name": call["tool_name"], "at": base + timedelta(milliseconds=50)},
            {
                "type": "tool_call",
                "phase": "completed",
                "call_id": call["call_id"],
                "tool_name": call["tool_name"],
                "arguments": call["arguments"],
                "result_summary": call["result_summary"],
                "artifact_refs": call["artifact_refs"],
                "at": base + timedelta(milliseconds=100),
            },
        ]
        for event in tool_events:
            self.assertTrue(AssistantToolCallRepository.append_event(call["call_id"], event))
        AssistantToolCallRepository.append_event(
            call["call_id"],
            {
                "type": "tool.continuation.run_created",
                "call_id": call["call_id"],
                "continuation_run_id": continuation["run_id"],
                "created_at": base + timedelta(milliseconds=110),
            },
        )

        trace = assistant_trace_service.get("asrun_trace_root", self.user)
        types = [step.type for step in trace.steps]

        self.assertIn("tool_call", types)
        self.assertIn("approval", types)
        self.assertIn("tool_result", types)
        self.assertIn("write", types)
        self.assertIn("final", types)
        self.assertEqual(trace.status, "completed")
        approval = next(step for step in trace.steps if step.type == "approval")
        self.assertEqual(approval.status, "success")
        tool_step = next(step for step in trace.steps if step.step_id == "tool:atc_trace_tool")
        self.assertEqual(tool_step.status, "success")
        result = next(step for step in trace.steps if step.type == "tool_result")
        self.assertEqual(result.parent_step_id, "tool:atc_trace_tool")
        write = next(step for step in trace.steps if step.type == "write")
        self.assertEqual(write.parent_step_id, "result:atc_trace_tool")
        self.assertEqual(trace.summary.tool_calls, 1)
        self.assertEqual(trace.summary.approvals, 1)
        self.assertEqual(trace.summary.artifacts, 1)
        self.assertEqual(trace.summary.file_writes, 1)
        self.assertNotIn("secret-value", trace.model_dump_json())

    def test_pending_tool_suppresses_proposal_final_and_waits_approval(self) -> None:
        root = self._run("asrun_trace_root", status="completed")
        call = self._tool_call(phase="awaiting_confirmation")
        AssistantRunRepository.append_event(
            root["run_id"],
            {"type": "final", "data": {"content": "已生成算法调用，请确认参数后执行。"}, "at": self.now},
        )
        AssistantToolCallRepository.append_event(
            call["call_id"],
            {
                "type": "tool_call",
                "phase": "awaiting_confirmation",
                "call_id": call["call_id"],
                "tool_name": call["tool_name"],
                "at": self.now,
            },
        )

        trace = assistant_trace_service.get("asrun_trace_root", self.user)

        self.assertEqual(trace.status, "waiting_approval")
        self.assertNotIn("final", [step.type for step in trace.steps])
        approval = next(step for step in trace.steps if step.type == "approval")
        self.assertEqual(approval.status, "waiting")
        self.assertEqual(approval.details.next_action, "等待用户确认后执行")

    def test_legacy_documents_without_trace_id_are_recovered(self) -> None:
        root = self._run("asrun_trace_root")
        root.pop("trace_id")
        AssistantRunRepository.save("run_id", root)
        call = self._tool_call()
        call.pop("trace_id")
        call["assistant_run_id"] = "asrun_trace_root"
        AssistantToolCallRepository.save("call_id", call)
        AssistantRunRepository.append_event(
            root["run_id"],
            {"type": "status", "stage": "intent", "message": "正在识别问题范围", "at": self.now},
        )
        AssistantToolCallRepository.append_event(
            call["call_id"],
            {"type": "tool_call", "phase": "awaiting_confirmation", "call_id": call["call_id"], "at": self.now},
        )

        trace = assistant_trace_service.get("asrun_trace_root", self.user)

        self.assertEqual(trace.trace_id, "asrun_trace_root")
        self.assertEqual(trace.status, "waiting_approval")
        self.assertIn("approval", [step.type for step in trace.steps])
        self.assertTrue(all(step.details.source_event_refs for step in trace.steps))

    def test_incremental_yield_reemits_updated_existing_step(self) -> None:
        """确认同一 step_id 在后续事件到达时可再次下发状态更新。"""
        root = self._run("asrun_trace_root", status="completed")
        call = self._tool_call(phase="awaiting_confirmation")
        AssistantToolCallRepository.append_event(
            call["call_id"],
            {
                "type": "tool_call",
                "phase": "awaiting_confirmation",
                "call_id": call["call_id"],
                "tool_name": call["tool_name"],
                "at": self.now,
            },
        )

        trace = assistant_trace_service.get("asrun_trace_root", self.user)
        emitted: set[str] = set()
        initial = list(assistant_trace_service._yield_steps(trace, emitted))
        self.assertTrue(
            any(
                item["step"]["step_id"] == "tool:atc_trace_tool"
                and item["step"]["status"] == "waiting"
                for item in initial
            )
        )

        AssistantToolCallRepository.append_event(
            call["call_id"],
            {
                "type": "tool.confirmed",
                "call_id": call["call_id"],
                "arguments": {"smiles": "CCC"},
                "at": self.now + timedelta(seconds=1),
            },
        )
        updated = assistant_trace_service.get("asrun_trace_root", self.user)
        confirmed_event = next(
            event
            for event in AssistantEventRepository.list_for_run(root["run_id"])
            if event.get("type") == "tool.confirmed"
        )
        increments = list(
            assistant_trace_service._yield_steps(
                updated,
                emitted,
                {str(confirmed_event.get("event_id") or "")},
            )
        )

        self.assertTrue(
            any(
                item["step"]["step_id"] == "tool:atc_trace_tool"
                and item["step"]["status"] == "running"
                for item in increments
            )
        )

    def test_projection_normalizes_naive_timestamps_to_utc(self) -> None:
        """兼容 SQLite/历史事件返回的无时区时间，避免跨流排序失败。"""
        parsed = assistant_trace_service._parse_datetime("2026-08-16T01:00:00")
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)
