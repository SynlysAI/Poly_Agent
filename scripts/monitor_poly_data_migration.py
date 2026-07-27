#!/usr/bin/env python3
"""Continuously monitor Poly Data migration progress from the command line."""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.data_catalog_service import DATASET_DEFINITIONS  # noqa: E402
from app.services.data_catalog_service import MINIO_OBJECT_MAPPINGS  # noqa: E402
from app.services.data_catalog_service import S3ObjectClient  # noqa: E402
from app.services.poly_data_extra_datasets import EXTRA_DATASET_SPECS  # noqa: E402


DEFAULT_MONGODB_URI = "mongodb://admin:password123@10.26.15.93:27018/ai4ms?authSource=admin"
DEFAULT_BUCKET = "polymer-data"
DEFAULT_LOG_FILES = [
    PROJECT_ROOT / ".runtime" / "logs" / "extra_05_12_migration.log",
    PROJECT_ROOT / ".runtime" / "logs" / "md_allatom_migration.log",
]
CORE_DATASET_IDS = ["radonpy_pi1070", "pi1m_v2", "smipoly", "polyuniverse", "md_allatom"]
EXTRA_DATASET_IDS = [spec.dataset_id for spec in EXTRA_DATASET_SPECS]
OBJECT_MAPPINGS_BY_DATASET: dict[str, list[str]] = defaultdict(list)
for mapping in MINIO_OBJECT_MAPPINGS:
    OBJECT_MAPPINGS_BY_DATASET[mapping.dataset_id].append(mapping.canonical_key)


@dataclass(frozen=True)
class DatasetRow:
    dataset_id: str
    display_name: str
    row_count: int
    record_count: int
    coverage_percent: float | None
    collection_name: str | None
    status: str
    expected_object_count: int
    minio_object_count: int | None
    catalog_object_count: int
    progress_state: str
    updated_at: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongodb-uri", default=load_env_value("DATA_ASSET_MONGODB_URI") or DEFAULT_MONGODB_URI)
    parser.add_argument("--bucket", default=load_env_value("MINIO_BUCKET") or DEFAULT_BUCKET)
    parser.add_argument("--minio-endpoint", default=load_env_value("MINIO_ENDPOINT") or settings.minio_endpoint)
    parser.add_argument("--minio-access-key", default=load_env_value("MINIO_ACCESS_KEY") or settings.minio_access_key)
    parser.add_argument("--minio-secret-key", default=load_env_value("MINIO_SECRET_KEY") or settings.minio_secret_key)
    parser.add_argument(
        "--minio-secure",
        action="store_true",
        default=load_env_bool("MINIO_SECURE", settings.minio_secure),
    )
    parser.add_argument(
        "--database",
        default=load_env_value("DATA_ASSET_MONGODB_DATABASE") or "poly_data",
        help="MongoDB database to inspect",
    )
    parser.add_argument(
        "--log",
        action="append",
        default=[],
        help="log file to tail; may be repeated",
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help="optional migration PID to watch",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="poll interval in seconds",
    )
    parser.add_argument(
        "--tail-lines",
        type=int,
        default=20,
        help="number of recent log lines to print on each refresh",
    )
    parser.add_argument(
        "--dataset-ids",
        default=",".join([*CORE_DATASET_IDS, *EXTRA_DATASET_IDS]),
        help="comma-separated dataset ids to report",
    )
    return parser.parse_args()


def load_env_value(key: str) -> str | None:
    for path in [PROJECT_ROOT / "backend" / ".env", PROJECT_ROOT / ".env"]:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            env_key, env_value = line.split("=", 1)
            if env_key.strip() == key:
                return env_value.strip().strip('"').strip("'")
    return os.getenv(key)


def load_env_bool(key: str, default: bool = False) -> bool:
    value = load_env_value(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_catalog_definitions() -> dict[str, dict[str, Any]]:
    return dict(DATASET_DEFINITIONS)


def build_minio_client(args: argparse.Namespace) -> S3ObjectClient | None:
    client = S3ObjectClient(
        endpoint=str(args.minio_endpoint or ""),
        access_key=str(args.minio_access_key or ""),
        secret_key=str(args.minio_secret_key or ""),
        secure=bool(args.minio_secure),
    )
    return client if client.is_configured() else None


def infer_progress_state(
    *,
    expected_object_count: int,
    minio_object_count: int | None,
    record_count: int,
    catalog_object_count: int,
) -> str:
    if expected_object_count <= 0:
        return "no_objects"
    if minio_object_count is None:
        return "minio_not_configured"
    if minio_object_count == 0 and record_count == 0 and catalog_object_count == 0:
        return "pending"
    if 0 < minio_object_count < expected_object_count:
        return "uploading"
    if minio_object_count >= expected_object_count and record_count == 0:
        return "uploaded"
    if minio_object_count >= expected_object_count and record_count > 0:
        return "imported" if catalog_object_count >= expected_object_count else "importing"
    if catalog_object_count > 0:
        return "catalogued"
    return "partial"


def collect_rows(db: Any, dataset_ids: list[str], *, minio_client: S3ObjectClient | None, bucket: str) -> list[DatasetRow]:
    definitions = load_catalog_definitions()
    extra_by_id = {spec.dataset_id: spec for spec in EXTRA_DATASET_SPECS}
    stats_rows = {
        str(doc.get("dataset_id")): dict(doc)
        for doc in db["dataset_stats"].find({}, {"_id": 0})
        if doc.get("dataset_id")
    }
    dataset_rows = {
        str(doc.get("dataset_id")): dict(doc)
        for doc in db["datasets"].find({}, {"_id": 0})
        if doc.get("dataset_id")
    }
    rows: list[DatasetRow] = []
    for dataset_id in dataset_ids:
        definition = definitions.get(dataset_id, {})
        extra_spec = extra_by_id.get(dataset_id)
        doc = dataset_rows.get(dataset_id, {})
        stats = stats_rows.get(dataset_id, {})
        object_keys = list(dict.fromkeys(OBJECT_MAPPINGS_BY_DATASET.get(dataset_id, [])))
        catalog_object_count = int(db["dataset_objects"].count_documents({"dataset_id": dataset_id}))
        minio_object_count = None
        if minio_client is not None:
            minio_object_count = sum(1 for object_key in object_keys if minio_client.head_object(bucket, object_key))
        row_count = int(doc.get("row_count") or definition.get("row_count") or (extra_spec.row_count if extra_spec else 0))
        record_count = int(doc.get("record_count") or stats.get("record_count") or 0)
        coverage_percent = None
        if row_count:
            coverage_percent = round(record_count / row_count * 100, 4)
        progress_state = infer_progress_state(
            expected_object_count=len(object_keys),
            minio_object_count=minio_object_count,
            record_count=record_count,
            catalog_object_count=catalog_object_count,
        )
        rows.append(
            DatasetRow(
                dataset_id=dataset_id,
                display_name=str(doc.get("display_name") or definition.get("display_name") or dataset_id),
                row_count=row_count,
                record_count=record_count,
                coverage_percent=coverage_percent,
                collection_name=str(doc.get("record_collection_key") or ""),
                status=str(doc.get("record_mode") or stats.get("status") or "metadata_only"),
                expected_object_count=len(object_keys),
                minio_object_count=minio_object_count,
                catalog_object_count=catalog_object_count,
                progress_state=progress_state,
                updated_at=normalize_dt(doc.get("updated_at") or stats.get("updated_at")),
            )
        )
    return rows


def normalize_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def collect_upload_jobs(db: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """Return recent upload jobs with derived progress and failure details."""
    rows = [dict(row) for row in db["upload_jobs"].find({}, {"_id": 0})]
    rows.sort(key=lambda row: str(row.get("started_at") or ""), reverse=True)
    jobs: list[dict[str, Any]] = []
    for row in rows[: max(limit, 0)]:
        total_files = int(row.get("total_files") or 0)
        completed_files = int(row.get("completed_files") or 0)
        started_at = _as_datetime(row.get("started_at"))
        updated_at = _as_datetime(row.get("updated_at"))
        elapsed = max((updated_at - started_at).total_seconds(), 0.001) if started_at and updated_at else None
        uploaded_bytes = int(row.get("uploaded_bytes") or 0)
        failures = [
            dict(item)
            for item in db["upload_checkpoints"].find(
                {"job_id": row.get("job_id"), "status": "failed"},
                {"_id": 0, "object_key": 1, "attempts": 1, "error": 1, "updated_at": 1},
            )
        ]
        failures.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        jobs.append(
            {
                **row,
                "progress_percent": round(completed_files / total_files * 100, 2) if total_files else 0.0,
                "throughput_mib_per_second": round(uploaded_bytes / 1024 / 1024 / elapsed, 2) if elapsed else None,
                "recent_failures": failures[:5],
            }
        )
    return jobs


def tail_file(path: Path, *, last_offset: int, max_lines: int) -> tuple[list[str], int]:
    if not path.exists():
        return [], last_offset
    size = path.stat().st_size
    if size < last_offset:
        last_offset = 0
    with path.open("r", encoding="utf-8", errors="replace") as fp:
        fp.seek(last_offset)
        data = fp.read()
        new_offset = fp.tell()
    lines = [line.rstrip("\n") for line in data.splitlines() if line.strip()]
    return lines[-max_lines:], new_offset


def pid_alive(pid: int | None) -> bool:
    if pid is None:
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def print_snapshot(
    *,
    db: Any,
    dataset_ids: list[str],
    pid: int | None,
    logs: list[Path],
    log_offsets: dict[Path, int],
    tail_lines: int,
    minio_client: S3ObjectClient | None,
    bucket: str,
) -> None:
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{stamp}] pid={pid or '-'} alive={'yes' if pid_alive(pid) else 'no'}", flush=True)
    minio_state = "not_configured" if minio_client is None else f"configured@{minio_client.endpoint}"
    print(
        f"bucket={bucket} minio={minio_state} dataset_stats={db['dataset_stats'].estimated_document_count()} migration_manifests={db['migration_manifests'].estimated_document_count()}",
        flush=True,
    )
    print("dataset | objects | catalog | records | rows | coverage | mode/state | updated", flush=True)
    print("-" * 112, flush=True)
    for row in collect_rows(db, dataset_ids, minio_client=minio_client, bucket=bucket):
        coverage = "-" if row.coverage_percent is None else f"{row.coverage_percent:.4f}%"
        object_progress = "?" if row.minio_object_count is None else f"{row.minio_object_count}/{row.expected_object_count}"
        print(
            f"{row.display_name[:18]:18} | "
            f"{object_progress:7} | "
            f"{row.catalog_object_count:7d} | "
            f"{row.record_count:7d} | "
            f"{row.row_count:7d} | "
            f"{coverage:8} | "
            f"{(row.status[:10] + '/' + row.progress_state[:10]):11.11} | "
            f"{(row.updated_at or '-'):23}",
            flush=True,
        )
    jobs = collect_upload_jobs(db)
    print("\nupload jobs", flush=True)
    if not jobs:
        print("  (none)", flush=True)
    for job in jobs:
        throughput = job.get("throughput_mib_per_second")
        throughput_text = "-" if throughput is None else f"{throughput:.2f} MiB/s"
        print(
            f"  {job.get('job_id')} status={job.get('status')} workers={job.get('worker_count')} "
            f"files={job.get('completed_files', 0)}/{job.get('total_files', 0)} "
            f"skipped={job.get('skipped_files', 0)} failed={job.get('failed_files', 0)} "
            f"progress={job.get('progress_percent', 0):.2f}% throughput={throughput_text}",
            flush=True,
        )
        for failure in job.get("recent_failures", []):
            print(
                f"    failed key={failure.get('object_key')} attempts={failure.get('attempts')} "
                f"error={failure.get('error')}",
                flush=True,
            )
    for log in logs:
        lines, new_offset = tail_file(log, last_offset=log_offsets.get(log, 0), max_lines=tail_lines)
        log_offsets[log] = new_offset
        print(f"\nlog: {log}", flush=True)
        if not lines:
            print("  (no new lines)", flush=True)
            continue
        for line in lines:
            print(f"  {line}", flush=True)


def main() -> int:
    args = parse_args()
    from pymongo import MongoClient

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    dataset_ids = [item.strip() for item in str(args.dataset_ids).split(",") if item.strip()]
    logs = [Path(item).expanduser() for item in args.log] if args.log else [path for path in DEFAULT_LOG_FILES if path.exists()]
    log_offsets = {path: 0 for path in logs}
    client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    db = client[args.database]
    minio_client = build_minio_client(args)

    try:
        while True:
            print_snapshot(
                db=db,
                dataset_ids=dataset_ids,
                pid=args.pid,
                logs=logs,
                log_offsets=log_offsets,
                tail_lines=args.tail_lines,
                minio_client=minio_client,
                bucket=str(args.bucket),
            )
            if args.pid is not None and not pid_alive(args.pid):
                print("\nprocess exited; monitoring finished.")
                return 0
            time.sleep(max(args.interval, 1.0))
    except KeyboardInterrupt:
        print("\nmonitor stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
