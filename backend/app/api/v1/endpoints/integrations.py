"""外部集成状态 API。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.services.integration_status_service import IntegrationStatusService


router = APIRouter(prefix="/integrations", tags=["integrations"])
service = IntegrationStatusService()


@router.get("/status", response_model=ApiResponse[dict])
def get_integration_status() -> ApiResponse[dict]:
    """查询 MVP 集成状态。"""
    return ApiResponse(code=0, message="ok", data=service.get_status())
