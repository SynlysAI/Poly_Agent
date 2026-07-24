"""Backfill and correct uploaded algorithm visibility and attribution flags.

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
TARGET_ATTRIBUTION = {
    "electrolyte_formulation_predictor": {
        "name": "含氟电解液配方性能预测模型团队",
        "role": "developer",
        "organization": "嘉庚实验室 / 厦门大学",
        "description": "算法由 嘉庚实验室 / 厦门大学 / 含氟电解液配方性能预测模型团队 提供。",
        "url": None,
        "citation_text": None,
        "license": None,
        "logo_asset": None,
        "logo_alt": "嘉庚实验室 / 厦门大学",
        "visibility": "prominent",
    },
    "raman_structure_analyzer": {
        "name": "Raman Structure Analyzer 模型团队",
        "role": "developer",
        "organization": "嘉庚实验室 / 厦门大学",
        "description": "算法由 嘉庚实验室 / 厦门大学 / Raman Structure Analyzer 模型团队 提供。",
        "url": "refer/raman",
        "citation_text": None,
        "license": None,
        "logo_asset": None,
        "logo_alt": "嘉庚实验室 / 厦门大学",
        "visibility": "prominent",
    },
}
TARGET_METHOD_ATTRIBUTION = {
    "raman_structure_analyzer": [
        {
            "name": "Raman/IR structure analysis reference implementation",
            "role": "implementation_source",
            "organization": "Raman Reference Implementation",
            "description": "Adapted from the local refer/raman reference code.",
            "url": None,
            "citation_text": None,
            "license": None,
            "logo_asset": None,
            "logo_alt": "Raman Reference Implementation",
            "visibility": "detail",
        }
    ]
}


def _missing_visibility_filter(collection_name: str) -> dict[str, Any]:
    filters: dict[str, Any] = {"visibility": {"$exists": False}}
    if collection_name == "algorithm_registry_entries":
        filters["source"] = "uploaded_package"
    return filters


def _count_algorithm_visibility(collection: Any, algorithm_id: str, visibility: str) -> int:
    return int(collection.count_documents({"algorithm_id": algorithm_id, "visibility": {"$ne": visibility}}))


def _count_field_mismatch(collection: Any, algorithm_id: str, field: str, value: Any) -> int:
    return int(collection.count_documents({"algorithm_id": algorithm_id, field: {"$ne": value}}))


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

        if collection_name in {"algorithm_registry_entries", "algorithm_versions"}:
            for algorithm_id, attribution in TARGET_ATTRIBUTION.items():
                update_count = _count_field_mismatch(collection, algorithm_id, "developer_attribution", attribution)
                print(f"{collection_name}: {algorithm_id} developer_attribution: {update_count}")
                if args.apply and update_count:
                    set_fields = {"developer_attribution": attribution}
                    if collection_name == "algorithm_versions":
                        set_fields.update(
                            {
                                "contract.developer": attribution["name"],
                                "contract.developer_organization": attribution["organization"],
                                "contract.source_url": attribution["url"],
                            }
                        )
                    collection.update_many({"algorithm_id": algorithm_id}, {"$set": set_fields})

            for algorithm_id, method_attribution in TARGET_METHOD_ATTRIBUTION.items():
                update_count = _count_field_mismatch(collection, algorithm_id, "method_attributions", method_attribution)
                print(f"{collection_name}: {algorithm_id} method_attributions: {update_count}")
                if args.apply and update_count:
                    set_fields = {"method_attributions": method_attribution}
                    if collection_name == "algorithm_versions":
                        set_fields["contract.method_attributions"] = method_attribution
                    collection.update_many({"algorithm_id": algorithm_id}, {"$set": set_fields})


if __name__ == "__main__":
    main()
