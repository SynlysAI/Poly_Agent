"""M7 推理成本判定器。"""

from __future__ import annotations

from evaluation.lui.schemas import GoldenTask, MetricOutcome, ObservedFacts


def task_token_usage(facts: ObservedFacts) -> tuple[int | None, bool, int]:
    """按去重口径计算任务 token 成本。

    优先使用 usage 事件；run usage 字段次之；两者皆缺时按字符估算。

    Args:
        facts: 任务级观测事实。

    Returns:
        (总 token, 是否估算, 工具提案 token) 三元组。
    """
    usage_event_total = None
    for event in facts.run.usage_events:
        total = event.get("total_tokens")
        if total is not None:
            usage_event_total = int((usage_event_total or 0) + int(total))
    if usage_event_total is not None:
        total_tokens = usage_event_total
        estimated = False
    elif facts.run.total_tokens is not None:
        total_tokens = int(facts.run.total_tokens)
        estimated = False
    elif facts.run.prompt_tokens is not None or facts.run.completion_tokens is not None:
        total_tokens = int((facts.run.prompt_tokens or 0) + (facts.run.completion_tokens or 0))
        estimated = False
    else:
        content = (facts.message.content if facts.message else "") or ""
        total_tokens = max(1, len(content) // 4) if content else None
        estimated = True
    proposal_tokens = 0
    for call in facts.tool_calls:
        usage = call.proposal_usage or {}
        if usage.get("total_tokens") is not None:
            proposal_tokens += int(usage["total_tokens"])
        elif usage.get("prompt_tokens") is not None or usage.get("completion_tokens") is not None:
            proposal_tokens += int((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
    return total_tokens, estimated, proposal_tokens


def evaluate(task: GoldenTask, facts: ObservedFacts) -> MetricOutcome:
    """执行 M7 成本判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。

    Returns:
        含每任务 token、估算标记与工具链路占比的判定结果。
    """
    total_tokens, estimated, proposal_tokens = task_token_usage(facts)
    budget = task.expected.token_budget
    passed: bool | None = None
    if budget is not None and total_tokens is not None and not estimated:
        passed = total_tokens <= budget
    tool_ratio = (
        round(proposal_tokens / total_tokens, 6)
        if total_tokens and not estimated
        else None
    )
    return MetricOutcome(
        key="m7",
        applicable=True,
        passed=passed,
        details={
            "total_tokens": total_tokens,
            "estimated": estimated,
            "proposal_tokens": proposal_tokens,
            "tool_token_ratio": tool_ratio,
            "token_budget": budget,
        },
    )
