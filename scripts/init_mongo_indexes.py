"""Initialize MongoDB indexes for Poly Agent production queries."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.mongo import get_database  # noqa: E402
from app.core.config import settings  # noqa: E402


INDEXES: dict[str, list[tuple[str, list[tuple[str, int]]]]] = {
    "computation_runs": [
        ("owner_status_updated", [("created_by", 1), ("status", 1), ("updated_at", -1)]),
        ("campaign_suggestion", [("campaign_id", 1), ("suggestion_id", 1)]),
    ],
    "computation_artifacts": [
        ("run_created", [("run_id", 1), ("created_at", -1)]),
    ],
    "audit_events": [
        ("entity_created", [("entity_type", 1), ("entity_id", 1), ("created_at", -1)]),
        ("actor_created", [("actor_user_id", 1), ("created_at", -1)]),
    ],
    "research_problem_specs": [
        ("owner_status_updated", [("owner_id", 1), ("status", 1), ("updated_at", -1)]),
        ("campaign", [("campaign_id", 1)]),
    ],
    "algorithm_runs": [
        ("owner_status_updated", [("created_by", 1), ("status", 1), ("updated_at", -1)]),
        ("research_stage", [("research_run_id", 1), ("stage_run_id", 1)]),
    ],
    "research_runs": [
        ("owner_status_updated", [("created_by", 1), ("status", 1), ("updated_at", -1)]),
        ("problem_spec", [("problem_spec_id", 1)]),
    ],
    "algorithm_packages": [
        ("owner_created", [("created_by", 1), ("created_at", -1)]),
    ],
    "algorithm_versions": [
        ("algorithm_status_created", [("algorithm_id", 1), ("status", 1), ("created_at", -1)]),
        ("algorithm_visibility_status_created", [("algorithm_id", 1), ("visibility", 1), ("status", 1), ("created_at", -1)]),
    ],
    "algorithm_registry_entries": [
        ("family_source_visibility_owner_status", [("algorithm_family", 1), ("source", 1), ("visibility", 1), ("owner", 1), ("status", 1)]),
    ],
    "agent_tool_policies": [
        ("algorithm_id", [("algorithm_id", 1)]),
    ],
    "agent_exec_runs": [
        ("run_id_unique", [("run_id", 1)]),
        (
            "provider_status_created",
            [("provider_id", 1), ("status", 1), ("created_at", -1)],
        ),
        ("chat_created", [("chat_id", 1), ("created_at", -1)]),
        ("owner_created", [("created_by", 1), ("created_at", -1)]),
    ],
    "agent_exec_artifacts": [
        ("run_path_unique", [("run_id", 1), ("path", 1)]),
        ("run_id", [("run_id", 1)]),
    ],
    "agent_exec_provider_policies": [
        ("provider_id_unique", [("provider_id", 1)]),
    ],
    "assistant_tool_calls": [
        ("call_id", [("call_id", 1)]),
        ("owner_chat_updated", [("created_by", 1), ("chat_id", 1), ("updated_at", -1)]),
        ("owner_phase_updated", [("created_by", 1), ("phase", 1), ("updated_at", -1)]),
    ],
    "assistant_runtime_assets": [
        ("asset_id", [("asset_id", 1)]),
        ("call_status_expires", [("call_id", 1), ("status", 1), ("expires_at", 1)]),
    ],
    "assistant_chats": [
        ("owner_updated", [("created_by", 1), ("updated_at", -1)]),
        ("owner_archived_updated", [("created_by", 1), ("archived", 1), ("updated_at", -1)]),
    ],
    "assistant_messages": [
        ("chat_created", [("chat_id", 1), ("created_at", 1)]),
        ("owner_chat_created", [("created_by", 1), ("chat_id", 1), ("created_at", 1)]),
    ],
    "report_jobs": [
        ("subject_created", [("subject.subject_type", 1), ("subject.subject_id", 1), ("created_at", -1)]),
        ("owner_status_updated", [("created_by", 1), ("status", 1), ("updated_at", -1)]),
    ],
    "global_task_index": [
        ("owner_module_status_updated", [("owner_id", 1), ("module_id", 1), ("status", 1), ("updated_at", -1)]),
        ("module_status_updated", [("module_id", 1), ("status", 1), ("updated_at", -1)]),
    ],
}

UNIQUE_INDEX_NAMES = {
    "agent_exec_runs.run_id_unique",
    "agent_exec_artifacts.run_path_unique",
    "agent_exec_provider_policies.provider_id_unique",
}


def main() -> None:
    if not settings.uses_mongodb:
        print(f"skip MongoDB index initialization: storage_backend={settings.storage_backend}")
        return
    database = get_database()
    for collection_name, specs in INDEXES.items():
        collection = database[collection_name]
        for index_name, keys in specs:
            collection.create_index(
                keys,
                name=index_name,
                background=True,
                unique=index_name in UNIQUE_INDEX_NAMES,
            )
            print(f"created index {collection_name}.{index_name}")


if __name__ == "__main__":
    main()
