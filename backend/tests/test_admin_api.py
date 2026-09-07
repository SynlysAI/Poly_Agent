"""用户与邀请码治理 API 测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import build_access_token
from app.core.config import settings
from app.infra.repositories import InviteCodeRepository, UserRepository
from app.schemas.identity_runtime import InviteCodeRecord, UserRecord


class AdminApiTest(ComputationTestCase):
    """覆盖管理员用户列表、时间字段和接口权限。"""

    def setUp(self) -> None:
        super().setUp()
        self.now = datetime.now()
        self.admin = self._user("admin_governance", role="admin", last_login_at=self.now)
        self.user = self._user("normal_governance", role="user")
        UserRepository.save(self.admin)
        UserRepository.save(self.user)
        self.admin_token, _ = build_access_token(
            self.admin.user_id, self.admin.username, self.admin.role
        )
        self.user_token, _ = build_access_token(
            self.user.user_id, self.user.username, self.user.role
        )

    @staticmethod
    def _user(user_id: str, *, role: str, last_login_at: datetime | None = None) -> UserRecord:
        """构建测试用户。

        Args:
            user_id: 用户 ID。
            role: 用户角色。
            last_login_at: 最近登录时间。

        Returns:
            测试用户记录。
        """
        return UserRecord(
            user_id=user_id,
            username=user_id,
            password_hash="unused",
            role=role,
            status="active",
            created_at=datetime(2026, 8, 28, 9, 0, 0),
            updated_at=datetime(2026, 8, 28, 10, 0, 0),
            last_login_at=last_login_at,
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

    def test_admin_user_list_contains_timestamps_and_admin_is_protected(self) -> None:
        settings.auth_enabled = True
        with self._patch_users():
            response = self.client.get(
                "/api/v1/admin/users",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["data"]["items"]
        self.assertEqual(len(items), 2)
        item = next(row for row in items if row["user_id"] == self.admin.user_id)
        self.assertEqual(item["created_at"], self.admin.created_at.isoformat())
        self.assertEqual(item["updated_at"], self.admin.updated_at.isoformat())
        self.assertEqual(item["last_login_at"], self.now.isoformat())

    def test_user_cannot_access_admin_apis(self) -> None:
        settings.auth_enabled = True
        with self._patch_users():
            endpoints = (
                ("get", "/api/v1/admin/users"),
                ("get", "/api/v1/admin/invite-codes"),
                ("post", "/api/v1/admin/invite-codes"),
                ("patch", f"/api/v1/admin/users/{self.user.user_id}/status"),
                ("patch", "/api/v1/admin/invite-codes/i_missing/disable"),
            )
            for method, path in endpoints:
                kwargs = {"json": {}} if method in {"post", "patch"} else {}
                response = getattr(self.client, method)(
                    path,
                    headers={"Authorization": f"Bearer {self.user_token}"},
                    **kwargs,
                )
                self.assertEqual(response.status_code, 403, path)

    def test_admin_can_create_and_disable_user_role_invite(self) -> None:
        settings.auth_enabled = True
        with self._patch_users():
            created = self.client.post(
                "/api/v1/admin/invite-codes",
                json={"expires_hours": 48, "max_uses": 2},
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            invite = created.json()["data"]
            self.assertEqual(invite["role"], "user")

            disabled = self.client.patch(
                f"/api/v1/admin/invite-codes/{invite['invite_id']}/disable",
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )
            self.assertEqual(disabled.status_code, 200, disabled.text)
            self.assertEqual(disabled.json()["data"]["status"], "disabled")

    def test_admin_account_cannot_be_disabled(self) -> None:
        settings.auth_enabled = True
        with self._patch_users():
            response = self.client.patch(
                f"/api/v1/admin/users/{self.admin.user_id}/status",
                json={"status": "disabled"},
                headers={"Authorization": f"Bearer {self.admin_token}"},
            )
        self.assertEqual(response.status_code, 400)


class InviteStatusApiTest(ComputationTestCase):
    """覆盖邀请码状态列表。"""

    def test_invite_list_contains_usage_and_status(self) -> None:
        now = datetime.now()
        record = InviteCodeRecord(
            invite_id="invite_test",
            invite_code="code_test",
            role="user",
            status="active",
            expires_at=now + timedelta(hours=1),
            max_uses=1,
            used_count=0,
            created_by="admin_test",
            created_at=now,
            updated_at=now,
        )
        InviteCodeRepository.save(record)
        response = self.client.get("/api/v1/admin/invite-codes")
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["data"]["items"][0]
        self.assertEqual(item["invite_id"], "invite_test")
        self.assertEqual(item["used_count"], 0)

    def test_local_demo_mode_can_create_user_invite(self) -> None:
        response = self.client.post(
            "/api/v1/admin/invite-codes",
            json={"expires_hours": 24, "max_uses": 1},
        )
        self.assertEqual(response.status_code, 200, response.text)
        invite = response.json()["data"]
        self.assertEqual(invite["role"], "user")
        self.assertEqual(invite["created_by"], "system")
