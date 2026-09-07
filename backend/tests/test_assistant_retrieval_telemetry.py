"""LUI 检索可观测性测试。"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.time import utc_now
from app.infra.research_engine_repositories import AssistantRunRepository
from app.schemas.assistant import AssistantReference
from app.services.assistant_retrieval_telemetry import (
    knowledge_result_entries,
    mark_used_in_answer,
    retrieval_result_event,
    web_result_entries,
)


@dataclass(frozen=True)
class _KnowledgeItem:
    title: str
    snippet: str
    source_id: str
    score: float


@dataclass(frozen=True)
class _KnowledgeOutcome:
    results: list[_KnowledgeItem]


@dataclass(frozen=True)
class _WebItem:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class _WebOutcome:
    results: list[_WebItem]


class AssistantRetrievalTelemetryTest(ComputationTestCase):
    def test_knowledge_entries_are_stable_and_ranked(self) -> None:
        """知识库条目应输出稳定 id、rank、score 与截断 snippet。"""
        outcome = _KnowledgeOutcome(
            results=[
                _KnowledgeItem("PVDF", "x" * 300, "kb:fh-1", 0.92),
                _KnowledgeItem("PTFE", "短摘要", "kb:fh-2", 0.81),
                _KnowledgeItem("FEP", "摘要", "kb:fh-3", 0.7),
            ]
        )
        entries = knowledge_result_entries(outcome, limit=2)
        self.assertEqual([item["id"] for item in entries], ["kb:fh-1", "kb:fh-2"])
        self.assertEqual([item["rank"] for item in entries], [1, 2])
        self.assertEqual(entries[0]["score"], 0.92)
        self.assertLessEqual(len(entries[0]["snippet"]), 240)

    def test_web_entries_use_url_as_stable_id(self) -> None:
        """联网条目应以 URL 作为稳定 id，rank 从 1 递增。"""
        outcome = _WebOutcome(
            results=[
                _WebItem("WeKnora", "https://github.com/Tencent/WeKnora", "开源框架"),
                _WebItem("Docs", "https://example.org/docs", "文档"),
            ]
        )
        entries = web_result_entries(outcome)
        self.assertEqual(entries[0]["id"], "https://github.com/Tencent/WeKnora")
        self.assertEqual([item["rank"] for item in entries], [1, 2])
        self.assertIsNone(entries[0]["score"])

    def test_mark_used_in_answer_matches_source_id_and_target(self) -> None:
        """used_in_answer 应同时支持 source_id 与 target 匹配。"""
        entries = [
            {"id": "kb:fh-1", "rank": 1},
            {"id": "kb:fh-2", "rank": 2},
        ]
        references = [
            AssistantReference(label="a", target="/knowledge", type="knowledge", source_id="kb:fh-1"),
            {"label": "b", "target": "kb:fh-2", "type": "knowledge"},
        ]
        marked = mark_used_in_answer(entries, references)
        self.assertEqual([item["used_in_answer"] for item in marked], [True, True])

    def test_retrieval_result_event_shape(self) -> None:
        """retrieval.result 事件应包含来源、状态与稳定条目。"""
        event = retrieval_result_event(
            source="knowledge",
            query_digest="abc123",
            status="searched",
            entries=[{"id": "kb:fh-1", "rank": 1, "used_in_answer": True}],
        )
        self.assertEqual(event["type"], "retrieval.result")
        self.assertEqual(event["source"], "knowledge")
        self.assertEqual(event["status"], "searched")
        self.assertTrue(event["results"][0]["used_in_answer"])

    def test_reference_schema_keeps_mapping_fields_optional(self) -> None:
        """引用新增映射字段应可空且不破坏旧结构。"""
        legacy = AssistantReference(label="旧引用", target="/research-engine")
        enriched = AssistantReference(
            label="知识引用",
            target="/knowledge",
            type="knowledge",
            source="knowledge",
            source_id="kb:fh-1",
            rank=1,
            score=0.9,
        )
        self.assertIsNone(legacy.source_id)
        self.assertEqual(enriched.model_dump()["source_id"], "kb:fh-1")

    def test_find_runs_by_evaluation_id(self) -> None:
        """run 应支持按 evaluation_id 回放查询。"""
        now = utc_now()
        document = {
            "run_id": "asrun_eval_tele",
            "trace_id": "asrun_eval_tele",
            "chat_id": "chat_eval",
            "created_by": "eval-user",
            "user_message_id": "message_eval",
            "status": "completed",
            "active": False,
            "stage": "completed",
            "event_seq": 0,
            "events": [],
            "created_at": now,
            "updated_at": now,
            "request_snapshot": {
                "content": "评测问题",
                "messages": [],
                "context": {
                    "evaluation_id": "lui-eval-20260828",
                    "task_id": "LUI-PF-0001",
                },
            },
        }
        self.assertTrue(AssistantRunRepository.create_active(document)[0])
        runs = AssistantRunRepository.find_by_evaluation_id("lui-eval-20260828")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["request_snapshot"]["context"]["task_id"], "LUI-PF-0001")
        self.assertEqual(AssistantRunRepository.find_by_evaluation_id(""), [])
