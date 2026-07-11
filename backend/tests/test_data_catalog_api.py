"""数据目录 API 和服务测试。"""

from __future__ import annotations

import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.core.auth import get_current_user
from app.infra.demo_store import demo_store
from app.schemas.data_catalog import (
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

    def is_configured(self) -> bool:
        return self.configured

    def head_object(self, bucket: str, object_key: str) -> dict | None:
        return self.objects.get(object_key)


class DataCatalogServiceTest(unittest.TestCase):
    """覆盖数据目录服务的 MinIO 对象状态逻辑。"""

    def test_dataset_catalog_uses_canonical_paths_and_reports_legacy_objects(self) -> None:
        now = datetime(2026, 7, 11, tzinfo=timezone.utc)
        service = DataCatalogService(
            s3_client=FakeS3Client(
                {
                    "poly_agent/datasets/radonpy_pi1070/docs/readme.md": {
                        "size_bytes": 10211,
                        "last_modified": now,
                    },
                    "01_RadonPy/01_RadonPy_README(1).md": {
                        "size_bytes": 10211,
                        "last_modified": now,
                    },
                }
            )
        )

        data = service.list_datasets()
        radonpy = next(item for item in data.items if item.dataset_id == "radonpy_pi1070")
        readme = next(item for item in radonpy.objects if item.role == "readme")

        self.assertEqual(readme.object_key, "poly_agent/datasets/radonpy_pi1070/docs/readme.md")
        self.assertTrue(readme.exists)
        self.assertEqual(readme.legacy_object_key, "01_RadonPy/01_RadonPy_README(1).md")
        self.assertTrue(readme.legacy_exists)
        self.assertIn("01_RadonPy/01_RadonPy_README(1).md", data.legacy_objects)

    def test_unconfigured_minio_returns_dataset_metadata_without_object_exists(self) -> None:
        service = DataCatalogService(s3_client=FakeS3Client(configured=False))

        data = service.list_datasets()

        self.assertEqual(len(data.items), 3)
        self.assertFalse(any(obj.exists for dataset in data.items for obj in dataset.objects))

    def test_relationships_only_count_persisted_foreign_keys(self) -> None:
        original = demo_store.load()
        try:
            demo_store.save({
                "ai4ms.Poly_Agent": [{"polymer_record_id": "mat-1"}],
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


class DataCatalogApiTest(unittest.TestCase):
    """覆盖数据目录 API 响应契约。"""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_overview_endpoint_returns_api_response(self) -> None:
        overview = DataCatalogOverviewData(
            status="degraded",
            bucket="polymer-data",
            dataset_count=3,
            object_count=6,
            total_rows=1019992,
            total_columns=203,
            canonical_root="poly_agent/datasets/",
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
        self.assertEqual(payload["data"]["canonical_root"], "poly_agent/datasets/")
        self.assertEqual(payload["data"]["legacy_objects"], ["OpenPoly/OpenPoly.csv"])

    def test_mongo_collections_endpoint_returns_total(self) -> None:
        data = DataCatalogMongoCollectionListData(items=[], total=0)
        with patch.object(DataCatalogService, "list_mongo_collections", return_value=data):
            response = self.client.get("/api/v1/data-catalog/mongo-collections")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["total"], 0)


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
                "ai4ms.Poly_Agent": [
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
        self.assertIn("ai4ms.Poly_Agent", keys)
        self.assertNotIn("audit_events", keys)
        self.assertNotIn("service_integrations", keys)
        material = next(item for item in data["items"] if item["collection_key"] == "ai4ms.Poly_Agent")
        self.assertEqual(material["source_id"], "ai4ms")
        self.assertEqual(material["database"], "ai4ms")
        self.assertEqual(material["collection_name"], "Poly_Agent")
        self.assertEqual(material["group"], "材料数据资产")
        self.assertEqual(material["data_domain"], "materials")
        self.assertIn("properties", material["analysis_facets"])
        self.assertIn("polymer_record_id", material["schema_summary"]["sample_fields"])

    def test_unknown_collection_returns_404(self) -> None:
        self._login_as("admin-user")

        response = self.client.get("/api/v1/data-catalog/mongo-collections/not_allowed/records")

        self.assertEqual(response.status_code, 404)

    def test_non_admin_cannot_list_collection_records(self) -> None:
        self._seed_demo_records()
        self._login_as("regular-user", role="user")

        response = self.client.get("/api/v1/data-catalog/mongo-collections/computation_runs/records")

        self.assertEqual(response.status_code, 403)

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
            "/api/v1/data-catalog/mongo-collections/ai4ms.Poly_Agent/records",
            params={"keyword": "isopropyl", "page": 1, "page_size": 10},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "ai4ms.Poly_Agent")
        self.assertEqual(data["source_id"], "ai4ms")
        self.assertEqual(data["database"], "ai4ms")
        self.assertEqual(data["collection_name"], "Poly_Agent")
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
            "/api/v1/data-catalog/mongo-collections/ai4ms.Poly_Agent/records/OPENPOLY-16172"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["collection_key"], "ai4ms.Poly_Agent")
        self.assertEqual(data["source_id"], "ai4ms")
        self.assertEqual(data["database"], "ai4ms")
        self.assertEqual(data["collection_name"], "Poly_Agent")
        self.assertEqual(data["title"], "poly(N -isopropylacrylamide)")
        self.assertEqual(data["primary_key"], {"polymer_record_id": "OPENPOLY-16172"})
        self.assertEqual(data["document"]["polymer"]["psmiles"], "[*]CC(C(NC(C)C)=O)[*]")
