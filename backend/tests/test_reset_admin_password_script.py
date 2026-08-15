"""受控管理员密码重置脚本测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "reset_admin_password.py"
)
SPEC = importlib.util.spec_from_file_location("reset_admin_password_under_test", SCRIPT_PATH)
reset_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reset_module)
sys.modules[SPEC.name] = reset_module


class FakeUserRepository:
    """记录管理员密码更新动作的测试仓储。"""

    def __init__(self, user) -> None:
        self.user = user
        self.updates: list[tuple[str, dict]] = []

    def find_by_username(self, username: str):
        """按用户名返回测试用户。"""
        return self.user if self.user.username == username else None

    def update_fields(self, key_field: str, key_value: str, fields: dict) -> bool:
        """记录待更新字段。"""
        self.updates.append((key_field, key_value, fields))
        return True


def admin_user() -> SimpleNamespace:
    """构造启用中的管理员测试用户。"""
    return SimpleNamespace(
        user_id="u_admin",
        username="admin",
        role="admin",
        status="active",
    )


def test_updates_existing_admin_with_hashed_password() -> None:
    """脚本只写入密码哈希，不保留明文。"""
    repository = FakeUserRepository(admin_user())

    result = reset_module.reset_admin_password(
        username="admin",
        new_password="StrongPassword123",
        user_repository=repository,
        hash_password=lambda password: f"hashed:{password}",
    )

    assert result["user_id"] == "u_admin"
    assert len(repository.updates) == 1
    key_field, key_value, fields = repository.updates[0]
    assert key_field == "user_id"
    assert key_value == "u_admin"
    assert fields["password_hash"] == "hashed:StrongPassword123"
    assert "StrongPassword123" not in result.values()


def test_rejects_weak_password() -> None:
    """弱密码不能进入数据库更新流程。"""
    repository = FakeUserRepository(admin_user())

    try:
        reset_module.reset_admin_password(
            username="admin",
            new_password="weakpassword",
            user_repository=repository,
            hash_password=lambda password: f"hashed:{password}",
        )
    except ValueError as error:
        assert "密码强度不足" in str(error)
    else:
        raise AssertionError("weak password was accepted")

    assert repository.updates == []


def test_main_reads_password_only_from_environment(capsys) -> None:
    """CLI 仅从环境变量读取新密码，并不输出明文。"""
    with (
        patch.dict("os.environ", {"POLY_AGENT_ADMIN_NEW_PASSWORD": "StrongPassword123"}),
        patch.object(reset_module, "reset_admin_password", return_value={"user_id": "u_admin"}) as reset,
    ):
        exit_code = reset_module.main(["--username", "admin"])

    assert exit_code == 0
    reset.assert_called_once_with(
        username="admin",
        new_password="StrongPassword123",
        user_repository=reset_module.UserRepository,
        hash_password=reset_module.AuthService.hash_password,
    )
    assert "StrongPassword123" not in capsys.readouterr().out
