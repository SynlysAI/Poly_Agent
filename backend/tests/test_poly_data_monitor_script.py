"""Poly Data migration monitor tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "monitor_poly_data_migration.py"
SPEC = importlib.util.spec_from_file_location("monitor_poly_data_migration", SCRIPT_PATH)
assert SPEC and SPEC.loader
monitor_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = monitor_script
SPEC.loader.exec_module(monitor_script)


class FakeCollection:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])

    def find(self, filters: dict, projection: dict | None = None):
        return [dict(row) for row in self.rows]

    def count_documents(self, filters: dict) -> int:
        if not filters:
            return len(self.rows)
        return sum(1 for row in self.rows if all(row.get(key) == value for key, value in filters.items()))

    def estimated_document_count(self) -> int:
        return len(self.rows)


class FakeDatabase:
    def __init__(self, collections: dict[str, FakeCollection] | None = None) -> None:
        self.collections = collections or {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


class FakeMinioClient:
    def __init__(self, existing: set[str]) -> None:
        self.existing = set(existing)

    def head_object(self, bucket: str, object_key: str):
        return {"size_bytes": 1} if object_key in self.existing else None


def test_collect_rows_reports_minio_progress() -> None:
    db = FakeDatabase(
        {
            "datasets": FakeCollection(
                [
                    {
                        "dataset_id": "omg",
                        "display_name": "OMG",
                        "row_count": 12_886_131,
                        "record_count": 0,
                        "record_mode": "metadata_only",
                    }
                ]
            ),
            "dataset_stats": FakeCollection([]),
            "dataset_objects": FakeCollection([]),
        }
    )
    client = FakeMinioClient({"datasets/omg/docs/readme.md"})

    rows = monitor_script.collect_rows(db, ["omg"], minio_client=client, bucket="polymer-data")

    assert len(rows) == 1
    row = rows[0]
    assert row.expected_object_count == 2
    assert row.minio_object_count == 1
    assert row.catalog_object_count == 0
    assert row.progress_state == "uploading"


def test_collect_upload_jobs_reports_live_throughput_and_failures() -> None:
    db = FakeDatabase(
        {
            "upload_jobs": FakeCollection(
                [
                    {
                        "job_id": "md-allatom-1",
                        "job_type": "md-allatom",
                        "status": "running",
                        "worker_count": 8,
                        "total_files": 100,
                        "completed_files": 25,
                        "skipped_files": 5,
                        "failed_files": 2,
                        "total_bytes": 1000,
                        "uploaded_bytes": 400,
                        "started_at": "2026-07-27T08:00:00+00:00",
                        "updated_at": "2026-07-27T08:01:00+00:00",
                    }
                ]
            ),
            "upload_checkpoints": FakeCollection(
                [
                    {
                        "job_id": "md-allatom-1",
                        "object_key": "datasets/md_allatom/raw/C/failed.data",
                        "status": "failed",
                        "attempts": 4,
                        "error": "OSError: failed",
                    }
                ]
            ),
        }
    )

    jobs = monitor_script.collect_upload_jobs(db)

    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "md-allatom-1"
    assert jobs[0]["progress_percent"] == 25.0
    assert jobs[0]["failed_files"] == 2
    assert jobs[0]["recent_failures"][0]["attempts"] == 4
