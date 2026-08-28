"""Platform capability status endpoints."""

from __future__ import annotations

from app.schemas.capabilities import CapabilityCatalogData, CapabilityStatusData
from app.schemas.common import ApiResponse
from app.core.auth import get_current_user, require_authenticated
from app.services.capability_service import CapabilityService
from app.services.capability_catalog_service import CapabilityCatalogService

from fastapi import APIRouter, Depends


router = APIRouter(prefix="/capabilities", tags=["capabilities"])
service = CapabilityService()
catalog_service = CapabilityCatalogService()


@router.get("", response_model=ApiResponse[CapabilityStatusData])
def list_capabilities() -> ApiResponse[CapabilityStatusData]:
    """Return product-facing capability readiness across modules."""
    return ApiResponse(data=service.get_capabilities())


@router.get(
    "/catalog",
    response_model=ApiResponse[CapabilityCatalogData],
    dependencies=[Depends(require_authenticated)],
)
def list_capability_catalog(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CapabilityCatalogData]:
    """返回当前用户可用的只读能力目录。

    Args:
        current_user: 当前登录用户；本地演示模式为空并按管理员处理。

    Returns:
        四个固定分组的能力中心目录。
    """
    return ApiResponse(code=0, message="ok", data=catalog_service.get_catalog(current_user))
