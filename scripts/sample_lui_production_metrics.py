#!/usr/bin/env python
"""LUI 生产采样脚本：默认 dry-run、只读聚合、不写生产数据。

用法示例：

```bash
# 1. 默认 dry-run（不指定数据源时只输出说明）
PYTHONPATH=backend conda run -n poly_agent python scripts/sample_lui_production_metrics.py

# 2. 从导出的 NDJSON 快照聚合（推荐：脚本不接触生产库）
PYTHONPATH=backend conda run -n poly_agent python scripts/sample_lui_production_metrics.py \
  --export-dir exports/prod-2026-08-28 \
  --output backend/evaluation/lui/reports/production-sample.json

# 3. 显式连接当前配置的数据库（只读，仍不写任何数据）
PYTHONPATH=backend conda run -n poly_agent python scripts/sample_lui_production_metrics.py \
  --from-db --since 2026-08-14T00:00:00+08:00 --limit 5000
```
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PYTHON_PATH = Path(__file__).resolve().parents[1] / "backend"
if str(PYTHON_PATH) not in sys.path:
    sys.path.insert(0, str(PYTHON_PATH))

from evaluation.lui.production import (  # noqa: E402
    build_label_sample,
    summarize_production_sample,
)


EXPORT_FILES = {
    "runs": "runs.ndjson",
    "tool_calls": "tool_calls.ndjson",
    "events": "events.ndjson",
}


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="Aggregate anonymized LUI production sample metrics (read-only)"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--export-dir",
        default=None,
        help="本地导出目录（runs/tool_calls/events NDJSON）；脚本不连接数据库",
    )
    source.add_argument(
        "--from-db",
        action="store_true",
        help="显式连接当前配置的数据库；只读，不写任何数据",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="采样窗口起始时间（ISO 格式，包含边界）",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="采样窗口结束时间（ISO 格式，包含边界）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="每类文档最大读取条数（默认 5000）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="汇总 JSON 输出路径；缺省打印到 stdout",
    )
    parser.add_argument(
        "--label-sample",
        type=int,
        default=0,
        help="额外导出 N 条匿名化 run 供人工标注",
    )
    parser.add_argument(
        "--label-output",
        default=None,
        help="人工标注样本 JSON 输出路径",
    )
    return parser


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    """读取 NDJSON 文件为字典列表。"""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _parse_time(value: str | None) -> datetime | None:
    """解析 ISO 时间参数。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"invalid time: {value}") from exc


def _doc_time(document: dict[str, Any]) -> datetime | None:
    """读取文档可比较时间。"""
    for key in ("created_at", "at", "updated_at"):
        value = document.get(key)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return None


def _within_window(
    document: dict[str, Any],
    since: datetime | None,
    until: datetime | None,
) -> bool:
    """判断文档是否落在采样窗口内。"""
    if since is None and until is None:
        return True
    candidate = _doc_time(document)
    if candidate is None:
        return False
    if since and candidate < since:
        return False
    if until and candidate > until:
        return False
    return True


def _load_window_from_repository(
    repository: Any,
    *,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    sort_field: str = "created_at",
) -> list[dict[str, Any]]:
    """按时间窗口从只读仓储读取样本。

    仓储按时间倒序分页返回。这里不能先取第一页再过滤，否则历史窗口
    会被最新数据遮挡；遇到早于 since 的记录可安全停止。

    Args:
        repository: 只读仓储对象，需提供 list_all 分页接口。
        since: 窗口起始时间。
        until: 窗口结束时间。
        limit: 最大读取条数。
        sort_field: 仓储排序时间字段。

    Returns:
        窗口内的原始文档列表。
    """
    safe_limit = max(0, limit)
    if safe_limit == 0:
        return []
    output: list[dict[str, Any]] = []
    page = 1
    while len(output) < safe_limit:
        rows, total = repository.list_all(
            page=page,
            page_size=safe_limit,
            sort_field=sort_field,
            reverse=True,
        )
        if not rows:
            break
        for row in rows:
            timestamp = _doc_time(row)
            if timestamp is None:
                continue
            if until is not None and timestamp > until:
                continue
            if since is not None and timestamp < since:
                return output
            output.append(row)
            if len(output) >= safe_limit:
                return output
        if page * safe_limit >= total:
            break
        page += 1
    return output


def load_from_export(
    export_dir: str,
    *,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """从本地 NDJSON 导出读取采样文档。

    Args:
        export_dir: 导出目录。
        since: 窗口起始时间。
        until: 窗口结束时间。
        limit: 每类文档最大条数。

    Returns:
        (runs, tool_calls, events) 三元组。
    """
    directory = Path(export_dir)
    if not directory.is_dir():
        raise SystemExit(f"export directory not found: {directory}")
    loaded = {
        key: [
            row
            for row in _load_ndjson(directory / filename)
            if _within_window(row, since, until)
        ][: max(0, limit)]
        for key, filename in EXPORT_FILES.items()
    }
    return loaded["runs"], loaded["tool_calls"], loaded["events"]


def load_from_db(
    *,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """从当前配置数据库只读读取采样文档。

    Args:
        since: 窗口起始时间。
        until: 窗口结束时间。
        limit: 每类文档最大条数。

    Returns:
        (runs, tool_calls, events) 三元组。
    """
    from app.infra.research_engine_repositories import (
        AssistantEventRepository,
        AssistantRunRepository,
        AssistantToolCallRepository,
    )

    safe_limit = max(1, limit)
    runs = _load_window_from_repository(
        AssistantRunRepository,
        since=since,
        until=until,
        limit=safe_limit,
    )
    calls = _load_window_from_repository(
        AssistantToolCallRepository,
        since=since,
        until=until,
        limit=safe_limit,
    )
    events = _load_window_from_repository(
        AssistantEventRepository,
        since=since,
        until=until,
        limit=safe_limit,
        sort_field="at",
    )
    return runs, calls, events


def main(argv: list[str] | None = None) -> int:
    """执行生产采样聚合。

    Args:
        argv: 命令行参数；None 时读取 sys.argv。

    Returns:
        进程退出码。
    """
    args = build_parser().parse_args(argv)
    if not args.export_dir and not args.from_db:
        print("dry-run: no data source specified")
        print("usage: --export-dir <dir> 或 --from-db（显式、只读）")
        print("本脚本不写任何数据库或生产数据；输出均为匿名化聚合")
        return 0
    since = _parse_time(args.since)
    until = _parse_time(args.until)
    if args.export_dir:
        runs, calls, events = load_from_export(
            args.export_dir, since=since, until=until, limit=args.limit
        )
        source = {"kind": "export", "export_dir": args.export_dir}
    else:
        runs, calls, events = load_from_db(
            since=since, until=until, limit=args.limit
        )
        source = {"kind": "db_readonly"}
    summary = summarize_production_sample(runs, calls, events)
    summary["source"] = source
    summary["window"] = {
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "limit": args.limit,
    }
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(f"sampled runs={len(runs)} tool_calls={len(calls)} events={len(events)}")
        print(f"output: {output_path}")
    else:
        print(payload)
    if args.label_sample > 0:
        if not args.label_output:
            raise SystemExit("--label-sample requires --label-output")
        label_rows = build_label_sample(runs, size=args.label_sample)
        label_path = Path(args.label_output)
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(
            json.dumps(label_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"label_sample: {len(label_rows)} -> {label_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
