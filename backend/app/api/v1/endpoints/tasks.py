"""全局任务中心 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.tasks import GlobalTaskCenterData
from app.services.task_center_service import TaskCenterService


router = APIRouter(prefix="/tasks", tags=["tasks"])
service = TaskCenterService()


def _access_user_id(current_user: dict[str, str] | None) -> str | None:
    """解析用于数据权限过滤的用户 ID。"""
    return current_user["user_id"] if current_user else None


def _is_admin(current_user: dict[str, str] | None) -> bool:
    """判断当前用户是否管理员。"""
    return bool(current_user and current_user.get("role") == "admin")


@router.get("/center", response_model=ApiResponse[GlobalTaskCenterData])
def list_global_tasks(
    module_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[GlobalTaskCenterData]:
    """统一查询全局任务，支持跨模块搜索和真实分页。"""
    data = service.list_tasks(
        module_id=module_id,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)
