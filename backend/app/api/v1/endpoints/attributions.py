"""来源、引用与机构标注 API。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.attribution import ModuleAttribution
from app.schemas.attribution import ModuleAttributionListData
from app.schemas.common import ApiResponse
from app.services.attribution_service import AttributionService

router = APIRouter(prefix="/attributions", tags=["来源与引用标注"])
service = AttributionService()


@router.get("/modules", response_model=ApiResponse[ModuleAttributionListData])
def list_module_attributions() -> ApiResponse[ModuleAttributionListData]:
    """列出系统模块来源标注。"""
    return ApiResponse(code=0, message="ok", data=service.list_modules())


@router.get("/modules/{module_id}", response_model=ApiResponse[ModuleAttribution])
def get_module_attribution(module_id: str) -> ApiResponse[ModuleAttribution]:
    """获取单个系统模块来源标注。"""
    return ApiResponse(code=0, message="ok", data=service.get_module(module_id))
