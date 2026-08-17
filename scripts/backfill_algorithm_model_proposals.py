"""Backfill version-level model proposals only when they are explicitly configured."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now  # noqa: E402
from app.infra.research_engine_repositories import (  # noqa: E402
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
)
from app.services.algorithm_model_proposal import resolve_model_proposal  # noqa: E402


PAGE_SIZE = 1000


def main() -> None:
    """回填算法版本缺失的 model_proposal。"""
    parser = argparse.ArgumentParser(description="Backfill missing algorithm version model proposals.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    mode_group.add_argument("--apply", action="store_true", help="Write missing model proposals.")
    parser.add_argument("--all-versions", action="store_true", help="Backfill all versions instead of active only.")
    args = parser.parse_args()

    apply_changes = args.apply
    print(f"mode={'apply' if apply_changes else 'dry-run'} scope={'all-versions' if args.all_versions else 'active-only'}")

    registries, _ = AlgorithmRegistryRepository.list_algorithms(page=1, page_size=PAGE_SIZE)
    scanned = 0
    missing = 0
    updated = 0
    samples: list[str] = []

    for registry in registries:
        algorithm_id = str(registry.get("algorithm_id") or "")
        if not algorithm_id:
            continue
        version_ids: list[str] = []
        if args.all_versions:
            versions, _ = AlgorithmVersionRepository.list_versions(
                algorithm_id=algorithm_id,
                page=1,
                page_size=PAGE_SIZE,
            )
            version_ids = [str(item.get("version_id") or "") for item in versions if item.get("version_id")]
        else:
            active_version_id = str(registry.get("active_version_id") or "")
            if active_version_id:
                version_ids = [active_version_id]

        for version_id in version_ids:
            version_doc = AlgorithmVersionRepository.find_one({"version_id": version_id})
            if not version_doc:
                continue
            scanned += 1
            current_proposal = version_doc.get("model_proposal")
            if isinstance(current_proposal, dict) and current_proposal:
                continue
            proposal, source = resolve_model_proposal(version_doc)
            if proposal is None:
                continue
            missing += 1
            if len(samples) < 5:
                samples.append(f"{algorithm_id}/{version_id}: source={source} proposal={str(proposal)[:120]}")
            if apply_changes:
                fields = {
                    "model_proposal": proposal,
                    "updated_at": utc_now(),
                }
                if AlgorithmVersionRepository.update_fields(version_id, fields):
                    updated += 1

    print(f"summary: scanned={scanned} missing={missing} updated={updated}")
    for sample in samples:
        print(f"sample: {sample}")


if __name__ == "__main__":
    main()
