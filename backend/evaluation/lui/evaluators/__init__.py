"""M1–M8 评测器入口。"""

from __future__ import annotations

from evaluation.lui.evaluators.answer import AnswerJudge, evaluate as evaluate_answer
from evaluation.lui.evaluators.cost import evaluate as evaluate_cost
from evaluation.lui.evaluators.escalation import evaluate as evaluate_escalation
from evaluation.lui.evaluators.hallucination import evaluate as evaluate_hallucination
from evaluation.lui.evaluators.latency import evaluate as evaluate_latency
from evaluation.lui.evaluators.retrieval import evaluate as evaluate_retrieval
from evaluation.lui.evaluators.task_success import evaluate as evaluate_task_success
from evaluation.lui.evaluators.tool_call import evaluate as evaluate_tool_call
from evaluation.lui.schemas import (
    GoldenTask,
    MetricOutcome,
    ObservedFacts,
    TaskEvaluation,
)

__all__ = [
    "AnswerJudge",
    "evaluate_answer",
    "evaluate_cost",
    "evaluate_escalation",
    "evaluate_hallucination",
    "evaluate_latency",
    "evaluate_retrieval",
    "evaluate_task_success",
    "evaluate_tool_call",
    "evaluate_task",
]


def evaluate_task(
    task: GoldenTask,
    facts: ObservedFacts,
    judge: AnswerJudge | None = None,
) -> TaskEvaluation:
    """对单任务执行 M1–M8 判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。
        judge: 可选 LLM-as-judge，仅作用于 Rubric 题。

    Returns:
        含八项指标判定的任务级结果。
    """
    outcomes: dict[str, MetricOutcome] = {
        "m2": evaluate_tool_call(task, facts),
        "m3": evaluate_retrieval(task, facts),
        "m4": evaluate_answer(task, facts, judge=judge),
        "m5": evaluate_hallucination(task, facts),
        "m6": evaluate_latency(task, facts),
        "m7": evaluate_cost(task, facts),
        "m8": evaluate_escalation(task, facts),
    }
    outcomes["m1"] = evaluate_task_success(task, facts, outcomes)
    ordered = {key: outcomes[key] for key in ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8")}
    return TaskEvaluation(
        task_id=task.id,
        category=task.category,
        mode=task.mode,
        outcomes=ordered,
    )
