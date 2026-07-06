"""计算任务 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.core.auth import get_current_user, require_admin
from app.schemas.common import ApiResponse
from app.schemas.computation import (
    ArtifactListData,
    ArtifactPreviewData,
    ArtifactStructureData,
    ArtifactSpectrumData,
    AuditEventListData,
    ComputationArtifact,
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


def _access_user_id(current_user: dict[str, str] | None) -> str | None:
    """解析用于数据权限过滤的用户 ID。"""
    return current_user["user_id"] if current_user else None


def _is_admin(current_user: dict[str, str] | None) -> bool:
    """判断当前用户是否管理员。"""
    return bool(current_user and current_user.get("role") == "admin")


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
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationListData]:
    """查询计算任务列表。"""
    data = service.list_runs(
        status=status,
        workflow_type=workflow_type,
        engine=engine,
        keyword=keyword,
        page=page,
        page_size=page_size,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/computations/{run_id}", response_model=ApiResponse[ComputationRun])
def get_computation(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationRun]:
    """查询计算任务详情。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_run(run_id, actor_user_id=_access_user_id(current_user), is_admin=_is_admin(current_user)),
    )


@router.post("/computations/{run_id}/cancel", response_model=ApiResponse[ComputationRun])
def cancel_computation(
    run_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationRun]:
    """取消计算任务。"""
    data = service.cancel_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/computations/{run_id}/retry", response_model=ApiResponse[ComputationCreateData])
def retry_computation(
    run_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationCreateData]:
    """重试计算任务。"""
    data = service.retry_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/computations/{run_id}/fail-stale", response_model=ApiResponse[ComputationRun])
def fail_stale_computation(
    run_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
    _admin: None = Depends(require_admin),
) -> ApiResponse[ComputationRun]:
    """强制将一个 stuck running 任务标记为 failed（仅管理员可操作）。"""
    data = service.force_fail_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=True,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/computations/{run_id}/artifacts", response_model=ApiResponse[ArtifactListData])
def list_computation_artifacts(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactListData]:
    """查询任务 artifacts。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=ArtifactListData(
            items=service.list_artifacts(
                run_id,
                actor_user_id=_access_user_id(current_user),
                is_admin=_is_admin(current_user),
            )
        ),
    )


@router.get("/artifacts/{artifact_id}", response_model=ApiResponse[ComputationArtifact])
def get_artifact(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationArtifact]:
    """查询 artifact 元数据。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_artifact(
            artifact_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.get("/artifacts/{artifact_id}/preview", response_model=ApiResponse[ArtifactPreviewData])
def preview_artifact(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactPreviewData]:
    """预览 artifact。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.preview_artifact(
            artifact_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.get("/artifacts/{artifact_id}/structure", response_model=ApiResponse[ArtifactStructureData])
def get_artifact_structure(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactStructureData]:
    """读取结构 artifact。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_artifact_structure(
            artifact_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.get("/artifacts/{artifact_id}/spectrum", response_model=ApiResponse[ArtifactSpectrumData])
def get_artifact_spectrum(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactSpectrumData]:
    """读取光谱/指标 artifact。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_artifact_spectrum(
            artifact_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> FileResponse:
    """下载 artifact 文件。"""
    artifact = service.get_artifact(
        artifact_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    path = service.resolve_artifact_path(artifact)
    service.audit_artifact_download(
        artifact,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return FileResponse(path=path, media_type=artifact.mime_type, filename=artifact.name)


@router.get("/audit-events", response_model=ApiResponse[AuditEventListData])
def list_audit_events(
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AuditEventListData]:
    """查询审计事件。"""
    data = service.list_audit_events(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)
