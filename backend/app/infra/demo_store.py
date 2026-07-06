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


COLLECTION_NAMES = [
    "computation_runs",
    "computation_artifacts",
    "optimization_campaigns",
    "optimization_candidates",
    "optimization_suggestions",
    "optimization_observations",
    "service_integrations",
    "audit_events",
    "research_problem_specs",
    "algorithm_registry_entries",
    "algorithm_runs",
    "research_runs",
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
