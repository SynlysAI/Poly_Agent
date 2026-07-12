"""Poly Agent 数据目录服务。"""

from __future__ import annotations

import hashlib
import hmac
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any

from fastapi import HTTPException
from pymongo.errors import PyMongoError

from app.core.config import settings
from app.infra.demo_store import demo_store
from app.infra.mongo import get_data_asset_database, get_database
from app.schemas.data_catalog import (
    CatalogStatus,
    DataCatalogCollectionRecordDetailData,
    DataCatalogCollectionRecordListData,
    DataCatalogCollectionSummary,
    DataCatalogDataset,
    DataCatalogDatasetListData,
    DataCatalogFieldSummary,
    DataCatalogObjectInfo,
    DataCatalogOverviewData,
    DataCatalogRecordSummary,
    DataCatalogSourceStatus,
    DataCatalogMongoCollectionListData,
    DataCatalogRelationshipEdge,
    DataCatalogRelationshipNode,
    DataCatalogRelationshipsData,
)


CANONICAL_ROOT = "poly_agent/datasets/"


@dataclass(frozen=True)
class ObjectMapping:
    """MinIO 对象重命名映射。"""

    dataset_id: str
    role: str
    legacy_key: str
    canonical_key: str


MINIO_OBJECT_MAPPINGS = [
    ObjectMapping(
        dataset_id="radonpy_pi1070",
        role="readme",
        legacy_key="01_RadonPy/01_RadonPy_README(1).md",
        canonical_key="poly_agent/datasets/radonpy_pi1070/docs/readme.md",
    ),
    ObjectMapping(
        dataset_id="radonpy_pi1070",
        role="raw_table",
        legacy_key="01_RadonPy/PI1070.xlsx",
        canonical_key="poly_agent/datasets/radonpy_pi1070/raw/pi1070.xlsx",
    ),
    ObjectMapping(
        dataset_id="pi1m_v2",
        role="readme",
        legacy_key="02_PI1M/02_Pl1M_README(2).md",
        canonical_key="poly_agent/datasets/pi1m_v2/docs/readme.md",
    ),
    ObjectMapping(
        dataset_id="pi1m_v2",
        role="raw_table",
        legacy_key="02_PI1M/PI1M_v2.csv",
        canonical_key="poly_agent/datasets/pi1m_v2/raw/pi1m_v2.csv",
    ),
    ObjectMapping(
        dataset_id="openpoly",
        role="raw_table",
        legacy_key="OpenPoly/OpenPoly.csv",
        canonical_key="poly_agent/datasets/openpoly/raw/openpoly.csv",
    ),
    ObjectMapping(
        dataset_id="openpoly",
        role="requirements_doc",
        legacy_key="OpenPoly/PolyAgent模型与数据集成需求收集表.docx",
        canonical_key="poly_agent/datasets/openpoly/docs/integration_requirements.docx",
    ),
]


DATASET_DEFINITIONS = {
    "radonpy_pi1070": {
        "display_name": "RadonPy PI1070",
        "source_category": "MD/量化计算数据",
        "confidence_label": "高可信计算结果",
        "description": "包含单体结构、量子化学描述符、模拟条件、热力学性质、介电/光学性质和热导率分量。",
        "row_count": 1077,
        "column_count": 157,
        "storage_prefix": "poly_agent/datasets/radonpy_pi1070/",
        "field_summaries": [
            ("smiles", "smiles", "重复单元结构", 1077, 1077, "*CC*"),
            ("density", "density", "密度", 1077, 1077, "0.837971504"),
            ("static_dielectric_const", "static_dielectric_const", "静态介电常数", 1077, 1077, "2.2102"),
            ("thermal_conductivity", "thermal_conductivity", "热导率", 1077, 1077, "0.2361"),
        ],
    },
    "pi1m_v2": {
        "display_name": "PI1M v2",
        "source_category": "模型生成结构数据",
        "confidence_label": "生成结构，含预测 SA Score",
        "description": "约百万规模聚合物结构库，包含 p-SMILES 与合成可及性评分。",
        "row_count": 995799,
        "column_count": 2,
        "storage_prefix": "poly_agent/datasets/pi1m_v2/",
        "field_summaries": [
            ("SMILES", "smiles", "聚合物重复单元 p-SMILES", 995799, 995799, "*CCC[Fe]CCCC(=O)OCCCCOCCCNCC(*)=O"),
            ("SA Score", "sa_score", "合成可及性评分，越低通常越容易合成", 995799, 995799, "4.174851129781874"),
        ],
    },
    "openpoly": {
        "display_name": "OpenPoly",
        "source_category": "多来源结构与物性汇总",
        "confidence_label": "文献/公开来源汇总，物性字段稀疏",
        "description": "包含结构、PSCORE、多类热/电/力/渗透物性及参考来源。",
        "row_count": 13116,
        "column_count": 44,
        "storage_prefix": "poly_agent/datasets/openpoly/",
        "field_summaries": [
            ("PSMILES", "psmiles", "聚合物结构表示", 13116, 13116, "[*]CC(C(NC(C)C)=O)[*]"),
            ("Tg_K", "tg_k", "玻璃化转变温度", 8471, 13116, "405.775"),
            ("Bandgap_Chain_eV", "bandgap_chain_ev", "链态带隙", 3380, 13116, "6.5196"),
            ("Dielectric_Constant_Electronic", "dielectric_constant_electronic", "电子介电常数", 295, 13116, "4.41"),
        ],
    },
}


_OBJECT_STATUS_CACHE: dict[str, tuple[float, dict[str, list[DataCatalogObjectInfo]]]] = {}
SENSITIVE_FIELD_PATTERNS = ("secret", "token", "password", "api_key", "access_key", "credential", "authorization")
POLY_AGENT_SOURCE_ID = "poly_agent"
MATERIAL_SOURCE_ID = "ai4ms"
MATERIAL_COLLECTION_KEY = "ai4ms.Poly_Agent"


@dataclass(frozen=True)
class MongoCollectionDefinition:
    """Mongo 集合目录定义。"""

    collection_key: str
    collection_name: str
    source_id: str
    display_name: str
    group: str
    data_domain: str
    description: str
    primary_keys: list[str]
    analysis_facets: list[str]


MONGO_COLLECTION_DEFINITIONS = [
    MongoCollectionDefinition(
        "ai4ms.Poly_Agent",
        "Poly_Agent",
        MATERIAL_SOURCE_ID,
        "高分子材料记录",
        "材料数据资产",
        "materials",
        "高分子结构、来源、物性、参考文献和导入追溯记录。",
        ["polymer_record_id"],
        ["dataset", "polymer", "properties", "reference", "provenance"],
    ),
    MongoCollectionDefinition(
        "computation_runs",
        "computation_runs",
        POLY_AGENT_SOURCE_ID,
        "计算任务",
        "计算任务与产物",
        "computation",
        "计算任务运行态、输入、状态、结果摘要。",
        ["run_id"],
        ["status", "workflow_type", "engine", "created_at"],
    ),
    MongoCollectionDefinition(
        "computation_artifacts",
        "computation_artifacts",
        POLY_AGENT_SOURCE_ID,
        "计算产物",
        "计算任务与产物",
        "computation",
        "计算输出文件元数据和受控下载索引。",
        ["artifact_id", "run_id"],
        ["artifact_type", "mime_type", "size_bytes", "created_at"],
    ),
    MongoCollectionDefinition(
        "research_problem_specs",
        "research_problem_specs",
        POLY_AGENT_SOURCE_ID,
        "研发问题规格",
        "研发流程与算法",
        "research",
        "材料研发问题、变量、目标和约束定义。",
        ["problem_spec_id"],
        ["status", "problem_type", "material_family", "created_at"],
    ),
    MongoCollectionDefinition(
        "execution_decisions",
        "execution_decisions",
        POLY_AGENT_SOURCE_ID,
        "执行决策",
        "研发流程与算法",
        "research",
        "人工工作台或 AutoResearch 执行模式决策。",
        ["decision_id"],
        ["mode", "status", "created_at"],
    ),
    MongoCollectionDefinition(
        "manual_algorithm_workflows",
        "manual_algorithm_workflows",
        POLY_AGENT_SOURCE_ID,
        "人工算法流程",
        "研发流程与算法",
        "research",
        "人工编排算法节点与步骤定义。",
        ["workflow_id"],
        ["validation_status", "created_at"],
    ),
    MongoCollectionDefinition(
        "workflow_runs",
        "workflow_runs",
        POLY_AGENT_SOURCE_ID,
        "算法流程运行",
        "研发流程与算法",
        "research",
        "WorkflowRun 状态、输入快照、步骤运行和产物引用。",
        ["workflow_run_id"],
        ["status", "created_at", "started_at", "finished_at"],
    ),
    MongoCollectionDefinition(
        "algorithm_runs",
        "algorithm_runs",
        POLY_AGENT_SOURCE_ID,
        "算法运行",
        "研发流程与算法",
        "research",
        "单个算法节点运行记录、输入快照、输出摘要和产物引用。",
        ["run_id"],
        ["status", "algorithm_id", "trigger_source", "created_at"],
    ),
    MongoCollectionDefinition(
        "research_runs",
        "research_runs",
        POLY_AGENT_SOURCE_ID,
        "AutoResearch 运行",
        "研发流程与算法",
        "research",
        "自动研发流程阶段状态、检查点和关联算法运行。",
        ["run_id"],
        ["status", "current_stage", "created_at"],
    ),
    MongoCollectionDefinition(
        "algorithm_registry_entries",
        "algorithm_registry_entries",
        POLY_AGENT_SOURCE_ID,
        "算法注册表",
        "研发流程与算法",
        "research",
        "算法能力、适用材料、输入输出 schema 和状态。",
        ["algorithm_id"],
        ["status", "type", "algorithm_family", "task_scope"],
    ),
    MongoCollectionDefinition(
        "optimization_campaigns",
        "optimization_campaigns",
        POLY_AGENT_SOURCE_ID,
        "优化任务",
        "优化闭环",
        "optimization",
        "实验/计算优化 campaign、目标和搜索空间。",
        ["campaign_id"],
        ["status", "planner_type", "created_at"],
    ),
    MongoCollectionDefinition(
        "alchemist_sessions",
        "alchemist_sessions",
        POLY_AGENT_SOURCE_ID,
        "Alchemist 会话",
        "优化闭环",
        "optimization",
        "实验设计变量、实验记录和模型训练状态。",
        ["session_id"],
        ["status", "model_backend", "experiment_count", "created_at"],
    ),
    MongoCollectionDefinition(
        "report_jobs",
        "report_jobs",
        POLY_AGENT_SOURCE_ID,
        "报告任务",
        "报告产物",
        "reporting",
        "研发报告生成任务、阶段状态和输入快照。",
        ["report_id"],
        ["status", "subject_type", "stage", "created_at"],
    ),
    MongoCollectionDefinition(
        "report_artifacts",
        "report_artifacts",
        POLY_AGENT_SOURCE_ID,
        "报告产物",
        "报告产物",
        "reporting",
        "报告输出文件元数据和存储引用。",
        ["artifact_id", "report_id"],
        ["artifact_type", "filename", "size_bytes", "created_at"],
    ),
]


COLLECTION_DEFINITION_BY_NAME = {definition.collection_key: definition for definition in MONGO_COLLECTION_DEFINITIONS}


class S3ObjectClient:
    """Minimal S3/MinIO HEAD client using AWS Signature V4."""

    def __init__(self, *, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        normalized = endpoint.strip().rstrip("/")
        if normalized and not normalized.startswith(("http://", "https://")):
            normalized = f"{'https' if secure else 'http'}://{normalized}"
        self.endpoint = normalized
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = "us-east-1"
        self.service = "s3"

    def is_configured(self) -> bool:
        """Return whether enough configuration exists to call MinIO."""
        return bool(self.endpoint and self.access_key and self.secret_key)

    def head_object(self, bucket: str, object_key: str) -> dict[str, Any] | None:
        """Return object metadata or None when object does not exist."""
        request = self._signed_request("HEAD", bucket, object_key)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                last_modified = response.headers.get("Last-Modified")
                parsed_last_modified = None
                if last_modified:
                    parsed_last_modified = parsedate_to_datetime(last_modified)
                    if parsed_last_modified.tzinfo is None:
                        parsed_last_modified = parsed_last_modified.replace(tzinfo=timezone.utc)
                return {
                    "size_bytes": int(response.headers.get("Content-Length") or 0),
                    "last_modified": parsed_last_modified,
                }
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _signed_request(self, method: str, bucket: str, object_key: str) -> urllib.request.Request:
        parsed_endpoint = urllib.parse.urlparse(self.endpoint)
        host = parsed_endpoint.netloc
        canonical_uri = f"/{bucket}/{urllib.parse.quote(object_key, safe='/-_.~')}"
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        date_stamp = amz_date[:8]
        payload_hash = hashlib.sha256(b"").hexdigest()
        canonical_headers = (
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [method, canonical_uri, "", canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = self._signing_key(date_stamp)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return urllib.request.Request(
            f"{self.endpoint}{canonical_uri}",
            method=method,
            headers={
                "x-amz-date": amz_date,
                "x-amz-content-sha256": payload_hash,
                "Authorization": authorization,
            },
        )

    def _signing_key(self, date_stamp: str) -> bytes:
        def sign(key: bytes, message: str) -> bytes:
            return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

        date_key = sign(("AWS4" + self.secret_key).encode("utf-8"), date_stamp)
        region_key = sign(date_key, self.region)
        service_key = sign(region_key, self.service)
        return sign(service_key, "aws4_request")


class DataCatalogService:
    """Builds the Poly Agent data catalog from MinIO and Mongo metadata."""

    def __init__(self, s3_client: S3ObjectClient | None = None) -> None:
        self.s3_client = s3_client or S3ObjectClient(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def get_overview(self) -> DataCatalogOverviewData:
        """Return data catalog overview."""
        dataset_data = self.list_datasets()
        mongo_data = self.list_mongo_collections()
        object_count = sum(len(dataset.objects) for dataset in dataset_data.items)
        total_rows = sum(dataset.row_count for dataset in dataset_data.items)
        total_columns = sum(dataset.column_count for dataset in dataset_data.items)
        minio_status = self._minio_status(dataset_data.items)
        mongo_status = self._mongo_status(mongo_data.items)
        status = "ready" if minio_status == "ready" and mongo_status == "ready" else "degraded"
        if minio_status == "not_configured":
            status = "not_configured"
        material_status = self._source_status(mongo_data.items, MATERIAL_SOURCE_ID)
        business_status = self._source_status(mongo_data.items, POLY_AGENT_SOURCE_ID)
        return DataCatalogOverviewData(
            status=status,
            bucket=settings.minio_bucket,
            dataset_count=len(dataset_data.items),
            object_count=object_count,
            total_rows=total_rows,
            total_columns=total_columns,
            canonical_root=CANONICAL_ROOT,
            legacy_objects=dataset_data.legacy_objects,
            sources=[
                DataCatalogSourceStatus(
                    source="minio",
                    status=minio_status,
                    detail="原始/半结构化数据文件对象存储",
                    bucket=settings.minio_bucket,
                ),
                DataCatalogSourceStatus(
                    source="mongodb.poly_agent",
                    status=business_status,
                    detail="计算任务、研发流程、优化闭环和报告产物结构化索引",
                    database=settings.mongodb_database,
                ),
                DataCatalogSourceStatus(
                    source="mongodb.ai4ms.Poly_Agent",
                    status=material_status,
                    detail="只读高分子材料记录、结构、物性和来源追溯",
                    database=settings.data_asset_mongodb_database,
                ),
            ],
            relationship_notes=[
                "MinIO 保存原始数据文件和大表对象，路径采用 poly_agent/datasets/* 规范命名。",
                "MongoDB ai4ms.Poly_Agent 保存材料结构、物性、来源和导入追溯。",
                "MongoDB poly_agent 保存计算任务、产物、研发流程、优化闭环和报告产物。",
            ],
        )

    def list_datasets(self) -> DataCatalogDatasetListData:
        """Return dataset catalog items."""
        object_status = self._load_object_status()
        datasets: list[DataCatalogDataset] = []
        legacy_objects: list[str] = []
        for dataset_id, definition in DATASET_DEFINITIONS.items():
            objects = object_status.get(dataset_id, [])
            legacy_objects.extend(item.legacy_object_key for item in objects if item.legacy_exists and item.legacy_object_key)
            datasets.append(
                DataCatalogDataset(
                    dataset_id=dataset_id,
                    display_name=str(definition["display_name"]),
                    source_category=str(definition["source_category"]),
                    confidence_label=str(definition["confidence_label"]),
                    description=str(definition["description"]),
                    row_count=int(definition["row_count"]),
                    column_count=int(definition["column_count"]),
                    storage_prefix=str(definition["storage_prefix"]),
                    objects=objects,
                    field_summaries=[
                        DataCatalogFieldSummary(
                            raw_name=raw_name,
                            canonical_name=canonical_name,
                            label=label,
                            non_empty_count=non_empty_count,
                            total_count=total_count,
                            example=example,
                        )
                        for raw_name, canonical_name, label, non_empty_count, total_count, example in definition[
                            "field_summaries"
                        ]
                    ],
                )
            )
        return DataCatalogDatasetListData(items=datasets, legacy_objects=sorted(set(legacy_objects)))

    def list_mongo_collections(self) -> DataCatalogMongoCollectionListData:
        """Return Mongo collection summaries."""
        if not settings.require_mongodb:
            return self._list_demo_mongo_collections()

        items: list[DataCatalogCollectionSummary] = []
        for definition in MONGO_COLLECTION_DEFINITIONS:
            items.append(self._collection_summary_from_mongo(definition))
        return DataCatalogMongoCollectionListData(items=items, total=len(items))

    def material_record_exists(self, material_record_id: str) -> bool:
        """Return whether a cross-database material reference is valid."""
        if not settings.require_mongodb:
            return any(
                str(item.get("polymer_record_id")) == material_record_id
                for item in demo_store.load().get(MATERIAL_COLLECTION_KEY, [])
            )
        if not settings.data_asset_mongodb_uri:
            return False
        try:
            return bool(get_data_asset_database()["Poly_Agent"].count_documents({"polymer_record_id": material_record_id}, limit=1))
        except PyMongoError:
            return False

    def get_relationships(self) -> DataCatalogRelationshipsData:
        """Aggregate only relationships backed by persisted foreign-key values."""
        if not settings.require_mongodb:
            data = demo_store.load()
            collections = {
                "materials": data.get(MATERIAL_COLLECTION_KEY, []),
                "computations": data.get("computation_runs", []),
                "computation_artifacts": data.get("computation_artifacts", []),
                "research_runs": data.get("research_runs", []),
                "algorithm_runs": data.get("algorithm_runs", []),
                "report_jobs": data.get("report_jobs", []),
                "report_artifacts": data.get("report_artifacts", []),
            }
        else:
            business = get_database()
            material_rows = []
            if settings.data_asset_mongodb_uri:
                try:
                    material_rows = list(get_data_asset_database()["Poly_Agent"].find({}, {"_id": 0, "polymer_record_id": 1}))
                except PyMongoError:
                    material_rows = []
            collections = {
                "materials": material_rows,
                "computations": list(business["computation_runs"].find({}, {"_id": 0, "run_id": 1, "material_record_id": 1})),
                "computation_artifacts": list(business["computation_artifacts"].find({}, {"_id": 0, "run_id": 1})),
                "research_runs": list(business["research_runs"].find({}, {"_id": 0, "run_id": 1})),
                "algorithm_runs": list(business["algorithm_runs"].find({}, {"_id": 0, "research_run_id": 1})),
                "report_jobs": list(business["report_jobs"].find({}, {"_id": 0, "report_id": 1})),
                "report_artifacts": list(business["report_artifacts"].find({}, {"_id": 0, "report_id": 1})),
            }

        material_ids = {str(item.get("polymer_record_id")) for item in collections["materials"] if item.get("polymer_record_id")}
        computation_ids = {str(item.get("run_id")) for item in collections["computations"] if item.get("run_id")}
        research_ids = {str(item.get("run_id")) for item in collections["research_runs"] if item.get("run_id")}
        report_ids = {str(item.get("report_id")) for item in collections["report_jobs"] if item.get("report_id")}
        material_links = sum(1 for item in collections["computations"] if item.get("material_record_id") in material_ids)
        computation_artifact_links = sum(1 for item in collections["computation_artifacts"] if item.get("run_id") in computation_ids)
        research_algorithm_links = sum(1 for item in collections["algorithm_runs"] if item.get("research_run_id") in research_ids)
        report_artifact_links = sum(1 for item in collections["report_artifacts"] if item.get("report_id") in report_ids)

        node_specs = [
            ("materials", "高分子材料", "materials"),
            ("computations", "计算任务", "computations"),
            ("computation_artifacts", "计算产物", "computation_artifacts"),
            ("research_runs", "ResearchRun", "research_runs"),
            ("algorithm_runs", "AlgorithmRun", "algorithm_runs"),
            ("report_jobs", "报告任务", "report_jobs"),
            ("report_artifacts", "报告产物", "report_artifacts"),
        ]
        nodes = [
            DataCatalogRelationshipNode(node_id=node_id, label=label, record_count=len(collections[key]))
            for node_id, label, key in node_specs
        ]

        def edge(source: str, target: str, linked: int, target_key: str, source_field: str, target_field: str):
            target_total = len(collections[target_key])
            return DataCatalogRelationshipEdge(
                source=source,
                target=target,
                linked_count=linked,
                target_coverage=(linked / target_total) if target_total else 0,
                source_field=source_field,
                target_field=target_field,
            )

        return DataCatalogRelationshipsData(
            nodes=nodes,
            edges=[
                edge("materials", "computations", material_links, "computations", "polymer_record_id", "material_record_id"),
                edge("computations", "computation_artifacts", computation_artifact_links, "computation_artifacts", "run_id", "run_id"),
                edge("research_runs", "algorithm_runs", research_algorithm_links, "algorithm_runs", "run_id", "research_run_id"),
                edge("report_jobs", "report_artifacts", report_artifact_links, "report_artifacts", "report_id", "report_id"),
            ],
            generated_at=datetime.now(timezone.utc),
            notes=["关系数仅来自已持久化外键；未关联历史记录不做推测。"],
        )

    def _list_demo_mongo_collections(self) -> DataCatalogMongoCollectionListData:
        data = demo_store.load()
        items = []
        for definition in MONGO_COLLECTION_DEFINITIONS:
            rows = data.get(definition.collection_key, [])
            sample = rows[0] if rows else {}
            items.append(self._collection_summary(definition, len(rows), "ready" if rows else "not_configured", sample))
        return DataCatalogMongoCollectionListData(items=items, total=len(items))

    def list_mongo_collection_records(
        self,
        collection_name: str,
        *,
        page: int = 1,
        page_size: int = 20,
        keyword: str | None = None,
    ) -> DataCatalogCollectionRecordListData:
        """Return paginated record summaries for a whitelisted Mongo collection."""
        definition = self._require_collection_definition(collection_name)
        rows, total = self._load_collection_rows(definition, page=page, page_size=page_size, keyword=keyword)
        return DataCatalogCollectionRecordListData(
            collection_key=definition.collection_key,
            collection_name=definition.collection_name,
            source_id=definition.source_id,
            database=self._definition_database_name(definition),
            primary_keys=definition.primary_keys,
            items=[self._record_summary(definition, row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_mongo_collection_record(
        self,
        collection_name: str,
        record_id: str,
    ) -> DataCatalogCollectionRecordDetailData:
        """Return a sanitized detail document from a whitelisted Mongo collection."""
        definition = self._require_collection_definition(collection_name)
        row = self._find_collection_record(definition, record_id)
        if row is None:
            raise HTTPException(status_code=404, detail="集合记录不存在")
        summary = self._record_summary(definition, row)
        return DataCatalogCollectionRecordDetailData(
            collection_key=definition.collection_key,
            collection_name=definition.collection_name,
            source_id=definition.source_id,
            database=self._definition_database_name(definition),
            record_id=summary.record_id,
            primary_key=summary.primary_key,
            title=summary.title,
            subtitle=summary.subtitle,
            status=summary.status,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            document=self._sanitize_document(row),
        )

    def _require_collection_definition(self, collection_name: str) -> MongoCollectionDefinition:
        definition = COLLECTION_DEFINITION_BY_NAME.get(collection_name)
        if not definition:
            raise HTTPException(status_code=404, detail="未知数据集合")
        return definition

    def _collection_summary_from_mongo(self, definition: MongoCollectionDefinition) -> DataCatalogCollectionSummary:
        if definition.source_id == MATERIAL_SOURCE_ID and not settings.data_asset_mongodb_uri:
            return self._collection_summary(definition, 0, "not_configured", {})
        try:
            db = self._database_for_definition(definition)
            names = set(db.list_collection_names())
            if definition.collection_name not in names:
                return self._collection_summary(definition, 0, "not_configured", {})
            collection = db[definition.collection_name]
            sample = collection.find_one({}, {"_id": 0}) or {}
            return self._collection_summary(definition, int(collection.estimated_document_count()), "ready", sample)
        except PyMongoError:
            return self._collection_summary(definition, None, "degraded", {})

    def _collection_summary(
        self,
        definition: MongoCollectionDefinition,
        count: int | None,
        status: CatalogStatus,
        sample: dict[str, Any],
    ) -> DataCatalogCollectionSummary:
        sample_fields = list(sample.keys())[:20]
        return DataCatalogCollectionSummary(
            collection_key=definition.collection_key,
            collection_name=definition.collection_name,
            source_id=definition.source_id,
            database=self._definition_database_name(definition),
            display_name=definition.display_name,
            group=definition.group,
            data_domain=definition.data_domain,
            description=definition.description,
            count=count,
            status=status,
            primary_keys=definition.primary_keys,
            sample_fields=sample_fields,
            analysis_facets=definition.analysis_facets,
            schema_summary={
                "sample_fields": sample_fields,
                "primary_keys": definition.primary_keys,
                "analysis_facets": definition.analysis_facets,
            },
        )

    def _database_for_definition(self, definition: MongoCollectionDefinition):
        if definition.source_id == MATERIAL_SOURCE_ID:
            return get_data_asset_database()
        return get_database()

    def _definition_database_name(self, definition: MongoCollectionDefinition) -> str:
        if definition.source_id == MATERIAL_SOURCE_ID:
            return settings.data_asset_mongodb_database
        return settings.mongodb_database

    def _load_collection_rows(
        self,
        definition: MongoCollectionDefinition,
        *,
        page: int,
        page_size: int,
        keyword: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        if not settings.require_mongodb:
            return self._load_demo_collection_rows(definition, page=page, page_size=page_size, keyword=keyword)

        if definition.source_id == MATERIAL_SOURCE_ID and not settings.data_asset_mongodb_uri:
            return [], 0

        try:
            db = self._database_for_definition(definition)
            collection = db[definition.collection_name]
            filters = self._build_keyword_filter(definition, keyword)
            total = int(collection.count_documents(filters))
            sort_field = self._preferred_sort_field(definition)
            cursor = (
                collection.find(filters, {"_id": 0})
                .sort([(sort_field, -1)])
                .skip((page - 1) * page_size)
                .limit(page_size)
            )
            return [dict(item) for item in cursor], total
        except PyMongoError:
            return self._load_demo_collection_rows(definition, page=page, page_size=page_size, keyword=keyword)

    def _load_demo_collection_rows(
        self,
        definition: MongoCollectionDefinition,
        *,
        page: int,
        page_size: int,
        keyword: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [dict(item) for item in demo_store.load().get(definition.collection_key, [])]
        normalized_keyword = (keyword or "").strip().lower()
        if normalized_keyword:
            rows = [row for row in rows if normalized_keyword in str(row).lower()]
        sort_field = self._preferred_sort_field(definition)
        rows.sort(key=lambda item: str(self._nested_value(item, sort_field) or ""), reverse=True)
        start = (page - 1) * page_size
        return rows[start : start + page_size], len(rows)

    def _find_collection_record(
        self,
        definition: MongoCollectionDefinition,
        record_id: str,
    ) -> dict[str, Any] | None:
        primary_key = definition.primary_keys[0] if definition.primary_keys else ""
        if not primary_key:
            return None

        if not settings.require_mongodb:
            return self._find_demo_collection_record(definition, record_id)

        if definition.source_id == MATERIAL_SOURCE_ID and not settings.data_asset_mongodb_uri:
            return None

        try:
            db = self._database_for_definition(definition)
            row = db[definition.collection_name].find_one({primary_key: record_id}, {"_id": 0})
            return dict(row) if row else None
        except PyMongoError:
            return self._find_demo_collection_record(definition, record_id)

    def _find_demo_collection_record(
        self,
        definition: MongoCollectionDefinition,
        record_id: str,
    ) -> dict[str, Any] | None:
        primary_key = definition.primary_keys[0] if definition.primary_keys else ""
        for row in demo_store.load().get(definition.collection_key, []):
            if str(row.get(primary_key, "")) == record_id:
                return dict(row)
        return None

    def _build_keyword_filter(self, definition: MongoCollectionDefinition, keyword: str | None) -> dict[str, Any]:
        normalized = (keyword or "").strip()
        if not normalized:
            return {}
        escaped = re.escape(normalized)
        if definition.source_id == MATERIAL_SOURCE_ID:
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_name",
                "dataset.dataset_code",
                "polymer.name",
                "polymer.name_normalized",
                "polymer.psmiles",
                "reference.source_type",
                "provenance.created_by",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        field_names = list(dict.fromkeys([*definition.primary_keys, "status", "created_by", "workflow_type", "engine"]))
        return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}

    def _record_summary(
        self,
        definition: MongoCollectionDefinition,
        row: dict[str, Any],
    ) -> DataCatalogRecordSummary:
        primary_key = {
            key: row.get(key)
            for key in definition.primary_keys
            if row.get(key) is not None
        }
        first_key = definition.primary_keys[0] if definition.primary_keys else ""
        record_id = str(row.get(first_key) or "")
        if definition.source_id == MATERIAL_SOURCE_ID:
            title = self._material_title(row) or record_id or definition.display_name
            subtitle = self._material_subtitle(row)
            preview_fields = self._material_preview_fields(row)
            created_at = self._nested_value(row, "provenance.created_at")
            updated_at = self._nested_value(row, "provenance.updated_at")
        else:
            title = record_id or self._first_non_empty(row, ["name", "display_name", "title"]) or definition.display_name
            subtitle = self._build_record_subtitle(row)
            preview_fields = self._preview_fields(row, definition.primary_keys)
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        return DataCatalogRecordSummary(
            record_id=record_id,
            primary_key=primary_key,
            title=str(title),
            subtitle=subtitle,
            status=str(row.get("status")) if row.get("status") is not None else None,
            created_at=created_at,
            updated_at=updated_at,
            preview_fields=preview_fields,
        )

    def _material_title(self, row: dict[str, Any]) -> str | None:
        polymer = row.get("polymer")
        if isinstance(polymer, dict):
            return self._first_non_empty(polymer, ["name", "name_normalized", "psmiles"])
        return None

    def _material_subtitle(self, row: dict[str, Any]) -> str | None:
        dataset = row.get("dataset") if isinstance(row.get("dataset"), dict) else {}
        polymer = row.get("polymer") if isinstance(row.get("polymer"), dict) else {}
        dataset_name = dataset.get("dataset_name") or dataset.get("dataset_code")
        psmiles = polymer.get("psmiles")
        if dataset_name and psmiles:
            return f"{dataset_name} · {psmiles}"
        return str(dataset_name or psmiles) if dataset_name or psmiles else None

    def _material_preview_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        dataset = row.get("dataset") if isinstance(row.get("dataset"), dict) else {}
        polymer = row.get("polymer") if isinstance(row.get("polymer"), dict) else {}
        properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        reference = row.get("reference") if isinstance(row.get("reference"), dict) else {}
        property_groups = [key for key, value in properties.items() if value]
        preview: dict[str, Any] = {}
        if dataset.get("dataset_name") or dataset.get("dataset_code"):
            preview["dataset"] = dataset.get("dataset_name") or dataset.get("dataset_code")
        if polymer.get("psmiles"):
            preview["psmiles"] = polymer.get("psmiles")
        if property_groups:
            preview["property_groups"] = ", ".join(property_groups)
        if reference.get("source_type"):
            preview["source_type"] = reference.get("source_type")
        if reference.get("n") is not None:
            preview["reference_count"] = reference.get("n")
        return preview

    def _preview_fields(self, row: dict[str, Any], primary_keys: list[str]) -> dict[str, Any]:
        preferred = [
            "workflow_type",
            "engine",
            "artifact_type",
            "event_type",
            "entity_type",
            "planner_type",
            "trigger_source",
            "created_by",
            "display_name",
            "name",
        ]
        preview: dict[str, Any] = {}
        for key in preferred:
            if key in row and key not in primary_keys and row.get(key) is not None:
                preview[key] = self._sanitize_value(key, row[key])
            if len(preview) >= 5:
                return preview
        for key, value in row.items():
            if key in primary_keys or key in {"_id", "created_at", "updated_at", "status"}:
                continue
            preview[key] = self._sanitize_value(key, value)
            if len(preview) >= 5:
                break
        return preview

    def _build_record_subtitle(self, row: dict[str, Any]) -> str | None:
        molecule = row.get("molecule")
        if isinstance(molecule, dict):
            name = molecule.get("name")
            smiles = molecule.get("smiles")
            if name and smiles:
                return f"{name} · {smiles}"
            return str(name or smiles) if name or smiles else None
        return self._first_non_empty(row, ["display_name", "name", "description", "event_type"])

    def _first_non_empty(self, row: dict[str, Any], keys: list[str]) -> str | None:
        for key in keys:
            value = row.get(key)
            if value:
                return str(value)
        return None

    def _preferred_sort_field(self, definition: MongoCollectionDefinition) -> str:
        if definition.source_id == MATERIAL_SOURCE_ID:
            return "provenance.created_at"
        if definition.collection_name == "optimization_candidates":
            return "candidate_key"
        return "created_at"

    def _nested_value(self, row: dict[str, Any], dotted_key: str) -> Any:
        value: Any = row
        for part in dotted_key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value

    def _sanitize_document(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, child in value.items():
                if key == "_id":
                    continue
                sanitized[key] = self._sanitize_value(key, child)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_document(item) for item in value]
        return value

    def _sanitize_value(self, key: str, value: Any) -> Any:
        if self._is_sensitive_field(key):
            if isinstance(value, dict):
                return {child_key: "***" for child_key in value}
            if isinstance(value, list):
                return ["***" for _ in value]
            return "***"
        if isinstance(value, dict):
            return self._sanitize_document(value)
        if isinstance(value, list):
            return [self._sanitize_document(item) for item in value]
        return value

    def _is_sensitive_field(self, key: str) -> bool:
        normalized = key.lower()
        return any(pattern in normalized for pattern in SENSITIVE_FIELD_PATTERNS)

    def _load_object_status(self) -> dict[str, list[DataCatalogObjectInfo]]:
        cache_key = self._object_status_cache_key()
        if cache_key:
            cached = _OBJECT_STATUS_CACHE.get(cache_key)
            if cached and cached[0] > monotonic():
                return cached[1]

        status: dict[str, list[DataCatalogObjectInfo]] = {}
        for mapping in MINIO_OBJECT_MAPPINGS:
            canonical = self._head_object(mapping.canonical_key)
            legacy = self._head_object(mapping.legacy_key)
            status.setdefault(mapping.dataset_id, []).append(
                DataCatalogObjectInfo(
                    object_key=mapping.canonical_key,
                    role=mapping.role,
                    exists=canonical is not None,
                    size_bytes=canonical.get("size_bytes") if canonical else None,
                    last_modified=canonical.get("last_modified") if canonical else None,
                    legacy_object_key=mapping.legacy_key,
                    legacy_exists=legacy is not None,
                )
            )
        if cache_key:
            ttl_seconds = max(settings.data_catalog_cache_ttl_seconds, 0)
            if ttl_seconds:
                _OBJECT_STATUS_CACHE[cache_key] = (monotonic() + ttl_seconds, status)
        return status

    def _object_status_cache_key(self) -> str | None:
        if not isinstance(self.s3_client, S3ObjectClient):
            return None
        return f"{settings.minio_bucket}:{self.s3_client.endpoint}"

    def _head_object(self, object_key: str) -> dict[str, Any] | None:
        if not self.s3_client.is_configured():
            return None
        try:
            return self.s3_client.head_object(settings.minio_bucket, object_key)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError):
            return None

    def _minio_status(self, datasets: list[DataCatalogDataset]) -> CatalogStatus:
        if not self.s3_client.is_configured():
            return "not_configured"
        objects = [item for dataset in datasets for item in dataset.objects]
        if objects and all(item.exists for item in objects):
            return "ready"
        return "degraded"

    def _mongo_status(self, collections: list[DataCatalogCollectionSummary]) -> CatalogStatus:
        if all(item.status == "ready" for item in collections):
            return "ready"
        if any(item.status == "ready" for item in collections):
            return "degraded"
        return "not_configured"

    def _source_status(self, collections: list[DataCatalogCollectionSummary], source_id: str) -> CatalogStatus:
        source_items = [item for item in collections if item.source_id == source_id]
        if not source_items:
            return "not_configured"
        if all(item.status == "ready" for item in source_items):
            return "ready"
        if any(item.status == "ready" for item in source_items):
            return "degraded"
        if any(item.status == "degraded" for item in source_items):
            return "degraded"
        return "not_configured"
