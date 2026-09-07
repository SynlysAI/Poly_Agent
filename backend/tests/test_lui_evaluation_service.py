"""LUI 评测基线服务与 API 测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.services.lui_evaluation_service import (
    list_baseline_modes,
    load_baseline_summary,
)
from app.core.auth import build_access_token
from app.core.config import settings
from app.infra.repositories import UserRepository
from app.schemas.identity_runtime import UserRecord


class LuiEvaluationServiceTest(unittest.TestCase):
    def test_lists_modes_and_ignores_non_baseline_files(self) -> None:
        """只识别 smoke/full 前缀的受控基线文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "smoke-2026.08.28.json").write_text("{}", encoding="utf-8")
            (base / "full-2026.08.28.json").write_text("{}", encoding="utf-8")
            (base / "manual-review-2026.08.28.json").write_text("{}", encoding="utf-8")
            self.assertEqual(list_baseline_modes(base), ["full", "smoke"])

    def test_loads_latest_baseline_summary(self) -> None:
        """应读取指定模式最新基线并投影页面字段。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = {
                "evaluation_id": "lui-eval-smoke-test",
                "dataset_version": "2026.08.28",
                "mode": "smoke",
                "generated_at": "2026-08-28T00:00:00+00:00",
                "summary": {"evaluated_tasks": 37, "task_success_rate": 1.0},
                "metrics": {"m1": {"label": "任务成功率", "pass_rate": 1.0}},
                "by_category": {},
                "by_mode": {},
                "metadata": {"facts_source": "fixture", "manual_review": {"metrics": {}}},
            }
            (base / "smoke-2026.08.27.json").write_text("{}", encoding="utf-8")
            (base / "smoke-2026.08.28.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            summary = load_baseline_summary("smoke", base)
            self.assertTrue(summary["available"])
            self.assertEqual(summary["evaluation_id"], "lui-eval-smoke-test")
            self.assertEqual(summary["source_file"], "smoke-2026.08.28.json")
            self.assertEqual(summary["facts_source"], "fixture")
            self.assertEqual(summary["manual_review"], {"metrics": {}})

    def test_missing_baseline_returns_available_false(self) -> None:
        """无基线时返回 available=False 与可用模式。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "smoke-2026.08.28.json").write_text("{}", encoding="utf-8")
            summary = load_baseline_summary("full", base)
            self.assertFalse(summary["available"])
            self.assertEqual(summary["available_modes"], ["smoke"])

    def test_rejects_unknown_mode(self) -> None:
        """非法模式应拒绝，防止路径拼接。"""
        with self.assertRaises(ValueError):
            load_baseline_summary("../secrets", "/tmp")


class LuiEvaluationApiTest(ComputationTestCase):
    def test_summary_endpoint_requires_admin_and_returns_payload(self) -> None:
        """评测基线接口应在关闭鉴权的测试环境返回基线投影。"""
        response = self.client.get("/api/v1/assistant/lui-evaluation/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("available", payload)
        self.assertIn(payload["mode"], ("smoke", "full"))


class LuiEvaluationAdminPermissionTest(ComputationTestCase):
    """评测报告接口必须保持管理员专属。"""

    def setUp(self) -> None:
        super().setUp()
        self.admin = UserRecord(
            user_id="admin_lui_eval",
            username="admin_lui_eval",
            password_hash="unused",
            role="admin",
            status="active",
            created_at=datetime(2026, 9, 1, 9, 0, 0),
            updated_at=datetime(2026, 9, 1, 9, 0, 0),
        )
        self.user = UserRecord(
            user_id="user_lui_eval",
            username="user_lui_eval",
            password_hash="unused",
            role="user",
            status="active",
            created_at=datetime(2026, 9, 1, 9, 0, 0),
            updated_at=datetime(2026, 9, 1, 9, 0, 0),
        )
        UserRepository.save(self.admin)
        UserRepository.save(self.user)
        self.admin_token, _ = build_access_token(
            self.admin.user_id, self.admin.username, self.admin.role
        )
        self.user_token, _ = build_access_token(
            self.user.user_id, self.user.username, self.user.role
        )

    def _patch_users(self):
        """把 token 用户解析到本次测试创建的真实用户。"""

        def fake_find(user_id: str) -> UserRecord | None:
            """按 ID 返回测试用户。

            Args:
                user_id: 用户 ID。

            Returns:
                对应用户记录。
            """
            if user_id == self.admin.user_id:
                return self.admin
            if user_id == self.user.user_id:
                return self.user
            return None

        return patch(
            "app.infra.repositories.UserRepository.find_by_user_id",
            side_effect=fake_find,
        )

    def test_summary_endpoint_rejects_normal_user(self) -> None:
        """普通用户访问评测基线接口应得到 403。"""
        settings.auth_enabled = True
        with self._patch_users():
            response = self.client.get(
                "/api/v1/assistant/lui-evaluation/summary",
                headers={"Authorization": f"Bearer {self.user_token}"},
            )
        self.assertEqual(response.status_code, 403)

    def test_summary_endpoint_allows_admin(self) -> None:
        """管理员访问评测基线接口应返回 200 与可用模式。"""
        settings.auth_enabled = True
        with self._patch_users():
            response = self.client.get(
                "/api/v1/assistant/lui-evaluation/summary",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("available", response.json()["data"])
