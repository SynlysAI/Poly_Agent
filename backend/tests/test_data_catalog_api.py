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

    def is_configured(self) -> bool:
        return self.configured

    def head_object(self, bucket: str, object_key: str) -> dict | None:
        return self.objects.get(object_key)


class FakeMongoCollection:
    """Small Mongo collection fake for dataset metadata tests."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def find(self, filters: dict, projection: dict | None = None) -> list[dict]:
        return [dict(row) for row in self.rows]

    def count_documents(self, filters: dict) -> int:
        if not filters:
            return len(self.rows)
        return sum(1 for row in self.rows if all(self._nested_value(row, key) == value for key, value in filters.items()))

    def estimated_document_count(self) -> int:
        return len(self.rows)

    def _nested_value(self, row: dict, dotted_key: str):
        value = row
        for part in dotted_key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value


class FakeMongoDatabase:
    """Collection lookup fake."""

    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self.collections = collections

    def __getitem__(self, name: str) -> FakeMongoCollection:
        return FakeMongoCollection(self.collections.get(name, []))


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

        self.assertEqual(len(data.items), 5)
        self.assertFalse(any(obj.exists for dataset in data.items for obj in dataset.objects))

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

        self.assertEqual(len(data.items), 5)
        openpoly = next(item for item in data.items if item.dataset_id == "openpoly")
        self.assertEqual(openpoly.display_name, "OpenPoly Mongo")
        self.assertEqual(openpoly.description, "从 poly_data.datasets 读取的数据集说明。")
        self.assertEqual(openpoly.record_collection_key, "poly_data.material_records")
        self.assertEqual(openpoly.record_count, 1)
        self.assertEqual(openpoly.record_mode, "full")
        self.assertEqual(openpoly.field_summaries[0].label, "Mongo 字段说明")
        self.assertIn("smipoly", {item.dataset_id for item in data.items})

    def test_overview_material_record_count_sums_poly_data_collections(self) -> None:
        original = demo_store.load()
        try:
            demo_store.save({
                "poly_data.material_records": [{"polymer_record_id": "OPENPOLY-1"}],
                "poly_data.radonpy_records": [{"radonpy_record_id": "RADONPY-1"}],
                "poly_data.pi1m_samples": [{"pi1m_record_id": "PI1M-1"}, {"pi1m_record_id": "PI1M-2"}],
                "poly_data.smipoly_monomers": [{"smipoly_record_id": "SMIPOLY-1"}],
                "poly_data.polyuniverse_monomers": [{"polyuniverse_record_id": "POLYUNIVERSE-1"}],
            })
            with patch("app.services.data_catalog_service.settings.require_mongodb", False):
                data = DataCatalogService(s3_client=FakeS3Client(configured=False)).get_overview()
        finally:
            demo_store.save(original)

        self.assertEqual(data.material_record_count, 6)
        self.assertNotEqual(data.material_record_count, data.total_rows)
        self.assertEqual(next(item for item in data.sources if item.source == "mongodb.poly_data").status, "ready")

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
