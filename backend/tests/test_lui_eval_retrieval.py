"""LUI M3 检索召回判定测试。"""

from __future__ import annotations

import unittest

from evaluation.lui.evaluators.retrieval import (
    ranked_observed_ids,
    recall_at_k,
)
from evaluation.lui.schemas import (
    ExpectedRetrieval,
    FixtureRetrieval,
    FixtureRetrievalItem,
    FixtureRun,
    GoldenTask,
    ObservedFacts,
)
from evaluation.lui.evaluators import evaluate_task


def _task(retrieval: ExpectedRetrieval) -> GoldenTask:
    """构建最小检索任务。"""
    return GoldenTask.model_validate(
        {
            "id": "LUI-RR-0001",
            "category": "knowledge_retrieval",
            "messages": [{"role": "user", "content": "检索"}],
            "expected": {"retrieval": retrieval.model_dump()},
        }
    )


def _facts(retrievals: list[FixtureRetrieval]) -> ObservedFacts:
    """构建最小观测事实。"""
    return ObservedFacts(
        task_id="LUI-RR-0001",
        run=FixtureRun(run_id="run-1", status="completed"),
        retrievals=retrievals,
    )


class LuiEvalRetrievalTest(unittest.TestCase):
    def test_recall_at_k_values(self) -> None:
        """Recall@K 应按 Top-K 命中比例计算。"""
        relevant = ["a", "b", "c"]
        ranked = ["x", "a", "b", "y", "c"]
        self.assertEqual(recall_at_k(relevant, ranked, 1), 0.0)
        self.assertEqual(recall_at_k(relevant, ranked, 3), round(2 / 3, 6))
        self.assertEqual(recall_at_k(relevant, ranked, 5), 1.0)

    def test_source_filter_and_best_rank_merge(self) -> None:
        """来源过滤生效，且多来源重复 ID 取最佳 rank。"""
        facts = _facts(
            [
                FixtureRetrieval(
                    source="web",
                    results=[
                        FixtureRetrievalItem(id="shared", rank=1),
                        FixtureRetrievalItem(id="web-only", rank=2),
                    ],
                ),
                FixtureRetrieval(
                    source="knowledge",
                    results=[FixtureRetrievalItem(id="shared", rank=3)],
                ),
            ]
        )
        self.assertEqual(ranked_observed_ids(facts, "web"), ["shared", "web-only"])
        self.assertEqual(ranked_observed_ids(facts, "any"), ["shared", "web-only"])

    def test_task_outcome_uses_primary_k5(self) -> None:
        """任务级判定主口径为 Recall@5。"""
        task = _task(ExpectedRetrieval(relevant_ids=["kb:1"], source="knowledge"))
        facts = _facts(
            [
                FixtureRetrieval(
                    source="knowledge",
                    results=[FixtureRetrievalItem(id="kb:1", rank=3)],
                )
            ]
        )
        outcome = evaluate_task(task, facts).outcomes["m3"]
        self.assertTrue(outcome.passed)
        self.assertEqual(outcome.details["recall@1"], 0.0)
        self.assertEqual(outcome.details["recall@3"], 1.0)
        self.assertEqual(outcome.details["recall@5"], 1.0)

    def test_missing_relevant_id_fails(self) -> None:
        """相关证据未进入 Top-K 时判定失败。"""
        task = _task(ExpectedRetrieval(relevant_ids=["kb:1", "kb:2"]))
        facts = _facts(
            [
                FixtureRetrieval(
                    source="knowledge",
                    results=[FixtureRetrievalItem(id="kb:1", rank=1)],
                )
            ]
        )
        outcome = evaluate_task(task, facts).outcomes["m3"]
        self.assertFalse(outcome.passed)
        self.assertEqual(outcome.score, 0.5)


if __name__ == "__main__":
    unittest.main()
