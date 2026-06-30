"""管理员接口模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from app.schemas.identity_runtime import InviteStatus
from app.schemas.identity_runtime import UserRole
from app.schemas.identity_runtime import UserStatus


class AdminUserListItem(BaseModel):
    """管理员用户列表项。"""

    user_id: str = Field(description="用户 ID")
    username: str = Field(description="用户名")
    real_name: str | None = Field(default=None, description="姓名")
    organization: str | None = Field(default=None, description="单位")
    role: UserRole = Field(description="角色")
    status: UserStatus = Field(description="状态")


class AdminUserListData(BaseModel):
    """管理员用户列表响应。"""

    total: int = Field(description="用户总数")
    items: list[AdminUserListItem] = Field(description="用户列表")


class AdminUserStatusRequest(BaseModel):
    """管理员更新用户状态请求。"""

    status: UserStatus = Field(description="用户状态：active/disabled")


class AdminUserStatusData(BaseModel):
    """管理员更新用户状态响应。"""

    user_id: str = Field(description="用户 ID")
    status: UserStatus = Field(description="当前状态")


class AdminInviteCodeListItem(BaseModel):
    """管理员邀请码列表项。"""

    invite_id: str = Field(description="邀请码 ID")
    invite_code: str = Field(description="邀请码")
    role: UserRole = Field(description="邀请码角色")
    status: InviteStatus = Field(description="邀请码状态")
    expires_at: datetime = Field(description="过期时间")
    max_uses: int = Field(description="最大使用次数")
    used_count: int = Field(description="已使用次数")
    created_by: str = Field(description="创建人用户 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class AdminInviteCodeListData(BaseModel):
    """管理员邀请码列表响应。"""

    total: int = Field(description="邀请码总数")
    items: list[AdminInviteCodeListItem] = Field(description="邀请码列表")


class InviteCodeCreateRequest(BaseModel):
    """创建邀请码请求。"""

    expires_hours: int = Field(default=72, ge=1, le=720, description="有效小时数")
    max_uses: int = Field(default=1, ge=1, le=100, description="最大使用次数")


class AdminInviteCodeCreateData(BaseModel):
    """创建邀请码响应。"""

    invite_id: str = Field(description="邀请码 ID")
    invite_code: str = Field(description="邀请码")
    role: UserRole = Field(description="邀请码角色")
    status: InviteStatus = Field(description="邀请码状态")
    expires_at: datetime = Field(description="过期时间")
    max_uses: int = Field(description="最大使用次数")
    used_count: int = Field(description="已使用次数")
    created_by: str = Field(description="创建人用户 ID")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class AdminInviteCodeStatusData(BaseModel):
    """管理员邀请码状态响应。"""

    invite_id: str = Field(description="邀请码 ID")
    status: InviteStatus = Field(description="邀请码状态")
