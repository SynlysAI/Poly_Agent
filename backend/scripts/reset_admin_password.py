"""受控重置共享认证库中的管理员密码。"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.infra.repositories import UserRepository
from app.services.auth_service import AuthService


PASSWORD_ENV_NAME = "POLY_AGENT_ADMIN_NEW_PASSWORD"


def _user_field(user: Any, field_name: str) -> Any:
    """兼容对象与字典两种用户记录形式读取字段。

    Args:
        user: 用户记录。
        field_name: 字段名。

    Returns:
        对应字段值。
    """
    if hasattr(user, field_name):
        return getattr(user, field_name)
    if isinstance(user, dict):
        return user.get(field_name)
    raise ValueError(f"用户记录缺少字段：{field_name}")


def _validate_password_strength(new_password: str) -> None:
    """校验新密码强度，避免生产账号使用弱口令。

    Args:
        new_password: 待设置的新密码。

    Raises:
        ValueError: 密码长度不足或字符类别不足。
    """
    if len(new_password) < 12:
        raise ValueError("密码强度不足：长度至少需要 12 位")
    categories = sum(
        (
            any(char.islower() for char in new_password),
            any(char.isupper() for char in new_password),
            any(char.isdigit() for char in new_password),
            any(not char.isalnum() for char in new_password),
        )
    )
    if categories < 3:
        raise ValueError("密码强度不足：需至少包含大写、小写、数字、符号中的三类")


def reset_admin_password(
    username: str,
    new_password: str,
    *,
    user_repository: Any = None,
    hash_password: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """重置已存在且启用中的管理员密码。

    Args:
        username: 管理员用户名。
        new_password: 新密码明文，仅在函数调用期间存在。
        user_repository: 可注入的用户仓储，测试使用。
        hash_password: 可注入的密码哈希函数，测试使用。

    Returns:
        不包含密码明文的重置结果。

    Raises:
        ValueError: 用户不存在、状态不可用或密码强度不足。
    """
    repository = user_repository or UserRepository
    password_hasher = hash_password or AuthService.hash_password
    _validate_password_strength(new_password)

    user = repository.find_by_username(username)
    if not user:
        raise ValueError(f"管理员不存在：{username}")
    if _user_field(user, "role") != "admin":
        raise ValueError(f"用户不是管理员：{username}")
    if _user_field(user, "status") != "active":
        raise ValueError(f"管理员当前不可用：{username}")

    user_id = str(_user_field(user, "user_id"))
    repository.update_fields(
        "user_id",
        user_id,
        {
            "password_hash": password_hasher(new_password),
            "updated_at": datetime.now(),
        },
    )
    return {"user_id": user_id}


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="受控重置共享认证库中的管理员密码；新密码仅从环境变量读取。"
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="要重置的管理员用户名，默认 admin。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行命令行重置流程。

    Args:
        argv: 命令行参数；测试可注入。

    Returns:
        进程退出码，0 表示成功。
    """
    args = build_parser().parse_args(argv)
    new_password = os.getenv(PASSWORD_ENV_NAME, "")
    if not new_password:
        print(f"请先通过安全方式设置 {PASSWORD_ENV_NAME}", file=sys.stderr)
        return 1

    try:
        result = reset_admin_password(
            username=args.username,
            new_password=new_password,
            user_repository=UserRepository,
            hash_password=AuthService.hash_password,
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"管理员密码已重置：username={args.username}, user_id={result['user_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
