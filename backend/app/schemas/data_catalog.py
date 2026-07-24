"""数据目录响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CatalogStatus = Literal["ready", "degraded", "not_configured"]
DatasetRecordMode = Literal["full", "sample", "metadata_only"]
DatasetRecordSortBy = Literal["row_index", "sa_score"]


class DataCatalogObjectInfo(BaseModel):
    """MinIO 对象状态。"""

    object_key: str
    role: str
    exists: bool = False
    size_bytes: int | None = None
    last_modified: datetime | None = None
    legacy_object_key: str | None = None
    legacy_exists: bool = False


class DataCatalogFieldSummary(BaseModel):
    """字段摘要。"""

    raw_name: str
    canonical_name: str
    label: str
    non_empty_count: int | None = None
    total_count: int | None = None
    example: str | None = None


class DataCatalogDataset(BaseModel):
    """数据集目录项。"""

    dataset_id: str
    display_name: str
    source_category: str
    confidence_label: str
    description: str
    row_count: int
    column_count: int
    storage_prefix: str
    record_collection_key: str | None = None
    record_count: int | None = None
    record_mode: DatasetRecordMode = "metadata_only"
    objects: list[DataCatalogObjectInfo] = Field(default_factory=list)
    field_summaries: list[DataCatalogFieldSummary] = Field(default_factory=list)


class DataCatalogCollectionSummary(BaseModel):
    """Mongo 集合摘要。"""

    collection_key: str
    collection_name: str
    source_id: str = "poly_agent"
    database: str | None = None
    display_name: str
    group: str
    data_domain: str | None = None
    description: str
    count: int | None = None
    status: CatalogStatus = "not_configured"
    primary_keys: list[str] = Field(default_factory=list)
    sample_fields: list[str] = Field(default_factory=list)
    analysis_facets: list[str] = Field(default_factory=list)
    schema_summary: dict[str, Any] = Field(default_factory=dict)


class DataCatalogSourceStatus(BaseModel):
    """数据源状态。"""

    source: str
    status: CatalogStatus
    detail: str
    bucket: str | None = None
    database: str | None = None


class DataCatalogOverviewData(BaseModel):
    """数据目录总览。"""

    status: CatalogStatus
    bucket: str
    dataset_count: int
    object_count: int
    total_rows: int
    total_columns: int
    material_record_count: int | None = None
    canonical_root: str
    legacy_objects: list[str] = Field(default_factory=list)
    sources: list[DataCatalogSourceStatus] = Field(default_factory=list)
    relationship_notes: list[str] = Field(default_factory=list)


class DataCatalogDatasetListData(BaseModel):
    """数据集列表响应。"""

    items: list[DataCatalogDataset]
    legacy_objects: list[str] = Field(default_factory=list)


class DataCatalogMongoCollectionListData(BaseModel):
    """Mongo 集合列表响应。"""

    items: list[DataCatalogCollectionSummary]
    total: int


class DataCatalogRelationshipNode(BaseModel):
    node_id: str
    label: str
    record_count: int


class DataCatalogRelationshipEdge(BaseModel):
    source: str
    target: str
    linked_count: int
    target_coverage: float = Field(ge=0, le=1)
    source_field: str
    target_field: str


class DataCatalogRelationshipsData(BaseModel):
    nodes: list[DataCatalogRelationshipNode]
    edges: list[DataCatalogRelationshipEdge]
    generated_at: datetime
    notes: list[str] = Field(default_factory=list)


class DataCatalogRecordSummary(BaseModel):
    """Mongo 集合记录摘要。"""

    record_id: str
    primary_key: dict[str, Any] = Field(default_factory=dict)
    title: str
    subtitle: str | None = None
    status: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    preview_fields: dict[str, Any] = Field(default_factory=dict)


class DataCatalogCollectionRecordListData(BaseModel):
    """Mongo 集合记录分页响应。"""

    collection_key: str
    collection_name: str
    source_id: str = "poly_agent"
    database: str | None = None
    primary_keys: list[str] = Field(default_factory=list)
    items: list[DataCatalogRecordSummary]
    page: int
    page_size: int
    total: int


class DataCatalogCollectionRecordDetailData(BaseModel):
    """Mongo 集合单条记录详情响应。"""

    collection_key: str
    collection_name: str
    source_id: str = "poly_agent"
    database: str | None = None
    record_id: str
    primary_key: dict[str, Any] = Field(default_factory=dict)
    title: str
    subtitle: str | None = None
    status: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    document: dict[str, Any] = Field(default_factory=dict)


class DataCatalogDatasetImportStatus(BaseModel):
    """数据集最近一次导入状态。"""

    job_id: str | None = None
    status: str = "unknown"
    imported_count: int | None = None
    failed_count: int | None = None
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None
    throughput_rows_per_second: float | None = None
    error: str | None = None


class DataCatalogHistogramBin(BaseModel):
    """数值字段直方图区间。"""

    start: float
    end: float
    count: int


class DataCatalogDatasetProfileData(BaseModel):
    """数据集画像与导入健康。"""

    dataset_id: str
    row_count: int
    record_count: int
    coverage_percent: float
    record_mode: DatasetRecordMode
    field_completeness: list[DataCatalogFieldSummary] = Field(default_factory=list)
    sa_score_histogram: list[DataCatalogHistogramBin] = Field(default_factory=list)
    duplicate_smiles_count: int | None = None
    unique_smiles_count: int | None = None
    numeric_histograms: dict[str, list[DataCatalogHistogramBin]] = Field(default_factory=dict)
    category_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    analysis_samples: list[dict[str, Any]] = Field(default_factory=list)
    asset_coverage: dict[str, Any] = Field(default_factory=dict)
    import_status: DataCatalogDatasetImportStatus = Field(default_factory=DataCatalogDatasetImportStatus)


class DataCatalogDatasetRecordListData(BaseModel):
    """数据集游标分页记录。"""

    dataset_id: str
    collection_key: str
    items: list[DataCatalogRecordSummary]
    page_size: int
    next_cursor: str | None = None
    total: int | None = None


class DataCatalogVisualSamplePoint(BaseModel):
    """前端可视化抽样点。"""

    record_id: str
    row_index: int | None = None
    x: float
    y: float
    sa_score: float | None = None
    smiles: str | None = None


class DataCatalogDatasetVisualSamplesData(BaseModel):
    """数据集可视化抽样数据。"""

    dataset_id: str
    sample_count: int
    total: int | None = None
    points: list[DataCatalogVisualSamplePoint] = Field(default_factory=list)
