"""Backfill and correct uploaded algorithm visibility flags.

Default behavior is dry-run. Use --dry-run to be explicit or --apply to write changes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.mongo import get_database  # noqa: E402


COLLECTIONS = ("algorithm_registry_entries", "algorithm_versions", "algorithm_packages")
TARGET_VISIBILITY = {
    "electrolyte_formulation_predictor": "private",
    "raman_structure_analyzer": "public",
}


def _missing_visibility_filter(collection_name: str) -> dict[str, Any]:
    filters: dict[str, Any] = {"visibility": {"$exists": False}}
    if collection_name == "algorithm_registry_entries":
        filters["source"] = "uploaded_package"
    return filters


def _count_algorithm_visibility(collection: Any, algorithm_id: str, visibility: str) -> int:
    return int(collection.count_documents({"algorithm_id": algorithm_id, "visibility": {"$ne": visibility}}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Update uploaded algorithm visibility flags.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    mode_group.add_argument("--apply", action="store_true", help="Write changes to MongoDB.")
    args = parser.parse_args()

    database = get_database()
    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode}")

    for collection_name in COLLECTIONS:
        collection = database[collection_name]

        missing_filter = _missing_visibility_filter(collection_name)
        missing_count = int(collection.count_documents(missing_filter))
        print(f"{collection_name}: missing visibility -> private: {missing_count}")
        if args.apply and missing_count:
            collection.update_many(missing_filter, {"$set": {"visibility": "private"}})

        for algorithm_id, visibility in TARGET_VISIBILITY.items():
            update_count = _count_algorithm_visibility(collection, algorithm_id, visibility)
            print(f"{collection_name}: {algorithm_id} -> {visibility}: {update_count}")
            if args.apply and update_count:
                collection.update_many({"algorithm_id": algorithm_id}, {"$set": {"visibility": visibility}})


if __name__ == "__main__":
    main()
