"""LUI 评测报告构建与渲染。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.lui.metrics import mean, safe_ratio
from evaluation.lui.schemas import DATASET_VERSION, TaskEvaluation


METRIC_KEYS = ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8")
METRIC_LABELS = {
    "m1": "任务成功率",
    "m2": "工具调用正确率",
    "m3": "检索召回 Recall@K",
    "m4": "最终回答准确率",
    "m5": "幻觉率",
    "m6": "P50/P95 延迟",
    "m7": "推理成本",
    "m8": "人工兜底比例",
}


def _metric_rows(evaluations: list[TaskEvaluation]) -> dict[str, dict[str, Any]]:
    """按指标聚合适用数、通过数、通过率与均分。

    通过率分母只包含给出明确 True/False 判定的任务；未设置阈值
    （passed=None）的任务计入“未判定”单列，不计为失败。
    """
    rows: dict[str, dict[str, Any]] = {}
    for key in METRIC_KEYS:
        applicable = [item for item in evaluations if item.outcomes[key].applicable]
        explicit = [
            item for item in applicable if item.outcomes[key].passed is not None
        ]
        passed = [item for item in explicit if item.outcomes[key].passed]
        scored = [
            float(item.outcomes[key].score)
            for item in applicable
            if item.outcomes[key].score is not None
        ]
        rows[key] = {
            "label": METRIC_LABELS[key],
            "applicable": len(applicable),
            "passed": len(passed),
            "explicit": len(explicit),
            "not_evaluable": len(applicable) - len(explicit),
            "pass_rate": safe_ratio(len(passed), len(explicit)),
            "score_mean": mean(scored),
        }
    return rows


def _group_rows(
    evaluations: list[TaskEvaluation],
    field: "str",
) -> dict[str, dict[str, Any]]:
    """按 category 或 mode 聚合任务成功率。"""
    groups: dict[str, list[TaskEvaluation]] = {}
    for item in evaluations:
        groups.setdefault(str(getattr(item, field)), []).append(item)
    return {
        name: {
            "tasks": len(items),
            "success": sum(1 for item in items if item.success),
            "success_rate": safe_ratio(sum(1 for item in items if item.success), len(items)),
        }
        for name, items in sorted(groups.items())
    }


def build_report(
    evaluations: list[TaskEvaluation],
    *,
    mode: str,
    evaluation_id: str,
    dataset_version: str = DATASET_VERSION,
    skipped_tasks: list[str] | None = None,
    missing_facts: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建机器可读评测报告。

    Args:
        evaluations: 任务级判定结果。
        mode: 评测模式（smoke/full）。
        evaluation_id: 评测批次 ID。
        dataset_version: Golden Set 版本。
        skipped_tasks: 跳过的任务 ID（如 smoke 模式无 fixture）。
        missing_facts: 缺少观测事实的任务 ID。
        metadata: 附加元信息（模型矩阵、采样次数等）。

    Returns:
        含汇总、分组与失败样例的报告字典。
    """
    success = sum(1 for item in evaluations if item.success)
    return {
        "evaluation_id": evaluation_id,
        "dataset_version": dataset_version,
        "mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "evaluated_tasks": len(evaluations),
            "successful_tasks": success,
            "task_success_rate": safe_ratio(success, len(evaluations)),
            "skipped_tasks": skipped_tasks or [],
            "missing_facts": missing_facts or [],
        },
        "metrics": _metric_rows(evaluations),
        "by_category": _group_rows(evaluations, "category"),
        "by_mode": _group_rows(evaluations, "mode"),
        "failures": [
            {
                "task_id": item.task_id,
                "category": item.category,
                "mode": item.mode,
                "failed_metrics": [
                    key for key in METRIC_KEYS if _failed(item, key)
                ],
            }
            for item in evaluations
            if not item.success or any(_failed(item, key) for key in METRIC_KEYS)
        ],
        "metadata": metadata or {},
    }


def _failed(item: TaskEvaluation, key: str) -> bool:
    """判断指标是否为明确失败。"""
    outcome = item.outcomes[key]
    return outcome.applicable and outcome.passed is False


def render_markdown(report: dict[str, Any]) -> str:
    """渲染人类可读 Markdown 报告。

    Args:
        report: build_report 输出。

    Returns:
        Markdown 文本。
    """
    summary = report["summary"]
    lines = [
        "# LUI Agent 评测报告",
        "",
        f"- 评测批次：`{report['evaluation_id']}`",
        f"- 数据集版本：`{report['dataset_version']}`",
        f"- 模式：`{report['mode']}`",
        f"- 生成时间：{report['generated_at']}",
        "",
        "## 总览",
        "",
        f"- 评测任务：{summary['evaluated_tasks']}；成功：{summary['successful_tasks']}；"
        f"任务成功率：{_display(summary['task_success_rate'])}",
        f"- 跳过：{len(summary['skipped_tasks'])}；缺事实：{len(summary['missing_facts'])}",
        "",
        "## 八项指标",
        "",
        "| 指标 | 适用 | 通过 | 通过率 | 未判定 | 均分 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key, row in report["metrics"].items():
        lines.append(
            f"| {row['label']}（{key}） | {row['applicable']} | {row['passed']} "
            f"| {_display(row['pass_rate'])} | {row['not_evaluable']} | {_display(row['score_mean'])} |"
        )
    lines.extend(["", "## 分桶成功率", "", "| 分桶 | 任务数 | 成功 | 成功率 |", "| --- | --- | --- | --- |"])
    for name, row in report["by_category"].items():
        lines.append(f"| {name} | {row['tasks']} | {row['success']} | {_display(row['success_rate'])} |")
    lines.extend(["", "## 模式成功率", "", "| 模式 | 任务数 | 成功 | 成功率 |", "| --- | --- | --- | --- |"])
    for name, row in report["by_mode"].items():
        lines.append(f"| {name} | {row['tasks']} | {row['success']} | {_display(row['success_rate'])} |")
    if report["failures"]:
        lines.extend(["", "## 失败任务", "", "| 任务 | 分桶 | 失败指标 |", "| --- | --- | --- |"])
        for item in report["failures"]:
            lines.append(f"| {item['task_id']} | {item['category']} | {', '.join(item['failed_metrics'])} |")
    else:
        lines.extend(["", "## 失败任务", "", "无"])
    lines.append("")
    return "\n".join(lines)


def _display(value: float | None) -> str:
    """格式化比率为百分比。"""
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def write_report(
    report: dict[str, Any],
    evaluations: list[TaskEvaluation],
    report_dir: str | Path,
) -> dict[str, Path]:
    """写出 JSON/Markdown 报告与失败样例文件。

    Args:
        report: 机器可读报告。
        evaluations: 任务级判定结果。
        report_dir: 报告输出目录。

    Returns:
        输出文件路径映射。
    """
    directory = Path(report_dir)
    cases_dir = directory / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    markdown_path = directory / "report.md"
    json_path.write_text(
        json.dumps(
            {
                **report,
                "tasks": [item.model_dump() for item in evaluations],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    for item in report["failures"]:
        evaluation = next((entry for entry in evaluations if entry.task_id == item["task_id"]), None)
        if evaluation is None:
            continue
        case_path = cases_dir / f"{item['task_id']}.md"
        lines = [
            f"# {item['task_id']}",
            "",
            f"- 分桶：{item['category']}",
            f"- 模式：{item['mode']}",
            f"- 失败指标：{', '.join(item['failed_metrics'])}",
            "",
        ]
        for key in METRIC_KEYS:
            outcome = evaluation.outcomes[key]
            lines.append(f"## {key} {METRIC_LABELS[key]}")
            lines.append("")
            lines.append(f"- applicable: {outcome.applicable}")
            lines.append(f"- passed: {outcome.passed}")
            lines.append(f"- details: `{json.dumps(outcome.details, ensure_ascii=False)}`")
            lines.append("")
        case_path.write_text("\n".join(lines), encoding="utf-8")
    return {"report_json": json_path, "report_markdown": markdown_path}


def save_baseline(report: dict[str, Any], path: str | Path) -> Path:
    """保存受控回归基线。

    Args:
        report: 机器可读报告。
        path: 基线 JSON 输出路径。

    Returns:
        基线文件路径。
    """
    baseline_path = Path(path)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline = {
        "evaluation_id": report["evaluation_id"],
        "dataset_version": report["dataset_version"],
        "mode": report["mode"],
        "generated_at": report["generated_at"],
        "summary": report["summary"],
        "metrics": report["metrics"],
        "by_category": report["by_category"],
        "by_mode": report["by_mode"],
    }
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return baseline_path
