"""访问令牌鉴权能力。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import Header
from fastapi import HTTPException

from app.core.config import settings
from app.infra.repositories import UserRepository


AUTH_SCHEME = "Bearer"


def _urlsafe_b64encode(raw: bytes) -> str:
    """执行 URL 安全的 Base64 编码。"""
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    """执行 URL 安全的 Base64 解码。"""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))


def _build_auth_secret() -> str:
    """生成本地鉴权签名密钥。

    Returns:
        用于访问令牌签名的密钥字符串。
    """
    if settings.auth_secret:
        return settings.auth_secret
    default_seed = f"{settings.project_root}:{settings.auth_username}:{settings.auth_password}"
    return hashlib.sha256(default_seed.encode("utf-8")).hexdigest()


def _sign_payload(payload_segment: str) -> str:
    """对令牌负载进行签名（hex digest，与 AI4MS 兼容）。

    Args:
        payload_segment: Base64 编码后的负载段。

    Returns:
        HMAC-SHA256 十六进制签名字符串。
    """
    return hmac.new(
        _build_auth_secret().encode("utf-8"),
        payload_segment.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _parse_authorization_token(authorization: str | None) -> str:
    """从请求头中解析 Bearer Token。

    Args:
        authorization: 请求头中的 Authorization 值。

    Returns:
        解析得到的访问令牌。
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != AUTH_SCHEME.lower() or not token:
        raise HTTPException(status_code=401, detail="无效的登录凭证")
    return token.strip()


def build_access_token(user_id: str, username: str, role: str) -> tuple[str, int]:
    """生成访问令牌。

    Args:
        user_id: 用户 ID。
        username: 登录用户名。
        role: 用户角色。

    Returns:
        访问令牌与过期时间戳。
    """
    expires_at = int(time.time()) + settings.auth_token_expire_hours * 3600
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expires_at,
        "iat": int(time.time()),
    }
    payload_segment = _urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    signature_segment = _sign_payload(payload_segment)
    return f"{payload_segment}.{signature_segment}", expires_at


def parse_access_token(token: str) -> dict[str, object]:
    """解析并校验访问令牌。

    Args:
        token: 访问令牌字符串。

    Returns:
        解码后的令牌负载。
    """
    try:
        payload_segment, signature_segment = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="无效的登录凭证") from exc

    expected_signature = _sign_payload(payload_segment)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise HTTPException(status_code=401, detail="无效的登录凭证")

    try:
        payload_raw = _urlsafe_b64decode(payload_segment)
        payload = json.loads(payload_raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail="无效的登录凭证") from exc

    expires_at = int(payload.get("exp", 0))
    user_id = str(payload.get("sub", ""))
    username = str(payload.get("username", ""))
    role = str(payload.get("role", ""))
    if not user_id or not username or role not in {"admin", "user"}:
        raise HTTPException(status_code=401, detail="无效的登录凭证")
    if expires_at <= int(time.time()):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return payload


def _build_current_user_context(user_id: str) -> dict[str, str]:
    """按用户 ID 构建真实的当前用户上下文。

    Args:
        user_id: Token 中的用户 ID。

    Returns:
        来自数据库的真实用户上下文。
    """
    user_record = UserRepository.find_by_user_id(user_id)
    if not user_record:
        raise HTTPException(status_code=401, detail="无效的登录凭证")
    if user_record.status != "active":
        raise HTTPException(status_code=401, detail="当前账号已被禁用")
    return {
        "user_id": user_record.user_id,
        "username": user_record.username,
        "role": user_record.role,
        "status": user_record.status,
    }


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, str] | None:
    """解析当前请求对应的登录用户。

    Args:
        authorization: 请求头中的 Authorization 值。

    Returns:
        当前登录用户信息；未启用登录时返回 `None`。
    """
    if not settings.auth_enabled:
        return None
    token = _parse_authorization_token(authorization)
    payload = parse_access_token(token)
    return _build_current_user_context(str(payload["sub"]))


def get_current_user_optional(authorization: str | None = Header(default=None)) -> dict[str, str] | None:
    """以可选方式解析当前请求对应的登录用户。

    Args:
        authorization: 请求头中的 Authorization 值。

    Returns:
        当前登录用户信息；未启用登录或未携带令牌时返回 `None`。
    """
    if not settings.auth_enabled:
        return None
    if not authorization:
        return None
    token = _parse_authorization_token(authorization)
    payload = parse_access_token(token)
    return _build_current_user_context(str(payload["sub"]))


def resolve_authenticated_username(authorization: str | None) -> str | None:
    """兼容旧接口，解析当前请求对应的登录用户名。

    Args:
        authorization: 请求头中的 Authorization 值。

    Returns:
        当前登录用户名；未启用登录时返回 `None`。
    """
    current_user = get_current_user(authorization)
    if not current_user:
        return None
    return current_user["username"]


def require_authenticated(authorization: str | None = Header(default=None)) -> None:
    """要求当前请求已通过登录验证。

    Args:
        authorization: 请求头中的 Authorization 值。
    """
    if not settings.auth_enabled:
        return
    get_current_user(authorization)


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """要求当前请求具备管理员权限。

    Args:
        authorization: 请求头中的 Authorization 值。
    """
    if not settings.auth_enabled:
        return
    current_user = get_current_user(authorization)
    if not current_user or current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
