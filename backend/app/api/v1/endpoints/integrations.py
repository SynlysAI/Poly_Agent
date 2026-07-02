"""外部集成状态 API。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header

from app.core.auth import get_current_user
from app.core.auth import require_admin
from app.schemas.common import ApiResponse
from app.schemas.integrations import ServiceIntegrationCheckData
from app.schemas.integrations import ServiceIntegrationConfig
from app.schemas.integrations import ServiceIntegrationListData
from app.schemas.integrations import ServiceIntegrationUpsertRequest
from app.services.integration_config_service import IntegrationConfigService
from app.services.integration_status_service import IntegrationStatusService


router = APIRouter(prefix="/integrations", tags=["integrations"])
service = IntegrationStatusService()
config_service = IntegrationConfigService()


@router.get("/status", response_model=ApiResponse[dict])
def get_integration_status() -> ApiResponse[dict]:
    """查询 MVP 集成状态。"""
    return ApiResponse(code=0, message="ok", data=service.get_status())


@router.get(
    "/configs",
    response_model=ApiResponse[ServiceIntegrationListData],
    dependencies=[Depends(require_admin)],
)
def list_integration_configs() -> ApiResponse[ServiceIntegrationListData]:
    """管理员查询外部集成配置摘要。"""
    return ApiResponse(code=0, message="ok", data=config_service.list_configs())


@router.put(
    "/configs/{service_key}",
    response_model=ApiResponse[ServiceIntegrationConfig],
    dependencies=[Depends(require_admin)],
)
def upsert_integration_config(
    service_key: str,
    payload: ServiceIntegrationUpsertRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> ApiResponse[ServiceIntegrationConfig]:
    """管理员创建或更新外部集成配置摘要。"""
    data = config_service.upsert_config(
        service_key,
        payload,
        actor_user_id=current_user["user_id"] if current_user else "system",
        request_id=request_id,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/configs/{service_key}/check",
    response_model=ApiResponse[ServiceIntegrationCheckData],
    dependencies=[Depends(require_admin)],
)
def check_integration_config(
    service_key: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> ApiResponse[ServiceIntegrationCheckData]:
    """管理员按持久化配置执行一次健康检查。"""
    data = config_service.check_config(
        service_key,
        actor_user_id=current_user["user_id"] if current_user else "system",
        request_id=request_id,
    )
    return ApiResponse(code=0, message="ok", data=data)
