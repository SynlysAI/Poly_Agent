"""M1 任务成功率判定器。"""

from __future__ import annotations

from evaluation.lui.schemas import GoldenTask, MetricOutcome, ObservedFacts


def has_unrecovered_tool_failure(facts: ObservedFacts) -> bool:
    """判断是否存在未被同工具后续成功调用恢复的失败。

    Args:
        facts: 任务级观测事实。

    Returns:
        存在未恢复失败时返回 True；重试链路中失败后成功的情况返回 False。
    """
    for index, call in enumerate(facts.tool_calls):
        if call.phase != "failed":
            continue
        recovered = any(
            later.tool_id == call.tool_id and later.phase == "completed"
            for later in facts.tool_calls[index + 1 :]
        )
        if not recovered:
            return True
    return False


def evaluate(
    task: GoldenTask,
    facts: ObservedFacts,
    sub_outcomes: dict[str, MetricOutcome],
) -> MetricOutcome:
    """执行 M1 端到端成功判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。
        sub_outcomes: 已计算的 M2/M4/M8 子判定。

    Returns:
        与期望 task_success 对比的判定结果。
    """
    expected = task.expected
    expected_cancel = expected.escalation.level == "cancel"
    status_ok = facts.run.status == "completed" or (
        expected_cancel and facts.run.status == "canceled"
    )
    tool_outcome = sub_outcomes.get("m2")
    if expected.tool_calls:
        tool_ok = bool(tool_outcome and tool_outcome.passed) and not (
            has_unrecovered_tool_failure(facts)
        )
    else:
        tool_ok = not (
            expected.task_success
            and any(call.phase == "failed" for call in facts.tool_calls)
        )
    answer_outcome = sub_outcomes.get("m4")
    answer_ok = (
        bool(answer_outcome and answer_outcome.passed) if expected.answer else True
    )
    escalation_outcome = sub_outcomes.get("m8")
    escalation_expected = expected.escalation.level != "none"
    escalation_ok = (
        bool(escalation_outcome and escalation_outcome.passed)
        if escalation_expected
        else True
    )
    computed_success = status_ok and tool_ok and answer_ok and escalation_ok
    passed = computed_success == expected.task_success
    failed_reasons = []
    if not status_ok:
        failed_reasons.append(f"run status={facts.run.status}")
    if not tool_ok:
        failed_reasons.append("tool call expectation not met")
    if not answer_ok:
        failed_reasons.append("answer expectation not met")
    if not escalation_ok:
        failed_reasons.append("escalation expectation not met")
    return MetricOutcome(
        key="m1",
        applicable=True,
        passed=passed,
        score=1.0 if computed_success else 0.0,
        details={
            "computed_success": computed_success,
            "expected_success": expected.task_success,
            "status_ok": status_ok,
            "tool_ok": tool_ok,
            "answer_ok": answer_ok,
            "escalation_ok": escalation_ok,
            "reasons": failed_reasons if not computed_success else [],
        },
    )
