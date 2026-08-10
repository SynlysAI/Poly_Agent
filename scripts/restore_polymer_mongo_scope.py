"""Remove Metal-only records from the shared Mongo database.

Default mode is a read-only report.  Stop both application stacks and use
``--apply`` only after the Agirent SQLite snapshot has been verified.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.infra.mongo import get_database  # noqa: E402


ALLOY_VALUES = {
    "titanium_alloy",
    "nickel_superalloy",
    "stainless_steel",
    "aluminum_alloy",
    "copper_alloy",
}
METAL_ONLY_ALGORITHM_IDS = {"lpbf_porosity_predictor", "am_alloy_property_predictor"}


def _contains_alloy(value: Any) -> bool:
    if isinstance(value, str):
        return value in ALLOY_VALUES
    if isinstance(value, dict):
        return any(_contains_alloy(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_alloy(item) for item in value)
    return False


def is_metal_registry_entry(document: dict[str, Any]) -> bool:
    return str(document.get("algorithm_id", "")) in METAL_ONLY_ALGORITHM_IDS


def is_metal_problem_spec(document: dict[str, Any]) -> bool:
    return _contains_alloy(document.get("material_family"))


def is_metal_handoff(document: dict[str, Any]) -> bool:
    return _contains_alloy(document.get("material_scope")) or str(document.get("algorithm_id", "")).startswith("lpbf_")


def assert_no_alloy_values(database: Any) -> None:
    """Verify the entire polymer database, not only the cleaned collections."""
    remaining: list[tuple[str, Any]] = []
    for collection_name in database.list_collection_names():
        if collection_name.startswith("system."):
            continue
        for document in database[collection_name].find({}, {"_id": 0}):
            if _contains_alloy(document):
                remaining.append((collection_name, document))
    if remaining:
        names = ", ".join(sorted({name for name, _ in remaining}))
        raise RuntimeError(f"alloy values remain in poly_agent collections: {names}")


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _write_backup(directory: Path, documents: dict[str, list[dict[str, Any]]]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for collection_name, rows in documents.items():
        (directory / f"{collection_name}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )


def inspect(database: Any) -> dict[str, list[dict[str, Any]]]:
    registry = [doc for doc in database["algorithm_registry_entries"].find({}, {"_id": 0}) if is_metal_registry_entry(doc)]
    specs = [doc for doc in database["research_problem_specs"].find({}, {"_id": 0}) if is_metal_problem_spec(doc)]
    handoffs = [doc for doc in database["algorithm_handoffs"].find({}, {"_id": 0}) if is_metal_handoff(doc)]
    return {
        "algorithm_registry_entries": registry,
        "research_problem_specs": specs,
        "algorithm_handoffs": handoffs,
    }


def apply_cleanup(database: Any, documents: dict[str, list[dict[str, Any]]]) -> None:
    for collection_name, rows in documents.items():
        if not rows:
            continue
        primary_key = {
            "algorithm_registry_entries": "algorithm_id",
            "research_problem_specs": "problem_spec_id",
            "algorithm_handoffs": "handoff_id",
        }[collection_name]
        database[collection_name].delete_many({primary_key: {"$in": [row[primary_key] for row in rows]}})

    from app.services.research_engine_service import ResearchEngineService

    ResearchEngineService().seed_default_algorithms()

    assert_no_alloy_values(database)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore Poly_Agent Mongo data to polymer-only scope")
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    database = get_database()
    documents = inspect(database)
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    for collection_name, rows in documents.items():
        print(f"{collection_name}: {len(rows)} metal documents")
    if not args.apply:
        return 0

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = args.backup_dir or (
        PROJECT_ROOT / ".runtime" / "backups" / f"polymer-scope-{timestamp}"
    )
    _write_backup(backup_dir, documents)
    apply_cleanup(database, documents)
    print(f"backup={backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
