"""Assistant LUI quality metrics tests."""

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
from app.services.assistant_quality_service import build_quality_metrics
from app.services import assistant_quality_service


class AssistantQualityMetricsTest(ComputationTestCase):
    def _run(self, run_id: str, *, requested_model: str = "m1", resolved_model: str = "m1") -> dict:
        """创建一条最小 completed assistant run 文档。"""
        now = utc_now()
        return {
            "run_id": run_id,
            "chat_id": f"chat_{run_id}",
            "created_by": "quality-user",
            "user_message_id": f"message_{run_id}",
            "status": "completed",
            "active": False,
            "stage": "completed",
            "event_seq": 0,
            "events": [],
            "created_at": now,
            "updated_at": now,
            "route": {
                "requested_provider_id": "p1",
                "requested_model_id": requested_model,
                "provider_id": "p1",
                "model_id": resolved_model,
                "route_reason": "user_selected",
                "capabilities": ["chat", "tool_calling"],
            },
            "request_snapshot": {
                "content": "测试问题",
                "messages": [],
                "context": {"selected_tool_ids": ["algorithm:demo"]},
            },
            "request_manifests": {},
        }

    def test_quality_metrics_compute_route_tool_and_context_breakdown(self) -> None:
        first_run = self._run("asrun_quality_1")
        second_run = self._run("asrun_quality_2", requested_model="m1", resolved_model="m2")
        second_run["request_snapshot"]["context"]["selected_tool_ids"] = []
        first_run["request_manifests"] = {
            "final_answer": {
                "request_kind": "final_answer",
                "context": {
                    "sections": [
                        {
                            "name": "project_facts",
                            "source": "ProjectGroundingService",
                            "token_estimate": 40,
                            "included": True,
                            "omitted_reason": None,
                        }
                    ]
                },
            }
        }
        self.assertTrue(AssistantRunRepository.create_active(first_run)[0])
        self.assertTrue(AssistantRunRepository.create_active(second_run)[0])

        AssistantToolCallRepository.save("call_id", {
            "call_id": "atc_quality_completed",
            "assistant_run_id": first_run["run_id"],
            "chat_id": first_run["chat_id"],
            "created_by": first_run["created_by"],
            "phase": "completed",
            "continuation_state": "completed",
            "proposal_route": {
                "provider_id": "p1",
                "model_id": "m1",
                "capabilities": ["chat", "tool_calling"],
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })
        AssistantToolCallRepository.save("call_id", {
            "call_id": "atc_quality_invalid",
            "assistant_run_id": first_run["run_id"],
            "chat_id": first_run["chat_id"],
            "created_by": first_run["created_by"],
            "phase": "awaiting_input",
            "arguments_parse_error": "invalid json",
            "proposal_route": {
                "provider_id": "p1",
                "model_id": "m1",
                "capabilities": ["chat"],
            },
            "created_at": utc_now(),
            "updated_at": utc_now(),
        })

        result = build_quality_metrics()

        self.assertEqual(result["totals"]["runs"], 2)
        self.assertEqual(result["totals"]["tool_calls"], 2)
        route_metric = next(item for item in result["metrics"] if item["key"] == "route_resolved_rate")
        self.assertEqual(route_metric["value"], 1.0)
        mismatch_metric = next(item for item in result["metrics"] if item["key"] == "requested_vs_resolved_mismatch")
        self.assertEqual(mismatch_metric["value"], 0.5)
        tool_capable_metric = next(item for item in result["metrics"] if item["key"] == "tool_capable_model_usage")
        self.assertEqual(tool_capable_metric["value"], 0.5)
        validation_metric = next(item for item in result["metrics"] if item["key"] == "tool_proposal_validation_failure")
        self.assertEqual(validation_metric["value"], 0.5)
        continuation_metric = next(item for item in result["metrics"] if item["key"] == "continuation_success")
        self.assertEqual(continuation_metric["value"], 1.0)
        distribution = result["context_token_distribution"]
        self.assertEqual(distribution["total_tokens"], 40)
        self.assertEqual(distribution["sections"][0]["name"], "project_facts")

    def test_event_replay_errors_counts_seq_gaps_and_duplicates(self) -> None:
        run = {
            "run_id": "asrun_quality_events",
            "chat_id": "chat_quality_events",
            "created_by": "quality-user",
        }
        for seq, event_type in ((1, "run.created"), (2, "run.started"), (4, "run.completed"), (4, "run.completed")):
            AssistantEventRepository.append(run, {
                "seq": seq,
                "type": event_type,
                "at": datetime.now().astimezone(),
            })

        result = build_quality_metrics()

        self.assertEqual(result["event_replay_errors"], 2)

    def test_time_window_and_cache_are_applied(self) -> None:
        assistant_quality_service._QUALITY_CACHE.clear()
        run = self._run("asrun_quality_window")
        run["created_at"] = utc_now()
        self.assertTrue(AssistantRunRepository.create_active(run)[0])

        future = utc_now().replace(year=utc_now().year + 1)
        empty = build_quality_metrics(since=future.isoformat())
        self.assertEqual(empty["totals"]["runs"], 0)

        first = build_quality_metrics(use_cache=True)
        second = build_quality_metrics(use_cache=True)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["totals"]["runs"], second["totals"]["runs"])
