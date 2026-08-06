"""远程接口配置 Demo 服务测试。

Demo 服务位于 examples/interface_config/demo_service，是一个独立的教学示例，
不接入后端路由。这里用 importlib 以独立模块名加载，避免与 backend.app 包冲突。
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SERVICE_DIR = REPO_ROOT / "examples" / "interface_config" / "demo_service"


def _load_demo_app():
    spec = importlib.util.spec_from_file_location(
        "polyagent_interface_demo_app",
        DEMO_SERVICE_DIR / "app.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


class InterfaceDemoServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_load_demo_app())

    def tearDown(self) -> None:
        self.client.close()

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "polyagent_interface_demo"

    def test_post_predict_returns_expected_shape(self) -> None:
        response = self.client.post("/predict", json={"smiles": "CCO"})
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["data"]["prediction"], float)
        assert body["data"]["smiles"] == "CCO"
        assert body["data"]["prediction"] > 0

    def test_get_predict_returns_expected_shape(self) -> None:
        response = self.client.get("/predict", params={"smiles": "CCO"})
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["data"]["prediction"], float)
        assert body["data"]["smiles"] == "CCO"

    def test_invalid_payload_is_rejected(self) -> None:
        assert self.client.post("/predict", json={}).status_code == 422
        assert self.client.post("/predict", json={"smiles": ""}).status_code == 422
        assert self.client.get("/predict").status_code == 422

    def test_bearer_token_is_required_when_configured(self) -> None:
        with patch.dict(os.environ, {"DEMO_API_TOKEN": "demo-secret"}, clear=False):
            missing = self.client.post("/predict", json={"smiles": "CCO"})
            assert missing.status_code == 401
            wrong = self.client.post(
                "/predict",
                json={"smiles": "CCO"},
                headers={"Authorization": "Bearer wrong"},
            )
            assert wrong.status_code == 401
            ok = self.client.post(
                "/predict",
                json={"smiles": "CCO"},
                headers={"Authorization": "Bearer demo-secret"},
            )
            assert ok.status_code == 200
            assert ok.json()["data"]["smiles"] == "CCO"
