"""M8 人工兜底分类判定器。"""

from __future__ import annotations

from evaluation.lui.schemas import (
    EscalationLevel,
    FixtureEscalation,
    GoldenTask,
    MetricOutcome,
    ObservedFacts,
)


ESCALATION_MAIN_LEVELS = {"takeover", "permission_block"}


def classify(escalation: FixtureEscalation, *, run_failed: bool) -> EscalationLevel:
    """把观测兜底信号分类为单一人兜底等级。

    Args:
        escalation: 观测到的人工介入信号。
        run_failed: run 是否以 failed 终态结束。

    Returns:
        分类后的兜底等级。
    """
    if escalation.user_canceled:
        return "cancel"
    if escalation.dead_letter or run_failed or escalation.needed_retry:
        return "takeover"
    if escalation.permission_blocked:
        return "permission_block"
    if escalation.awaiting_input_terminal or escalation.param_completions > 0:
        return "param_completion"
    if escalation.confirmations > 0:
        return "confirmation"
    return "none"


def evaluate(task: GoldenTask, facts: ObservedFacts) -> MetricOutcome:
    """执行 M8 人工兜底判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。

    Returns:
        含分类等级、是否计入主指标与归因的判定结果。
    """
    level = classify(facts.escalation, run_failed=facts.run.status == "failed")
    counted = level in ESCALATION_MAIN_LEVELS
    passed = level == task.expected.escalation.level
    return MetricOutcome(
        key="m8",
        applicable=True,
        passed=passed,
        score=1.0 if passed else 0.0,
        details={
            "classified_level": level,
            "expected_level": task.expected.escalation.level,
            "counted_in_main_rate": counted,
            "reason": task.expected.escalation.reason,
            "signals": facts.escalation.model_dump(),
        },
    )
