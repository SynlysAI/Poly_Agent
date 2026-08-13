"""把本地 Mongo 的垂类算法/模型配置合并进 SQLite。

该脚本只对源 MongoDB 执行读取操作；目标只能是本地 SQLite 文件。默认
dry-run，显式传 ``--apply`` 才会备份 SQLite、按主键合并写入并生成清单。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import MongoClient
from pymongo.read_preferences import ReadPreference


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.infra.sqlite_store import SqliteDocumentStore


DEFAULT_MONGODB_URI = "mongodb://127.0.0.1:27017/poly_agent"
DEFAULT_SOURCE_DATABASE = "poly_agent"

# 只导入垂类算法的关联数据；model_config 集合整体导入。
RELATED_COLLECTIONS = (
    "algorithm_packages",
    "algorithm_versions",
    "algorithm_resources",
    "algorithm_runs",
)
MODEL_CONFIG_COLLECTIONS = (
    "algorithm_handoffs",
    "llm_routing_configs",
    "service_integrations",
)
COLLECTION_PRIMARY_KEYS = {
    "algorithm_registry_entries": "algorithm_id",
    "algorithm_packages": "package_id",
    "algorithm_versions": "version_id",
    "algorithm_resources": "resource_id",
    "algorithm_runs": "run_id",
    "algorithm_handoffs": "handoff_id",
    "llm_routing_configs": "config_id",
    "service_integrations": "service_key",
}


def sanitize_document(document: dict[str, Any]) -> dict[str, Any]:
    """递归把 Mongo 专属类型转换成 JSON 兼容值。"""

    def convert(value: Any) -> Any:
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return convert(document)


def select_registry_documents(database: Any) -> list[dict[str, Any]]:
    """选择垂类预测算法和远程接口模型。"""
    collection = database["algorithm_registry_entries"]
    return [
        sanitize_document(dict(document))
        for document in collection.find({}, {"_id": 0})
        if document.get("algorithm_family") == "vertical_prediction"
        or document.get("source") == "remote_interface"
    ]


def load_source_documents(database: Any) -> dict[str, list[dict[str, Any]]]:
    """读取本次要同步的源文档。"""
    registry = select_registry_documents(database)
    algorithm_ids = sorted(
        {
            document["algorithm_id"]
            for document in registry
            if document.get("algorithm_id")
        }
    )
    documents: dict[str, list[dict[str, Any]]] = {
        "algorithm_registry_entries": registry,
    }

    for collection_name in RELATED_COLLECTIONS:
        rows: list[dict[str, Any]] = []
        if collection_name in database.list_collection_names():
            rows = [
                sanitize_document(dict(document))
                for document in database[collection_name].find(
                    {"algorithm_id": {"$in": algorithm_ids}}, {"_id": 0}
                )
            ]
        documents[collection_name] = rows

    for collection_name in MODEL_CONFIG_COLLECTIONS:
        rows = []
        if collection_name in database.list_collection_names():
            rows = [
                sanitize_document(dict(document))
                for document in database[collection_name].find({}, {"_id": 0})
            ]
        documents[collection_name] = rows

    return documents


def merge_documents(
    existing: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    primary_key: str,
) -> list[dict[str, Any]]:
    """保留未命中的旧行，用源行替换同主键行并追加新行。"""
    unique_rows = {
        row[primary_key]: row
        for row in source_rows
        if row.get(primary_key) is not None
    }
    incoming_keys = set(unique_rows)
    kept = [
        row for row in existing if row.get(primary_key) not in incoming_keys
    ]
    return [*kept, *unique_rows.values()]


def build_target_data(
    target_store: SqliteDocumentStore,
    source_documents: dict[str, list[dict[str, Any]]],
    existing_data: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按集合主键把源数据合并进现有 SQLite 数据。"""
    data = dict(existing_data) if existing_data is not None else target_store.load()
    for collection_name, source_rows in source_documents.items():
        primary_key = COLLECTION_PRIMARY_KEYS[collection_name]
        data[collection_name] = merge_documents(
            data.get(collection_name, []), source_rows, primary_key
        )
    return data


def summarize_changes(
    current: dict[str, list[dict[str, Any]]],
    target: dict[str, list[dict[str, Any]]],
    source_documents: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """汇总每个集合的源计数、新增、替换和最终计数。"""
    summaries = []
    for collection_name, source_rows in source_documents.items():
        primary_key = COLLECTION_PRIMARY_KEYS[collection_name]
        existing_keys = {
            row.get(primary_key)
            for row in current.get(collection_name, [])
            if row.get(primary_key) is not None
        }
        incoming_keys = [
            row.get(primary_key)
            for row in source_rows
            if row.get(primary_key) is not None
        ]
        summaries.append(
            {
                "collection": collection_name,
                "source_count": len(source_rows),
                "existing_count": len(current.get(collection_name, [])),
                "added": sum(key not in existing_keys for key in incoming_keys),
                "replaced": sum(key in existing_keys for key in incoming_keys),
                "final_count": len(target[collection_name]),
            }
        )
    return summaries


def backup_sqlite(output_path: Path, timestamp: str) -> Path:
    """把 SQLite 及 WAL/SHM 文件复制到时间戳备份目录。"""
    backup_dir = output_path.parent / "backups" / f"vertical-algorithms-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, backup_dir / output_path.name)
    for suffix in ("-wal", "-shm"):
        sibling = Path(f"{output_path}{suffix}")
        if sibling.exists():
            shutil.copy2(sibling, backup_dir / sibling.name)
    return backup_dir


def write_manifest(manifest_path: Path, payload: dict[str, Any]) -> None:
    """写入本次同步清单。"""
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="同步垂类算法/模型配置到本地 SQLite")
    parser.add_argument(
        "--mongodb-uri",
        default=DEFAULT_MONGODB_URI,
        help="源 MongoDB 连接串（只读）",
    )
    parser.add_argument("--source-database", default=DEFAULT_SOURCE_DATABASE)
    parser.add_argument(
        "--output-path",
        default=str(settings.sqlite_database_path),
        help="目标 SQLite 文件路径",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="备份并写入 SQLite；缺省只打印 dry-run 汇总",
    )
    return parser


def main() -> int:
    """执行一次性只读同步。"""
    args = build_parser().parse_args()
    client = MongoClient(
        args.mongodb_uri,
        serverSelectionTimeoutMS=5000,
        read_preference=ReadPreference.SECONDARY_PREFERRED,
    )
    try:
        client.admin.command("ping")
        source_database = client[args.source_database]
        source_documents = load_source_documents(source_database)
    finally:
        client.close()

    output_path = Path(args.output_path).expanduser().resolve()
    target_store = SqliteDocumentStore(output_path)
    current = (
        target_store.load()
        if args.apply or output_path.exists()
        else {}
    )
    target = build_target_data(target_store, source_documents, current)
    summaries = summarize_changes(current, target, source_documents)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    payload = {
        "operation": "vertical_algorithm_sqlite_sync",
        "source_database": args.source_database,
        "dry_run": not args.apply,
        "target_path": str(output_path),
        "backup_path": None,
        "collections": summaries,
    }

    if not args.apply:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    backup_dir = backup_sqlite(output_path, timestamp)
    payload["backup_path"] = str(backup_dir)
    target_store.save(target)
    manifest_path = output_path.with_name(
        f"{output_path.name}.vertical-algorithms.manifest.json"
    )
    write_manifest(manifest_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
