"""M4 最终回答准确率判定器。"""

from __future__ import annotations

import re
from typing import Any, Protocol

from evaluation.lui.schemas import GoldenTask, MetricOutcome, ObservedFacts


REFUSAL_MARKERS = ("无法", "不能", "超出", "范围外", "不支持", "拒绝", "风险", "边界")
INSUFFICIENCY_MARKERS = ("信息不足", "无法确认", "未检索到", "不确定", "缺少", "请补充", "没有找到")
NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


class AnswerJudge(Protocol):
    """LLM-as-judge 协议，用于开放题 Rubric 判定。"""

    def judge(self, task: GoldenTask, content: str) -> "JudgeResult":
        """输出 0-1 分与判定依据。"""


class JudgeResult(dict):
    """judge 结果字典：score 与 rationale。"""

    @property
    def score(self) -> float:
        """返回 0-1 分。"""
        return float(self.get("score") or 0.0)

    @property
    def rationale(self) -> str:
        """返回判定依据。"""
        return str(self.get("rationale") or "")


def _normalize(text: str, *, case_sensitive: bool) -> str:
    """按任务配置规范化文本。"""
    value = str(text or "").strip()
    return value if case_sensitive else value.lower()


def _extract_numbers(content: str) -> list[float]:
    """从回答中提取数值样本。"""
    return [float(item) for item in NUMBER_PATTERN.findall(content)]


def _numeric_within(
    numbers: list[float],
    expected: float,
    tolerance_kind: str,
    tolerance_value: float | None,
) -> bool:
    """判断是否存在落入容忍区间的数值。"""
    for value in numbers:
        if tolerance_kind == "absolute":
            if abs(value - expected) <= (tolerance_value or 0.0):
                return True
        elif tolerance_kind == "relative":
            if abs(value - expected) <= (tolerance_value or 0.0) * max(abs(expected), 1e-12):
                return True
        elif value == expected:
            return True
    return False


def _judge_as_result(judge: Any, task: GoldenTask, content: str) -> JudgeResult:
    """兼容 dict 与 Protocol 两种 judge 返回。"""
    raw = judge.judge(task, content)
    if isinstance(raw, JudgeResult):
        return raw
    return JudgeResult(raw)


def evaluate(
    task: GoldenTask,
    facts: ObservedFacts,
    judge: AnswerJudge | None = None,
) -> MetricOutcome:
    """执行 M4 回答准确率判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。
        judge: 可选 LLM-as-judge；仅 Rubric 题使用。

    Returns:
        含判定方式与依据的判定结果。
    """
    expected = task.expected.answer
    if not expected:
        return MetricOutcome(key="m4", applicable=False)
    content = (facts.message.content if facts.message else "") or ""
    normalized = _normalize(content, case_sensitive=expected.case_sensitive)
    reasons: list[str] = []

    if expected.type in {"exact", "facts"}:
        target = _normalize(expected.value or "", case_sensitive=expected.case_sensitive)
        if expected.type == "exact":
            passed = normalized == target
            if not passed:
                reasons.append(f"expected exact {target!r}")
        else:
            passed = target in normalized
            if not passed:
                reasons.append(f"missing fact {target!r}")
    elif expected.type == "numeric":
        numbers = _extract_numbers(normalized)
        tolerance = expected.numeric_tolerance
        passed = _numeric_within(
            numbers,
            float(expected.numeric_value or 0.0),
            tolerance.kind if tolerance else "exact",
            tolerance.value if tolerance else None,
        )
        if not passed:
            reasons.append(f"no number within tolerance of {expected.numeric_value}")
    elif expected.type in {"keywords", "rubric"}:
        missing = [
            item
            for item in expected.must_include
            if _normalize(item, case_sensitive=expected.case_sensitive) not in normalized
        ]
        if expected.type == "rubric" and judge is not None:
            result = _judge_as_result(judge, task, content)
            score = max(0.0, min(1.0, result.score))
            passed = score >= expected.min_rubric_score and not missing
            reasons.append(f"judge score={score:.3f}: {result.rationale}")
        else:
            score = (
                round((len(expected.must_include) - len(missing)) / len(expected.must_include), 6)
                if expected.must_include
                else 1.0
            )
            passed = score >= expected.min_rubric_score
        if missing:
            reasons.append(f"missing keywords: {', '.join(missing)}")
    elif expected.type == "refusal":
        passed = any(marker in normalized for marker in REFUSAL_MARKERS)
        if not passed:
            reasons.append("no refusal marker found")
    elif expected.type == "insufficient_info":
        passed = any(marker in normalized for marker in INSUFFICIENCY_MARKERS)
        if not passed:
            reasons.append("no insufficiency marker found")
    else:  # pragma: no cover - schema 已限制取值
        passed = False
        reasons.append(f"unknown answer type {expected.type}")

    forbidden_hits = [
        item
        for item in expected.forbidden
        if _normalize(item, case_sensitive=expected.case_sensitive) in normalized
    ]
    if forbidden_hits:
        passed = False
        reasons.append(f"forbidden content present: {', '.join(forbidden_hits)}")
    if not normalized:
        passed = False
        reasons.append("empty answer")

    return MetricOutcome(
        key="m4",
        applicable=True,
        passed=passed,
        score=1.0 if passed else 0.0,
        details={"type": expected.type, "reasons": reasons},
    )
