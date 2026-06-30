"""认证接口模型。"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

from app.schemas.identity_runtime import UserRole, UserStatus


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(description="登录用户名")
    password: str = Field(description="登录密码")


class RegisterRequest(BaseModel):
    """邀请码注册请求。"""

    invite_code: str = Field(description="邀请码")
    username: str = Field(description="注册用户名")
    real_name: str | None = Field(default=None, description="姓名")
    organization: str | None = Field(default=None, description="单位")
    password: str = Field(description="登录密码")


class LoginData(BaseModel):
    """登录结果数据。"""

    auth_enabled: bool = Field(description="是否启用登录校验")
    user_id: str = Field(description="当前登录用户 ID")
    username: str = Field(description="当前登录用户名")
    role: UserRole = Field(description="当前登录用户角色")
    status: UserStatus = Field(description="当前登录用户状态")
    access_token: str = Field(description="访问令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")
    expires_at: int = Field(description="过期时间戳（秒）")


class AuthStatusData(BaseModel):
    """认证状态数据。"""

    auth_enabled: bool = Field(description="是否启用登录校验")
    authenticated: bool = Field(description="当前请求是否已认证")
    username: str | None = Field(default=None, description="当前登录用户名")


class CurrentUserData(BaseModel):
    """当前用户信息。"""

    auth_enabled: bool = Field(description="是否启用登录鉴权")
    authenticated: bool = Field(description="是否已认证")
    user_id: str | None = Field(default=None, description="用户 ID")
    username: str | None = Field(default=None, description="用户名")
    role: UserRole | None = Field(default=None, description="角色")
    status: UserStatus | None = Field(default=None, description="状态")
