#!/usr/bin/env python
"""LUI Agent 离线评测 CLI。

用法示例：

```bash
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_eval.py \
  --dataset backend/evaluation/lui/dataset --mode smoke \
  --report-dir backend/evaluation/lui/reports
```
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PYTHON_PATH = Path(__file__).resolve().parents[1] / "backend"
if str(PYTHON_PATH) not in sys.path:
    sys.path.insert(0, str(PYTHON_PATH))

from evaluation.lui.report import save_baseline, write_report  # noqa: E402
from evaluation.lui.runner import run_evaluation  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Run offline LUI agent evaluation")
    parser.add_argument(
        "--dataset",
        default="backend/evaluation/lui/dataset",
        help="Golden Set 目录（默认 backend/evaluation/lui/dataset）",
    )
    parser.add_argument(
        "--mode",
        choices=("smoke", "full"),
        default="smoke",
        help="smoke 只跑内置 fixture；full 跑全部任务",
    )
    parser.add_argument(
        "--facts-dir",
        default=None,
        help="录制事实目录（full 模式按 {task_id}.json 读取）",
    )
    parser.add_argument(
        "--report-dir",
        default="backend/evaluation/lui/reports",
        help="报告输出目录",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="可选：将基线写入指定 JSON 路径",
    )
    parser.add_argument(
        "--evaluation-id",
        default=None,
        help="评测批次 ID；缺省按模式与数据集版本生成",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行评测并输出报告。

    Args:
        argv: 命令行参数；None 时读取 sys.argv。

    Returns:
        进程退出码；存在失败任务时返回 1。
    """
    args = build_parser().parse_args(argv)
    report, evaluations = run_evaluation(
        args.dataset,
        mode=args.mode,
        facts_dir=args.facts_dir,
        evaluation_id=args.evaluation_id,
    )
    paths = write_report(report, evaluations, args.report_dir)
    if args.baseline:
        paths["baseline"] = save_baseline(report, args.baseline)
    print(f"evaluation_id: {report['evaluation_id']}")
    print(f"evaluated: {report['summary']['evaluated_tasks']}")
    print(f"skipped: {len(report['summary']['skipped_tasks'])}")
    print(f"missing_facts: {len(report['summary']['missing_facts'])}")
    print(f"task_success_rate: {report['summary']['task_success_rate']}")
    print(f"report: {paths['report_json']}")
    print(f"markdown: {paths['report_markdown']}")
    if args.baseline:
        print(f"baseline: {paths['baseline']}")
    failed = sum(1 for item in evaluations if not item.success)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
