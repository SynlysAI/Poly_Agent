"""材料数据资产 MongoDB 连接配置回归测试。"""

from __future__ import annotations

from app.core.config import settings
from app.infra import mongo


def test_data_asset_client_prefers_dedicated_uri(monkeypatch) -> None:
    """数据资产库必须使用独立 URI，而不是业务库的本地连接。"""
    calls: list[str] = []
    fake_client = object()

    def fake_mongo_client(uri: str, **_kwargs):
        calls.append(uri)
        return fake_client

    monkeypatch.setattr(mongo, "MongoClient", fake_mongo_client)
    monkeypatch.setattr(settings, "data_asset_mongodb_uri", "mongodb://asset-host:27018", raising=False)
    mongo.get_data_asset_client.cache_clear()

    try:
        assert mongo.get_data_asset_client() is fake_client
        assert calls == ["mongodb://asset-host:27018"]
    finally:
        mongo.get_data_asset_client.cache_clear()
