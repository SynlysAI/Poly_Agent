"""计算任务 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.computation import (
    ArtifactListData,
    ArtifactPreviewData,
    ComputationCreateData,
    ComputationCreateRequest,
    ComputationListData,
    ComputationRun,
)
from app.services.computation_service import ComputationService


router = APIRouter(tags=["computations"])
service = ComputationService()


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    """解析当前操作人。"""
    return current_user["user_id"] if current_user else "demo_user"


def _request_id(request: Request) -> str | None:
    """读取请求追踪 ID。"""
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


@router.post("/computations", response_model=ApiResponse[ComputationCreateData])
def create_computation(
    payload: ComputationCreateRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationCreateData]:
    """创建计算任务。"""
    data = service.create_run(payload, actor_user_id=_actor_user_id(current_user), request_id=_request_id(request))
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/computations", response_model=ApiResponse[ComputationListData])
def list_computations(
    status: str | None = Query(default=None),
    workflow_type: str | None = Query(default=None),
    engine: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[ComputationListData]:
    """查询计算任务列表。"""
    data = service.list_runs(
        status=status,
        workflow_type=workflow_type,
        engine=engine,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/computations/{run_id}", response_model=ApiResponse[ComputationRun])
def get_computation(run_id: str) -> ApiResponse[ComputationRun]:
    """查询计算任务详情。"""
    return ApiResponse(code=0, message="ok", data=service.get_run(run_id))


@router.post("/computations/{run_id}/cancel", response_model=ApiResponse[ComputationRun])
def cancel_computation(
    run_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationRun]:
    """取消计算任务。"""
    data = service.cancel_run(run_id, actor_user_id=_actor_user_id(current_user), request_id=_request_id(request))
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/computations/{run_id}/retry", response_model=ApiResponse[ComputationCreateData])
def retry_computation(
    run_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationCreateData]:
    """重试计算任务。"""
    data = service.retry_run(run_id, actor_user_id=_actor_user_id(current_user), request_id=_request_id(request))
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/computations/{run_id}/artifacts", response_model=ApiResponse[ArtifactListData])
def list_computation_artifacts(run_id: str) -> ApiResponse[ArtifactListData]:
    """查询任务 artifacts。"""
    return ApiResponse(code=0, message="ok", data=ArtifactListData(items=service.list_artifacts(run_id)))


@router.get("/artifacts/{artifact_id}/preview", response_model=ApiResponse[ArtifactPreviewData])
def preview_artifact(artifact_id: str) -> ApiResponse[ArtifactPreviewData]:
    """预览 artifact。"""
    return ApiResponse(code=0, message="ok", data=service.preview_artifact(artifact_id))


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str) -> FileResponse:
    """下载 artifact 文件。"""
    artifact = service.get_artifact(artifact_id)
    path = service.resolve_artifact_path(artifact)
    return FileResponse(path=path, media_type=artifact.mime_type, filename=artifact.name)
