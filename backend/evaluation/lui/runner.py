"""LUI 离线评测运行器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from evaluation.lui.evaluators import AnswerJudge, evaluate_task
from evaluation.lui.report import build_report
from evaluation.lui.schemas import (
    DATASET_VERSION,
    GoldenTask,
    ObservedFacts,
    TaskEvaluation,
)


def load_dataset(dataset_dir: str | Path) -> list[GoldenTask]:
    """加载并校验 Golden 数据集。

    Args:
        dataset_dir: 存放 *.yaml 任务清单的目录。

    Returns:
        按 ID 排序的任务列表。
    """
    directory = Path(dataset_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"dataset directory not found: {directory}")
    tasks: list[GoldenTask] = []
    seen_ids: set[str] = set()
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in raw or []:
            task = GoldenTask.model_validate(item)
            if task.id in seen_ids:
                raise ValueError(f"duplicate golden task id: {task.id}")
            seen_ids.add(task.id)
            tasks.append(task)
    tasks.sort(key=lambda item: item.id)
    return tasks


def fixture_facts(task: GoldenTask) -> ObservedFacts | None:
    """从任务内嵌 fixture 构建观测事实。"""
    if task.fixture is None:
        return None
    payload = task.fixture.model_dump()
    return ObservedFacts(task_id=task.id, **payload)


def captured_facts(
    task: GoldenTask,
    facts_dir: str | Path,
) -> ObservedFacts | None:
    """从录制事实目录读取任务观测事实。

    Args:
        task: Golden 任务。
        facts_dir: 存放 {task_id}.json 的目录。

    Returns:
        观测事实；文件不存在时返回 None。
    """
    path = Path(facts_dir) / f"{task.id}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ObservedFacts.model_validate(payload)


def run_evaluation(
    dataset_dir: str | Path,
    *,
    mode: str = "smoke",
    facts_dir: str | Path | None = None,
    judge: AnswerJudge | None = None,
    evaluation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[TaskEvaluation]]:
    """执行离线评测并构建报告。

    Args:
        dataset_dir: Golden 数据集目录。
        mode: smoke 只跑内置 fixture；full 跑全部任务。
        facts_dir: 录制事实目录；smoke 模式忽略。
        judge: 可选 LLM-as-judge。
        evaluation_id: 评测批次 ID；缺省自动生成。
        metadata: 附加元信息。

    Returns:
        (报告字典, 任务级判定列表) 二元组。
    """
    tasks = load_dataset(dataset_dir)
    evaluations: list[TaskEvaluation] = []
    skipped: list[str] = []
    missing: list[str] = []
    facts_source = "none"
    for task in tasks:
        facts: ObservedFacts | None
        if mode == "smoke":
            facts = fixture_facts(task)
            facts_source = "fixture"
        elif facts_dir is not None:
            facts = captured_facts(task, facts_dir)
            facts_source = "captured"
        else:
            facts = fixture_facts(task) or captured_facts(
                task, Path(dataset_dir).parent / "fixtures"
            )
            facts_source = "fixture-or-captured"
        if facts is None:
            if mode == "smoke":
                skipped.append(task.id)
            else:
                missing.append(task.id)
            continue
        facts.task_id = task.id
        evaluations.append(evaluate_task(task, facts, judge=judge))
    if not evaluation_id:
        safe_mode = mode.replace("/", "-")
        evaluation_id = f"lui-eval-{safe_mode}-{DATASET_VERSION}"
    report = build_report(
        evaluations,
        mode=mode,
        evaluation_id=evaluation_id,
        dataset_version=DATASET_VERSION,
        skipped_tasks=skipped,
        missing_facts=missing,
        metadata={
            "facts_source": facts_source,
            **(metadata or {}),
        },
    )
    return report, evaluations
