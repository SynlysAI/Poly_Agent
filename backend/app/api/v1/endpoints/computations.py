"""计算任务 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from app.core.auth import get_current_user, require_admin
from app.core.config import settings
from app.schemas.common import ApiResponse
from app.schemas.computation import (
    ArtifactListResponseData,
    ArtifactPreviewResponseData,
    ArtifactStructureResponseData,
    ArtifactSpectrumResponseData,
    AuditEventListData,
    ComputationArtifact,
    ComputationArtifactResponse,
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


def _artifact_download_url(artifact_id: str) -> str:
    """生成受控 artifact 下载 URL。"""
    return f"{settings.api_prefix}/artifacts/{artifact_id}/download"


def _public_artifact(artifact: ComputationArtifact) -> ComputationArtifactResponse:
    """转换为不暴露本地 storage_uri 的 artifact 响应。"""
    return ComputationArtifactResponse(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        step_key=artifact.step_key,
        artifact_type=artifact.artifact_type,
        name=artifact.name,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        checksum_sha256=artifact.checksum_sha256,
        download_url=_artifact_download_url(artifact.artifact_id),
        parser_name=artifact.parser_name,
        parser_version=artifact.parser_version,
        metadata=artifact.metadata,
        created_at=artifact.created_at,
    )


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


@router.get("/computations/{run_id}/artifacts", response_model=ApiResponse[ArtifactListResponseData])
def list_computation_artifacts(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactListResponseData]:
    """查询任务 artifacts。"""
    artifacts = service.list_artifacts(
        run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(
        code=0,
        message="ok",
        data=ArtifactListResponseData(items=[_public_artifact(item) for item in artifacts]),
    )


@router.get("/artifacts/{artifact_id}", response_model=ApiResponse[ComputationArtifactResponse])
def get_artifact(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ComputationArtifactResponse]:
    """查询 artifact 元数据。"""
    artifact = service.get_artifact(
        artifact_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(
        code=0,
        message="ok",
        data=_public_artifact(artifact),
    )


@router.get("/artifacts/{artifact_id}/preview", response_model=ApiResponse[ArtifactPreviewResponseData])
def preview_artifact(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactPreviewResponseData]:
    """预览 artifact。"""
    preview = service.preview_artifact(
        artifact_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    data = ArtifactPreviewResponseData(artifact=_public_artifact(preview.artifact), preview=preview.preview)
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/artifacts/{artifact_id}/structure", response_model=ApiResponse[ArtifactStructureResponseData])
def get_artifact_structure(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactStructureResponseData]:
    """读取结构 artifact。"""
    structure = service.get_artifact_structure(
        artifact_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    data = ArtifactStructureResponseData(
        artifact=_public_artifact(structure.artifact),
        structure=structure.structure,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/artifacts/{artifact_id}/spectrum", response_model=ApiResponse[ArtifactSpectrumResponseData])
def get_artifact_spectrum(
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactSpectrumResponseData]:
    """读取光谱/指标 artifact。"""
    spectrum = service.get_artifact_spectrum(
        artifact_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    data = ArtifactSpectrumResponseData(
        artifact=_public_artifact(spectrum.artifact),
        spectrum=spectrum.spectrum,
    )
    return ApiResponse(code=0, message="ok", data=data)


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
