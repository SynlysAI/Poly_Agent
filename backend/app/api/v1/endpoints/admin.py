"""管理员接口。"""

from __future__ import annotations

import secrets
from datetime import datetime
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from app.core.auth import get_current_user
from app.core.auth import require_admin
from app.infra.repositories import InviteCodeRepository
from app.infra.repositories import UserRepository
from app.schemas.admin import AdminInviteCodeCreateData
from app.schemas.admin import AdminInviteCodeListData
from app.schemas.admin import AdminInviteCodeListItem
from app.schemas.admin import AdminInviteCodeStatusData
from app.schemas.admin import AdminUserListData
from app.schemas.admin import AdminUserListItem
from app.schemas.admin import AdminUserStatusData
from app.schemas.admin import AdminUserStatusRequest
from app.schemas.admin import InviteCodeCreateRequest
from app.schemas.common import ApiResponse
from app.schemas.identity_runtime import InviteCodeRecord

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users", response_model=ApiResponse[AdminUserListData])
def list_users() -> ApiResponse[AdminUserListData]:
    """查询全部用户列表。

    Returns:
        用户列表响应。
    """
    users = UserRepository.list_all()
    items = [
        AdminUserListItem(
            user_id=user.user_id,
            username=user.username,
            real_name=user.real_name,
            organization=user.organization,
            role=user.role,
            status=user.status,
        )
        for user in users
    ]
    return ApiResponse(code=0, message="ok", data=AdminUserListData(total=len(items), items=items))


@router.get("/invite-codes", response_model=ApiResponse[AdminInviteCodeListData])
def list_invite_codes() -> ApiResponse[AdminInviteCodeListData]:
    """查询全部邀请码列表。

    Returns:
        邀请码列表响应。
    """
    invite_codes = InviteCodeRepository.list_all()
    items = [
        AdminInviteCodeListItem(
            invite_id=record.invite_id,
            invite_code=record.invite_code,
            role=record.role,
            status=record.status,
            expires_at=record.expires_at,
            max_uses=record.max_uses,
            used_count=record.used_count,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        for record in invite_codes
    ]
    return ApiResponse(code=0, message="ok", data=AdminInviteCodeListData(total=len(items), items=items))


@router.post("/invite-codes", response_model=ApiResponse[AdminInviteCodeCreateData])
def create_invite_code(
    payload: InviteCodeCreateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AdminInviteCodeCreateData]:
    """创建新的邀请码。

    Args:
        payload: 创建邀请码请求。
        current_user: 当前管理员上下文。

    Returns:
        新建的邀请码信息。
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")

    now = datetime.now()
    invite_record = InviteCodeRecord(
        invite_id=f"invite_{uuid4().hex[:12]}",
        invite_code=secrets.token_urlsafe(12),
        role="user",
        status="active",
        expires_at=now + timedelta(hours=payload.expires_hours),
        max_uses=payload.max_uses,
        used_count=0,
        created_by=current_user["user_id"],
        created_at=now,
        updated_at=now,
    )
    InviteCodeRepository.save(invite_record)
    data = AdminInviteCodeCreateData(
        invite_id=invite_record.invite_id,
        invite_code=invite_record.invite_code,
        role=invite_record.role,
        status=invite_record.status,
        expires_at=invite_record.expires_at,
        max_uses=invite_record.max_uses,
        used_count=invite_record.used_count,
        created_by=invite_record.created_by,
        created_at=invite_record.created_at,
        updated_at=invite_record.updated_at,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.patch("/users/{user_id}/status", response_model=ApiResponse[AdminUserStatusData])
def update_user_status(
    user_id: str,
    payload: AdminUserStatusRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AdminUserStatusData]:
    """更新指定用户状态。

    Args:
        user_id: 目标用户 ID。
        payload: 状态更新请求。
        current_user: 当前管理员上下文。

    Returns:
        更新后的用户状态。
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")

    target_user = UserRepository.find_by_user_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if payload.status == "disabled" and target_user.role == "admin":
        raise HTTPException(status_code=400, detail="一期不允许禁用管理员账号")

    updated = UserRepository.update_status(user_id=user_id, status=payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ApiResponse(
        code=0,
        message="ok",
        data=AdminUserStatusData(user_id=user_id, status=payload.status),
    )


@router.patch("/invite-codes/{invite_id}/disable", response_model=ApiResponse[AdminInviteCodeStatusData])
def disable_invite_code(invite_id: str) -> ApiResponse[AdminInviteCodeStatusData]:
    """禁用指定邀请码。

    Args:
        invite_id: 目标邀请码 ID。

    Returns:
        更新后的邀请码状态。
    """
    disabled = InviteCodeRepository.disable(invite_id=invite_id)
    if not disabled:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    return ApiResponse(
        code=0,
        message="ok",
        data=AdminInviteCodeStatusData(invite_id=invite_id, status="disabled"),
    )
