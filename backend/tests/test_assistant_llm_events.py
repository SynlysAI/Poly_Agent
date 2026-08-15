"""LLM 请求生命周期事件测试。"""

from __future__ import annotations

from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.llm_context import record_llm_observation_scope, reset_llm_observation_scope
from app.core.time import utc_now
from app.infra.research_engine_repositories import AssistantEventRepository, AssistantRunRepository
from app.services.llm_model_service import LLMModelService


class _Usage:
    prompt_tokens = 12
    completion_tokens = 7
    total_tokens = 19


class _Message:
    content = "ok"


class _Choice:
    message = _Message()
    finish_reason = "stop"


class _Response:
    choices = [_Choice()]
    usage = _Usage()


class _Delta:
    content = "stream-ok"


class _StreamChoice:
    delta = _Delta()


class _StreamChunk:
    choices = [_StreamChoice()]
    usage = _Usage()


class _FakeChatCompletions:
    def __init__(self, response=None, stream_chunks=None, error=None):
        self.response = response
        self.stream_chunks = stream_chunks
        self.error = error

    def create(self, **kwargs):
        if self.error:
            raise self.error
        if self.stream_chunks is not None:
            return iter(self.stream_chunks)
        return self.response


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, response=None, stream_chunks=None, error=None):
        self.chat = _FakeChat(_FakeChatCompletions(response, stream_chunks, error))


class AssistantLlmEventsTest(ComputationTestCase):
    def _run(self, run_id: str) -> dict:
        now = utc_now()
        return {
            "run_id": run_id,
            "chat_id": f"chat_{run_id}",
            "created_by": "llm-event-user",
            "user_message_id": f"message_{run_id}",
            "status": "queued",
            "active": True,
            "stage": "queued",
            "event_seq": 0,
            "events": [],
            "created_at": now,
            "updated_at": now,
            "request_snapshot": {},
            "route": {},
        }

    def _create_run(self, run_id: str) -> None:
        document = self._run(run_id)
        created, _current = AssistantRunRepository.create_active(document)
        self.assertTrue(created)

    def _event_types(self, run_id: str) -> list[str]:
        return [item["type"] for item in AssistantEventRepository.list_for_run(run_id)]

    def _route(self) -> dict:
        return {
            "purpose": "qa",
            "route_reason": "purpose_default",
            "provider_id": "p1",
            "model_id": "m1",
            "capabilities": ["chat"],
            "provider_type": "openai_compatible",
            "provider_config": {"base_url": "https://example.test/v1"},
        }

    def test_complete_text_emits_started_and_usage(self) -> None:
        self._create_run("asrun_llm_text")
        service = LLMModelService()
        with patch.object(service, "_resolve_chat_route", return_value=self._route()):
            with patch.object(service, "_chat_client", return_value=_FakeClient(_Response())):
                record_llm_observation_scope({"run_id": "asrun_llm_text"})
                try:
                    self.assertEqual(
                        service.complete_text(messages=[{"role": "user", "content": "hi"}]),
                        "ok",
                    )
                finally:
                    reset_llm_observation_scope()

        event_types = self._event_types("asrun_llm_text")
        self.assertIn("llm.request.started", event_types)
        self.assertIn("llm.usage.recorded", event_types)
        self.assertNotIn("llm.request.failed", event_types)
        events = AssistantEventRepository.list_for_run("asrun_llm_text")
        usage_event = next(item for item in events if item["type"] == "llm.usage.recorded")
        self.assertEqual(usage_event["data"]["usage"]["total_tokens"], 19)
        self.assertEqual(usage_event["data"]["request_kind"], "final_answer")

    def test_complete_message_emits_tool_proposal_started_and_flush_usage(self) -> None:
        self._create_run("asrun_llm_tool_proposal")
        service = LLMModelService()
        with patch.object(service, "_resolve_chat_route", return_value=self._route()):
            with patch.object(service, "_chat_client", return_value=_FakeClient(_Response())):
                record_llm_observation_scope({
                    "run_id": "asrun_llm_tool_proposal",
                    "call_id": "atc_proposal_pending",
                })
                try:
                    message = service.complete_message(
                        messages=[{"role": "user", "content": "use tool"}],
                        tools=[{"type": "function", "function": {"name": "demo"}}],
                    )
                    service.emit_tool_proposal_usage(
                        call_id="atc_proposal_pending",
                        route=self._route(),
                        usage=_Usage(),
                        finish_reason="stop",
                        request_id="request-tool",
                    )
                finally:
                    reset_llm_observation_scope()

        self.assertEqual(message.content, "ok")
        event_types = self._event_types("asrun_llm_tool_proposal")
        self.assertIn("llm.request.started", event_types)
        self.assertIn("llm.usage.recorded", event_types)
        started = next(
            item for item in AssistantEventRepository.list_for_run("asrun_llm_tool_proposal")
            if item["type"] == "llm.request.started"
        )
        self.assertEqual(started["data"]["request_kind"], "tool_proposal")
        self.assertEqual(started["data"]["tools_count"], 1)
        self.assertEqual(started["call_id"], "atc_proposal_pending")
        usage = next(
            item for item in AssistantEventRepository.list_for_run("asrun_llm_tool_proposal")
            if item["type"] == "llm.usage.recorded"
        )
        self.assertEqual(usage["call_id"], "atc_proposal_pending")
        self.assertEqual(usage["data"]["usage"]["total_tokens"], 19)

    def test_stream_text_emits_usage_from_stream_chunk(self) -> None:
        self._create_run("asrun_llm_stream")
        service = LLMModelService()
        with patch.object(service, "_resolve_chat_route", return_value=self._route()):
            with patch.object(
                service,
                "_chat_client",
                return_value=_FakeClient(stream_chunks=[_StreamChunk()]),
            ):
                record_llm_observation_scope({"run_id": "asrun_llm_stream"})
                try:
                    self.assertEqual(
                        list(service.stream_text(messages=[{"role": "user", "content": "hi"}])),
                        ["stream-ok"],
                    )
                finally:
                    reset_llm_observation_scope()

        event_types = self._event_types("asrun_llm_stream")
        self.assertIn("llm.request.started", event_types)
        self.assertIn("llm.usage.recorded", event_types)
        self.assertNotIn("llm.request.failed", event_types)

    def test_request_failure_emits_failed_event(self) -> None:
        self._create_run("asrun_llm_failed")
        service = LLMModelService()
        with patch.object(service, "_resolve_chat_route", return_value=self._route()):
            with patch.object(
                service,
                "_chat_client",
                return_value=_FakeClient(error=RuntimeError("boom")),
            ):
                record_llm_observation_scope({"run_id": "asrun_llm_failed"})
                try:
                    with self.assertRaisesRegex(RuntimeError, "boom"):
                        service.complete_text(messages=[{"role": "user", "content": "hi"}])
                finally:
                    reset_llm_observation_scope()

        event_types = self._event_types("asrun_llm_failed")
        self.assertIn("llm.request.started", event_types)
        self.assertIn("llm.request.failed", event_types)
        self.assertNotIn("llm.usage.recorded", event_types)

    def test_prompt_snapshot_is_sanitized_and_bounded_by_ttl(self) -> None:
        self._create_run("asrun_llm_snapshot")
        service = LLMModelService()
        with patch.object(service, "_resolve_chat_route", return_value=self._route()):
            with patch.object(service, "_chat_client", return_value=_FakeClient(_Response())):
                record_llm_observation_scope({"run_id": "asrun_llm_snapshot"})
                try:
                    service.complete_message(
                        messages=[
                            {
                                "role": "user",
                                "content": "请用 token=super-secret 回答问题",
                            }
                        ],
                        tools=[],
                    )
                finally:
                    reset_llm_observation_scope()

        document = AssistantRunRepository.find_one({"run_id": "asrun_llm_snapshot"})
        self.assertIsNotNone(document)
        snapshots = document.get("prompt_snapshots") or {}
        self.assertEqual(len(snapshots), 1)
        snapshot = next(iter(snapshots.values()))
        self.assertNotIn("super-secret", str(snapshot["messages"]))
        self.assertIn("token=[REDACTED]", snapshot["messages"][0]["content"])
        self.assertIsNotNone(snapshot["expires_at"])
