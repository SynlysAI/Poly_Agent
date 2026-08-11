"""开发 demo 本地 JSON 数据存储。

该存储仅用于 MongoDB 不可用的本地演示环境；生产和正常开发仍优先使用 MongoDB。
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from app.core.config import settings
from app.services.poly_data_extra_datasets import EXTRA_DATASET_SPECS


COLLECTION_NAMES = [
    "computation_runs",
    "computation_artifacts",
    "optimization_campaigns",
    "optimization_candidates",
    "optimization_suggestions",
    "optimization_observations",
    "service_integrations",
    "llm_routing_configs",
    "audit_events",
    "research_problem_specs",
    "execution_decisions",
    "manual_algorithm_workflows",
    "workflow_runs",
    "algorithm_registry_entries",
    "agent_tool_policies",
    "algorithm_packages",
    "algorithm_versions",
    "algorithm_resources",
    "algorithm_runs",
    "experiment_dispatches",
    "experiment_dispatch_profiles",
    "experiment_dispatch_targets",
    "algorithm_handoffs",
    "research_runs",
    "report_jobs",
    "report_artifacts",
    "poly_data.material_records",
    "poly_data.radonpy_records",
    "poly_data.pi1m_samples",
    "poly_data.smipoly_monomers",
    "poly_data.polyuniverse_monomers",
    "poly_data.md_allatom_files",
    "poly_data.md_allatom_diamines",
    "poly_data.md_allatom_dianhydrides",
    "poly_data.md_allatom_carbon_results",
    *[f"poly_data.{spec.collection_name}" for spec in EXTRA_DATASET_SPECS],
    "poly_data.dataset_stats",
]


class DemoJsonStore:
    """轻量 JSON 存储。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, list[dict[str, Any]]]:
        """读取完整数据。"""
        with self._lock:
            if not self.path.exists():
                return {name: [] for name in COLLECTION_NAMES}
            with self.path.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
            data = {name: list(raw.get(name, [])) for name in COLLECTION_NAMES}
            return data

    def save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """保存完整数据。"""
        with self._lock:
            payload = {name: data.get(name, []) for name in COLLECTION_NAMES}
            tmp_path = self.path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2, default=_json_default)
            tmp_path.replace(self.path)

    def mutate(self, callback):
        """以锁保护方式读改写。"""
        with self._lock:
            data = self.load()
            result = callback(data)
            self.save(data)
            return result


def _json_default(value: Any) -> str:
    """JSON 序列化默认处理。"""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def clone_document(document: dict[str, Any]) -> dict[str, Any]:
    """复制文档，避免调用方意外修改存储态。"""
    return deepcopy(document)


demo_store = DemoJsonStore(settings.runtime_root / "demo-db.json")
