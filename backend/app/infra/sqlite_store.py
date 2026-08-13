"""本地 SQLite 文档存储。

开发/测试环境使用该存储替代 MongoDB；SQLite 的 WAL 与 BEGIN IMMEDIATE
保证后端、worker 等跨进程访问时的原子读写。
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.poly_data_extra_datasets import EXTRA_DATASET_SPECS


COLLECTION_NAMES = [
    "users",
    "invite_codes",
    "alchemist_sessions",
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
    "assistant_tool_calls",
    "assistant_chats",
    "assistant_messages",
    "assistant_runs",
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


def _json_default(value: Any) -> str:
    """JSON 序列化默认处理。"""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def clone_document(document: dict[str, Any]) -> dict[str, Any]:
    """复制文档，避免调用方意外修改存储态。"""
    return deepcopy(document)


class SqliteDocumentStore:
    """SQLite 文档存储，接口与旧 demo JSON store 兼容。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """创建独立连接并启用跨进程安全参数。"""
        connection = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        # 多个进程同时首次打开文件时，设置 WAL 可能与写事务短暂竞争。
        for attempt in range(5):
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 4:
                    raise
                time.sleep(0.01)
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_name TEXT NOT NULL,
                document_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_collection "
            "ON documents(collection_name)"
        )
        return connection

    @contextmanager
    def _connection(self):
        """提供自动提交并关闭的连接。"""
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _load_unlocked(self, connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
        """在当前连接事务内读取全部文档。"""
        data: dict[str, list[dict[str, Any]]] = {name: [] for name in COLLECTION_NAMES}
        rows = connection.execute(
            "SELECT collection_name, document_json FROM documents ORDER BY id"
        ).fetchall()
        for row in rows:
            name = row["collection_name"]
            if name in data:
                data[name].append(json.loads(row["document_json"]))
        return data

    def _save_unlocked(
        self,
        connection: sqlite3.Connection,
        data: dict[str, list[dict[str, Any]]],
    ) -> None:
        """在当前连接事务内整体替换全部文档。"""
        connection.execute("DELETE FROM documents")
        rows = [
            (name, json.dumps(document, ensure_ascii=False, default=_json_default))
            for name in COLLECTION_NAMES
            for document in data.get(name, [])
        ]
        connection.executemany(
            "INSERT INTO documents(collection_name, document_json) VALUES (?, ?)",
            rows,
        )

    def load(self) -> dict[str, list[dict[str, Any]]]:
        """读取完整数据。"""
        with self._connection() as connection:
            return self._load_unlocked(connection)

    def save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """以原子事务保存完整数据。"""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._save_unlocked(connection, data)

    def mutate(self, callback):
        """以 SQLite 写事务保护方式读改写。"""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            data = self._load_unlocked(connection)
            result = callback(data)
            self._save_unlocked(connection, data)
            return result

    def clear(self) -> None:
        """清空 SQLite 文件中的全部文档。"""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM documents")

    def ping(self) -> bool:
        """验证 SQLite 文件是否可读。"""
        try:
            with self._connection() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False


demo_store = SqliteDocumentStore(settings.sqlite_database_path)
