"""SQLite/MongoDB 存储分层的配置、存储与健康检查测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.api.v1.endpoints.health import health_check
from app.core.config import Settings, settings
from app.infra import computation_repositories
from app.infra.alchemist_repositories import AlchemistSessionRepository
from app.infra.repositories import InviteCodeRepository, UserRepository
from app.infra.sqlite_store import SqliteDocumentStore, demo_store
from app.schemas.identity_runtime import InviteCodeRecord, UserRecord


class StorageBackendConfigTest(unittest.TestCase):
    """覆盖 STORAGE_BACKEND 默认值、显式覆盖与安全校验。"""

    def _settings(self, env: dict[str, str]) -> Settings:
        with tempfile.TemporaryDirectory(prefix="poly-agent-storage-test-") as runtime_root:
            merged = {
                "POLY_AGENT_RUNTIME_ROOT": runtime_root,
                "POLY_AGENT_UPLOAD_ROOT": os.path.join(runtime_root, "uploads"),
                "POLY_AGENT_OUTPUT_ROOT": os.path.join(runtime_root, "outputs"),
                "POLY_AGENT_LOG_ROOT": os.path.join(runtime_root, "logs"),
                **env,
            }
            with patch.dict(os.environ, merged, clear=False):
                return Settings()

    def test_local_env_defaults_to_sqlite(self) -> None:
        instance = self._settings({"APP_ENV": "dev"})
        self.assertEqual(instance.storage_backend, "sqlite")
        self.assertFalse(instance.require_mongodb)
        self.assertTrue(instance.uses_sqlite)

    def test_production_defaults_to_mongodb(self) -> None:
        instance = self._settings({"APP_ENV": "production", "STORAGE_BACKEND": "mongodb"})
        self.assertEqual(instance.storage_backend, "mongodb")
        self.assertTrue(instance.require_mongodb)
        self.assertTrue(instance.uses_mongodb)

    def test_explicit_backend_overrides_environment_default(self) -> None:
        instance = self._settings({"APP_ENV": "dev", "STORAGE_BACKEND": "mongodb"})
        self.assertEqual(instance.storage_backend, "mongodb")
        self.assertTrue(instance.require_mongodb)

    def test_invalid_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._settings({"APP_ENV": "dev", "STORAGE_BACKEND": "filesystem"})

    def test_non_local_sqlite_is_rejected_by_deployment_validation(self) -> None:
        instance = self._settings(
            {
                "APP_ENV": "production",
                "STORAGE_BACKEND": "sqlite",
                "AUTH_ENABLED": "true",
                "AUTH_USERNAME": "poly-admin",
                "AUTH_PASSWORD": "not-the-default-password",
                "AUTH_SECRET": "0123456789abcdef0123456789abcdef",
                "CORS_ALLOWED_ORIGINS": "https://polyagent.example.com",
            }
        )
        with self.assertRaisesRegex(RuntimeError, "STORAGE_BACKEND must be mongodb"):
            instance.validate_deployment_security()


class SqliteDocumentStoreTest(unittest.TestCase):
    """覆盖 SQLite 文档存储的基础读写。"""

    def test_save_load_and_mutate_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-sqlite-test-") as tmp_dir:
            store = SqliteDocumentStore(Path(tmp_dir) / "store.sqlite3")
            now = datetime.now()
            store.save(
                {
                    "assistant_runs": [
                        {"run_id": "run-1", "status": "queued", "updated_at": now}
                    ],
                    "users": [],
                }
            )
            loaded = store.load()
            self.assertEqual(loaded["assistant_runs"][0]["run_id"], "run-1")

            store.mutate(lambda data: data["assistant_runs"].append({"run_id": "run-2"}))
            self.assertEqual(len(store.load()["assistant_runs"]), 2)
            self.assertTrue(store.ping())

    def test_collection_scoped_read_and_mutate_preserve_other_collections(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-sqlite-scoped-test-") as tmp_dir:
            store = SqliteDocumentStore(Path(tmp_dir) / "store.sqlite3")
            store.save(
                {
                    "assistant_runs": [
                        {"run_id": "run-1", "status": "queued"},
                        {"run_id": "run-2", "status": "completed"},
                    ],
                    "assistant_events": [],
                    "users": [{"user_id": "user-1"}],
                }
            )

            self.assertEqual(
                store.load_collection_where("assistant_runs", "run_id", "run-1"),
                [{"run_id": "run-1", "status": "queued"}],
            )
            result = store.mutate_collection(
                "assistant_runs",
                lambda data: data["assistant_runs"].pop(0),
            )

            self.assertEqual(result, {"run_id": "run-1", "status": "queued"})
            self.assertEqual(
                store.load_collection("assistant_runs"),
                [{"run_id": "run-2", "status": "completed"}],
            )
            self.assertEqual(store.load_collection("users"), [{"user_id": "user-1"}])


class SqliteRepositoryTest(unittest.TestCase):
    """验证直连仓库在 SQLite 模式下不创建 MongoClient。"""

    def setUp(self) -> None:
        self.original_path = demo_store.path
        self.original_backend = settings.storage_backend
        self.original_unavailable = computation_repositories._mongo_unavailable
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="poly-agent-repo-test-")
        demo_store.path = Path(self.tmp_dir.name) / "store.sqlite3"
        settings.storage_backend = "sqlite"
        computation_repositories._mongo_unavailable = False

    def tearDown(self) -> None:
        demo_store.path = self.original_path
        settings.storage_backend = self.original_backend
        computation_repositories._mongo_unavailable = self.original_unavailable
        self.tmp_dir.cleanup()

    def test_auth_and_alchemist_repositories_use_sqlite_without_mongo(self) -> None:
        def forbidden_client(*_args, **_kwargs):
            raise AssertionError("SQLite 模式不应创建 MongoClient")

        now = datetime.now()
        user = UserRecord(
            user_id="u1",
            username="alice",
            password_hash="hash",
            role="admin",
            status="active",
            created_at=now,
            updated_at=now,
        )
        invite = InviteCodeRecord(
            invite_id="i1",
            invite_code="code-1",
            role="user",
            status="active",
            expires_at=now + timedelta(days=1),
            max_uses=1,
            used_count=0,
            created_by="admin",
            created_at=now,
            updated_at=now,
        )
        with patch("app.infra.mongo.MongoClient", forbidden_client):
            UserRepository.save(user)
            self.assertEqual(UserRepository.find_by_username("alice").user_id, "u1")

            InviteCodeRepository.save(invite)
            consumed = InviteCodeRepository.consume_available_code("code-1", now)
            self.assertIsNotNone(consumed)
            self.assertEqual(consumed.used_count, 1)
            self.assertIsNone(InviteCodeRepository.consume_available_code("code-1", now))

            AlchemistSessionRepository.save({"session_id": "s1", "created_by": "u1"})
            self.assertEqual(
                AlchemistSessionRepository.find_by_id("s1")["session_id"],
                "s1",
            )


class StorageHealthCheckTest(unittest.TestCase):
    """验证健康检查按当前存储后端返回状态。"""

    def test_sqlite_health_does_not_ping_mongodb(self) -> None:
        def forbidden_client(*_args, **_kwargs):
            raise AssertionError("SQLite 健康检查不应连接 MongoDB")

        with patch.object(settings, "storage_backend", "sqlite"), patch(
            "app.infra.mongo.MongoClient", forbidden_client
        ):
            payload = health_check().data

        self.assertEqual(payload["storage_backend"], "sqlite")
        self.assertEqual(payload["sqlite"], "up")
        self.assertEqual(payload["mongodb"], "not_configured")
