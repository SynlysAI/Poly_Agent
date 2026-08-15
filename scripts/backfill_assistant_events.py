"""Backfill legacy assistant run/tool events into the append-only event log."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.research_engine_repositories import AssistantEventRepository  # noqa: E402


def main() -> None:
    """执行历史 assistant events 幂等回填。"""
    parser = argparse.ArgumentParser(description="Backfill assistant_events from legacy embedded events.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only print the apply command.")
    mode.add_argument("--apply", action="store_true", help="Backfill missing events.")
    args = parser.parse_args()

    if not args.apply:
        print("dry-run: no documents changed; rerun with --apply")
        return
    result = AssistantEventRepository.backfill_all()
    print(
        "assistant_events backfill complete: "
        f"runs={result['runs']} calls={result['calls']} events={result['events']}"
    )


if __name__ == "__main__":
    main()
