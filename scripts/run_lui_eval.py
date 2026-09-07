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
import json
import sys
from pathlib import Path

PYTHON_PATH = Path(__file__).resolve().parents[1] / "backend"
if str(PYTHON_PATH) not in sys.path:
    sys.path.insert(0, str(PYTHON_PATH))

from evaluation.lui.report import compare_baseline, save_baseline, write_report  # noqa: E402
from evaluation.lui.manual_review import (  # noqa: E402
    build_review_sheet,
    load_review_sheet,
    summarize_review,
    validate_sheet_completed,
    validate_review_sheet_alignment,
)
from evaluation.lui.runner import (  # noqa: E402
    default_evaluation_id,
    load_dataset,
    run_evaluation,
)
from evaluation.lui.schemas import DATASET_VERSION  # noqa: E402


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
        "--check-baseline",
        default=None,
        help="可选：与受控基线对比，出现通过率或覆盖率回归时退出码为 2",
    )
    parser.add_argument(
        "--evaluation-id",
        default=None,
        help="评测批次 ID；缺省按模式与数据集版本生成",
    )
    parser.add_argument(
        "--export-review-sheet",
        default=None,
        help="可选：按 20%% 分层抽样导出 M4/M5 人工抽检表 JSON",
    )
    parser.add_argument(
        "--manual-review",
        default=None,
        help="可选：读取已完成的人工抽检表并汇入报告 manual_review 字段",
    )
    parser.add_argument(
        "--reviewer",
        default="",
        help="抽检人名称；仅 --export-review-sheet 时写入抽检表",
    )
    parser.add_argument(
        "--metadata",
        default=None,
        help='可选：JSON 字符串，附加到报告 metadata（如 \'{"model": "deepseek-chat"}\'）',
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
    manual_review_summary = None
    gate: dict | None = None
    if args.manual_review:
        sheet = load_review_sheet(args.manual_review)
        validate_sheet_completed(sheet)
        validate_review_sheet_alignment(
            sheet,
            evaluation_id=args.evaluation_id or default_evaluation_id(args.mode),
            dataset_version=DATASET_VERSION,
        )
        manual_review_summary = summarize_review(sheet)
    report, evaluations = run_evaluation(
        args.dataset,
        mode=args.mode,
        facts_dir=args.facts_dir,
        evaluation_id=args.evaluation_id,
        manual_review_summary=manual_review_summary,
        metadata=json.loads(args.metadata) if args.metadata else None,
    )
    if args.export_review_sheet:
        tasks = load_dataset(args.dataset)
        sheet = build_review_sheet(
            tasks,
            evaluations,
            evaluation_id=report["evaluation_id"],
            dataset_version=report["dataset_version"],
            generated_at=report["generated_at"],
            reviewer=args.reviewer,
        )
        Path(args.export_review_sheet).parent.mkdir(parents=True, exist_ok=True)
        Path(args.export_review_sheet).write_text(
            sheet.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"review_sheet: {args.export_review_sheet}")
        print(f"review_items: {len(sheet.items)}")
    paths = write_report(report, evaluations, args.report_dir)
    if args.check_baseline:
        baseline_payload = json.loads(
            Path(args.check_baseline).read_text(encoding="utf-8")
        )
        gate = compare_baseline(report, baseline_payload)
        print(f"baseline_gate: {'PASS' if gate['ok'] else 'FAIL'}")
        print(f"baseline_gate_reason: {gate['reason']}")
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
    if gate is not None and not gate["ok"]:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
