"""Platform capability status endpoints."""

from __future__ import annotations

from app.schemas.capabilities import CapabilityStatusData
from app.schemas.common import ApiResponse
from app.services.capability_service import CapabilityService

from fastapi import APIRouter


router = APIRouter(prefix="/capabilities", tags=["capabilities"])
service = CapabilityService()


@router.get("", response_model=ApiResponse[CapabilityStatusData])
def list_capabilities() -> ApiResponse[CapabilityStatusData]:
    """Return product-facing capability readiness across modules."""
    return ApiResponse(data=service.get_capabilities())
