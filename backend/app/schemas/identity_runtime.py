"""认证运行态领域模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


UserRole = Literal["admin", "user"]
UserStatus = Literal["active", "disabled"]
InviteStatus = Literal["active", "disabled", "expired", "used_up"]


class UserRecord(BaseModel):
    """用户运行态实体。"""

    user_id: str
    username: str
    real_name: str | None = None
    organization: str | None = None
    password_hash: str
    role: UserRole
    status: UserStatus
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    created_by: str | None = None


class InviteCodeRecord(BaseModel):
    """邀请码运行态实体。"""

    invite_id: str
    invite_code: str
    role: UserRole
    status: InviteStatus
    expires_at: datetime
    max_uses: int
    used_count: int
    created_by: str
    created_at: datetime
    updated_at: datetime
