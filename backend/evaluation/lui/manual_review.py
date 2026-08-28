"""LUI 评测 M4/M5 人工抽检工具。

负责按分桶分层抽样、导出抽检表、汇总人工与机器判定不一致率。
抽检表为 JSON 文件：先生成待填记录，人工补齐 agree/reason 后再
由 runner 合并进评测报告与基线。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from evaluation.lui.metrics import safe_ratio
from evaluation.lui.schemas import GoldenTask, TaskEvaluation


REVIEW_METRICS = ("m4", "m5")
REVIEW_SHEET_VERSION = 1
DEFAULT_SAMPLE_RATIO = 0.2
DEFAULT_MIN_PER_METRIC = 2
REASON_CATEGORIES = ("task_ambiguous", "judge_false_positive", "judge_false_negative")
REASON_LABELS = {
    "task_ambiguous": "任务歧义",
    "judge_false_positive": "判定器误判",
    "judge_false_negative": "判定器漏判",
}
DISAGREEMENT_RATE_LIMIT = 0.05


class ReviewItem(BaseModel):
    """一条待人工复核的指标判定记录。"""

    task_id: str
    category: str
    metric: str
    prompt: str
    expected: dict[str, Any]
    answer: str
    machine_passed: bool | None
    machine_reasons: list[str] = Field(default_factory=list)
    agree: bool | None = None
    reason_category: str | None = None
    comment: str = ""

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, value: str) -> str:
        """校验抽检指标只允许 M4/M5。"""
        if value not in REVIEW_METRICS:
            raise ValueError(f"review metric must be one of {REVIEW_METRICS}")
        return value

    @field_validator("reason_category")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        """校验不一致原因归类。"""
        if value is not None and value not in REASON_CATEGORIES:
            raise ValueError(f"reason_category must be one of {REASON_CATEGORIES}")
        return value


class ReviewSheet(BaseModel):
    """一轮人工抽检的完整记录。"""

    version: int = REVIEW_SHEET_VERSION
    evaluation_id: str
    dataset_version: str
    sample_ratio: float
    generated_at: str
    reviewer: str = ""
    items: list[ReviewItem]


def sample_review_items(
    tasks: list[GoldenTask],
    evaluations: list[TaskEvaluation],
    *,
    ratio: float = DEFAULT_SAMPLE_RATIO,
    min_per_metric: int = DEFAULT_MIN_PER_METRIC,
) -> list[tuple[str, str]]:
    """按指标与分桶分层抽样待复核的 (task_id, metric) 对。

    分配为确定性按比例配额，天然可复现。

    Args:
        tasks: Golden 任务列表。
        evaluations: 任务级判定结果。
        ratio: 抽检比例；不低于 20%。
        min_per_metric: 每项指标最少抽检数。

    Returns:
        (task_id, metric) 二元组列表，按指标内任务 ID 排序。
    """
    if ratio < DEFAULT_SAMPLE_RATIO:
        raise ValueError(f"sample ratio must be >= {DEFAULT_SAMPLE_RATIO}")
    evaluation_by_id = {item.task_id: item for item in evaluations}
    sampled: list[tuple[str, str]] = []
    for metric in REVIEW_METRICS:
        candidates = [
            item
            for item in evaluations
            if item.outcomes[metric].applicable
        ]
        by_category: dict[str, list[TaskEvaluation]] = defaultdict(list)
        for item in candidates:
            by_category[item.category].append(item)
        target = max(
            min_per_metric,
            min(len(candidates), math.ceil(len(candidates) * ratio)),
        )
        # 按分桶等比例分配配额：每桶保底 1 条，超额时先压缩大桶，
        # 不足时优先补足样本最多的桶，保证可复现且无整桶丢失。
        quotas = {
            category: max(1, round(len(items) * ratio))
            for category, items in by_category.items()
        }
        while sum(quotas.values()) > target and any(v > 1 for v in quotas.values()):
            largest = max((c for c, v in quotas.items() if v > 1), key=lambda c: quotas[c])
            quotas[largest] -= 1
        while sum(quotas.values()) < target:
            growable = [
                c for c, items in by_category.items() if quotas[c] < len(items)
            ]
            if not growable:
                break
            largest = max(growable, key=lambda c: len(by_category[c]))
            quotas[largest] += 1
        selected = [
            item
            for category in sorted(by_category)
            for item in by_category[category][: quotas[category]]
        ]
        deduped = {item.task_id: item for item in selected}
        sampled.extend(
            (task_id, metric) for task_id in sorted(deduped)
            if evaluation_by_id[task_id].outcomes[metric].applicable
        )
    return sampled


def build_review_sheet(
    tasks: list[GoldenTask],
    evaluations: list[TaskEvaluation],
    *,
    evaluation_id: str,
    dataset_version: str,
    ratio: float = DEFAULT_SAMPLE_RATIO,
    generated_at: str = "",
    reviewer: str = "",
) -> ReviewSheet:
    """构建待填写的人工抽检表。

    Args:
        tasks: Golden 任务列表。
        evaluations: 任务级判定结果。
        evaluation_id: 评测批次 ID。
        dataset_version: 数据集版本。
        ratio: 抽检比例。
        generated_at: 生成时间。
        reviewer: 抽检人。

    Returns:
        含抽样记录的 ReviewSheet。
    """
    task_by_id = {item.id: item for item in tasks}
    evaluation_by_id = {item.task_id: item for item in evaluations}
    pairs = sample_review_items(tasks, evaluations, ratio=ratio)
    items: list[ReviewItem] = []
    for task_id, metric in pairs:
        task = task_by_id[task_id]
        evaluation = evaluation_by_id[task_id]
        outcome = evaluation.outcomes[metric]
        if metric == "m4":
            expected = (
                task.expected.answer.model_dump(exclude_none=True)
                if task.expected.answer
                else {}
            )
            reasons = list(outcome.details.get("reasons") or [])
        else:
            expected = task.expected.hallucination.model_dump(exclude_none=True)
            reasons = list(outcome.details.get("findings") or [])
        items.append(
            ReviewItem(
                task_id=task_id,
                category=task.category,
                metric=metric,
                prompt="\n".join(
                    f"[{message.role}] {message.content}"
                    for message in task.messages
                ),
                expected=expected,
                answer=(
                    task.fixture.message.content
                    if task.fixture and task.fixture.message
                    else ""
                ),
                machine_passed=outcome.passed,
                machine_reasons=reasons,
            )
        )
    return ReviewSheet(
        evaluation_id=evaluation_id,
        dataset_version=dataset_version,
        sample_ratio=ratio,
        generated_at=generated_at,
        reviewer=reviewer,
        items=items,
    )


def load_review_sheet(path: str | Path) -> ReviewSheet:
    """读取并校验人工抽检表。

    Args:
        path: 抽检表 JSON 路径。

    Returns:
        解析后的 ReviewSheet。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ReviewSheet.model_validate(payload)


def summarize_review(sheet: ReviewSheet) -> dict[str, Any]:
    """汇总人工抽检结果并计算判定器不一致率。

    Args:
        sheet: 已补齐人工判定结论的抽检表。

    Returns:
        按指标拆解的抽检数、不一致数、不一致率、原因归类与
        是否达到 5% 上线的结论。
    """
    summary: dict[str, Any] = {
        "evaluation_id": sheet.evaluation_id,
        "dataset_version": sheet.dataset_version,
        "sample_ratio": sheet.sample_ratio,
        "reviewer": sheet.reviewer,
        "generated_at": sheet.generated_at,
        "disagreement_rate_limit": DISAGREEMENT_RATE_LIMIT,
        "metrics": {},
    }
    for metric in REVIEW_METRICS:
        items = [item for item in sheet.items if item.metric == metric]
        reviewed = [item for item in items if item.agree is not None]
        disagreements = [item for item in reviewed if not item.agree]
        reasons: dict[str, int] = {key: 0 for key in REASON_CATEGORIES}
        for item in disagreements:
            if item.reason_category:
                reasons[item.reason_category] += 1
        rate = safe_ratio(len(disagreements), len(reviewed))
        summary["metrics"][metric] = {
            "sampled": len(items),
            "reviewed": len(reviewed),
            "disagreements": len(disagreements),
            "disagreement_rate": rate,
            "within_limit": rate is None or rate <= DISAGREEMENT_RATE_LIMIT,
            "reasons": {REASON_LABELS[key]: value for key, value in reasons.items()},
            "disagreement_task_ids": [item.task_id for item in disagreements],
        }
    return summary


def validate_review_sheet_alignment(
    sheet: ReviewSheet,
    *,
    evaluation_id: str,
    dataset_version: str,
) -> None:
    """校验人工抽检表与当前评测批次严格对齐。

    Args:
        sheet: 待并入当前报告的人工抽检表。
        evaluation_id: 当前评测批次 ID。
        dataset_version: 当前 Golden Set 版本。

    Raises:
        ValueError: 抽检表属于其他评测批次或数据集版本。
    """
    mismatches = [
        f"{field}: review={review_value!r}, current={current_value!r}"
        for field, review_value, current_value in (
            ("evaluation_id", sheet.evaluation_id, evaluation_id),
            ("dataset_version", sheet.dataset_version, dataset_version),
        )
        if review_value != current_value
    ]
    if mismatches:
        raise ValueError("manual review sheet mismatch: " + "; ".join(mismatches))


def validate_sheet_completed(sheet: ReviewSheet) -> None:
    """校验抽检表所有记录均已填写人工结论。

    Args:
        sheet: 待校验抽检表。

    Raises:
        ValueError: 存在未填写 agree 或不一致但未归类原因的记录。
    """
    for item in sheet.items:
        if item.agree is None:
            raise ValueError(f"review item not completed: {item.task_id}/{item.metric}")
        if not item.agree and item.reason_category is None:
            raise ValueError(
                f"disagreement requires reason_category: {item.task_id}/{item.metric}"
            )
