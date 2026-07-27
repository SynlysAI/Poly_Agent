"""Poly Agent 数据目录服务。"""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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
    DataCatalogDatasetProfileData,
    DataCatalogDatasetRecordListData,
    DataCatalogDatasetVisualSamplesData,
    DataCatalogFieldSummary,
    DataCatalogHistogramBin,
    DataCatalogDatasetImportStatus,
    DataCatalogVisualSamplePoint,
    DataCatalogObjectInfo,
    DataCatalogOverviewData,
    DataCatalogRecordSummary,
    DataCatalogSourceStatus,
    DataCatalogMongoCollectionListData,
    DataCatalogRelationshipEdge,
    DataCatalogRelationshipNode,
    DataCatalogRelationshipsData,
)
from app.services.poly_data_extra_datasets import EXTRA_DATASET_SPECS, extra_dataset_definition_map


CANONICAL_ROOT = "datasets/"
POLY_DATA_SOURCE_ID = "poly_data"
MATERIAL_COLLECTION_NAME = "material_records"
MATERIAL_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{MATERIAL_COLLECTION_NAME}"
RADONPY_COLLECTION_NAME = "radonpy_records"
RADONPY_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{RADONPY_COLLECTION_NAME}"
PI1M_COLLECTION_NAME = "pi1m_samples"
PI1M_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{PI1M_COLLECTION_NAME}"
SMIPOLY_COLLECTION_NAME = "smipoly_monomers"
SMIPOLY_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{SMIPOLY_COLLECTION_NAME}"
POLYUNIVERSE_COLLECTION_NAME = "polyuniverse_monomers"
POLYUNIVERSE_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{POLYUNIVERSE_COLLECTION_NAME}"
MD_ALLATOM_FILES_COLLECTION_NAME = "md_allatom_files"
MD_ALLATOM_FILES_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{MD_ALLATOM_FILES_COLLECTION_NAME}"
MD_ALLATOM_DIAMINES_COLLECTION_NAME = "md_allatom_diamines"
MD_ALLATOM_DIAMINES_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{MD_ALLATOM_DIAMINES_COLLECTION_NAME}"
MD_ALLATOM_DIANHYDRIDES_COLLECTION_NAME = "md_allatom_dianhydrides"
MD_ALLATOM_DIANHYDRIDES_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{MD_ALLATOM_DIANHYDRIDES_COLLECTION_NAME}"
MD_ALLATOM_CARBON_RESULTS_COLLECTION_NAME = "md_allatom_carbon_results"
MD_ALLATOM_CARBON_RESULTS_COLLECTION_KEY = f"{POLY_DATA_SOURCE_ID}.{MD_ALLATOM_CARBON_RESULTS_COLLECTION_NAME}"
MD_ALLATOM_DEFAULT_FAMILIES = ("C", "F", "Si")

DATASET_RECORD_COLLECTIONS = {
    "openpoly": (MATERIAL_COLLECTION_KEY, "full"),
    "radonpy_pi1070": (RADONPY_COLLECTION_KEY, "full"),
    "pi1m_v2": (PI1M_COLLECTION_KEY, "full"),
    "smipoly": (SMIPOLY_COLLECTION_KEY, "full"),
    "polyuniverse": (POLYUNIVERSE_COLLECTION_KEY, "full"),
    "md_allatom": (MD_ALLATOM_CARBON_RESULTS_COLLECTION_KEY, "full"),
    **{
        spec.dataset_id: (f"{POLY_DATA_SOURCE_ID}.{spec.collection_name}", "full")
        for spec in EXTRA_DATASET_SPECS
    },
}


@dataclass(frozen=True)
class ObjectMapping:
    """MinIO 对象重命名映射。"""

    dataset_id: str
    role: str
    legacy_key: str | None
    canonical_key: str


MINIO_OBJECT_MAPPINGS = [
    ObjectMapping(
        dataset_id="radonpy_pi1070",
        role="readme",
        legacy_key="poly_agent/datasets/radonpy_pi1070/docs/readme.md",
        canonical_key="datasets/radonpy_pi1070/docs/readme.md",
    ),
    ObjectMapping(
        dataset_id="radonpy_pi1070",
        role="raw_table",
        legacy_key="poly_agent/datasets/radonpy_pi1070/raw/pi1070.xlsx",
        canonical_key="datasets/radonpy_pi1070/raw/pi1070.xlsx",
    ),
    ObjectMapping(
        dataset_id="pi1m_v2",
        role="readme",
        legacy_key="poly_agent/datasets/pi1m_v2/docs/readme.md",
        canonical_key="datasets/pi1m_v2/docs/readme.md",
    ),
    ObjectMapping(
        dataset_id="pi1m_v2",
        role="raw_table",
        legacy_key="poly_agent/datasets/pi1m_v2/raw/pi1m_v2.csv",
        canonical_key="datasets/pi1m_v2/raw/pi1m_v2.csv",
    ),
    ObjectMapping(
        dataset_id="openpoly",
        role="raw_table",
        legacy_key="poly_agent/datasets/openpoly/raw/openpoly.csv",
        canonical_key="datasets/openpoly/raw/openpoly.csv",
    ),
    ObjectMapping(
        dataset_id="openpoly",
        role="requirements_doc",
        legacy_key="poly_agent/datasets/openpoly/docs/integration_requirements.docx",
        canonical_key="datasets/openpoly/docs/integration_requirements.docx",
    ),
    ObjectMapping(
        dataset_id="smipoly",
        role="readme",
        legacy_key=None,
        canonical_key="datasets/smipoly/docs/readme.md",
    ),
    ObjectMapping(
        dataset_id="smipoly",
        role="raw_table",
        legacy_key=None,
        canonical_key="datasets/smipoly/raw/202207_smip_monset.csv",
    ),
    ObjectMapping(
        dataset_id="polyuniverse",
        role="readme",
        legacy_key=None,
        canonical_key="datasets/polyuniverse/docs/readme.md",
    ),
    ObjectMapping(
        dataset_id="polyuniverse",
        role="raw_diCOOH",
        legacy_key=None,
        canonical_key="datasets/polyuniverse/raw/diCOOH.csv",
    ),
    ObjectMapping(
        dataset_id="polyuniverse",
        role="raw_epoxy_diE",
        legacy_key=None,
        canonical_key="datasets/polyuniverse/raw/epoxy_diE.csv",
    ),
    ObjectMapping(
        dataset_id="polyuniverse",
        role="raw_epoxy_diN",
        legacy_key=None,
        canonical_key="datasets/polyuniverse/raw/epoxy_diN.csv",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="structured_diamine",
        legacy_key=None,
        canonical_key="datasets/md_allatom/structured/diamine.csv",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="structured_dianhydride",
        legacy_key=None,
        canonical_key="datasets/md_allatom/structured/dianhydride.csv",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="structured_carbon",
        legacy_key=None,
        canonical_key="datasets/md_allatom/structured/carbon.csv",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="requirements_doc",
        legacy_key=None,
        canonical_key="datasets/md_allatom/docs/integration_requirements.docx",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="manifest_C",
        legacy_key=None,
        canonical_key="datasets/md_allatom/manifests/C.json",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="manifest_F",
        legacy_key=None,
        canonical_key="datasets/md_allatom/manifests/F.json",
    ),
    ObjectMapping(
        dataset_id="md_allatom",
        role="manifest_Si",
        legacy_key=None,
        canonical_key="datasets/md_allatom/manifests/Si.json",
    ),
    *[
        ObjectMapping(
            dataset_id=spec.dataset_id,
            role=file_spec.role,
            legacy_key=None,
            canonical_key=file_spec.object_key,
        )
        for spec in EXTRA_DATASET_SPECS
        for file_spec in spec.files
    ],
]


DATASET_DEFINITIONS = {
    "radonpy_pi1070": {
        "display_name": "RadonPy PI1070",
        "source_category": "MD/量化计算数据",
        "confidence_label": "高可信计算结果",
        "description": "包含单体结构、量子化学描述符、模拟条件、热力学性质、介电/光学性质和热导率分量。",
        "row_count": 1077,
        "column_count": 157,
        "storage_prefix": "datasets/radonpy_pi1070/",
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
        "storage_prefix": "datasets/pi1m_v2/",
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
        "storage_prefix": "datasets/openpoly/",
        "field_summaries": [
            ("PSMILES", "psmiles", "聚合物结构表示", 13116, 13116, "[*]CC(C(NC(C)C)=O)[*]"),
            ("Tg_K", "tg_k", "玻璃化转变温度", 8471, 13116, "405.775"),
            ("Bandgap_Chain_eV", "bandgap_chain_ev", "链态带隙", 3380, 13116, "6.5196"),
            ("Dielectric_Constant_Electronic", "dielectric_constant_electronic", "电子介电常数", 295, 13116, "4.41"),
        ],
    },
    "smipoly": {
        "display_name": "SMiPoly",
        "source_category": "公开资料整理 / 结构数据",
        "confidence_label": "单体结构库，无物性标签",
        "description": "SMiPoly 单体输入库，包含单体编号、分子式、分子量、SMILES 和 IUPAC 名称。",
        "row_count": 1083,
        "column_count": 5,
        "storage_prefix": "datasets/smipoly/",
        "field_summaries": [
            ("comID", "com_id", "单体记录编号", 1083, 1083, "CID174"),
            ("MolecularFormula", "molecular_formula", "分子式", 1083, 1083, "C2H6O2"),
            ("MolecularWeight", "molecular_weight", "分子量", 1083, 1083, "62.07"),
            ("SMILES", "smiles", "单体 SMILES", 1083, 1083, "C(CO)O"),
            ("IUPACName", "iupac_name", "IUPAC 名称", 1082, 1083, "ethane-1,2-diol"),
        ],
    },
    "polyuniverse": {
        "display_name": "PolyUniverse",
        "source_category": "虚拟结构生成 / 候选单体",
        "confidence_label": "生成候选单体，无物性标签",
        "description": "PolyUniverse Generation 示例小分子原料库，包含二羧酸、双环氧和双胺候选单体 SMILES。",
        "row_count": 51787,
        "column_count": 1,
        "storage_prefix": "datasets/polyuniverse/",
        "field_summaries": [
            ("Smiles", "smiles", "候选单体 SMILES", 51787, 51787, "CC12CC1C(CC2C(O)=O)C(O)=O"),
            ("source_file", "source_file", "来源 CSV 文件", 51787, 51787, "diCOOH.csv"),
            ("monomer_class", "monomer_class", "单体类别", 51787, 51787, "dicarboxylic_acid"),
        ],
    },
    "md_allatom": {
        "display_name": "MD-AllAtom",
        "source_category": "全原子分子动力学数据",
        "confidence_label": "结构化 MD 结果 + 原始模拟文件",
        "description": "包含 C/F/Si 三类 MD-AllAtom 原始模拟文件索引，以及二胺、二酐字典和碳基全原子 MD 结构统计结果。",
        "row_count": 10000,
        "column_count": 26,
        "storage_prefix": "datasets/md_allatom/",
        "field_summaries": [
            ("diamine_id", "diamine_id", "二胺编号", 9944, 9944, "1"),
            ("dianhydride_id", "dianhydride_id", "二酐编号", 9944, 9944, "1"),
            ("dp", "dp", "聚合度", 9944, 9944, "32"),
            ("temperature", "temperature", "温度 K", 9944, 9944, "250"),
            ("e2e_mean", "e2e_mean", "均方末端距平均值 Å", 9944, 9944, "369.37"),
            ("rg_mean", "rg_mean", "回转半径平均值 Å", 9944, 9944, "143.78"),
            ("persist_len_mean", "persist_len_mean", "持久长度平均值 Å", 9944, 9944, "114.87"),
            ("data_file", "data_file", "模拟输入 data 文件", 9944, 9944, "polymer_1_1_32npt.data"),
            ("out_file", "out_file", "模拟输出 out 文件", 9944, 9944, "250_1_1_32_.out"),
        ],
    },
    **extra_dataset_definition_map(),
}


_OBJECT_STATUS_CACHE: dict[str, tuple[float, dict[str, list[DataCatalogObjectInfo]]]] = {}
SENSITIVE_FIELD_PATTERNS = ("secret", "token", "password", "api_key", "access_key", "credential", "authorization")
POLY_AGENT_SOURCE_ID = "poly_agent"
MATERIAL_SOURCE_ID = POLY_DATA_SOURCE_ID


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
    search_fields: list[str] = field(default_factory=list)


MONGO_COLLECTION_DEFINITIONS = [
    MongoCollectionDefinition(
        MATERIAL_COLLECTION_KEY,
        MATERIAL_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "高分子材料记录",
        "材料数据资产",
        "materials",
        "Poly Data 高分子结构、来源、物性、参考文献和导入追溯记录。",
        ["polymer_record_id"],
        ["dataset", "polymer", "properties", "reference", "provenance"],
    ),
    MongoCollectionDefinition(
        RADONPY_COLLECTION_KEY,
        RADONPY_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "RadonPy PI1070 记录",
        "材料数据资产",
        "radonpy_records",
        "RadonPy PI1070 全量行级记录，包含重复单元结构、计算描述符和热/电/输运物性。",
        ["radonpy_record_id"],
        ["dataset", "smiles", "properties", "simulation", "source_file"],
    ),
    MongoCollectionDefinition(
        PI1M_COLLECTION_KEY,
        PI1M_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "PI1M v2 记录",
        "材料数据资产",
        "pi1m_samples",
        "PI1M v2 结构库全量行级记录，包含 p-SMILES、合成可及性评分和导入行号。",
        ["pi1m_record_id"],
        ["dataset", "smiles", "sa_score", "row_index", "smiles_hash"],
    ),
    MongoCollectionDefinition(
        SMIPOLY_COLLECTION_KEY,
        SMIPOLY_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "SMiPoly 单体记录",
        "材料数据资产",
        "smipoly_monomers",
        "SMiPoly 单体输入库全量记录，包含结构、分子式、分子量和 IUPAC 名称。",
        ["smipoly_record_id"],
        ["dataset", "com_id", "smiles", "molecular_formula", "molecular_weight", "source_file"],
    ),
    MongoCollectionDefinition(
        POLYUNIVERSE_COLLECTION_KEY,
        POLYUNIVERSE_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "PolyUniverse 单体记录",
        "材料数据资产",
        "polyuniverse_monomers",
        "PolyUniverse 候选单体全量记录，按来源文件区分二羧酸、双环氧和双胺类别。",
        ["polyuniverse_record_id"],
        ["dataset", "monomer_class", "source_file", "smiles", "row_index"],
    ),
    MongoCollectionDefinition(
        MD_ALLATOM_FILES_COLLECTION_KEY,
        MD_ALLATOM_FILES_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "MD-AllAtom 原始文件索引",
        "材料数据资产",
        "md_allatom_files",
        "MD-AllAtom C/F/Si 原始模拟文件在 MinIO 中的对象索引和 SFTP 来源追溯。",
        ["md_allatom_file_id"],
        ["dataset", "family", "filename", "extension", "object_key", "sync_status"],
    ),
    MongoCollectionDefinition(
        MD_ALLATOM_DIAMINES_COLLECTION_KEY,
        MD_ALLATOM_DIAMINES_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "MD-AllAtom 二胺字典",
        "材料数据资产",
        "md_allatom_diamines",
        "MD-AllAtom 结构化二胺单体字典，包含 CAS、名称、缩写和 SMILES。",
        ["md_allatom_diamine_id"],
        ["dataset", "diamine_id", "cas", "abbr", "smiles"],
    ),
    MongoCollectionDefinition(
        MD_ALLATOM_DIANHYDRIDES_COLLECTION_KEY,
        MD_ALLATOM_DIANHYDRIDES_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "MD-AllAtom 二酐字典",
        "材料数据资产",
        "md_allatom_dianhydrides",
        "MD-AllAtom 结构化二酐单体字典，包含 CAS、名称、缩写和 SMILES。",
        ["md_allatom_dianhydride_id"],
        ["dataset", "dianhydride_id", "cas", "abbr", "smiles"],
    ),
    MongoCollectionDefinition(
        MD_ALLATOM_CARBON_RESULTS_COLLECTION_KEY,
        MD_ALLATOM_CARBON_RESULTS_COLLECTION_NAME,
        MATERIAL_SOURCE_ID,
        "MD-AllAtom 碳基结果",
        "材料数据资产",
        "md_allatom_carbon_results",
        "MD-AllAtom 碳基全原子 MD 结构统计结果，按 CSV 行号保留重复自然键记录。",
        ["md_allatom_carbon_result_id"],
        ["dataset", "family", "diamine_id", "dianhydride_id", "dp", "temperature", "e2e_mean", "rg_mean"],
    ),
    *[
        MongoCollectionDefinition(
            f"{POLY_DATA_SOURCE_ID}.{spec.collection_name}",
            spec.collection_name,
            MATERIAL_SOURCE_ID,
            f"{spec.display_name} 记录",
            "材料数据资产",
            spec.data_domain,
            spec.description,
            list(spec.primary_keys),
            list(spec.analysis_facets),
            list(spec.search_fields),
        )
        for spec in EXTRA_DATASET_SPECS
    ],
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
        material_record_count = self._material_record_count(mongo_data.items)
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
            material_record_count=material_record_count,
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
                    source="mongodb.poly_data",
                    status=material_status,
                    detail="Poly Data 高分子材料数据资产、结构、物性和来源追溯",
                    database=settings.data_asset_mongodb_database,
                ),
            ],
            relationship_notes=[
                "MinIO 保存原始数据文件和大表对象，路径采用 datasets/* 规范命名。",
                "MongoDB poly_data 保存材料结构、物性、来源和导入追溯。",
                "MongoDB poly_agent 保存计算任务、产物、研发流程、优化闭环和报告产物。",
            ],
        )

    def _material_record_count(self, collections: list[DataCatalogCollectionSummary]) -> int | None:
        material_collections = [item for item in collections if item.source_id == MATERIAL_SOURCE_ID]
        if not material_collections:
            return None
        if any(item.count is None or item.status == "degraded" for item in material_collections):
            return None
        return sum(int(item.count or 0) for item in material_collections)

    def list_datasets(self) -> DataCatalogDatasetListData:
        """Return dataset catalog items."""
        object_status = self._load_object_status()
        definitions = self._load_dataset_definitions()
        datasets: list[DataCatalogDataset] = []
        legacy_objects: list[str] = []
        for dataset_id, definition in definitions.items():
            objects = object_status.get(dataset_id, [])
            record_info = self._dataset_record_info(dataset_id, row_count=int(definition["row_count"]))
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
                    record_collection_key=record_info["record_collection_key"],
                    record_count=record_info["record_count"],
                    record_mode=record_info["record_mode"],
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

    def get_dataset_profile(self, dataset_id: str) -> DataCatalogDatasetProfileData:
        """Return aggregate dataset profile data suitable for dashboard rendering."""
        dataset = self._dataset_by_id(dataset_id)
        record_count = int(dataset.record_count or 0)
        coverage = round((record_count / dataset.row_count) * 100, 4) if dataset.row_count else 0
        stats = self._load_dataset_stats(dataset_id)
        if dataset_id == "md_allatom" and not stats:
            stats = self._fallback_md_allatom_dataset_stats(dataset)
            if stats.get("record_count") is not None:
                record_count = int(stats.get("record_count") or 0)
                coverage = round((record_count / dataset.row_count) * 100, 4) if dataset.row_count else 0
        import_status = self._load_dataset_import_status(dataset_id)
        histogram = [
            DataCatalogHistogramBin(start=float(item["start"]), end=float(item["end"]), count=int(item["count"]))
            for item in stats.get("sa_score_histogram", [])
            if isinstance(item, dict) and {"start", "end", "count"} <= set(item)
        ]
        return DataCatalogDatasetProfileData(
            dataset_id=dataset_id,
            row_count=dataset.row_count,
            record_count=record_count,
            coverage_percent=coverage,
            record_mode=dataset.record_mode,
            field_completeness=dataset.field_summaries,
            sa_score_histogram=histogram,
            duplicate_smiles_count=stats.get("duplicate_smiles_count"),
            unique_smiles_count=stats.get("unique_smiles_count"),
            numeric_histograms=self._profile_numeric_histograms(stats),
            category_counts=self._profile_category_counts(stats),
            analysis_samples=self._profile_analysis_samples(stats),
            asset_coverage=stats.get("asset_coverage") if isinstance(stats.get("asset_coverage"), dict) else {},
            import_status=import_status,
        )

    def has_dataset_stats(self, dataset_id: str) -> bool:
        """Return whether the dataset has profile/statistics data available."""
        if not settings.require_mongodb:
            return bool(self._load_dataset_stats(dataset_id))
        if dataset_id == "md_allatom":
            stats = self._load_dataset_stats(dataset_id)
            if stats:
                return True
            return bool(self._load_md_allatom_carbon_result_rows())
        return bool(self._load_dataset_stats(dataset_id))

    def _profile_numeric_histograms(self, stats: dict[str, Any]) -> dict[str, list[DataCatalogHistogramBin]]:
        raw = stats.get("numeric_histograms")
        if not isinstance(raw, dict):
            return {}
        histograms: dict[str, list[DataCatalogHistogramBin]] = {}
        for field, bins in raw.items():
            if not isinstance(bins, list):
                continue
            histograms[str(field)] = [
                DataCatalogHistogramBin(start=float(item["start"]), end=float(item["end"]), count=int(item["count"]))
                for item in bins
                if isinstance(item, dict) and {"start", "end", "count"} <= set(item)
            ]
        return histograms

    def _profile_category_counts(self, stats: dict[str, Any]) -> dict[str, dict[str, int]]:
        raw = stats.get("category_counts")
        if not isinstance(raw, dict):
            return {}
        counts: dict[str, dict[str, int]] = {}
        for field, values in raw.items():
            if not isinstance(values, dict):
                continue
            counts[str(field)] = {str(key): int(value) for key, value in values.items() if isinstance(value, (int, float))}
        return counts

    def _profile_analysis_samples(self, stats: dict[str, Any]) -> list[dict[str, Any]]:
        raw = stats.get("analysis_samples")
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw[:5000] if isinstance(item, dict)]

    def list_dataset_records(
        self,
        dataset_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 50,
        sort_by: str = "row_index",
        sa_min: float | None = None,
        sa_max: float | None = None,
        keyword: str | None = None,
        row_start: int | None = None,
        row_end: int | None = None,
    ) -> DataCatalogDatasetRecordListData:
        """Return keyset-paginated dataset records."""
        dataset = self._dataset_by_id(dataset_id)
        if dataset_id != "pi1m_v2":
            rows, total = self._load_collection_rows(
                self._require_collection_definition(dataset.record_collection_key or ""),
                page=1,
                page_size=page_size,
                keyword=keyword,
            )
            return DataCatalogDatasetRecordListData(
                dataset_id=dataset_id,
                collection_key=dataset.record_collection_key or "",
                items=[self._record_summary(self._require_collection_definition(dataset.record_collection_key or ""), row) for row in rows],
                page_size=page_size,
                next_cursor=None,
                total=total,
            )

        definition = self._require_collection_definition(PI1M_COLLECTION_KEY)
        limit = max(1, min(page_size, 200))
        if not settings.require_mongodb:
            rows = self._load_demo_pi1m_dataset_rows(
                cursor=cursor,
                page_size=limit,
                sort_by=sort_by,
                sa_min=sa_min,
                sa_max=sa_max,
                keyword=keyword,
                row_start=row_start,
                row_end=row_end,
            )
            total = len(demo_store.load().get(PI1M_COLLECTION_KEY, []))
        else:
            rows = self._load_mongo_pi1m_dataset_rows(
                cursor=cursor,
                page_size=limit,
                sort_by=sort_by,
                sa_min=sa_min,
                sa_max=sa_max,
                keyword=keyword,
                row_start=row_start,
                row_end=row_end,
            )
            total = dataset.record_count

        next_cursor = None
        visible_rows = rows[:limit]
        if len(rows) > limit and visible_rows:
            next_cursor = self._encode_cursor(visible_rows[-1], sort_by)
        return DataCatalogDatasetRecordListData(
            dataset_id=dataset_id,
            collection_key=PI1M_COLLECTION_KEY,
            items=[self._record_summary(definition, row) for row in visible_rows],
            page_size=limit,
            next_cursor=next_cursor,
            total=total,
        )

    def get_dataset_visual_samples(self, dataset_id: str, *, limit: int = 5000) -> DataCatalogDatasetVisualSamplesData:
        """Return bounded visual sample points for large dataset exploration."""
        dataset = self._dataset_by_id(dataset_id)
        bounded_limit = max(100, min(limit, 20000))
        if dataset_id != "pi1m_v2":
            return DataCatalogDatasetVisualSamplesData(dataset_id=dataset_id, sample_count=0, total=dataset.record_count, points=[])

        stats = self._load_dataset_stats(dataset_id)
        stored_points = stats.get("visual_samples")
        if isinstance(stored_points, list) and stored_points:
            points = [self._visual_point_from_row(item) for item in stored_points[:bounded_limit]]
            return DataCatalogDatasetVisualSamplesData(
                dataset_id=dataset_id,
                sample_count=len(points),
                total=dataset.record_count,
                points=points,
            )

        rows = self._load_pi1m_visual_rows(bounded_limit)
        points = [self._visual_point_from_row(row) for row in rows]
        return DataCatalogDatasetVisualSamplesData(
            dataset_id=dataset_id,
            sample_count=len(points),
            total=dataset.record_count,
            points=points,
        )

    def _dataset_by_id(self, dataset_id: str) -> DataCatalogDataset:
        for dataset in self.list_datasets().items:
            if dataset.dataset_id == dataset_id:
                return dataset
        raise HTTPException(status_code=404, detail="未知数据集")

    def _load_dataset_stats(self, dataset_id: str) -> dict[str, Any]:
        if not settings.require_mongodb:
            return self._demo_dataset_stats(dataset_id)
        if not settings.data_asset_mongodb_uri:
            return {}
        try:
            doc = get_data_asset_database()["dataset_stats"].find_one({"dataset_id": dataset_id}, {"_id": 0})
            return dict(doc) if doc else {}
        except PyMongoError:
            return {}

    def _fallback_md_allatom_dataset_stats(self, dataset: DataCatalogDataset) -> dict[str, Any]:
        """Rebuild MD-AllAtom stats from the live collections when the stats document is missing."""
        rows = self._load_md_allatom_carbon_result_rows()
        file_rows = self._load_md_allatom_file_rows()
        record_count = len(rows)
        if not rows:
            return {
                "record_count": record_count,
                "asset_coverage": {
                    "file_count": len(file_rows),
                    "families": self._md_allatom_family_file_counts(file_rows),
                    "structured_records": {"carbon_results": len(rows)},
                },
                "category_counts": {},
                "numeric_histograms": {},
                "analysis_samples": [],
            }

        category_counts: dict[str, dict[str, int]] = {"temperature": {}, "dp": {}, "family": {}}
        numeric_fields = {"e2e_mean": [], "rg_mean": [], "persist_len_mean": []}
        samples: list[dict[str, Any]] = []
        sample_step = max(len(rows) // 5000, 1)
        for index, row in enumerate(rows):
            for field in ["temperature", "dp", "family"]:
                value = row.get(field)
                if value is None:
                    continue
                key = str(value)
                category_counts[field][key] = category_counts[field].get(key, 0) + 1
            for field in numeric_fields:
                numeric_value = self._to_float(row.get(field))
                if numeric_value is not None:
                    numeric_fields[field].append(numeric_value)
            if index % sample_step == 0:
                samples.append({
                    "record_id": str(row.get("md_allatom_carbon_result_id") or ""),
                    "x": row.get("temperature"),
                    "y": row.get("e2e_mean"),
                    "category": f"dp={row.get('dp')}" if row.get("dp") is not None else "dp=-",
                    "dp": row.get("dp"),
                    "temperature": row.get("temperature"),
                    "rg_mean": row.get("rg_mean"),
                    "persist_len_mean": row.get("persist_len_mean"),
                })

        return {
            "record_count": record_count,
            "asset_coverage": {
                "file_count": len(file_rows),
                "families": self._md_allatom_family_file_counts(file_rows),
                "structured_records": {"carbon_results": len(rows)},
            },
            "category_counts": category_counts,
            "numeric_histograms": {field: self._histogram(values) for field, values in numeric_fields.items()},
            "analysis_samples": samples,
        }

    def _load_md_allatom_carbon_result_rows(self) -> list[dict[str, Any]]:
        if not settings.data_asset_mongodb_uri:
            return [dict(row) for row in demo_store.load().get(MD_ALLATOM_CARBON_RESULTS_COLLECTION_KEY, [])]
        try:
            db = get_data_asset_database()
            return [dict(row) for row in db[MD_ALLATOM_CARBON_RESULTS_COLLECTION_NAME].find({}, {"_id": 0})]
        except PyMongoError:
            return []

    def _load_md_allatom_file_rows(self) -> list[dict[str, Any]]:
        if not settings.data_asset_mongodb_uri:
            return [dict(row) for row in demo_store.load().get(MD_ALLATOM_FILES_COLLECTION_KEY, [])]
        try:
            db = get_data_asset_database()
            return [dict(row) for row in db[MD_ALLATOM_FILES_COLLECTION_NAME].find({}, {"_id": 0})]
        except PyMongoError:
            return []

    def _md_allatom_family_file_counts(self, file_rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {family: 0 for family in MD_ALLATOM_DEFAULT_FAMILIES}
        for row in file_rows:
            family = str(row.get("family") or "")
            if family:
                counts[family] = counts.get(family, 0) + 1
        return counts

    def _load_dataset_import_status(self, dataset_id: str) -> DataCatalogDatasetImportStatus:
        if not settings.require_mongodb:
            return DataCatalogDatasetImportStatus(status="demo")
        if not settings.data_asset_mongodb_uri:
            return DataCatalogDatasetImportStatus(status="not_configured")
        try:
            doc = get_data_asset_database()["import_jobs"].find_one(
                {"dataset_id": dataset_id},
                {"_id": 0},
                sort=[("started_at", -1)],
            )
            if not doc:
                return DataCatalogDatasetImportStatus(status="unknown")
            return DataCatalogDatasetImportStatus(
                job_id=doc.get("job_id"),
                status=str(doc.get("status") or "unknown"),
                imported_count=doc.get("imported_count"),
                failed_count=doc.get("failed_count"),
                started_at=doc.get("started_at"),
                finished_at=doc.get("finished_at"),
                throughput_rows_per_second=doc.get("throughput_rows_per_second"),
                error=doc.get("error"),
            )
        except PyMongoError:
            return DataCatalogDatasetImportStatus(status="degraded")

    def _demo_dataset_stats(self, dataset_id: str) -> dict[str, Any]:
        if dataset_id != "pi1m_v2":
            for row in demo_store.load().get("poly_data.dataset_stats", []):
                if row.get("dataset_id") == dataset_id:
                    return dict(row)
            return {}
        rows = demo_store.load().get(PI1M_COLLECTION_KEY, [])
        scores = [self._to_float(row.get("sa_score")) for row in rows if self._to_float(row.get("sa_score")) is not None]
        smiles_values = [str(row.get("smiles")) for row in rows if row.get("smiles")]
        return {
            "sa_score_histogram": self._histogram(scores),
            "unique_smiles_count": len(set(smiles_values)),
            "duplicate_smiles_count": max(0, len(smiles_values) - len(set(smiles_values))),
        }

    def _load_mongo_pi1m_dataset_rows(
        self,
        *,
        cursor: str | None,
        page_size: int,
        sort_by: str,
        sa_min: float | None,
        sa_max: float | None,
        keyword: str | None,
        row_start: int | None,
        row_end: int | None,
    ) -> list[dict[str, Any]]:
        if not settings.data_asset_mongodb_uri:
            return []
        filters = self._build_pi1m_dataset_filter(
            cursor=cursor,
            sort_by=sort_by,
            sa_min=sa_min,
            sa_max=sa_max,
            keyword=keyword,
            row_start=row_start,
            row_end=row_end,
        )
        sort = [("sa_score", 1), ("row_index", 1)] if sort_by == "sa_score" else [("row_index", 1)]
        try:
            cursor_rows = (
                get_data_asset_database()[PI1M_COLLECTION_NAME]
                .find(filters, {"_id": 0})
                .sort(sort)
                .limit(page_size + 1)
            )
            return [dict(item) for item in cursor_rows]
        except PyMongoError:
            return []

    def _load_demo_pi1m_dataset_rows(
        self,
        *,
        cursor: str | None,
        page_size: int,
        sort_by: str,
        sa_min: float | None,
        sa_max: float | None,
        keyword: str | None,
        row_start: int | None,
        row_end: int | None,
    ) -> list[dict[str, Any]]:
        rows = [dict(row) for row in demo_store.load().get(PI1M_COLLECTION_KEY, [])]
        decoded = self._decode_cursor(cursor)
        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            keyword_hash = self._smiles_hash(normalized_keyword)
            rows = [
                row
                for row in rows
                if normalized_keyword in {str(row.get("pi1m_record_id") or ""), str(row.get("smiles") or ""), str(row.get("smiles_hash") or "")}
                or keyword_hash == row.get("smiles_hash")
            ]
        if row_start is not None:
            rows = [row for row in rows if int(row.get("row_index") or row.get("sample_index") or 0) >= row_start]
        if row_end is not None:
            rows = [row for row in rows if int(row.get("row_index") or row.get("sample_index") or 0) <= row_end]
        if sa_min is not None:
            rows = [row for row in rows if (self._to_float(row.get("sa_score")) or -math.inf) >= sa_min]
        if sa_max is not None:
            rows = [row for row in rows if (self._to_float(row.get("sa_score")) or math.inf) <= sa_max]
        if sort_by == "sa_score":
            rows.sort(key=lambda row: (self._to_float(row.get("sa_score")) or math.inf, int(row.get("row_index") or 0)))
            if decoded:
                rows = [
                    row
                    for row in rows
                    if (
                        self._to_float(row.get("sa_score")) or math.inf,
                        int(row.get("row_index") or 0),
                    )
                    > (float(decoded.get("sa_score") or -math.inf), int(decoded.get("row_index") or 0))
                ]
        else:
            rows.sort(key=lambda row: int(row.get("row_index") or row.get("sample_index") or 0))
            if decoded:
                rows = [row for row in rows if int(row.get("row_index") or 0) > int(decoded.get("row_index") or 0)]
        return rows[: page_size + 1]

    def _build_pi1m_dataset_filter(
        self,
        *,
        cursor: str | None,
        sort_by: str,
        sa_min: float | None,
        sa_max: float | None,
        keyword: str | None,
        row_start: int | None,
        row_end: int | None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        row_filter: dict[str, Any] = {}
        if row_start is not None:
            row_filter["$gte"] = row_start
        if row_end is not None:
            row_filter["$lte"] = row_end
        if row_filter:
            filters["row_index"] = row_filter
        sa_filter: dict[str, Any] = {}
        if sa_min is not None:
            sa_filter["$gte"] = sa_min
        if sa_max is not None:
            sa_filter["$lte"] = sa_max
        if sa_filter:
            filters["sa_score"] = sa_filter
        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            keyword_filter: list[dict[str, Any]] = [
                {"pi1m_record_id": normalized_keyword},
                {"smiles": normalized_keyword},
                {"smiles_hash": self._smiles_hash(normalized_keyword)},
            ]
            if normalized_keyword.isdigit():
                keyword_filter.extend([
                    {"row_index": int(normalized_keyword)},
                    {"sample_index": int(normalized_keyword)},
                ])
            filters["$or"] = keyword_filter
        decoded = self._decode_cursor(cursor)
        if decoded:
            if sort_by == "sa_score":
                cursor_score = float(decoded.get("sa_score") or -math.inf)
                cursor_row = int(decoded.get("row_index") or 0)
                filters["$and"] = filters.get("$and", [])
                filters["$and"].append(
                    {
                        "$or": [
                            {"sa_score": {"$gt": cursor_score}},
                            {"sa_score": cursor_score, "row_index": {"$gt": cursor_row}},
                        ]
                    }
                )
            else:
                cursor_row = int(decoded.get("row_index") or 0)
                current = filters.get("row_index")
                if isinstance(current, dict):
                    current["$gt"] = max(int(current.get("$gt", 0)), cursor_row)
                else:
                    filters["row_index"] = {"$gt": cursor_row}
        return filters

    def _load_pi1m_visual_rows(self, limit: int) -> list[dict[str, Any]]:
        if not settings.require_mongodb:
            return demo_store.load().get(PI1M_COLLECTION_KEY, [])[:limit]
        if not settings.data_asset_mongodb_uri:
            return []
        try:
            collection = get_data_asset_database()[PI1M_COLLECTION_NAME]
            total = max(int(collection.estimated_document_count()), 1)
            step = max(total // limit, 1)
            cursor = (
                collection.find({"row_index": {"$mod": [step, 0]}}, {"_id": 0, "pi1m_record_id": 1, "row_index": 1, "smiles": 1, "sa_score": 1})
                .sort([("row_index", 1)])
                .limit(limit)
            )
            return [dict(item) for item in cursor]
        except PyMongoError:
            return []

    def _encode_cursor(self, row: dict[str, Any], sort_by: str) -> str:
        payload = {"row_index": row.get("row_index") or row.get("sample_index") or 0}
        if sort_by == "sa_score":
            payload["sa_score"] = row.get("sa_score")
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _decode_cursor(self, cursor: str | None) -> dict[str, Any]:
        if not cursor:
            return {}
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            raise HTTPException(status_code=400, detail="无效游标")

    def _visual_point_from_row(self, row: dict[str, Any]) -> DataCatalogVisualSamplePoint:
        record_id = str(row.get("record_id") or row.get("pi1m_record_id") or "")
        row_index = row.get("row_index") or row.get("sample_index")
        smiles = row.get("smiles")
        x, y = self._stable_xy(str(smiles or record_id))
        return DataCatalogVisualSamplePoint(
            record_id=record_id,
            row_index=int(row_index) if row_index is not None else None,
            x=x,
            y=y,
            sa_score=self._to_float(row.get("sa_score")),
            smiles=str(smiles) if smiles else None,
        )

    def _stable_xy(self, value: str) -> tuple[float, float]:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        x = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
        y = int.from_bytes(digest[4:8], "big") / 0xFFFFFFFF
        return round((x * 2) - 1, 6), round((y * 2) - 1, 6)

    def _smiles_hash(self, value: str) -> str:
        return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()

    def _to_float(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(number) or math.isinf(number):
            return None
        return number

    def _histogram(self, values: list[float], bins: int = 12) -> list[dict[str, Any]]:
        if not values:
            return []
        lower = min(values)
        upper = max(values)
        if lower == upper:
            return [{"start": lower, "end": upper, "count": len(values)}]
        width = (upper - lower) / bins
        counts = [0 for _ in range(bins)]
        for value in values:
            index = min(int((value - lower) / width), bins - 1)
            counts[index] += 1
        return [
            {"start": round(lower + width * index, 4), "end": round(lower + width * (index + 1), 4), "count": count}
            for index, count in enumerate(counts)
        ]

    def _dataset_record_info(self, dataset_id: str, *, row_count: int | None = None) -> dict[str, Any]:
        collection_info = DATASET_RECORD_COLLECTIONS.get(dataset_id)
        if not collection_info:
            return {"record_collection_key": None, "record_count": None, "record_mode": "metadata_only"}
        collection_key, configured_mode = collection_info
        definition = COLLECTION_DEFINITION_BY_NAME.get(collection_key)
        if not definition:
            return {"record_collection_key": None, "record_count": None, "record_mode": "metadata_only"}
        count: int | None = None
        if not settings.require_mongodb:
            count = len(demo_store.load().get(collection_key, []))
        elif settings.data_asset_mongodb_uri:
            try:
                db = self._database_for_definition(definition)
                if definition.collection_name == MATERIAL_COLLECTION_NAME:
                    count = int(db[definition.collection_name].count_documents({"dataset.dataset_code": dataset_id}))
                else:
                    count = int(db[definition.collection_name].estimated_document_count())
            except PyMongoError:
                count = None
        mode = configured_mode if count else "metadata_only"
        if dataset_id == "pi1m_v2" and count is not None and row_count and count < row_count:
            mode = "sample"
        return {"record_collection_key": collection_key, "record_count": count, "record_mode": mode}

    def _load_dataset_definitions(self) -> dict[str, dict[str, Any]]:
        """Load dataset metadata from poly_data, falling back to built-in definitions."""
        if not settings.require_mongodb or not settings.data_asset_mongodb_uri:
            return DATASET_DEFINITIONS
        try:
            db = get_data_asset_database()
            dataset_docs = list(db["datasets"].find({}, {"_id": 0}))
            if not dataset_docs:
                return DATASET_DEFINITIONS
            field_docs = list(db["dataset_fields"].find({}, {"_id": 0}))
        except PyMongoError:
            return DATASET_DEFINITIONS

        fields_by_dataset: dict[str, list[tuple[Any, ...]]] = {}
        for field in field_docs:
            dataset_id = str(field.get("dataset_id") or "")
            if not dataset_id:
                continue
            fields_by_dataset.setdefault(dataset_id, []).append(
                (
                    field.get("raw_name") or field.get("canonical_name") or "",
                    field.get("canonical_name") or field.get("raw_name") or "",
                    field.get("label") or field.get("canonical_name") or field.get("raw_name") or "",
                    field.get("non_empty_count"),
                    field.get("total_count"),
                    field.get("example"),
                )
            )

        loaded: dict[str, dict[str, Any]] = {}
        ordered_ids = [*DATASET_DEFINITIONS.keys(), *[str(doc.get("dataset_id")) for doc in dataset_docs]]
        docs_by_id = {str(doc.get("dataset_id")): doc for doc in dataset_docs if doc.get("dataset_id")}
        for dataset_id in dict.fromkeys(ordered_ids):
            doc = docs_by_id.get(dataset_id)
            fallback = DATASET_DEFINITIONS.get(dataset_id, {})
            if not doc and not fallback:
                continue
            doc = doc or {}
            loaded[dataset_id] = {
                "display_name": doc.get("display_name") or fallback.get("display_name") or dataset_id,
                "source_category": doc.get("source_category") or fallback.get("source_category") or "材料数据",
                "confidence_label": doc.get("confidence_label") or fallback.get("confidence_label") or "已登记数据",
                "description": doc.get("description") or fallback.get("description") or "",
                "row_count": doc.get("row_count") if doc.get("row_count") is not None else fallback.get("row_count", 0),
                "column_count": doc.get("column_count") if doc.get("column_count") is not None else fallback.get("column_count", 0),
                "storage_prefix": doc.get("storage_prefix") or fallback.get("storage_prefix") or f"{CANONICAL_ROOT}{dataset_id}/",
                "field_summaries": fields_by_dataset.get(dataset_id) or fallback.get("field_summaries", []),
            }
        return loaded or DATASET_DEFINITIONS

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
            return bool(
                get_data_asset_database()[MATERIAL_COLLECTION_NAME].count_documents(
                    {"polymer_record_id": material_record_id}, limit=1
                )
            )
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
            return self._relationships_from_rows(collections)
        return self._relationships_from_mongo()

    def _relationships_from_rows(self, collections: dict[str, list[dict[str, Any]]]) -> DataCatalogRelationshipsData:
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

    def _relationships_from_mongo(self) -> DataCatalogRelationshipsData:
        business = get_database()
        data_asset_db = get_data_asset_database() if settings.data_asset_mongodb_uri else None

        def count(collection_name: str, *, asset: bool = False) -> int:
            try:
                db = data_asset_db if asset else business
                if db is None:
                    return 0
                return int(db[collection_name].estimated_document_count())
            except PyMongoError:
                return 0

        material_count = count(MATERIAL_COLLECTION_NAME, asset=True)
        computation_count = count("computation_runs")
        artifact_count = count("computation_artifacts")
        research_count = count("research_runs")
        algorithm_count = count("algorithm_runs")
        report_count = count("report_jobs")
        report_artifact_count = count("report_artifacts")

        def distinct_values(collection_name: str, field: str) -> list[Any]:
            try:
                return [value for value in business[collection_name].distinct(field) if value]
            except PyMongoError:
                return []

        def linked_by_membership(source_ids: list[Any], collection_name: str, field: str, *, asset: bool = False) -> int:
            if not source_ids:
                return 0
            try:
                db = data_asset_db if asset else business
                if db is None:
                    return 0
                return int(db[collection_name].count_documents({field: {"$in": source_ids}}))
            except PyMongoError:
                return 0

        computation_material_ids = distinct_values("computation_runs", "material_record_id")
        computation_ids = distinct_values("computation_runs", "run_id")
        research_ids = distinct_values("research_runs", "run_id")
        report_ids = distinct_values("report_jobs", "report_id")

        material_links = linked_by_membership(
            computation_material_ids,
            MATERIAL_COLLECTION_NAME,
            "polymer_record_id",
            asset=True,
        )
        computation_artifact_links = linked_by_membership(computation_ids, "computation_artifacts", "run_id")
        research_algorithm_links = linked_by_membership(research_ids, "algorithm_runs", "research_run_id")
        report_artifact_links = linked_by_membership(report_ids, "report_artifacts", "report_id")

        node_specs = [
            ("materials", "高分子材料", material_count),
            ("computations", "计算任务", computation_count),
            ("computation_artifacts", "计算产物", artifact_count),
            ("research_runs", "ResearchRun", research_count),
            ("algorithm_runs", "AlgorithmRun", algorithm_count),
            ("report_jobs", "报告任务", report_count),
            ("report_artifacts", "报告产物", report_artifact_count),
        ]
        nodes = [
            DataCatalogRelationshipNode(node_id=node_id, label=label, record_count=record_count)
            for node_id, label, record_count in node_specs
        ]

        def edge(source: str, target: str, linked: int, target_total: int, source_field: str, target_field: str):
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
                edge("materials", "computations", material_links, computation_count, "polymer_record_id", "material_record_id"),
                edge("computations", "computation_artifacts", computation_artifact_links, artifact_count, "run_id", "run_id"),
                edge("research_runs", "algorithm_runs", research_algorithm_links, algorithm_count, "run_id", "research_run_id"),
                edge("report_jobs", "report_artifacts", report_artifact_links, report_artifact_count, "report_id", "report_id"),
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

        if definition.data_domain == "pi1m_samples":
            row_start = ((page - 1) * page_size) + 1 if page > 1 and not keyword else None
            row_end = page * page_size if page > 1 and not keyword else None
            rows = self._load_mongo_pi1m_dataset_rows(
                cursor=None,
                page_size=page_size,
                sort_by="row_index",
                sa_min=None,
                sa_max=None,
                keyword=keyword,
                row_start=row_start,
                row_end=row_end,
            )
            try:
                total = int(self._database_for_definition(definition)[definition.collection_name].estimated_document_count())
            except PyMongoError:
                total = len(rows)
            return rows[:page_size], total

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
        if definition.data_domain == "materials":
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
        if definition.data_domain == "radonpy_records":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "smiles",
                "source_file",
                "properties.density",
                "properties.static_dielectric_const",
                "properties.thermal_conductivity",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.data_domain == "pi1m_samples":
            clauses: list[dict[str, Any]] = [
                {"pi1m_record_id": normalized},
                {"smiles": normalized},
                {"smiles_hash": self._smiles_hash(normalized)},
            ]
            if normalized.isdigit():
                clauses.extend([{"row_index": int(normalized)}, {"sample_index": int(normalized)}])
            score = self._to_float(normalized)
            if score is not None:
                clauses.append({"sa_score": score})
            return {"$or": clauses}
        if definition.data_domain == "smipoly_monomers":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "dataset.dataset_name",
                "com_id",
                "molecular_formula",
                "smiles",
                "iupac_name",
                "source_file",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.data_domain == "polyuniverse_monomers":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "dataset.dataset_name",
                "monomer_class",
                "source_file",
                "smiles",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.data_domain == "md_allatom_files":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "dataset.dataset_name",
                "family",
                "remote_path",
                "object_key",
                "filename",
                "extension",
                "sync_status",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.data_domain == "md_allatom_diamines":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "diamine_id",
                "cas",
                "name",
                "name_cn",
                "abbr",
                "smiles",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.data_domain == "md_allatom_dianhydrides":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "dianhydride_id",
                "cas",
                "name",
                "name_cn",
                "abbr",
                "smiles",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.data_domain == "md_allatom_carbon_results":
            field_names = [
                *definition.primary_keys,
                "dataset.dataset_id",
                "family",
                "diamine_id",
                "dianhydride_id",
                "dp",
                "temperature",
                "data_file",
                "out_file",
            ]
            return {"$or": [{field: {"$regex": escaped, "$options": "i"}} for field in field_names]}
        if definition.search_fields:
            field_names = list(
                dict.fromkeys(
                    [
                        *definition.primary_keys,
                        "dataset.dataset_id",
                        "dataset.dataset_name",
                        *definition.search_fields,
                    ]
                )
            )
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
        if definition.data_domain == "materials":
            title = self._material_title(row) or record_id or definition.display_name
            subtitle = self._material_subtitle(row)
            preview_fields = self._material_preview_fields(row)
            created_at = self._nested_value(row, "provenance.created_at")
            updated_at = self._nested_value(row, "provenance.updated_at")
        elif definition.data_domain == "radonpy_records":
            title = str(row.get("smiles") or record_id or definition.display_name)
            subtitle = f"RadonPy PI1070 · {record_id}" if record_id else "RadonPy PI1070"
            preview_fields = self._dataset_record_preview_fields(row, ["density", "static_dielectric_const", "thermal_conductivity"])
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "pi1m_samples":
            title = str(row.get("smiles") or record_id or definition.display_name)
            subtitle = f"PI1M v2 · {record_id}" if record_id else "PI1M v2"
            preview_fields = self._dataset_record_preview_fields(row, ["sa_score", "row_index", "sample_index"])
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "smipoly_monomers":
            title = str(row.get("iupac_name") or row.get("smiles") or record_id or definition.display_name)
            subtitle = f"SMiPoly · {row.get('com_id') or record_id}" if record_id else "SMiPoly"
            preview_fields = self._dataset_record_preview_fields(
                row,
                ["com_id", "smiles", "molecular_formula", "molecular_weight", "source_file"],
            )
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "polyuniverse_monomers":
            title = str(row.get("smiles") or record_id or definition.display_name)
            monomer_class = row.get("monomer_class") or "candidate_monomer"
            subtitle = f"PolyUniverse · {monomer_class} · {row.get('source_file') or ''}".strip(" ·")
            preview_fields = self._dataset_record_preview_fields(
                row,
                ["monomer_class", "source_file", "row_index"],
            )
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "md_allatom_files":
            title = str(row.get("filename") or record_id or definition.display_name)
            subtitle = f"MD-AllAtom · {row.get('family') or '-'} · {row.get('extension') or ''}".strip(" ·")
            preview_fields = self._dataset_record_preview_fields(
                row,
                ["family", "extension", "size_bytes", "sync_status", "object_key"],
            )
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "md_allatom_diamines":
            title = str(row.get("abbr") or row.get("name") or row.get("smiles") or record_id or definition.display_name)
            subtitle = f"MD-AllAtom 二胺 · {row.get('diamine_id') or record_id}"
            preview_fields = self._dataset_record_preview_fields(row, ["diamine_id", "cas", "name_cn", "smiles"])
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "md_allatom_dianhydrides":
            title = str(row.get("abbr") or row.get("name") or row.get("smiles") or record_id or definition.display_name)
            subtitle = f"MD-AllAtom 二酐 · {row.get('dianhydride_id') or record_id}"
            preview_fields = self._dataset_record_preview_fields(row, ["dianhydride_id", "cas", "name_cn", "smiles"])
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif definition.data_domain == "md_allatom_carbon_results":
            title = f"{row.get('family') or 'C'} · diamine {row.get('diamine_id') or '-'} / dianhydride {row.get('dianhydride_id') or '-'}"
            subtitle = f"dp {row.get('dp') or '-'} · {row.get('temperature') or '-'} K · {record_id}"
            preview_fields = self._dataset_record_preview_fields(
                row,
                ["diamine_id", "dianhydride_id", "dp", "temperature", "e2e_mean", "rg_mean", "persist_len_mean"],
            )
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
        elif row.get("dataset") and definition.source_id == MATERIAL_SOURCE_ID:
            title = str(row.get("title") or record_id or definition.display_name)
            dataset = row.get("dataset") if isinstance(row.get("dataset"), dict) else {}
            subtitle = f"{dataset.get('dataset_name') or definition.display_name} · {row.get('source_file') or ''}".strip(" ·")
            preview_fields = self._preview_fields(row, definition.primary_keys)
            created_at = row.get("created_at")
            updated_at = row.get("updated_at")
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

    def _dataset_record_preview_fields(self, row: dict[str, Any], preferred_fields: list[str]) -> dict[str, Any]:
        preview: dict[str, Any] = {}
        dataset = row.get("dataset") if isinstance(row.get("dataset"), dict) else {}
        properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        if dataset.get("dataset_name") or dataset.get("dataset_id"):
            preview["dataset"] = dataset.get("dataset_name") or dataset.get("dataset_id")
        if row.get("smiles"):
            preview["smiles"] = row.get("smiles")
        for field in preferred_fields:
            value = row.get(field) if field in row else properties.get(field)
            if value is not None:
                preview[field] = value
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
        if definition.data_domain == "materials":
            return "provenance.created_at"
        if definition.data_domain == "pi1m_samples":
            return "row_index"
        if definition.data_domain in {
            "radonpy_records",
            "smipoly_monomers",
            "polyuniverse_monomers",
            "md_allatom_files",
            "md_allatom_diamines",
            "md_allatom_dianhydrides",
            "md_allatom_carbon_results",
            *[spec.data_domain for spec in EXTRA_DATASET_SPECS],
        }:
            return definition.primary_keys[0] if definition.primary_keys else "created_at"
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
            legacy = self._head_object(mapping.legacy_key) if mapping.legacy_key else None
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
