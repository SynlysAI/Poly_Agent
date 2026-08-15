"""统一认证 MongoDB 连接配置回归测试。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime

from app.core.config import settings
from app.core.auth import get_current_user
from app.infra import mongo
from app.infra.repositories import UserRepository
from app.schemas.identity_runtime import UserRecord


def test_settings_reads_dedicated_auth_mongodb_uri(monkeypatch) -> None:
    """生产环境可显式配置 AI4MS 认证库连接。"""
    from app.core.config import Settings

    monkeypatch.setenv("AUTH_MONGODB_URI", "mongodb://auth-host:27018/ai4ms")
    configured = Settings()

    assert configured.auth_mongodb_uri == "mongodb://auth-host:27018/ai4ms"


def test_auth_client_prefers_dedicated_uri(monkeypatch) -> None:
    """认证库必须使用独立 URI，而不是业务库连接。"""
    calls: list[str] = []
    fake_client = object()

    def fake_mongo_client(uri: str, **_kwargs):
        calls.append(uri)
        return fake_client

    monkeypatch.setattr(mongo, "MongoClient", fake_mongo_client)
    monkeypatch.setattr(settings, "auth_mongodb_uri", "mongodb://auth-host:27018", raising=False)
    mongo._get_auth_client.cache_clear()

    try:
        assert mongo._get_auth_client() is fake_client
        assert calls == ["mongodb://auth-host:27018"]
    finally:
        mongo._get_auth_client.cache_clear()


def test_auth_client_falls_back_to_main_uri(monkeypatch) -> None:
    """未配置独立认证库时保持与业务库共用连接。"""
    calls: list[str] = []
    fake_client = object()

    def fake_mongo_client(uri: str, **_kwargs):
        calls.append(uri)
        return fake_client

    monkeypatch.setattr(mongo, "MongoClient", fake_mongo_client)
    monkeypatch.setattr(settings, "auth_mongodb_uri", "", raising=False)
    mongo._get_auth_client.cache_clear()

    try:
        assert mongo._get_auth_client() is fake_client
        assert calls == [settings.mongodb_uri]
    finally:
        mongo._get_auth_client.cache_clear()


def test_ai4ms_portal_token_resolves_active_poly_agent_user(monkeypatch) -> None:
    """AI4MS 签发的兼容 token 必须能装载 Poly Agent 当前用户。"""
    secret = "0123456789abcdef0123456789abcdef"
    now = int(time.time())
    payload = {
        "sub": "u_sso_compat",
        "username": "sso-user",
        "role": "user",
        "organization": "AI4MS",
        "iat": now,
        "exp": now + 3600,
    }
    payload_segment = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("utf-8").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_segment.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    current_time = datetime.now()
    user = UserRecord(
        user_id="u_sso_compat",
        username="sso-user",
        password_hash="not-used",
        role="user",
        status="active",
        created_at=current_time,
        updated_at=current_time,
    )

    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "auth_secret", secret)
    monkeypatch.setattr(
        UserRepository,
        "find_by_user_id",
        classmethod(lambda _cls, _user_id: user),
    )

    current_user = get_current_user(f"Bearer {payload_segment}.{signature}")

    assert current_user["user_id"] == "u_sso_compat"
    assert current_user["username"] == "sso-user"
