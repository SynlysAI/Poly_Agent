"""Shared fixtures for computation and optimization tests."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.infra.demo_store import demo_store
from app.infra.mongo import get_mongo_client
from app.main import app


class ComputationTestCase(unittest.TestCase):
    """Isolated runtime/demo-store fixture for MVP computation tests."""

    def setUp(self) -> None:
        self.runtime_root = Path(tempfile.mkdtemp(prefix="poly-agent-test-"))
        self.original_runtime_root = settings.runtime_root
        self.original_outputs_root = settings.outputs_root
        self.original_auth_enabled = settings.auth_enabled
        self.original_demo_store_path = demo_store.path
        settings.runtime_root = self.runtime_root
        settings.outputs_root = self.runtime_root / "outputs"
        settings.outputs_root.mkdir(parents=True, exist_ok=True)
        settings.auth_enabled = False
        demo_store.path = self.runtime_root / "demo-db.json"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        get_mongo_client().close()
        settings.runtime_root = self.original_runtime_root
        settings.outputs_root = self.original_outputs_root
        settings.auth_enabled = self.original_auth_enabled
        demo_store.path = self.original_demo_store_path
        shutil.rmtree(self.runtime_root, ignore_errors=True)
        get_mongo_client.cache_clear()


def computation_payload(**overrides: object) -> dict:
    """Build a minimal computation create request."""
    payload = {
        "workflow_type": "MOCK_XTB_ONLY",
        "engine": "MOCK",
        "molecule": {"smiles": "CCO", "name": "test"},
    }
    payload.update(overrides)
    return payload
