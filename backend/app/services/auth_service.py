"""认证服务。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from uuid import uuid4

from app.core.auth import build_access_token
from app.infra.mongo import get_invite_codes_collection, get_users_collection
from app.infra.repositories import InviteCodeRepository
from app.infra.repositories import UserRepository
from app.schemas.auth import LoginData
from app.schemas.identity_runtime import UserRecord

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260000


def ensure_identity_indexes() -> None:
    """确保用户与邀请码集合索引已创建。"""
    get_users_collection().create_index("username", unique=True)
    get_users_collection().create_index("user_id", unique=True)
    get_invite_codes_collection().create_index("invite_code", unique=True)
    get_invite_codes_collection().create_index("invite_id", unique=True)
    get_invite_codes_collection().create_index("expires_at")


class AuthService:
    """认证服务。"""

    @staticmethod
    def hash_password(password: str) -> str:
        """计算密码哈希值。

        Args:
            password: 明文密码。

        Returns:
            PBKDF2-SHA256 密码哈希结果。
        """
        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            PASSWORD_HASH_ITERATIONS,
        )
        return (
            f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}$"
            f"{salt.hex()}${password_hash.hex()}"
        )

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """校验密码与哈希值是否匹配。

        Args:
            password: 明文密码。
            password_hash: 已保存的密码哈希值。

        Returns:
            密码是否匹配。
        """
        if password_hash.startswith(f"{PASSWORD_HASH_ALGORITHM}$"):
            try:
                _, iterations_raw, salt_hex, expected_hash = password_hash.split("$", 3)
                iterations = int(iterations_raw)
                salt = bytes.fromhex(salt_hex)
            except (ValueError, TypeError):
                return False
            actual_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                iterations,
            ).hex()
            return hmac.compare_digest(actual_hash, expected_hash)

        legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy_hash, password_hash)

    @staticmethod
    def register(
        invite_code: str,
        username: str,
        password: str,
        real_name: str | None = None,
        organization: str | None = None,
    ) -> UserRecord:
        """基于邀请码注册用户。

        Args:
            invite_code: 邀请码。
            username: 用户名。
            password: 明文密码。
            real_name: 用户姓名。
            organization: 用户单位。

        Returns:
            新创建的用户记录。
        """
        if UserRepository.find_by_username(username):
            raise ValueError("用户名已存在")
        now = datetime.now()
        invite = InviteCodeRepository.consume_available_code(invite_code, now)
        if not invite:
            original_invite = InviteCodeRepository.find_by_code(invite_code)
            if not original_invite:
                raise ValueError("邀请码不存在")
            if original_invite.status != "active":
                raise ValueError("邀请码不可用")
            if original_invite.expires_at <= now:
                raise ValueError("邀请码已过期")
            if original_invite.used_count >= original_invite.max_uses:
                raise ValueError("邀请码已用尽")
            raise ValueError("邀请码不可用")

        user_record = UserRecord(
            user_id=f"u_{uuid4().hex[:12]}",
            username=username,
            real_name=real_name,
            organization=organization,
            password_hash=AuthService.hash_password(password),
            role=invite.role,
            status="active",
            created_at=now,
            updated_at=now,
            last_login_at=None,
            created_by=invite.created_by,
        )
        try:
            UserRepository.save(user_record)
        except Exception:
            InviteCodeRepository.rollback_usage(invite.invite_id)
            raise
        return user_record

    @staticmethod
    def login(username: str, password: str) -> LoginData:
        """使用数据库用户执行登录。

        Args:
            username: 登录用户名。
            password: 明文密码。

        Returns:
            登录结果数据。
        """
        user = UserRepository.find_by_username(username)
        if not user or not AuthService.verify_password(password, user.password_hash):
            raise ValueError("账号或密码错误")
        if user.status != "active":
            raise ValueError("当前账号已被禁用")

        token, expires_at = build_access_token(user.user_id, user.username, user.role)
        UserRepository.update_last_login(user.user_id)
        return LoginData(
            auth_enabled=True,
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            status=user.status,
            access_token=token,
            token_type="Bearer",
            expires_at=expires_at,
        )
