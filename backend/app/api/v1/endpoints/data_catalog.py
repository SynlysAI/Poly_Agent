"""数据目录 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.data_catalog import (
    DataCatalogCollectionRecordDetailData,
    DataCatalogCollectionRecordListData,
    DataCatalogDatasetProfileData,
    DataCatalogDatasetRecordListData,
    DataCatalogDatasetVisualSamplesData,
    DataCatalogDatasetListData,
    DataCatalogMongoCollectionListData,
    DataCatalogOverviewData,
    DataCatalogRelationshipsData,
)
from app.services.data_catalog_service import DataCatalogService


router = APIRouter(prefix="/data-catalog", tags=["data-catalog"])


@router.get("/overview", response_model=ApiResponse[DataCatalogOverviewData])
def get_data_catalog_overview() -> ApiResponse[DataCatalogOverviewData]:
    """查询数据目录总览。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().get_overview())


@router.get("/datasets", response_model=ApiResponse[DataCatalogDatasetListData])
def list_data_catalog_datasets() -> ApiResponse[DataCatalogDatasetListData]:
    """查询数据集目录。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().list_datasets())


@router.get("/datasets/{dataset_id}/profile", response_model=ApiResponse[DataCatalogDatasetProfileData])
def get_data_catalog_dataset_profile(dataset_id: str) -> ApiResponse[DataCatalogDatasetProfileData]:
    """查询单个数据集画像与导入健康。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().get_dataset_profile(dataset_id))


@router.get("/datasets/{dataset_id}/visual-samples", response_model=ApiResponse[DataCatalogDatasetVisualSamplesData])
def get_data_catalog_dataset_visual_samples(
    dataset_id: str,
    limit: int = Query(default=5000, ge=100, le=20000),
) -> ApiResponse[DataCatalogDatasetVisualSamplesData]:
    """查询数据集可视化抽样点。"""
    data = DataCatalogService().get_dataset_visual_samples(dataset_id, limit=limit)
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/datasets/{dataset_id}/records", response_model=ApiResponse[DataCatalogDatasetRecordListData])
def list_data_catalog_dataset_records(
    dataset_id: str,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="row_index", pattern="^(row_index|sa_score)$"),
    sa_min: float | None = Query(default=None),
    sa_max: float | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=240),
    row_start: int | None = Query(default=None, ge=1),
    row_end: int | None = Query(default=None, ge=1),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[DataCatalogDatasetRecordListData]:
    """游标分页查询数据集记录。"""
    _require_record_drilldown_access(current_user)
    data = DataCatalogService().list_dataset_records(
        dataset_id,
        cursor=cursor,
        page_size=page_size,
        sort_by=sort_by,
        sa_min=sa_min,
        sa_max=sa_max,
        keyword=keyword,
        row_start=row_start,
        row_end=row_end,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/mongo-collections", response_model=ApiResponse[DataCatalogMongoCollectionListData])
def list_data_catalog_mongo_collections() -> ApiResponse[DataCatalogMongoCollectionListData]:
    """查询 MongoDB 结构化集合说明。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().list_mongo_collections())


@router.get("/relationships", response_model=ApiResponse[DataCatalogRelationshipsData])
def get_data_catalog_relationships() -> ApiResponse[DataCatalogRelationshipsData]:
    """Return verified cross-collection relationship counts."""
    return ApiResponse(data=DataCatalogService().get_relationships())


def _require_record_drilldown_access(current_user: dict[str, str] | None) -> None:
    """限制原始集合记录下钻为管理员只读能力。"""
    if current_user is not None and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")


@router.get(
    "/mongo-collections/{collection_name}/records",
    response_model=ApiResponse[DataCatalogCollectionRecordListData],
)
def list_data_catalog_mongo_collection_records(
    collection_name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=120),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[DataCatalogCollectionRecordListData]:
    """分页查询白名单 Mongo 集合的记录摘要。"""
    _require_record_drilldown_access(current_user)
    data = DataCatalogService().list_mongo_collection_records(
        collection_name,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/mongo-collections/{collection_name}/records/{record_id}",
    response_model=ApiResponse[DataCatalogCollectionRecordDetailData],
)
def get_data_catalog_mongo_collection_record(
    collection_name: str,
    record_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[DataCatalogCollectionRecordDetailData]:
    """查询白名单 Mongo 集合的单条脱敏记录详情。"""
    _require_record_drilldown_access(current_user)
    data = DataCatalogService().get_mongo_collection_record(collection_name, record_id)
    return ApiResponse(code=0, message="ok", data=data)
