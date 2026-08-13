"""默认管理员账号引导逻辑测试。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.infra import computation_repositories
from app.infra.repositories import UserRepository
from app.infra.sqlite_store import demo_store
from app.schemas.identity_runtime import UserRecord
from app.services.auth_service import AuthService


class DefaultAdminBootstrapTest(unittest.TestCase):
    """覆盖默认管理员引导的幂等与开关行为。"""

    def setUp(self) -> None:
        self.original_path = demo_store.path
        self.original_values = {
            "storage_backend": settings.storage_backend,
            "auth_enabled": settings.auth_enabled,
            "auth_bootstrap_enabled": settings.auth_bootstrap_enabled,
            "auth_username": settings.auth_username,
            "auth_password": settings.auth_password,
        }
        self.original_mongo_unavailable = computation_repositories._mongo_unavailable
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="poly-agent-admin-test-")
        demo_store.path = Path(self.tmp_dir.name) / "store.sqlite3"
        settings.storage_backend = "sqlite"
        computation_repositories._mongo_unavailable = False
        settings.auth_enabled = True
        settings.auth_bootstrap_enabled = True
        settings.auth_username = "admin"
        settings.auth_password = "admin123456"

    def tearDown(self) -> None:
        demo_store.path = self.original_path
        for key, value in self.original_values.items():
            setattr(settings, key, value)
        computation_repositories._mongo_unavailable = self.original_mongo_unavailable
        self.tmp_dir.cleanup()

    def test_creates_default_admin_when_missing(self) -> None:
        created = AuthService.ensure_default_admin()

        self.assertIsNotNone(created)
        self.assertEqual(created.username, "admin")
        self.assertEqual(created.role, "admin")
        self.assertEqual(created.status, "active")
        self.assertEqual(created.created_by, "system")
        stored = UserRepository.find_by_username("admin")
        self.assertIsNotNone(stored)
        self.assertTrue(
            AuthService.verify_password("admin123456", stored.password_hash)
        )
        self.assertFalse(
            AuthService.verify_password("wrong-password", stored.password_hash)
        )

    def test_skips_existing_account_without_overwriting_password(self) -> None:
        now = datetime.now()
        existing_hash = AuthService.hash_password("custom-password")
        UserRepository.save(
            UserRecord(
                user_id="u_existing",
                username="admin",
                password_hash=existing_hash,
                role="admin",
                status="active",
                created_at=now,
                updated_at=now,
                created_by="human",
            )
        )

        result = AuthService.ensure_default_admin()

        self.assertIsNone(result)
        stored = UserRepository.find_by_username("admin")
        self.assertEqual(stored.user_id, "u_existing")
        self.assertEqual(stored.password_hash, existing_hash)

    def test_skips_when_auth_disabled(self) -> None:
        settings.auth_enabled = False

        self.assertIsNone(AuthService.ensure_default_admin())
        self.assertIsNone(UserRepository.find_by_username("admin"))

    def test_skips_when_bootstrap_disabled(self) -> None:
        settings.auth_bootstrap_enabled = False

        self.assertIsNone(AuthService.ensure_default_admin())
        self.assertIsNone(UserRepository.find_by_username("admin"))

    def test_app_startup_bootstraps_default_admin(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import create_app

        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/api/v1/auth/status").status_code, 200)

        stored = UserRepository.find_by_username("admin")
        self.assertIsNotNone(stored)
