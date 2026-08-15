"""统一认证 MongoDB 连接配置回归测试。"""

from __future__ import annotations

from app.core.config import settings
from app.infra import mongo


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
