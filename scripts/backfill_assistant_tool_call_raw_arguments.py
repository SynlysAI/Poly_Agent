"""Backfill missing raw_arguments for assistant algorithm tool calls.

历史 ``assistant_tool_calls`` 中部分记录在模型原始提案字段进入持久化之前创建，
因此 ``raw_arguments`` 可能为空。该脚本仅补齐缺失记录，使用当前 ``arguments``
生成稳定 JSON，不覆盖任何已有原始提案。默认 dry-run，可重复执行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now  # noqa: E402
from app.infra.research_engine_repositories import AssistantToolCallRepository  # noqa: E402


PAGE_SIZE = 1000


def _is_missing_raw_arguments(value: Any) -> bool:
    """判断原始提案是否为空值或纯空白。"""
    return value is None or str(value).strip() == ""


def _raw_arguments_from_arguments(arguments: Any) -> str:
    """把当前执行参数序列化为稳定的原始提案 JSON。"""
    return json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)


def main() -> None:
    """执行历史模型原始提案缺失值幂等回填。"""
    parser = argparse.ArgumentParser(description="Backfill missing raw_arguments for assistant tool calls.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    mode_group.add_argument("--apply", action="store_true", help="Write missing raw_arguments records.")
    parser.add_argument("--algorithm-id", help="Only process the specified algorithm_id.")
    args = parser.parse_args()

    apply_changes = args.apply
    algorithm_id = str(args.algorithm_id or "").strip() or None
    print(f"mode={'apply' if apply_changes else 'dry-run'} algorithm_id={algorithm_id or 'all'}")

    scanned = 0
    missing = 0
    updated = 0
    samples: list[str] = []
    page = 1
    while True:
        documents, total = AssistantToolCallRepository.list_all(
            {},
            sort_field="created_at",
            reverse=False,
            page=page,
            page_size=PAGE_SIZE,
        )
        for document in documents:
            if algorithm_id and document.get("algorithm_id") != algorithm_id:
                continue
            scanned += 1
            if not _is_missing_raw_arguments(document.get("raw_arguments")):
                continue
            missing += 1
            call_id = str(document.get("call_id") or "")
            raw_arguments = _raw_arguments_from_arguments(document.get("arguments"))
            if not call_id:
                continue
            if len(samples) < 5:
                samples.append(f"{call_id}: {raw_arguments[:120]}")
            if apply_changes:
                fields = {
                    "raw_arguments": raw_arguments,
                    "arguments_parse_error": None,
                    "updated_at": utc_now(),
                }
                if AssistantToolCallRepository.update_fields(call_id, fields):
                    AssistantToolCallRepository.append_event(
                        call_id,
                        {
                            "type": "tool.proposal.backfilled",
                            "call_id": call_id,
                            "message": "历史原始提案已按最终参数回填",
                        },
                    )
                    updated += 1

        if len(documents) < PAGE_SIZE or page * PAGE_SIZE >= total:
            break
        page += 1

    print(f"summary: scanned={scanned} missing={missing} updated={updated}")
    for sample in samples:
        print(f"sample: {sample}")


if __name__ == "__main__":
    main()
