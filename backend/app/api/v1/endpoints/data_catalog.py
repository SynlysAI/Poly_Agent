"""数据目录 API。"""

from __future__ import annotations

import urllib.parse
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.data_catalog import (
    DataCatalogApiCatalogData,
    DataCatalogCollectionRecordDetailData,
    DataCatalogCollectionRecordListData,
    DataCatalogDatasetProfileData,
    DataCatalogDatasetRecordListData,
    DataCatalogDatasetVisualSamplesData,
    DataCatalogMdAllatomCFileListData,
    DataCatalogDatasetListData,
    DataCatalogMinioObjectListData,
    DataCatalogMongoCollectionListData,
    DataCatalogCollectionAnalysisData,
    DataCatalogOverviewData,
    DataCatalogRelationshipsData,
)
from app.services.data_catalog_service import DataCatalogService


router = APIRouter(prefix="/data-catalog", tags=["data-catalog"], dependencies=[Depends(get_current_user)])


def _iter_download_body(body: Any) -> Iterator[bytes]:
    """Yield a binary body in bounded chunks and close it when possible."""
    try:
        while True:
            chunk = body.read(1024 * 1024)
            if not chunk:
                break
            yield chunk
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()


def _content_disposition(filename: str) -> str:
    quoted = urllib.parse.quote(filename)
    return f"attachment; filename*=UTF-8''{quoted}"


@router.get("/overview", response_model=ApiResponse[DataCatalogOverviewData])
def get_data_catalog_overview() -> ApiResponse[DataCatalogOverviewData]:
    """查询数据目录总览。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().get_overview())


@router.get("/api-catalog", response_model=ApiResponse[DataCatalogApiCatalogData])
def get_data_catalog_api_catalog() -> ApiResponse[DataCatalogApiCatalogData]:
    """查询数据调用 API 清单。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().get_api_catalog())


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
) -> ApiResponse[DataCatalogDatasetRecordListData]:
    """游标分页查询数据集记录。"""
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


@router.get("/minio-objects", response_model=ApiResponse[DataCatalogMinioObjectListData])
def list_data_catalog_minio_objects(
    dataset_id: str | None = Query(default=None, max_length=120),
) -> ApiResponse[DataCatalogMinioObjectListData]:
    """查询 MinIO 白名单逻辑对象。"""
    return ApiResponse(code=0, message="ok", data=DataCatalogService().list_minio_objects(dataset_id=dataset_id))


@router.get("/md-allatom/c-files/{folder}", response_model=ApiResponse[DataCatalogMdAllatomCFileListData])
def list_data_catalog_md_allatom_c_files(
    folder: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=160),
) -> ApiResponse[DataCatalogMdAllatomCFileListData]:
    """按 C 类目录查询 MD-AllAtom 已入库原始文件。"""
    data = DataCatalogService().list_md_allatom_c_files(
        folder,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/md-allatom/c-files/{folder}/{filename}/download")
def download_data_catalog_md_allatom_c_file(folder: str, filename: str) -> StreamingResponse:
    """通过后端代理下载 MD-AllAtom C 类已入库原始文件。"""
    download = DataCatalogService().open_md_allatom_c_file(folder, filename)
    headers = {
        "Content-Disposition": _content_disposition(download.asset.filename),
        "X-Content-Type-Options": "nosniff",
    }
    if download.asset.size_bytes is not None:
        headers["Content-Length"] = str(download.asset.size_bytes)
    return StreamingResponse(
        _iter_download_body(download.body),
        media_type=download.asset.mime_type,
        headers=headers,
    )


@router.get("/minio-objects/{asset_id}/download")
def download_data_catalog_minio_object(asset_id: str) -> StreamingResponse:
    """通过后端代理下载 MinIO 白名单逻辑对象。"""
    download = DataCatalogService().open_minio_object(asset_id)
    headers = {
        "Content-Disposition": _content_disposition(download.asset.filename),
        "X-Content-Type-Options": "nosniff",
    }
    if download.asset.size_bytes is not None:
        headers["Content-Length"] = str(download.asset.size_bytes)
    return StreamingResponse(
        _iter_download_body(download.body),
        media_type=download.asset.mime_type,
        headers=headers,
    )


@router.get(
    "/mongo-collections/{collection_name}/records",
    response_model=ApiResponse[DataCatalogCollectionRecordListData],
)
def list_data_catalog_mongo_collection_records(
    collection_name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=120),
    use_cursor: bool = Query(default=False),
    cursor: str | None = Query(default=None, max_length=512),
) -> ApiResponse[DataCatalogCollectionRecordListData]:
    """分页查询白名单 Mongo 集合的记录摘要。"""
    data = DataCatalogService().list_mongo_collection_records(
        collection_name,
        page=page,
        page_size=page_size,
        keyword=keyword,
        use_cursor=use_cursor,
        cursor=cursor,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/mongo-collections/{collection_name}/analysis",
    response_model=ApiResponse[DataCatalogCollectionAnalysisData],
)
def get_data_catalog_mongo_collection_analysis(
    collection_name: str,
    sample_size: int = Query(default=1000, ge=200, le=5000),
    refresh: bool = Query(default=False),
) -> ApiResponse[DataCatalogCollectionAnalysisData]:
    """查询白名单 Mongo 集合的受控画像和领域分析。"""
    data = DataCatalogService().get_collection_analysis(
        collection_name,
        sample_size=sample_size,
        refresh=refresh,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/mongo-collections/{collection_name}/records/{record_id}",
    response_model=ApiResponse[DataCatalogCollectionRecordDetailData],
)
def get_data_catalog_mongo_collection_record(
    collection_name: str,
    record_id: str,
) -> ApiResponse[DataCatalogCollectionRecordDetailData]:
    """查询白名单 Mongo 集合的单条脱敏记录详情。"""
    data = DataCatalogService().get_mongo_collection_record(collection_name, record_id)
    return ApiResponse(code=0, message="ok", data=data)
