"""一次性把 poly data 样本只读导入本地 SQLite。

该脚本只会对源 MongoDB 执行读取操作，绝不写入、删除或修改源库；目标库只
能是本地 SQLite。生产环境与开发环境共享的数据安全边界在此强制落实。

默认按集合合并导入；显式传 ``--reset`` 时也只清空并重灌 ``poly_data.*``
集合，``users``/``invite_codes`` 等身份数据与其他业务集合始终保留。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from pymongo import MongoClient
from pymongo.read_preferences import ReadPreference

from app.core.config import settings
from app.infra.sqlite_store import COLLECTION_NAMES, SqliteDocumentStore


DEFAULT_SOURCE_DATABASE = "poly_data"
DATASET_STATS_COLLECTION = "dataset_stats"


def poly_data_collection_names() -> list[str]:
    """返回所有 poly_data 数据集合名（不含 poly_data. 前缀）。"""
    prefix = "poly_data."
    return [name[len(prefix):] for name in COLLECTION_NAMES if name.startswith(prefix)]


def source_collection_names(source_db: Any, requested: list[str] | None) -> list[str]:
    """解析并校验需要抽样的源集合名。"""
    available = set(source_db.list_collection_names())
    if requested:
        missing = [name for name in requested if name not in available]
        if missing:
            raise SystemExit(f"源库不存在以下集合：{', '.join(missing)}")
        return requested
    names = poly_data_collection_names()
    return [name for name in names if name in available]


def sample_collection(
    source_db: Any,
    collection_name: str,
    *,
    sample_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    """只读抽取单个集合的样本。

    Args:
        source_db: 源 MongoDB database 对象。
        collection_name: 源集合名。
        sample_size: 每集合最大样本数。

    Returns:
        (源集合估计总量, 样本文档列表)。
    """
    collection = source_db[collection_name]
    total = int(collection.estimated_document_count())
    cursor = collection.find({}, {"_id": 0}).sort("_id", 1)
    if collection_name != DATASET_STATS_COLLECTION:
        cursor = cursor.limit(max(0, sample_size))
    documents = [dict(document) for document in cursor]
    return total, documents


def write_target(
    target_store: SqliteDocumentStore,
    samples: dict[str, list[dict[str, Any]]],
    *,
    reset: bool,
) -> None:
    """把样本写入目标 SQLite；reset 只重灌 poly_data.* 集合。"""
    data = target_store.load()
    if reset:
        for name in data:
            if name.startswith("poly_data."):
                data[name] = []
    for collection_name, documents in samples.items():
        data[f"poly_data.{collection_name}"] = documents
    target_store.save(data)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="只读抽样导入 poly data 到本地 SQLite")
    parser.add_argument(
        "--mongodb-uri",
        default=None,
        help="源 MongoDB 连接串；也可用 SEED_POLY_DATA_MONGODB_URI 注入",
    )
    parser.add_argument("--source-database", default=DEFAULT_SOURCE_DATABASE)
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument(
        "--output-path",
        default=str(settings.sqlite_database_path),
        help="目标 SQLite 文件路径",
    )
    parser.add_argument(
        "--collections",
        default="",
        help="逗号分隔的源集合名；默认导入代码中登记的全部 poly_data 集合",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="清空全部 poly_data.* 集合后重灌（默认合并不清空）",
    )
    parser.add_argument(
        "--no-reset",
        dest="reset",
        action="store_false",
        help="保留现有数据，仅覆盖本次抽样集合（默认行为）",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    """执行一次性只读抽样。"""
    args = build_parser().parse_args()
    mongodb_uri = (
        args.mongodb_uri
        or os.getenv("SEED_POLY_DATA_MONGODB_URI")
        or os.getenv("DATA_ASSET_MONGODB_URI")
    )
    if not mongodb_uri:
        raise SystemExit(
            "缺少 --mongodb-uri，且未设置 SEED_POLY_DATA_MONGODB_URI；"
            "脚本拒绝在不提供只读源连接串的情况下运行。"
        )
    if args.sample_size < 0:
        raise SystemExit("--sample-size 不能为负数")

    client = MongoClient(
        mongodb_uri,
        serverSelectionTimeoutMS=5000,
        read_preference=ReadPreference.SECONDARY_PREFERRED,
    )
    try:
        client.admin.command("ping")
        source_db = client[args.source_database]
        requested = (
            [item.strip() for item in args.collections.split(",") if item.strip()]
            or None
        )
        names = source_collection_names(source_db, requested)
        samples: dict[str, list[dict[str, Any]]] = {}
        manifest_collections: list[dict[str, Any]] = []
        for collection_name in names:
            total, documents = sample_collection(
                source_db,
                collection_name,
                sample_size=args.sample_size,
            )
            samples[collection_name] = documents
            manifest_collections.append(
                {
                    "collection": collection_name,
                    "source_count": total,
                    "sample_count": len(documents),
                }
            )
    finally:
        client.close()

    output_path = Path(args.output_path).expanduser().resolve()
    manifest = {
        "operation": "poly_data_sqlite_seed",
        "source_database": args.source_database,
        "sample_size": args.sample_size,
        "dataset_stats_full": True,
        "target_path": str(output_path),
        "reset": args.reset,
        "dry_run": args.dry_run,
        "collections": manifest_collections,
    }
    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    target_store = SqliteDocumentStore(output_path)
    write_target(target_store, samples, reset=args.reset)
    manifest_path = output_path.with_name(f"{output_path.name}.seed-manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
