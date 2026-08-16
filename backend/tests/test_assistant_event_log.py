"""Assistant append-only event log tests."""

from __future__ import annotations

from datetime import datetime

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


class AssistantEventLogTest(ComputationTestCase):
    def _run(self, run_id: str = "asrun_event_1") -> dict:
        """Create a minimal assistant run document for event persistence tests."""
        now = utc_now()
        return {
            "run_id": run_id,
            "chat_id": "chat_event_1",
            "created_by": "event-user-1",
            "user_message_id": "message_event_1",
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

    def test_append_event_dual_writes_and_replays_legacy_stream(self) -> None:
        document = self._run()
        self.assertTrue(AssistantRunRepository.create_active(document)[0])

        first = AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "status", "stage": "queued", "message": "已进入回答队列", "at": utc_now()},
        )
        second = AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "route.resolved", "route": {"provider_id": "p1", "model_id": "m1"}, "at": utc_now()},
        )
        third = AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "run_status", "status": "running", "stage": "running", "at": utc_now()},
        )

        self.assertEqual([first["seq"], second["seq"], third["seq"]], [1, 2, 3])
        stored = AssistantEventRepository.list_for_run(document["run_id"])
        self.assertEqual([item["type"] for item in stored], ["run.created", "route.resolved", "run.started"])
        self.assertEqual([item["seq"] for item in stored], [1, 2, 3])
        self.assertTrue(all(item["event_id"].startswith("asevt_") for item in stored))
        self.assertTrue(all(item["schema_version"] == 1 for item in stored))
        self.assertTrue(all(item["chat_id"] == document["chat_id"] for item in stored))
        self.assertTrue(all(item["created_by"] == document["created_by"] for item in stored))
        self.assertTrue(all(isinstance(item["at"], (datetime, str)) for item in stored))

        replay = AssistantRunRepository.events_after(document["run_id"])
        self.assertEqual([item["type"] for item in replay], ["status", "route.resolved", "run_status"])
        self.assertEqual(replay[1]["route"]["model_id"], "m1")
        incremental = AssistantEventRepository.events_after(document["run_id"], after_seq=2)
        self.assertEqual([item["type"] for item in incremental], ["run.started"])

    def test_backfill_is_idempotent_and_falls_back_to_embedded_events(self) -> None:
        document = self._run("asrun_backfill_1")
        self.assertTrue(AssistantRunRepository.create_active(document)[0])
        AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "run_status", "status": "completed", "stage": "completed", "at": utc_now()},
        )
        AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "context.assembled", "manifest": {"digest": "sha256:test"}, "at": utc_now()},
        )

        AssistantEventRepository.clear_run(document["run_id"])
        self.assertEqual(AssistantEventRepository.backfill_run(document["run_id"]), 2)
        self.assertEqual(AssistantEventRepository.backfill_run(document["run_id"]), 0)
        events = AssistantEventRepository.list_for_run(document["run_id"])
        self.assertEqual([item["type"] for item in events], ["run.completed", "context.assembled"])

        AssistantEventRepository.clear_run(document["run_id"])
        self.assertEqual(AssistantEventRepository.backfill_run(document["run_id"]), 2)
        fallback = AssistantRunRepository.events_after(document["run_id"])
        self.assertEqual(len(fallback), 2)

    def test_replay_merges_partial_unified_events_with_embedded_events(self) -> None:
        document = self._run("asrun_partial_1")
        self.assertTrue(AssistantRunRepository.create_active(document)[0])
        AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "run_status", "status": "running", "stage": "running", "at": utc_now()},
        )
        AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "route.fallback", "reason": "provider_error", "at": utc_now()},
        )
        AssistantRunRepository.append_event(
            document["run_id"],
            {"type": "run_status", "status": "failed", "stage": "failed", "at": utc_now()},
        )
        AssistantEventRepository.clear_run(document["run_id"])
        run = AssistantRunRepository.find_one({"run_id": document["run_id"]}) or {}
        AssistantEventRepository.append(run, run["events"][1])

        replay = AssistantRunRepository.events_after(document["run_id"])

        self.assertEqual([item["type"] for item in replay], ["run_status", "route.fallback", "run_status"])
        self.assertEqual([item["seq"] for item in replay], [1, 2, 3])

    def test_tool_call_events_dual_write_with_call_scoped_sequence(self) -> None:
        now = utc_now()
        call = {
            "call_id": "atc_event_1",
            "assistant_run_id": "asrun_tool_1",
            "chat_id": "chat_event_1",
            "created_by": "event-user-1",
            "phase": "requested",
            "event_seq": 0,
            "events": [],
            "created_at": now,
            "updated_at": now,
        }
        AssistantToolCallRepository.save("call_id", call)

        first = AssistantToolCallRepository.append_event(
            call["call_id"],
            {"type": "tool_call", "phase": "requested", "call_id": call["call_id"], "created_at": utc_now()},
        )
        second = AssistantToolCallRepository.append_event(
            call["call_id"],
            {
                "type": "tool_call",
                "phase": "awaiting_confirmation",
                "call_id": call["call_id"],
                "created_at": utc_now(),
            },
        )

        self.assertTrue(first)
        self.assertTrue(second)
        events, _ = AssistantEventRepository.list_all(
            {"call_id": call["call_id"]},
            sort_field="seq",
            reverse=False,
            page=1,
            page_size=100,
        )
        self.assertEqual([event["type"] for event in events], ["tool.proposed", "tool.awaiting_confirmation"])
        self.assertEqual([event["seq"] for event in events], [1, 2])
        self.assertTrue(all(event["run_id"] == call["assistant_run_id"] for event in events))

    def test_backfill_all_covers_legacy_runs_and_tool_calls(self) -> None:
        run = self._run("asrun_backfill_all")
        self.assertTrue(AssistantRunRepository.create_active(run)[0])
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "run_status", "status": "completed", "stage": "completed", "at": utc_now()},
        )
        AssistantEventRepository.clear_run(run["run_id"])
        call = {
            "call_id": "atc_backfill_all",
            "assistant_run_id": run["run_id"],
            "chat_id": run["chat_id"],
            "created_by": run["created_by"],
            "phase": "completed",
            "event_seq": 1,
            "events": [
                {
                    "seq": 1,
                    "type": "tool_call",
                    "call_id": "atc_backfill_all",
                    "phase": "completed",
                    "created_at": utc_now(),
                }
            ],
        }
        AssistantToolCallRepository.save("call_id", call)

        result = AssistantEventRepository.backfill_all()

        self.assertEqual(result["runs"], 1)
        self.assertEqual(result["calls"], 1)
        self.assertEqual(result["events"], 2)
        self.assertEqual(AssistantEventRepository.backfill_all()["events"], 0)

    def test_run_replay_does_not_let_call_scoped_sequence_collide(self) -> None:
        run = self._run("asrun_collision_1")
        self.assertTrue(AssistantRunRepository.create_active(run)[0])
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "route.resolved", "route": {"model_id": "run-model"}, "at": utc_now()},
        )
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "run_status", "status": "running", "stage": "running", "at": utc_now()},
        )
        call = {
            "call_id": "atc_collision_1",
            "assistant_run_id": run["run_id"],
            "chat_id": run["chat_id"],
            "created_by": run["created_by"],
            "phase": "awaiting_confirmation",
            "event_seq": 2,
            "events": [
                {"seq": 1, "type": "tool_call", "call_id": "atc_collision_1", "phase": "requested", "created_at": utc_now()},
                {"seq": 2, "type": "tool_call", "call_id": "atc_collision_1", "phase": "awaiting_confirmation", "created_at": utc_now()},
            ],
        }
        AssistantToolCallRepository.save("call_id", call)
        AssistantEventRepository.backfill_call(call["call_id"])

        replay = AssistantRunRepository.events_after(run["run_id"])

        self.assertEqual([event["type"] for event in replay], ["route.resolved", "run_status"])

    def test_incremental_event_query_supports_limit_and_call_scope_filter(self) -> None:
        """增量事件查询应只返回游标后的事件，并能排除工具调用事件。"""
        run = self._run("asrun_incremental_query")
        self.assertTrue(AssistantRunRepository.create_active(run)[0])
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "status", "stage": "running", "at": utc_now()},
        )
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "route.resolved", "route": {"model_id": "m1"}, "at": utc_now()},
        )
        AssistantRunRepository.append_event(
            run["run_id"],
            {"type": "tool_call", "call_id": "atc_query", "phase": "requested", "at": utc_now()},
        )

        incremental = AssistantEventRepository.events_after(
            run["run_id"],
            after_seq=1,
            limit=10,
            exclude_call_scoped=True,
        )

        self.assertEqual([event["type"] for event in incremental], ["route.resolved"])
