"""数据目录 API 和服务测试。"""

from __future__ import annotations

import unittest
import re
import sys
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.core.auth import get_current_user
from app.core.config import settings
from app.infra.demo_store import demo_store
from app.schemas.data_catalog import (
    DataCatalogCollectionAnalysisData,
    DataCatalogCollectionSummary,
    DataCatalogMongoCollectionListData,
    DataCatalogOverviewData,
    DataCatalogSourceStatus,
)
from app.services.data_catalog_service import DataCatalogService

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class FakeS3Client:
    """Small fake S3 client for data catalog service tests."""

    def __init__(self, objects: dict[str, dict] | None = None, configured: bool = True) -> None:
        self.objects = objects or {}
        self.configured = configured
        self.head_calls: list[tuple[str, str]] = []
        self.get_calls: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return self.configured

    def head_object(self, bucket: str, object_key: str) -> dict | None:
        self.head_calls.append((bucket, object_key))
        return self.objects.get(object_key)

    def get_object(self, bucket: str, object_key: str) -> dict | None:
        self.get_calls.append((bucket, object_key))
        item = self.objects.get(object_key)
        if not item:
            return None
        content = item.get("content", b"")
        return {
            "body": BytesIO(content),
            "size_bytes": len(content),
            "mime_type": item.get("mime_type", "application/octet-stream"),
        }


class FakeMongoCollection:
    """Small Mongo collection fake for dataset metadata tests."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def find(self, filters: dict, projection: dict | None = None) -> list[dict]:
        if not filters:
            return [dict(row) for row in self.rows]
        return [
            dict(row)
            for row in self.rows
            if all(self._matches_filter(self._nested_value(row, key), value) for key, value in filters.items())
        ]

    def find_one(self, filters: dict, projection: dict | None = None, **kwargs) -> dict | None:
        rows = self.find(filters, projection)
        sort = kwargs.get("sort")
        if sort:
            for key, direction in reversed(sort):
                rows.sort(key=lambda row: row.get(key) or "", reverse=direction < 0)
        return rows[0] if rows else None

    def count_documents(self, filters: dict) -> int:
        if not filters:
            return len(self.rows)
        return sum(
            1 for row in self.rows
            if all(self._matches_filter(self._nested_value(row, key), value) for key, value in filters.items())
        )

    def estimated_document_count(self) -> int:
        return len(self.rows)

    def _nested_value(self, row: dict, dotted_key: str):
        value = row
        for part in dotted_key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _matches_filter(self, actual, expected) -> bool:
        if isinstance(expected, dict) and "$regex" in expected:
            return re.search(str(expected["$regex"]), str(actual or "")) is not None
        return actual == expected


class FakeMongoDatabase:
    """Collection lookup fake."""

    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self.collections = collections

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return FakeMongoCollection(self.collections.get(name, []))


class ProfileMongoCollection(FakeMongoCollection):
    def __init__(self, rows: list[dict], count: int | None = None) -> None:
        super().__init__(rows)
        self._count = len(rows) if count is None else count

    def find_one(self, filters: dict, projection: dict | None = None, **kwargs) -> dict | None:
        rows = self.find(filters, projection)
        return rows[0] if rows else None

    def count_documents(self, filters: dict) -> int:
        if not filters:
            return self._count
        return super().count_documents(filters)

    def estimated_document_count(self) -> int:
        return self._count


class ProfileMongoDatabase(FakeMongoDatabase):
    def __init__(self, collections: dict[str, list[dict]], counts: dict[str, int] | None = None) -> None:
        super().__init__(collections)
        self.counts = counts or {}

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return ProfileMongoCollection(self.collections.get(name, []), self.counts.get(name))


class DataCatalogServiceTest(unittest.TestCase):
    """覆盖数据目录服务的 MinIO 对象状态逻辑。"""

    def test_dataset_catalog_uses_canonical_paths_and_reports_legacy_objects(self) -> None:
        now = datetime(2026, 7, 11, tzinfo=timezone.utc)
        service = DataCatalogService(
            s3_client=FakeS3Client(
                {
                    "datasets/radonpy_pi1070/docs/readme.md": {
                        "size_bytes": 10211,
                        "last_modified": now,
                    },
                    "poly_agent/datasets/radonpy_pi1070/docs/readme.md": {
                        "size_bytes": 10211,
                        "last_modified": now,
                    },
                }
            )
        )

        data = service.list_datasets()
        radonpy = next(item for item in data.items if item.dataset_id == "radonpy_pi1070")
        readme = next(item for item in radonpy.objects if item.role == "readme")

        self.assertEqual(readme.object_key, "datasets/radonpy_pi1070/docs/readme.md")
        self.assertTrue(readme.exists)
        self.assertEqual(readme.legacy_object_key, "poly_agent/datasets/radonpy_pi1070/docs/readme.md")
        self.assertTrue(readme.legacy_exists)
        self.assertIn("poly_agent/datasets/radonpy_pi1070/docs/readme.md", data.legacy_objects)

    def test_unconfigured_minio_returns_dataset_metadata_without_object_exists(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client(configured=False))

        data = service.list_datasets()

        self.assertEqual(len(data.items), 16)
        self.assertFalse(any(obj.exists for dataset in data.items for obj in dataset.objects))

    def test_minio_objects_use_logical_asset_ids_and_reject_unknown_dataset_without_s3(self) -> None:
        fake_s3 = FakeS3Client(
            {
                "datasets/radonpy_pi1070/docs/readme.md": {
                    "size_bytes": 12,
                    "last_modified": datetime(2026, 7, 29, tzinfo=timezone.utc),
                }
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        data = service.list_minio_objects(dataset_id="radonpy_pi1070")

        self.assertGreaterEqual(data.total, 1)
        readme = next(item for item in data.items if item.role == "readme")
        self.assertEqual(readme.asset_id, "radonpy_pi1070__readme")
        self.assertEqual(readme.filename, "readme.md")
        self.assertTrue(readme.exists)
        self.assertEqual(readme.permission, "download")
        self.assertNotIn("datasets/radonpy_pi1070/docs/readme.md", readme.download_path)

        before_calls = list(fake_s3.head_calls)
        with self.assertRaises(HTTPException) as context:
            service.list_minio_objects(dataset_id="../radonpy_pi1070")

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(fake_s3.head_calls, before_calls)

    def test_minio_download_uses_asset_whitelist_before_s3(self) -> None:
        fake_s3 = FakeS3Client(
            {
                "datasets/radonpy_pi1070/docs/readme.md": {
                    "content": b"# RadonPy\n",
                    "mime_type": "text/markdown",
                }
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        download = service.open_minio_object("radonpy_pi1070__readme")

        self.assertEqual(download.asset.filename, "readme.md")
        self.assertEqual(download.asset.size_bytes, len(b"# RadonPy\n"))
        self.assertEqual(download.asset.mime_type, "text/markdown")
        self.assertEqual(download.body.read(), b"# RadonPy\n")
        self.assertEqual(fake_s3.get_calls, [("polymer-data", "datasets/radonpy_pi1070/docs/readme.md")])

        with self.assertRaises(HTTPException) as context:
            service.open_minio_object("../datasets/radonpy_pi1070/docs/readme.md")

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(fake_s3.get_calls, [("polymer-data", "datasets/radonpy_pi1070/docs/readme.md")])

    def test_md_allatom_c_files_list_and_download_use_mongo_index_before_s3(self) -> None:
        object_key = "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data"
        fake_s3 = FakeS3Client(
            {
                object_key: {
                    "content": b"LAMMPS data\n",
                    "mime_type": "application/octet-stream",
                }
            }
        )
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-1",
                        "family": "C",
                        "object_key": object_key,
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 12,
                        "sync_status": "uploaded",
                        "created_at": datetime(2026, 7, 29, tzinfo=timezone.utc),
                    },
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-2",
                        "family": "C",
                        "object_key": "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16npt.data",
                        "filename": "polymer_1_1_16npt.data",
                        "size_bytes": 9,
                        "sync_status": "failed",
                    },
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-F-1",
                        "family": "F",
                        "object_key": "datasets/md_allatom/raw/F/1_1_16/polymer_1_1_16minf.data",
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 11,
                        "sync_status": "uploaded",
                    },
                ]
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            listed = service.list_md_allatom_c_files("1_1_16", keyword="minf")
            download = service.open_md_allatom_c_file("1_1_16", "polymer_1_1_16minf.data")

        self.assertEqual(listed.total, 1)
        self.assertEqual(listed.items[0].folder, "1_1_16")
        self.assertEqual(listed.items[0].filename, "polymer_1_1_16minf.data")
        self.assertTrue(listed.items[0].exists)
        self.assertNotIn(object_key, listed.items[0].download_path)
        self.assertEqual(download.asset.filename, "polymer_1_1_16minf.data")
        self.assertEqual(download.asset.size_bytes, len(b"LAMMPS data\n"))
        self.assertEqual(download.body.read(), b"LAMMPS data\n")
        self.assertEqual(fake_s3.get_calls, [("polymer-data", object_key)])

    def test_md_allatom_c_download_accepts_indexed_legacy_minio_prefix(self) -> None:
        object_key = "polymer-multi-modal/MD-AllAtom/C/1_1_16/polymer_1_1_16minf.data"
        fake_s3 = FakeS3Client(
            {
                object_key: {
                    "content": b"legacy minio data\n",
                    "mime_type": "application/octet-stream",
                }
            }
        )
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-legacy",
                        "family": "C",
                        "object_key": object_key,
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 18,
                        "sync_status": "uploaded",
                    }
                ]
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            download = service.open_md_allatom_c_file("1_1_16", "polymer_1_1_16minf.data")

        self.assertEqual(download.asset.filename, "polymer_1_1_16minf.data")
        self.assertEqual(download.body.read(), b"legacy minio data\n")
        self.assertEqual(fake_s3.get_calls, [("polymer-data", object_key)])

    def test_md_allatom_c_download_falls_back_to_legacy_minio_prefix_for_canonical_index(self) -> None:
        canonical_key = "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data"
        legacy_key = "polymer-multi-modal/MD-AllAtom/C/1_1_16/polymer_1_1_16minf.data"
        fake_s3 = FakeS3Client(
            {
                legacy_key: {
                    "content": b"legacy fallback data\n",
                    "mime_type": "application/octet-stream",
                }
            }
        )
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-canonical",
                        "family": "C",
                        "object_key": canonical_key,
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 21,
                        "sync_status": "uploaded",
                    }
                ]
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            download = service.open_md_allatom_c_file("1_1_16", "polymer_1_1_16minf.data")

        self.assertEqual(download.body.read(), b"legacy fallback data\n")
        self.assertEqual(fake_s3.get_calls, [("polymer-data", canonical_key), ("polymer-data", legacy_key)])

    def test_md_allatom_c_list_marks_indexed_file_missing_when_minio_object_absent(self) -> None:
        object_key = "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data"
        fake_s3 = FakeS3Client({})
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-missing",
                        "family": "C",
                        "object_key": object_key,
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 12,
                        "sync_status": "uploaded",
                    }
                ]
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            listed = service.list_md_allatom_c_files("1_1_16")

        self.assertEqual(listed.total, 1)
        self.assertFalse(listed.items[0].exists)
        self.assertEqual(fake_s3.get_calls, [])
        self.assertIn(("polymer-data", object_key), fake_s3.head_calls)

    def test_md_allatom_c_download_rejects_missing_index_before_s3(self) -> None:
        fake_s3 = FakeS3Client(
            {
                "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data": {
                    "content": b"LAMMPS data\n",
                }
            }
        )
        service = DataCatalogService(s3_client=fake_s3)
        fake_db = FakeMongoDatabase({"md_allatom_files": []})

        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
            self.assertRaises(HTTPException) as context,
        ):
            service.open_md_allatom_c_file("1_1_16", "polymer_1_1_16minf.data")

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(fake_s3.get_calls, [])

    def test_md_allatom_c_download_requires_index_object_key_to_match_requested_file(self) -> None:
        indexed_object_key = "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16npt.data"
        requested_object_key = "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data"
        fake_s3 = FakeS3Client(
            {
                indexed_object_key: {"content": b"wrong indexed object\n"},
                requested_object_key: {"content": b"requested object without index\n"},
            }
        )
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-mismatch",
                        "family": "C",
                        "object_key": indexed_object_key,
                        "filename": "polymer_1_1_16minf.data",
                        "sync_status": "uploaded",
                    }
                ]
            }
        )
        service = DataCatalogService(s3_client=fake_s3)

        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
            self.assertRaises(HTTPException) as context,
        ):
            service.open_md_allatom_c_file("1_1_16", "polymer_1_1_16minf.data")

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(fake_s3.get_calls, [])

    def test_md_allatom_c_file_parameters_reject_path_traversal(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client())

        for folder, filename in [
            ("../1_1_16", "polymer_1_1_16minf.data"),
            ("1_1_16", "../polymer_1_1_16minf.data"),
            ("1_1_16", "subdir/polymer_1_1_16minf.data"),
            ("1.1.16", "polymer_1_1_16minf.data"),
        ]:
            with self.subTest(folder=folder, filename=filename):
                with self.assertRaises(HTTPException) as context:
                    service.open_md_allatom_c_file(folder, filename)
                self.assertEqual(context.exception.status_code, 404)

    def test_dataset_catalog_prefers_poly_data_metadata(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client(configured=False))
        fake_db = FakeMongoDatabase(
            {
                "datasets": [
                    {
                        "dataset_id": "openpoly",
                        "display_name": "OpenPoly Mongo",
                        "source_category": "Mongo metadata",
                        "confidence_label": "Mongo verified",
                        "description": "从 poly_data.datasets 读取的数据集说明。",
                        "row_count": 10,
                        "column_count": 2,
                        "storage_prefix": "datasets/openpoly/",
                    }
                ],
                "dataset_fields": [
                    {
                        "dataset_id": "openpoly",
                        "raw_name": "PSMILES",
                        "canonical_name": "psmiles",
                        "label": "Mongo 字段说明",
                        "non_empty_count": 9,
                        "total_count": 10,
                        "example": "[*]CC[*]",
                    }
                ],
                "material_records": [
                    {
                        "polymer_record_id": "OPENPOLY-1",
                        "dataset": {"dataset_code": "openpoly"},
                    }
                ],
            }
        )

        with (
            patch("app.services.data_catalog_service.settings.require_mongodb", True),
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            data = service.list_datasets()

        self.assertEqual(len(data.items), 16)
        openpoly = next(item for item in data.items if item.dataset_id == "openpoly")
        self.assertEqual(openpoly.display_name, "OpenPoly Mongo")
        self.assertEqual(openpoly.description, "从 poly_data.datasets 读取的数据集说明。")
        self.assertEqual(openpoly.record_collection_key, "poly_data.material_records")
        self.assertEqual(openpoly.record_count, 1)
        self.assertEqual(openpoly.record_mode, "sample")
        self.assertEqual(openpoly.coverage_percent, 10.0)
        self.assertEqual(openpoly.field_summaries[0].label, "Mongo 字段说明")
        self.assertIn("smipoly", {item.dataset_id for item in data.items})

    def test_dataset_catalog_marks_every_incomplete_collection_as_sample(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client(configured=False))
        fake_db = FakeMongoDatabase(
            {
                "datasets": [
                    {
                        "dataset_id": "omg",
                        "display_name": "OMG",
                        "source_category": "reaction data",
                        "confidence_label": "source table",
                        "description": "partial import",
                        "row_count": 5,
                        "column_count": 4,
                        "storage_prefix": "datasets/omg/",
                    }
                ],
                "dataset_fields": [],
                "omg_polymers": [
                    {"record_id": "OMG-00000001"},
                    {"record_id": "OMG-00000002"},
                ],
            }
        )

        with (
            patch("app.services.data_catalog_service.settings.require_mongodb", True),
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            data = service.list_datasets()

        omg = next(item for item in data.items if item.dataset_id == "omg")
        self.assertEqual(omg.record_count, 2)
        self.assertEqual(omg.record_mode, "sample")
        self.assertEqual(omg.coverage_percent, 40.0)
        self.assertEqual(omg.verification_status, "partial")

    def test_dataset_catalog_exposes_active_import_progress_fields(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client(configured=False))
        now = datetime(2026, 7, 29, 1, 46, tzinfo=timezone.utc)
        fake_db = FakeMongoDatabase(
            {
                "datasets": [
                    {
                        "dataset_id": "omg",
                        "display_name": "OMG",
                        "source_category": "reaction data",
                        "confidence_label": "source table",
                        "description": "running import",
                        "row_count": 12886131,
                        "column_count": 4,
                        "storage_prefix": "datasets/omg/",
                    }
                ],
                "dataset_fields": [],
                "import_jobs": [
                    {
                        "job_id": "omg-full-import",
                        "dataset_id": "omg",
                        "status": "running",
                        "processed_count": 20000,
                        "expected_count": 12886131,
                        "checkpoint_count": 2,
                        "active_chunk_index": 2,
                        "active_source_file": "OMG_polymers.csv",
                        "active_row_start": 10001,
                        "active_row_end": 20000,
                        "started_at": now,
                        "updated_at": now,
                        "throughput_rows_per_second": 1250.5,
                    }
                ],
                "omg_polymers": [{"record_id": "OMG-00000001"}, {"record_id": "OMG-00000002"}],
            }
        )

        with (
            patch("app.services.data_catalog_service.settings.require_mongodb", True),
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            data = service.list_datasets()

        omg = next(item for item in data.items if item.dataset_id == "omg")
        self.assertEqual(omg.verification_status, "running")
        self.assertEqual(omg.import_status.status, "running")
        self.assertEqual(omg.import_status.processed_count, 20000)
        self.assertEqual(omg.import_status.active_chunk_index, 2)
        self.assertEqual(omg.import_status.active_source_file, "OMG_polymers.csv")
        self.assertEqual(omg.import_status.active_row_start, 10001)
        self.assertEqual(omg.import_status.active_row_end, 20000)

    def test_dataset_catalog_exposes_verified_coverage_for_exact_count(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client(configured=False))
        fake_db = FakeMongoDatabase(
            {
                "datasets": [
                    {
                        "dataset_id": "nanomine",
                        "display_name": "NanoMine",
                        "source_category": "table",
                        "confidence_label": "source table",
                        "description": "complete import",
                        "row_count": 2,
                        "column_count": 4,
                        "storage_prefix": "datasets/nanomine/",
                        "verification_status": "verified",
                    }
                ],
                "dataset_fields": [],
                "nanomine_records": [
                    {"record_id": "NANOMINE-00000001"},
                    {"record_id": "NANOMINE-00000002"},
                ],
            }
        )

        with (
            patch("app.services.data_catalog_service.settings.require_mongodb", True),
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
        ):
            data = service.list_datasets()

        nanomine = next(item for item in data.items if item.dataset_id == "nanomine")
        self.assertEqual(nanomine.record_mode, "full")
        self.assertEqual(nanomine.coverage_percent, 100.0)
        self.assertEqual(nanomine.verification_status, "verified")

    def test_overview_material_record_count_sums_poly_data_collections(self) -> None:
        original = demo_store.load()
        try:
            demo_store.save({
                "poly_data.material_records": [{"polymer_record_id": "OPENPOLY-1"}],
                "poly_data.radonpy_records": [{"radonpy_record_id": "RADONPY-1"}],
                "poly_data.pi1m_samples": [{"pi1m_record_id": "PI1M-1"}, {"pi1m_record_id": "PI1M-2"}],
                "poly_data.smipoly_monomers": [{"smipoly_record_id": "SMIPOLY-1"}],
                "poly_data.polyuniverse_monomers": [{"polyuniverse_record_id": "POLYUNIVERSE-1"}],
                "poly_data.md_allatom_files": [{"md_allatom_file_id": "MDALLATOM-FILE-C-000001"}],
                "poly_data.md_allatom_diamines": [{"md_allatom_diamine_id": "MDALLATOM-DIAMINE-000001"}],
                "poly_data.md_allatom_dianhydrides": [{"md_allatom_dianhydride_id": "MDALLATOM-DIANHYDRIDE-000001"}],
                "poly_data.md_allatom_carbon_results": [{"md_allatom_carbon_result_id": "MDALLATOM-C-000001"}],
            })
            with patch("app.services.data_catalog_service.settings.require_mongodb", False):
                data = DataCatalogService(s3_client=FakeS3Client(configured=False)).get_overview()
        finally:
            demo_store.save(original)

        self.assertEqual(data.material_record_count, 10)
        self.assertNotEqual(data.material_record_count, data.total_rows)
        self.assertEqual(next(item for item in data.sources if item.source == "mongodb.poly_data").status, "degraded")

    def test_material_record_count_returns_none_for_degraded_poly_data_collection(self) -> None:
        data = DataCatalogService(s3_client=FakeS3Client(configured=False))._material_record_count([
            DataCatalogCollectionSummary(
                collection_key="poly_data.material_records",
                collection_name="material_records",
                source_id="poly_data",
                display_name="高分子材料记录",
                group="材料数据资产",
                description="material records",
                count=1,
                status="ready",
            ),
            DataCatalogCollectionSummary(
                collection_key="poly_data.radonpy_records",
                collection_name="radonpy_records",
                source_id="poly_data",
                display_name="RadonPy PI1070 记录",
                group="材料数据资产",
                description="radonpy records",
                count=None,
                status="degraded",
            ),
        ])

        self.assertIsNone(data)

    def test_relationships_only_count_persisted_foreign_keys(self) -> None:
        original = demo_store.load()
        try:
            demo_store.save({
                "poly_data.material_records": [{"polymer_record_id": "mat-1"}],
                "computation_runs": [
                    {"run_id": "comp-1", "material_record_id": "mat-1"},
                    {"run_id": "comp-2"},
                ],
                "computation_artifacts": [
                    {"artifact_id": "a-1", "run_id": "comp-1"},
                    {"artifact_id": "a-x", "run_id": "missing"},
                ],
                "research_runs": [{"run_id": "rr-1"}],
                "algorithm_runs": [{"run_id": "ar-1", "research_run_id": "rr-1"}],
                "report_jobs": [{"report_id": "report-1"}],
                "report_artifacts": [{"artifact_id": "ra-1", "report_id": "report-1"}],
            })
            with patch("app.services.data_catalog_service.settings.require_mongodb", False):
                data = DataCatalogService().get_relationships()
        finally:
            demo_store.save(original)

        edges = {(item.source, item.target): item for item in data.edges}
        self.assertEqual(edges[("materials", "computations")].linked_count, 1)
        self.assertEqual(edges[("computations", "computation_artifacts")].linked_count, 1)
        self.assertEqual(edges[("research_runs", "algorithm_runs")].linked_count, 1)
        self.assertEqual(edges[("report_jobs", "report_artifacts")].linked_count, 1)
        self.assertEqual(edges[("materials", "computations")].target_coverage, 0.5)

    def test_collection_analysis_reports_sampled_statistics_and_correlations(self) -> None:
        original = demo_store.load()
        rows = [
            {"record_id": f"TOPORG-{index:04d}", "Topology": "linear" if index % 2 else "branched", "Rg2": index + 1, "Density": (index + 1) * 2}
            for index in range(230)
        ]
        try:
            demo_store.save({**original, "poly_data.toporg_records": rows})
            with patch("app.services.data_catalog_service.settings.require_mongodb", False):
                data = DataCatalogService().get_collection_analysis(
                    "poly_data.toporg_records",
                    sample_size=200,
                    refresh=True,
                )
        finally:
            demo_store.save(original)

        self.assertEqual(data.total_count, 230)
        self.assertEqual(data.sample_count, 200)
        self.assertEqual(data.analysis_status, "partial")
        rg2 = next(item for item in data.field_stats if item.field == "Rg2")
        self.assertEqual(rg2.value_type, "number")
        self.assertEqual(rg2.numeric_summary["min"], 1.0)
        self.assertGreaterEqual(len(data.correlations), 1)
        self.assertTrue(any(item.title == "结构类别分布" for item in data.insights))


class DataCatalogApiTest(unittest.TestCase):
    """覆盖数据目录 API 响应契约。"""

    def setUp(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        self.client.close()

    def test_overview_endpoint_returns_api_response(self) -> None:
        overview = DataCatalogOverviewData(
            status="degraded",
            bucket="polymer-data",
            dataset_count=3,
            object_count=6,
            total_rows=1019992,
            total_columns=203,
            material_record_count=13117,
            canonical_root="datasets/",
            legacy_objects=["OpenPoly/OpenPoly.csv"],
            sources=[
                DataCatalogSourceStatus(
                    source="minio",
                    status="degraded",
                    detail="object status",
                    bucket="polymer-data",
                )
            ],
            relationship_notes=["MinIO 保存原始数据文件。"],
        )
        with patch.object(DataCatalogService, "get_overview", return_value=overview):
            response = self.client.get("/api/v1/data-catalog/overview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["canonical_root"], "datasets/")
        self.assertEqual(payload["data"]["legacy_objects"], ["OpenPoly/OpenPoly.csv"])
        self.assertEqual(payload["data"]["material_record_count"], 13117)

    def test_mongo_collections_endpoint_returns_total(self) -> None:
        data = DataCatalogMongoCollectionListData(items=[], total=0)
        with patch.object(DataCatalogService, "list_mongo_collections", return_value=data):
            response = self.client.get("/api/v1/data-catalog/mongo-collections")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 0)

    def test_collection_analysis_endpoint_returns_controlled_profile(self) -> None:
        analysis = DataCatalogCollectionAnalysisData(
            collection_key="poly_data.toporg_records",
            collection_name="toporg_records",
            source_id="poly_data",
            database="poly_data",
            display_name="ToPoRg 记录",
            data_domain="toporg_records",
            analysis_status="partial",
            generated_at=datetime.now(timezone.utc),
            total_count=1342,
            sample_count=200,
            sample_limit=200,
            analysis_scope="full_count_sample_distribution",
        )
        with patch.object(DataCatalogService, "get_collection_analysis", return_value=analysis):
            response = self.client.get(
                "/api/v1/data-catalog/mongo-collections/poly_data.toporg_records/analysis",
                params={"sample_size": 200},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["analysis_status"], "partial")
        self.assertEqual(response.json()["data"]["sample_limit"], 200)

    def test_api_catalog_registers_all_read_only_data_interfaces_without_secrets(self) -> None:
        with (
            patch("app.services.data_catalog_service.settings.minio_endpoint", "http://minio-secret.example"),
            patch("app.services.data_catalog_service.settings.minio_access_key", "MINIO_ACCESS_KEY_SECRET"),
            patch("app.services.data_catalog_service.settings.minio_secret_key", "MINIO_SECRET_KEY_SECRET"),
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://secret-user:secret-pass@mongo.example/poly_data"),
        ):
            response = self.client.get("/api/v1/data-catalog/api-catalog")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        paths = {item["path"] for item in data["endpoints"]}
        self.assertEqual(data["authentication"]["header"], "Authorization: Bearer $POLY_AGENT_TOKEN")
        self.assertIn("access_token", data["read_only_statement"])
        self.assertIn("不需要也不会提供底层存储账号或密钥", data["read_only_statement"])
        self.assertTrue(all(item["method"] == "GET" for item in data["endpoints"]))
        self.assertTrue(all(item["permission"] in {"read", "download"} for item in data["endpoints"]))
        endpoint_by_id = {item["endpoint_id"]: item for item in data["endpoints"]}
        self.assertEqual(endpoint_by_id["mongo_collections"]["name"], "MongoDB 可访问集合")
        self.assertEqual(endpoint_by_id["mongo_collection_analysis"]["name"], "MongoDB 集合分析")
        self.assertEqual(endpoint_by_id["minio_objects"]["name"], "MinIO 文件列表")
        self.assertIn("返回文件流，不是 JSON", endpoint_by_id["minio_download"]["summary"])
        self.assertEqual(endpoint_by_id["md_allatom_c_files"]["name"], "MD-AllAtom C 文件列表")
        self.assertIn("1_1_16", endpoint_by_id["md_allatom_c_download"]["examples"]["curl"])
        self.assertIn("polymer_1_1_16minf.data", endpoint_by_id["md_allatom_c_download"]["examples"]["python"])
        self.assertTrue({
            "/data-catalog/overview",
            "/data-catalog/datasets",
            "/data-catalog/datasets/{dataset_id}/profile",
            "/data-catalog/datasets/{dataset_id}/records",
            "/data-catalog/datasets/{dataset_id}/visual-samples",
            "/data-catalog/mongo-collections",
            "/data-catalog/mongo-collections/{collection_name}/records",
            "/data-catalog/mongo-collections/{collection_name}/analysis",
            "/data-catalog/mongo-collections/{collection_name}/records/{record_id}",
            "/data-catalog/relationships",
            "/data-catalog/minio-objects",
            "/data-catalog/minio-objects/{asset_id}/download",
            "/data-catalog/md-allatom/c-files/{folder}",
            "/data-catalog/md-allatom/c-files/{folder}/{filename}/download",
        }.issubset(paths))
        serialized = response.text
        self.assertIn("$POLY_AGENT_TOKEN", serialized)
        self.assertNotIn("MINIO_ACCESS_KEY_SECRET", serialized)
        self.assertNotIn("MINIO_SECRET_KEY_SECRET", serialized)
        self.assertNotIn("mongodb://secret-user", serialized)
        self.assertNotIn("http://minio-secret.example", serialized)

    def test_data_catalog_routes_require_bearer_when_auth_enabled(self) -> None:
        original_auth_enabled = settings.auth_enabled
        settings.auth_enabled = True
        try:
            urls = [
                "/api/v1/data-catalog/api-catalog",
                "/api/v1/data-catalog/overview",
                "/api/v1/data-catalog/datasets",
                "/api/v1/data-catalog/datasets/pi1m_v2/profile",
                "/api/v1/data-catalog/datasets/pi1m_v2/records",
                "/api/v1/data-catalog/datasets/pi1m_v2/visual-samples",
                "/api/v1/data-catalog/mongo-collections",
                "/api/v1/data-catalog/mongo-collections/poly_data.material_records/records",
                "/api/v1/data-catalog/mongo-collections/poly_data.material_records/analysis",
                "/api/v1/data-catalog/mongo-collections/poly_data.material_records/records/OPENPOLY-16172",
                "/api/v1/data-catalog/relationships",
                "/api/v1/data-catalog/minio-objects?dataset_id=radonpy_pi1070",
                "/api/v1/data-catalog/minio-objects/radonpy_pi1070__readme/download",
                "/api/v1/data-catalog/md-allatom/c-files/1_1_16",
                "/api/v1/data-catalog/md-allatom/c-files/1_1_16/polymer_1_1_16minf.data/download",
            ]
            statuses = [self.client.get(url).status_code for url in urls]
        finally:
            settings.auth_enabled = original_auth_enabled

        self.assertEqual(statuses, [401 for _ in statuses])

    def test_md_allatom_c_download_endpoint_returns_file_headers_without_storage_uri(self) -> None:
        object_key = "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data"
        fake_s3 = FakeS3Client(
            {
                object_key: {
                    "content": b"LAMMPS data\n",
                    "mime_type": "application/octet-stream",
                }
            }
        )
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-1",
                        "family": "C",
                        "object_key": object_key,
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 12,
                        "sync_status": "uploaded",
                    }
                ]
            }
        )
        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
            patch("app.services.data_catalog_service.S3ObjectClient", return_value=fake_s3),
        ):
            response = self.client.get(
                "/api/v1/data-catalog/md-allatom/c-files/1_1_16/polymer_1_1_16minf.data/download"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"LAMMPS data\n")
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/octet-stream")
        self.assertEqual(response.headers["content-length"], str(len(b"LAMMPS data\n")))
        self.assertIn("polymer_1_1_16minf.data", response.headers["content-disposition"])
        self.assertNotIn(object_key, response.text)
        self.assertEqual(fake_s3.get_calls, [("polymer-data", object_key)])

    def test_md_allatom_c_list_endpoint_returns_template_download_paths(self) -> None:
        fake_db = FakeMongoDatabase(
            {
                "md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-1",
                        "family": "C",
                        "object_key": "datasets/md_allatom/raw/C/1_1_16/polymer_1_1_16minf.data",
                        "filename": "polymer_1_1_16minf.data",
                        "size_bytes": 12,
                        "sync_status": "already_migrated",
                    }
                ]
            }
        )
        with (
            patch("app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example/poly_data"),
            patch("app.services.data_catalog_service.get_data_asset_database", return_value=fake_db),
            patch("app.services.data_catalog_service.S3ObjectClient", return_value=FakeS3Client({})),
        ):
            response = self.client.get("/api/v1/data-catalog/md-allatom/c-files/1_1_16", params={"keyword": "minf"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["folder"], "1_1_16")
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["filename"], "polymer_1_1_16minf.data")
        self.assertFalse(data["items"][0]["exists"])
        self.assertEqual(
            data["items"][0]["download_path"],
            "/data-catalog/md-allatom/c-files/1_1_16/polymer_1_1_16minf.data/download",
        )

    def test_minio_download_endpoint_returns_file_headers_without_storage_uri(self) -> None:
        fake_s3 = FakeS3Client(
            {
                "datasets/radonpy_pi1070/docs/readme.md": {
                    "content": b"# RadonPy\n",
                    "mime_type": "text/markdown",
                }
            }
        )
        with patch("app.services.data_catalog_service.S3ObjectClient", return_value=fake_s3):
            response = self.client.get("/api/v1/data-catalog/minio-objects/radonpy_pi1070__readme/download")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"# RadonPy\n")
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/markdown")
        self.assertEqual(response.headers["content-length"], str(len(b"# RadonPy\n")))
        self.assertIn("readme.md", response.headers["content-disposition"])
        self.assertNotIn("datasets/radonpy_pi1070/docs/readme.md", response.text)
        self.assertEqual(fake_s3.get_calls, [("polymer-data", "datasets/radonpy_pi1070/docs/readme.md")])

    def test_data_catalog_router_exposes_no_user_write_methods(self) -> None:
        methods = {
            method
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/v1/data-catalog")
            for method in getattr(route, "methods", set())
        }

        self.assertTrue(methods)
        self.assertTrue(methods.issubset({"GET", "HEAD"}))

    def test_dataset_list_marks_md_allatom_complete_for_actual_demo_rows(self) -> None:
        demo_data = {"poly_data.md_allatom_carbon_results": [{} for _ in range(9608)]}
        with (
            patch("app.services.data_catalog_service.settings.require_mongodb", False),
            patch("app.services.data_catalog_service.demo_store.load", return_value=demo_data),
        ):
            response = self.client.get("/api/v1/data-catalog/datasets")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        md_allatom = next(item for item in data["items"] if item["dataset_id"] == "md_allatom")
        self.assertEqual(md_allatom["row_count"], 9608)
        self.assertEqual(md_allatom["record_count"], 9608)
        self.assertEqual(md_allatom["coverage_percent"], 100.0)
        self.assertEqual(md_allatom["verification_status"], "verified")


class DataCatalogRecordDrilldownApiTest(ComputationTestCase):
    """覆盖 Mongo 集合记录下钻 API 契约。"""

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _login_as(user_id: str, role: str = "admin") -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "username": user_id,
            "role": role,
            "status": "active",
        }

    def _seed_demo_records(self) -> None:
        demo_store.save(
            {
                "computation_runs": [
                    {
                        "run_id": "run-001",
                        "workflow_type": "LOCAL_XTB",
                        "engine": "XTB",
                        "status": "completed",
                        "molecule": {"smiles": "CCO", "name": "ethanol"},
                        "parameters": {"method": "GFN2-xTB"},
                        "resources": {"num_cores": 2},
                        "mongo_uri": "mongodb://secret-user:secret-pass@mongo.example/poly_data",
                        "dsn": "postgres://secret-user:secret-pass@db.example/app",
                        "connection_info": {
                            "private_key": "-----BEGIN PRIVATE KEY-----",
                            "cookie": "session=secret",
                        },
                        "created_by": "user-a",
                        "created_at": "2026-07-11T10:00:00Z",
                        "updated_at": "2026-07-11T10:05:00Z",
                        "result_summary": {"energy": -12.3},
                    },
                    {
                        "run_id": "run-002",
                        "workflow_type": "LOCAL_STRUCTURE",
                        "engine": "LOCAL",
                        "status": "failed",
                        "molecule": {"smiles": "CCC", "name": "propane"},
                        "created_by": "user-b",
                        "created_at": "2026-07-11T11:00:00Z",
                        "updated_at": "2026-07-11T11:02:00Z",
                    },
                ],
                "service_integrations": [
                    {
                        "service_key": "secret-service",
                        "display_name": "Secret Service",
                        "enabled": True,
                        "endpoint": "https://service.example/api",
                        "secret_refs": {"bearer_token": "SERVICE_TOKEN_ENV"},
                        "config_summary": {"timeout": 30, "api_key": "plain-secret"},
                        "created_at": "2026-07-11T12:00:00Z",
                    }
                ],
                "audit_events": [
                    {
                        "event_id": "audit-001",
                        "event_type": "download",
                        "entity_type": "artifact",
                        "entity_id": "artifact-001",
                        "created_at": "2026-07-11T12:30:00Z",
                    }
                ],
                "poly_data.material_records": [
                    {
                        "polymer_record_id": "OPENPOLY-16172",
                        "dataset": {
                            "dataset_name": "OpenPoly",
                            "dataset_code": "openpoly",
                            "source_type": "literature",
                            "source_file": "OpenPoly.csv",
                        },
                        "polymer": {
                            "name": "poly(N -isopropylacrylamide)",
                            "psmiles": "[*]CC(C(NC(C)C)=O)[*]",
                            "pscore": 331.80531218949864,
                        },
                        "properties": {
                            "thermal": {"tg_K": 405.775},
                            "mechanical": {"youngs_modulus_MPa": 0.24828},
                            "transport": {"methanol_permeability_cm2_per_s": 4e-7},
                        },
                        "reference": {"source_type": "literature", "n": 21},
                        "provenance": {
                            "created_by": "openpoly_importer",
                            "created_at": "2026-07-10T01:39:34.005Z",
                            "updated_at": "2026-07-10T01:39:34.005Z",
                        },
                    }
                ],
                "poly_data.radonpy_records": [
                    {
                        "radonpy_record_id": "RADONPY_PI1070-000001",
                        "dataset": {"dataset_id": "radonpy_pi1070", "dataset_name": "RadonPy PI1070"},
                        "smiles": "*CC*",
                        "source_file": "pi1070.xlsx",
                        "properties": {
                            "density": 0.837971504,
                            "static_dielectric_const": 2.2102,
                            "thermal_conductivity": 0.2361,
                        },
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.pi1m_samples": [
                    {
                        "pi1m_record_id": "PI1M_V2-000001",
                        "dataset": {"dataset_id": "pi1m_v2", "dataset_name": "PI1M v2"},
                        "smiles": "*CCC[Fe]CCCC(=O)OCCCCOCCCNCC(*)=O",
                        "sa_score": 4.174851129781874,
                        "row_index": 1,
                        "sample_index": 1,
                        "created_at": "2026-07-21T03:00:00Z",
                    },
                    {
                        "pi1m_record_id": "PI1M_V2-000002",
                        "dataset": {"dataset_id": "pi1m_v2", "dataset_name": "PI1M v2"},
                        "smiles": "*CC*",
                        "sa_score": 2.1,
                        "row_index": 2,
                        "sample_index": 2,
                        "created_at": "2026-07-21T03:01:00Z",
                    },
                    {
                        "pi1m_record_id": "PI1M_V2-000003",
                        "dataset": {"dataset_id": "pi1m_v2", "dataset_name": "PI1M v2"},
                        "smiles": "*CCC*",
                        "sa_score": 6.5,
                        "row_index": 3,
                        "sample_index": 3,
                        "created_at": "2026-07-21T03:02:00Z",
                    }
                ],
                "poly_data.smipoly_monomers": [
                    {
                        "smipoly_record_id": "SMIPOLY-CID174",
                        "dataset": {"dataset_id": "smipoly", "dataset_name": "SMiPoly"},
                        "com_id": "CID174",
                        "molecular_formula": "C2H6O2",
                        "molecular_weight": 62.07,
                        "smiles": "C(CO)O",
                        "iupac_name": "ethane-1,2-diol",
                        "source_file": "202207_smip_monset.csv",
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.polyuniverse_monomers": [
                    {
                        "polyuniverse_record_id": "POLYUNIVERSE-epoxy_diE-000001",
                        "dataset": {"dataset_id": "polyuniverse", "dataset_name": "PolyUniverse"},
                        "monomer_class": "diepoxy",
                        "source_file": "epoxy_diE.csv",
                        "row_index": 1,
                        "smiles": "C1OC1",
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.md_allatom_files": [
                    {
                        "md_allatom_file_id": "MDALLATOM-FILE-C-000001",
                        "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
                        "family": "C",
                        "remote_path": "/polymer-multi-modal/MD-AllAtom/C/polymer_1_1_32npt.data",
                        "object_key": "datasets/md_allatom/raw/C/polymer_1_1_32npt.data",
                        "filename": "polymer_1_1_32npt.data",
                        "extension": ".data",
                        "size_bytes": 12,
                        "sync_status": "uploaded",
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.md_allatom_diamines": [
                    {
                        "md_allatom_diamine_id": "MDALLATOM-DIAMINE-000001",
                        "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
                        "diamine_id": 1,
                        "cas": "341-58-2",
                        "name": "TFDB",
                        "name_cn": "二胺",
                        "abbr": "TFDB",
                        "smiles": "CN",
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.md_allatom_dianhydrides": [
                    {
                        "md_allatom_dianhydride_id": "MDALLATOM-DIANHYDRIDE-000001",
                        "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
                        "dianhydride_id": 1,
                        "cas": "1107-00-2",
                        "name": "6FDA",
                        "name_cn": "六氟二酐",
                        "abbr": "6FDA",
                        "smiles": "O=C1OC(=O)c2ccccc12",
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.md_allatom_carbon_results": [
                    {
                        "md_allatom_carbon_result_id": "MDALLATOM-C-000001",
                        "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
                        "family": "C",
                        "diamine_id": 1,
                        "dianhydride_id": 1,
                        "dp": 32,
                        "temperature": 250,
                        "e2e_mean": 369.37,
                        "rg_mean": 143.78,
                        "persist_len_mean": 114.87,
                        "data_file": "polymer_1_1_32npt.data",
                        "out_file": "250_1_1_32_.out",
                        "created_at": "2026-07-21T03:00:00Z",
                    }
                ],
                "poly_data.dataset_stats": [
                    {
                        "dataset_id": "md_allatom",
                        "record_count": 9944,
                        "asset_coverage": {"families": {"C": 1, "F": 0, "Si": 0}, "file_count": 1},
                        "category_counts": {"temperature": {"250": 1}, "dp": {"32": 1}},
                        "numeric_histograms": {
                            "e2e_mean": [{"start": 360, "end": 380, "count": 1}],
                            "rg_mean": [{"start": 140, "end": 150, "count": 1}],
                            "persist_len_mean": [{"start": 110, "end": 120, "count": 1}],
                        },
                        "analysis_samples": [
                            {
                                "record_id": "MDALLATOM-C-000001",
                                "x": 250,
                                "y": 369.37,
                                "category": "dp=32",
                            }
                        ],
                    }
                ],
            }
        )

    def test_collection_list_exposes_business_and_material_sources_only(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get("/api/v1/data-catalog/mongo-collections")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        keys = {item["collection_key"] for item in data["items"]}
        self.assertIn("computation_runs", keys)
        self.assertIn("poly_data.material_records", keys)
        self.assertIn("poly_data.radonpy_records", keys)
        self.assertIn("poly_data.pi1m_samples", keys)
        self.assertIn("poly_data.smipoly_monomers", keys)
        self.assertIn("poly_data.polyuniverse_monomers", keys)
        self.assertIn("poly_data.md_allatom_files", keys)
        self.assertIn("poly_data.md_allatom_carbon_results", keys)
        self.assertNotIn("audit_events", keys)
        self.assertNotIn("service_integrations", keys)
        material = next(item for item in data["items"] if item["collection_key"] == "poly_data.material_records")
        self.assertEqual(material["source_id"], "poly_data")
        self.assertEqual(material["database"], "poly_data")
        self.assertEqual(material["collection_name"], "material_records")
        self.assertEqual(material["group"], "材料数据资产")
        self.assertEqual(material["data_domain"], "materials")
        self.assertIn("properties", material["analysis_facets"])
        self.assertIn("polymer_record_id", material["schema_summary"]["sample_fields"])

        radonpy = next(item for item in data["items"] if item["collection_key"] == "poly_data.radonpy_records")
        self.assertEqual(radonpy["collection_name"], "radonpy_records")
        self.assertEqual(radonpy["data_domain"], "radonpy_records")
        self.assertEqual(radonpy["primary_keys"], ["radonpy_record_id"])

        pi1m = next(item for item in data["items"] if item["collection_key"] == "poly_data.pi1m_samples")
        self.assertEqual(pi1m["collection_name"], "pi1m_samples")
        self.assertEqual(pi1m["data_domain"], "pi1m_samples")
        self.assertEqual(pi1m["primary_keys"], ["pi1m_record_id"])

        smipoly = next(item for item in data["items"] if item["collection_key"] == "poly_data.smipoly_monomers")
        self.assertEqual(smipoly["collection_name"], "smipoly_monomers")
        self.assertEqual(smipoly["data_domain"], "smipoly_monomers")
        self.assertEqual(smipoly["primary_keys"], ["smipoly_record_id"])

        polyuniverse = next(item for item in data["items"] if item["collection_key"] == "poly_data.polyuniverse_monomers")
        self.assertEqual(polyuniverse["collection_name"], "polyuniverse_monomers")
        self.assertEqual(polyuniverse["data_domain"], "polyuniverse_monomers")
        self.assertEqual(polyuniverse["primary_keys"], ["polyuniverse_record_id"])

        md_files = next(item for item in data["items"] if item["collection_key"] == "poly_data.md_allatom_files")
        self.assertEqual(md_files["collection_name"], "md_allatom_files")
        self.assertEqual(md_files["data_domain"], "md_allatom_files")
        self.assertEqual(md_files["primary_keys"], ["md_allatom_file_id"])

    def test_unknown_collection_returns_404(self) -> None:
        self._login_as("admin-user")

        response = self.client.get("/api/v1/data-catalog/mongo-collections/not_allowed/records")

        self.assertEqual(response.status_code, 404)

    def test_authenticated_user_can_drill_down_records(self) -> None:
        self._seed_demo_records()
        self._login_as("regular-user", role="user")

        collection_response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/computation_runs/records"
        )
        detail_response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/computation_runs/records/run-001"
        )
        with patch("app.services.data_catalog_service.settings.require_mongodb", False):
            dataset_response = self.client.get(
                "/api/v1/data-catalog/datasets/pi1m_v2/records",
                params={"page_size": 10},
            )

        self.assertEqual(collection_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(dataset_response.status_code, 200)
        self.assertNotIn("secret_refs", detail_response.json()["data"]["document"])

    def test_list_collection_records_supports_pagination_and_keyword(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/computation_runs/records",
            params={"keyword": "ethanol", "page": 1, "page_size": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_name"], "computation_runs")
        self.assertEqual(data["primary_keys"], ["run_id"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["record_id"], "run-001")
        self.assertEqual(data["items"][0]["primary_key"], {"run_id": "run-001"})
        self.assertEqual(data["items"][0]["title"], "run-001")
        self.assertEqual(data["items"][0]["status"], "completed")
        self.assertIn("workflow_type", data["items"][0]["preview_fields"])

    def test_list_collection_records_supports_cursor_pagination(self) -> None:
        original = demo_store.load()
        try:
            demo_store.save(
                {
                    **original,
                    "poly_data.nanomine_records": [
                        {"record_id": "NANOMINE-00000001", "title": "row 1", "row_index": 1},
                        {"record_id": "NANOMINE-00000002", "title": "row 2", "row_index": 2},
                        {"record_id": "NANOMINE-00000003", "title": "row 3", "row_index": 3},
                    ],
                }
            )
            self._login_as("admin-user")
            with patch("app.services.data_catalog_service.settings.require_mongodb", False):
                first = self.client.get(
                    "/api/v1/data-catalog/mongo-collections/poly_data.nanomine_records/records",
                    params={"page_size": 2, "use_cursor": "true"},
                )
                cursor = first.json()["data"]["next_cursor"]
                second = self.client.get(
                    "/api/v1/data-catalog/mongo-collections/poly_data.nanomine_records/records",
                    params={"page_size": 2, "use_cursor": "true", "cursor": cursor},
                )
        finally:
            demo_store.save(original)

        self.assertEqual(first.status_code, 200)
        self.assertIsNotNone(cursor)
        self.assertEqual([item["record_id"] for item in first.json()["data"]["items"]], [
            "NANOMINE-00000003",
            "NANOMINE-00000002",
        ])
        self.assertEqual([item["record_id"] for item in second.json()["data"]["items"]], ["NANOMINE-00000001"])
        self.assertIsNone(second.json()["data"]["next_cursor"])

    def test_list_collection_records_rejects_cursor_from_another_collection(self) -> None:
        original = demo_store.load()
        try:
            demo_store.save(
                {
                    **original,
                    "poly_data.nanomine_records": [
                        {"record_id": "NANOMINE-00000001", "row_index": 1},
                        {"record_id": "NANOMINE-00000002", "row_index": 2},
                    ],
                    "poly_data.tropic_records": [
                        {"record_id": "TROPIC-00000001", "row_index": 1},
                    ],
                }
            )
            self._login_as("admin-user")
            with patch("app.services.data_catalog_service.settings.require_mongodb", False):
                first = self.client.get(
                    "/api/v1/data-catalog/mongo-collections/poly_data.nanomine_records/records",
                    params={"page_size": 1, "use_cursor": "true"},
                )
                response = self.client.get(
                    "/api/v1/data-catalog/mongo-collections/poly_data.tropic_records/records",
                    params={
                        "page_size": 1,
                        "use_cursor": "true",
                        "cursor": first.json()["data"]["next_cursor"],
                    },
                )
        finally:
            demo_store.save(original)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["data"]["detail"], "游标与当前集合不匹配")

    def test_get_collection_record_returns_sanitized_document(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/computation_runs/records/run-001"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_name"], "computation_runs")
        self.assertEqual(data["record_id"], "run-001")
        self.assertEqual(data["document"]["result_summary"]["energy"], -12.3)
        self.assertEqual(data["document"]["mongo_uri"], "***")
        self.assertEqual(data["document"]["dsn"], "***")
        self.assertEqual(data["document"]["connection_info"], {"private_key": "***", "cookie": "***"})

    def test_hidden_system_collection_cannot_be_drilled_down(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/service_integrations/records/secret-service"
        )

        self.assertEqual(response.status_code, 404)

    def test_material_collection_records_use_polymer_summary(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.material_records/records",
            params={"keyword": "isopropyl", "page": 1, "page_size": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.material_records")
        self.assertEqual(data["source_id"], "poly_data")
        self.assertEqual(data["database"], "poly_data")
        self.assertEqual(data["collection_name"], "material_records")
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["record_id"], "OPENPOLY-16172")
        self.assertEqual(item["title"], "poly(N -isopropylacrylamide)")
        self.assertEqual(item["created_at"], "2026-07-10T01:39:34.005Z")
        self.assertEqual(item["preview_fields"]["dataset"], "OpenPoly")
        self.assertEqual(item["preview_fields"]["psmiles"], "[*]CC(C(NC(C)C)=O)[*]")
        self.assertEqual(item["preview_fields"]["property_groups"], "thermal, mechanical, transport")
        self.assertEqual(item["preview_fields"]["source_type"], "literature")

    def test_material_collection_detail_uses_cross_source_key(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.material_records/records/OPENPOLY-16172"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.material_records")
        self.assertEqual(data["source_id"], "poly_data")
        self.assertEqual(data["database"], "poly_data")
        self.assertEqual(data["collection_name"], "material_records")
        self.assertEqual(data["title"], "poly(N -isopropylacrylamide)")
        self.assertEqual(data["primary_key"], {"polymer_record_id": "OPENPOLY-16172"})
        self.assertEqual(data["document"]["polymer"]["psmiles"], "[*]CC(C(NC(C)C)=O)[*]")

    def test_radonpy_collection_records_use_dataset_summary(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.radonpy_records/records",
            params={"keyword": "0.2361", "page": 1, "page_size": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.radonpy_records")
        self.assertEqual(data["collection_name"], "radonpy_records")
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["record_id"], "RADONPY_PI1070-000001")
        self.assertEqual(item["title"], "*CC*")
        self.assertEqual(item["preview_fields"]["dataset"], "RadonPy PI1070")
        self.assertEqual(item["preview_fields"]["thermal_conductivity"], 0.2361)

    def test_pi1m_collection_detail_uses_sample_key(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.pi1m_samples/records/PI1M_V2-000001"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.pi1m_samples")
        self.assertEqual(data["collection_name"], "pi1m_samples")
        self.assertEqual(data["primary_key"], {"pi1m_record_id": "PI1M_V2-000001"})
        self.assertEqual(data["title"], "*CCC[Fe]CCCC(=O)OCCCCOCCCNCC(*)=O")
        self.assertEqual(data["document"]["sa_score"], 4.174851129781874)

    def test_pi1m_dataset_profile_reports_partial_mode_and_histogram_before_full_import(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")
        with patch("app.services.data_catalog_service.settings.require_mongodb", False):
            response = self.client.get("/api/v1/data-catalog/datasets/pi1m_v2/profile")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["dataset_id"], "pi1m_v2")
        self.assertEqual(data["record_mode"], "sample")
        self.assertEqual(data["record_count"], 3)
        self.assertGreater(data["coverage_percent"], 0)
        self.assertGreater(len(data["sa_score_histogram"]), 0)
        self.assertEqual(data["unique_smiles_count"], 3)

    def test_pi1m_dataset_records_use_cursor_and_sa_filter(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")
        with patch("app.services.data_catalog_service.settings.require_mongodb", False):
            first = self.client.get(
                "/api/v1/data-catalog/datasets/pi1m_v2/records",
                params={"page_size": 2, "sort_by": "row_index"},
            )
            cursor = first.json()["data"]["next_cursor"]
            second = self.client.get(
                "/api/v1/data-catalog/datasets/pi1m_v2/records",
                params={"page_size": 2, "sort_by": "row_index", "cursor": cursor},
            )
            filtered = self.client.get(
                "/api/v1/data-catalog/datasets/pi1m_v2/records",
                params={"page_size": 10, "sa_min": 5},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual([item["record_id"] for item in first.json()["data"]["items"]], ["PI1M_V2-000001", "PI1M_V2-000002"])
        self.assertIsNotNone(cursor)
        self.assertEqual([item["record_id"] for item in second.json()["data"]["items"]], ["PI1M_V2-000003"])
        self.assertEqual([item["record_id"] for item in filtered.json()["data"]["items"]], ["PI1M_V2-000003"])

    def test_pi1m_visual_samples_are_bounded_metadata(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")
        with patch("app.services.data_catalog_service.settings.require_mongodb", False):
            response = self.client.get("/api/v1/data-catalog/datasets/pi1m_v2/visual-samples", params={"limit": 100})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["dataset_id"], "pi1m_v2")
        self.assertEqual(data["sample_count"], 3)
        self.assertLessEqual(data["sample_count"], 100)
        self.assertIn("x", data["points"][0])
        self.assertIn("y", data["points"][0])

    def test_smipoly_collection_records_use_monomer_summary(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.smipoly_monomers/records",
            params={"keyword": "ethane", "page": 1, "page_size": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.smipoly_monomers")
        self.assertEqual(data["collection_name"], "smipoly_monomers")
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["record_id"], "SMIPOLY-CID174")
        self.assertEqual(item["title"], "ethane-1,2-diol")
        self.assertEqual(item["preview_fields"]["dataset"], "SMiPoly")
        self.assertEqual(item["preview_fields"]["molecular_formula"], "C2H6O2")
        self.assertEqual(item["preview_fields"]["molecular_weight"], 62.07)

    def test_polyuniverse_collection_detail_uses_source_row_key(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.polyuniverse_monomers/records/POLYUNIVERSE-epoxy_diE-000001"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.polyuniverse_monomers")
        self.assertEqual(data["collection_name"], "polyuniverse_monomers")
        self.assertEqual(data["primary_key"], {"polyuniverse_record_id": "POLYUNIVERSE-epoxy_diE-000001"})
        self.assertEqual(data["title"], "C1OC1")
        self.assertEqual(data["document"]["monomer_class"], "diepoxy")

    def test_md_allatom_dataset_profile_returns_generic_analysis_stats(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")
        with patch("app.services.data_catalog_service.settings.require_mongodb", False):
            response = self.client.get("/api/v1/data-catalog/datasets/md_allatom/profile")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["dataset_id"], "md_allatom")
        self.assertEqual(data["asset_coverage"]["file_count"], 1)
        self.assertEqual(data["category_counts"]["temperature"]["250"], 1)
        self.assertEqual(data["numeric_histograms"]["e2e_mean"][0]["count"], 1)
        self.assertEqual(data["analysis_samples"][0]["record_id"], "MDALLATOM-C-000001")

    def test_md_allatom_dataset_profile_falls_back_when_stats_document_is_missing(self) -> None:
        service = DataCatalogService()
        with patch("app.services.data_catalog_service.settings.require_mongodb", True), patch(
            "app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example"
        ), patch("app.services.data_catalog_service.get_data_asset_database", return_value=ProfileMongoDatabase(
            {
                "datasets": [{"dataset_id": "md_allatom", "display_name": "MD-AllAtom", "row_count": 10000, "column_count": 26, "storage_prefix": "datasets/md_allatom/"}],
                "dataset_fields": [],
                "dataset_stats": [],
                "md_allatom_carbon_results": [
                    {
                        "md_allatom_carbon_result_id": "MDALLATOM-C-000001",
                        "family": "C",
                        "dp": 32,
                        "temperature": 250,
                        "e2e_mean": 369.37,
                        "rg_mean": 143.78,
                        "persist_len_mean": 114.87,
                    }
                ],
                "md_allatom_files": [
                    {"md_allatom_file_id": "MDALLATOM-FILE-C-000001", "family": "C"}
                ],
            },
            counts={"md_allatom_carbon_results": 1, "md_allatom_files": 1},
        )):
            data = service.get_dataset_profile("md_allatom")

        self.assertEqual(data.record_count, 1)
        self.assertEqual(data.asset_coverage["file_count"], 1)
        self.assertEqual(data.category_counts["temperature"]["250"], 1)
        self.assertEqual(data.numeric_histograms["e2e_mean"][0].count, 1)
        self.assertEqual(data.analysis_samples[0]["record_id"], "MDALLATOM-C-000001")

    def test_has_dataset_stats_reports_fallback_data_for_md_allatom(self) -> None:
        service = DataCatalogService()
        with patch("app.services.data_catalog_service.settings.require_mongodb", True), patch(
            "app.services.data_catalog_service.settings.data_asset_mongodb_uri", "mongodb://example"
        ), patch("app.services.data_catalog_service.get_data_asset_database", return_value=ProfileMongoDatabase(
            {
                "datasets": [{"dataset_id": "md_allatom", "display_name": "MD-AllAtom", "row_count": 10000, "column_count": 26, "storage_prefix": "datasets/md_allatom/"}],
                "dataset_fields": [],
                "dataset_stats": [],
                "md_allatom_carbon_results": [{"md_allatom_carbon_result_id": "MDALLATOM-C-000001"}],
            },
            counts={"md_allatom_carbon_results": 1},
        )):
            self.assertTrue(service.has_dataset_stats("md_allatom"))

    def test_md_allatom_collection_records_use_domain_summary(self) -> None:
        self._seed_demo_records()
        self._login_as("admin-user")

        response = self.client.get(
            "/api/v1/data-catalog/mongo-collections/poly_data.md_allatom_carbon_results/records",
            params={"keyword": "250", "page": 1, "page_size": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "poly_data.md_allatom_carbon_results")
        self.assertEqual(data["total"], 1)
        item = data["items"][0]
        self.assertEqual(item["record_id"], "MDALLATOM-C-000001")
        self.assertEqual(item["title"], "C · diamine 1 / dianhydride 1")
        self.assertEqual(item["preview_fields"]["temperature"], 250)
