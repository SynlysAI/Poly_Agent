"""Backfill creator names for old uploaded algorithm versions and packages.

Old algorithm_versions / algorithm_packages documents were created before the
``created_by_name`` field existed, so the version management UI fell back to
showing the raw ``created_by`` user id. This script resolves each stored
``created_by`` user id against the unified auth users collection and writes the
matching ``username`` into ``created_by_name``.

Default behavior is dry-run. Use --dry-run to be explicit or --apply to write
changes. The script is idempotent and can be re-run safely.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.mongo import get_database, get_users_collection  # noqa: E402


COLLECTIONS = ("algorithm_versions", "algorithm_packages")


def _needs_backfill_filter() -> dict[str, Any]:
    """Documents whose created_by_name is missing/empty or is still the raw id."""
    return {
        "created_by": {"$exists": True, "$nin": ["", None]},
        "$expr": {
            "$or": [
                {"$eq": [{"$ifNull": ["$created_by_name", ""]}, ""]},
                {"$eq": ["$created_by_name", "$created_by"]},
            ]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill created_by_name from user ids for algorithm versions and packages."
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Print planned changes without writing.")
    mode_group.add_argument("--apply", action="store_true", help="Write changes to MongoDB.")
    args = parser.parse_args()

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode}")

    database = get_database()
    users = get_users_collection()

    id_to_name: dict[str, str] = {}
    for doc in users.find({}, {"_id": 0, "user_id": 1, "username": 1}):
        user_id = str(doc.get("user_id") or "").strip()
        username = str(doc.get("username") or "").strip()
        if user_id and username:
            id_to_name[user_id] = username
    print(f"users loaded: {len(id_to_name)}")

    total_pending = 0
    total_unresolved = 0
    for collection_name in COLLECTIONS:
        collection = database[collection_name]
        docs = list(collection.find(_needs_backfill_filter(), {"_id": 1, "created_by": 1}))
        pending = 0
        unresolved = 0
        sample_mappings: list[str] = []
        for doc in docs:
            created_by = str(doc.get("created_by") or "").strip()
            username = id_to_name.get(created_by)
            if not username:
                unresolved += 1
                continue
            pending += 1
            if len(sample_mappings) < 5:
                sample_mappings.append(f"{created_by} -> {username}")
        print(
            f"{collection_name}: needs_backfill={len(docs)} "
            f"resolvable={pending} unresolved={unresolved}"
        )
        if sample_mappings:
            print(f"{collection_name} samples: " + "; ".join(sample_mappings))
        if args.apply and pending:
            updated = 0
            for doc in docs:
                created_by = str(doc.get("created_by") or "").strip()
                username = id_to_name.get(created_by)
                if not username:
                    continue
                result = collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"created_by_name": username}},
                )
                updated += result.modified_count
            print(f"{collection_name}: updated={updated}")
        total_pending += pending
        total_unresolved += unresolved

    print(f"summary: pending={total_pending} unresolved={total_unresolved}")


if __name__ == "__main__":
    main()
