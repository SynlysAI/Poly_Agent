"""M6 延迟判定器。"""

from __future__ import annotations

from evaluation.lui.metrics import percentile
from evaluation.lui.schemas import GoldenTask, MetricOutcome, ObservedFacts


def evaluate(task: GoldenTask, facts: ObservedFacts) -> MetricOutcome:
    """执行 M6 延迟判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。

    Returns:
        含四类延迟样本与预算判定；失败/取消样本单列不混入。
    """
    completed = facts.run.status == "completed"
    e2e_samples = [facts.run.duration_ms] if completed and facts.run.duration_ms is not None else []
    first_token_samples = (
        [facts.run.first_token_ms]
        if completed and facts.run.first_token_ms is not None
        else []
    )
    tool_samples = [
        call.duration_ms
        for call in facts.tool_calls
        if call.phase == "completed" and call.duration_ms is not None
    ]
    retrieval_samples = [
        retrieval.duration_ms
        for retrieval in facts.retrievals
        if retrieval.status == "searched" and retrieval.duration_ms is not None
    ]
    budget = task.expected.latency_budget_ms
    passed: bool | None = None
    if budget is not None:
        passed = bool(e2e_samples) and e2e_samples[0] <= budget
    return MetricOutcome(
        key="m6",
        applicable=True,
        passed=passed,
        score=(e2e_samples[0] / budget) if (budget and e2e_samples) else None,
        details={
            "completed": completed,
            "end_to_end_ms": e2e_samples[0] if e2e_samples else None,
            "first_token_ms": first_token_samples[0] if first_token_samples else None,
            "tool_ms_p50": percentile(tool_samples, 0.5),
            "tool_ms_p95": percentile(tool_samples, 0.95),
            "retrieval_ms_p50": percentile(retrieval_samples, 0.5),
            "failed_or_canceled_samples": 0 if completed else 1,
            "latency_budget_ms": budget,
        },
    )
