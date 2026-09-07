"""M2 工具调用正确率判定器。"""

from __future__ import annotations

import math
from typing import Any

from evaluation.lui.metrics import safe_ratio
from evaluation.lui.schemas import (
    ExpectedToolCall,
    FixtureToolCall,
    GoldenTask,
    MetricOutcome,
    ObservedFacts,
    ToleranceRule,
)


def _normalize_scalar(value: Any) -> Any:
    """把标量规范化为可比较形式。"""
    if isinstance(value, str):
        return value.strip()
    return value


def _values_equal(expected: Any, observed: Any) -> bool:
    """按语义比较两个参数值；列表忽略顺序。"""
    expected = _normalize_scalar(expected)
    observed = _normalize_scalar(observed)
    if isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            return False
        return sorted(map(repr, expected)) == sorted(map(repr, observed))
    if isinstance(expected, dict) and isinstance(observed, dict):
        return expected.keys() == observed.keys() and all(
            _values_equal(expected[key], observed.get(key)) for key in expected
        )
    if isinstance(expected, bool) or isinstance(observed, bool):
        return expected is observed
    return expected == observed


def _significant_round(value: float, digits: int) -> float:
    """按有效数字位数取整。"""
    if value == 0:
        return 0.0
    return round(value, -int(math.floor(math.log10(abs(value)))) + (int(digits) - 1))


def compare_argument(
    expected: Any,
    observed: Any,
    tolerance: ToleranceRule | None,
) -> tuple[bool, str | None]:
    """按容忍规则比较单个参数值。

    Args:
        expected: Golden 期望值。
        observed: 实际解析值。
        tolerance: 容忍规则；None 按 exact 处理。

    Returns:
        (是否通过, 失败原因) 二元组。
    """
    rule = tolerance or ToleranceRule(kind="exact")
    if rule.kind == "ignore":
        return True, None
    if expected is None:
        return observed is None, "expected field missing in golden"
    if observed is None:
        return False, "observed field missing"
    if rule.kind == "exact":
        ok = _values_equal(expected, observed)
        return ok, None if ok else f"expected {expected!r}, got {observed!r}"
    try:
        expected_num = float(expected)
        observed_num = float(observed)
    except (TypeError, ValueError):
        return False, f"non-numeric value with {rule.kind} tolerance"
    if rule.value is None:
        return False, "tolerance value missing"
    if rule.kind == "absolute":
        ok = abs(observed_num - expected_num) <= rule.value
    elif rule.kind == "relative":
        ok = abs(observed_num - expected_num) <= rule.value * max(abs(expected_num), 1e-12)
    elif rule.kind == "significant_figures":
        digits = max(1, int(rule.value))
        ok = _significant_round(observed_num, digits) == _significant_round(expected_num, digits)
    else:  # pragma: no cover - schema 已限制取值
        ok = False
    return ok, None if ok else f"expected {expected_num!r}, got {observed_num!r} under {rule.kind}"


def evaluate_arguments(
    expected_call: ExpectedToolCall,
    observed: FixtureToolCall,
) -> tuple[bool, list[str]]:
    """判定一次已选对工具的调用参数。

    Args:
        expected_call: Golden 期望调用。
        observed: 实际工具调用事实。

    Returns:
        (参数是否全部正确, 错误列表) 二元组。
    """
    errors: list[str] = []
    if observed.arguments_parse_error:
        errors.append(f"arguments parse error: {observed.arguments_parse_error}")
    if observed.missing_fields:
        errors.append(f"missing required fields: {', '.join(observed.missing_fields)}")
    ignored = set(expected_call.ignored_extra_fields)
    for field, expected_value in expected_call.arguments.items():
        ok, reason = compare_argument(
            expected_value,
            observed.arguments.get(field),
            expected_call.argument_tolerance.get(field),
        )
        if not ok and reason:
            errors.append(f"{field}: {reason}")
    if expected_call.forbid_extra_arguments:
        extra = set(observed.arguments) - set(expected_call.arguments) - ignored
        if extra:
            errors.append(f"unexpected extra fields: {', '.join(sorted(extra))}")
    return (not errors), errors


def evaluate(task: GoldenTask, facts: ObservedFacts) -> MetricOutcome:
    """执行 M2 工具选择与参数判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。

    Returns:
        含任务级通过性、precision/recall 与参数准确率的判定结果。
    """
    expected_calls = task.expected.tool_calls
    observed_calls = facts.tool_calls
    expected_tool_tasks = bool(expected_calls)
    applicable = expected_tool_tasks or bool(observed_calls)
    if not applicable:
        return MetricOutcome(key="m2", applicable=False)

    # 匹配优先级：completed 优先，failed/awaiting_input 等中间态靠后，
    # 避免重试链路中的失败尝试抢占期望调用。
    observed_order = sorted(
        range(len(observed_calls)),
        key=lambda index: (0 if observed_calls[index].phase == "completed" else 1, index),
    )
    used: set[int] = set()
    matched_expected = 0
    selected_correct = 0
    argument_correct = 0
    argument_errors: list[str] = []
    for expected_call in expected_calls:
        candidate = next(
            (
                index
                for index in observed_order
                if index not in used
                and observed_calls[index].tool_id == expected_call.tool_id
                and (
                    expected_call.function_name is None
                    or observed_calls[index].function_name == expected_call.function_name
                )
            ),
            None,
        )
        if candidate is None:
            argument_errors.append(
                f"expected tool call not found: {expected_call.tool_id}"
            )
            continue
        used.add(candidate)
        matched_expected += 1
        selected_correct += 1
        args_ok, errors = evaluate_arguments(expected_call, observed_calls[candidate])
        if args_ok:
            argument_correct += 1
        else:
            argument_errors.extend(errors)

    # 选择 precision 只统计 completed 调用：失败/等待补参的重试中间态
    # 属于过程噪声，不计入模型选择错误。
    completed_total = sum(1 for call in observed_calls if call.phase == "completed")
    expected_total = len(expected_calls)
    precision = safe_ratio(selected_correct, completed_total) if completed_total else None
    recall = safe_ratio(matched_expected, expected_total) if expected_total else None
    argument_accuracy = safe_ratio(argument_correct, max(matched_expected, 0))
    matched_completed = sum(
        1 for index in used if observed_calls[index].phase == "completed"
    )
    unexpected = completed_total - matched_completed
    passed: bool | None
    if expected_tool_tasks:
        passed = (
            matched_expected == expected_total
            and argument_correct == matched_expected
            and unexpected == 0
        )
    else:
        passed = completed_total == 0
    return MetricOutcome(
        key="m2",
        applicable=True,
        passed=passed,
        score=recall if expected_tool_tasks else precision,
        details={
            "task_tool_accuracy": passed,
            "selection_precision": precision,
            "selection_recall": recall,
            "argument_accuracy": argument_accuracy,
            "unexpected_calls": unexpected,
            "errors": argument_errors,
        },
    )
