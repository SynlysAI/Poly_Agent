"""用户与邀请码仓储。

本地环境使用 SQLite，生产环境使用 MongoDB；公共读写逻辑由 BaseRepository
统一提供。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.infra.computation_repositories import BaseRepository
from app.infra.mongo import (
    get_invite_codes_collection,
    get_users_collection,
)
from app.infra.sqlite_store import clone_document, demo_store
from app.schemas.identity_runtime import InviteCodeRecord, UserRecord


class UserRepository(BaseRepository):
    """用户仓储。"""

    collection_name = "users"

    @classmethod
    def _collection(cls):
        return get_users_collection()

    @classmethod
    def save(cls, user_record: UserRecord) -> None:
        """保存用户记录。"""
        super().save("user_id", user_record.model_dump(mode="python"))

    @classmethod
    def find_by_username(cls, username: str) -> UserRecord | None:
        """按用户名查询用户记录。"""
        doc = cls.find_one({"username": username})
        return UserRecord(**doc) if doc else None

    @classmethod
    def find_by_user_id(cls, user_id: str) -> UserRecord | None:
        """按用户 ID 查询用户记录。"""
        doc = cls.find_one({"user_id": user_id})
        return UserRecord(**doc) if doc else None

    @classmethod
    def update_last_login(cls, user_id: str) -> None:
        """更新用户最近登录时间。"""
        now = datetime.now()
        cls.update_fields(
            "user_id",
            user_id,
            {"last_login_at": now, "updated_at": now},
        )

    @classmethod
    def list_all(cls) -> list[UserRecord]:
        """查询全部用户列表。"""
        items, _ = BaseRepository.list_all(
            cls,
            {},
            sort_field="created_at",
            page=1,
            page_size=100_000,
        )
        return [UserRecord(**doc) for doc in items]

    @classmethod
    def update_status(cls, user_id: str, status: str) -> bool:
        """更新用户状态。"""
        return cls.update_fields(
            "user_id",
            user_id,
            {"status": status, "updated_at": datetime.now()},
        )

    @classmethod
    def count_active_admins(cls) -> int:
        """统计启用中的管理员数量。"""
        return cls.count({"role": "admin", "status": "active"})


class InviteCodeRepository(BaseRepository):
    """邀请码仓储。"""

    collection_name = "invite_codes"

    @classmethod
    def _collection(cls):
        return get_invite_codes_collection()

    @classmethod
    def save(cls, invite_record: InviteCodeRecord) -> None:
        """保存邀请码记录。"""
        super().save("invite_id", invite_record.model_dump(mode="python"))

    @classmethod
    def find_by_code(cls, invite_code: str) -> InviteCodeRecord | None:
        """按邀请码查询记录。"""
        doc = cls.find_one({"invite_code": invite_code})
        return InviteCodeRecord(**doc) if doc else None

    @classmethod
    def consume_available_code(
        cls,
        invite_code: str,
        now: datetime,
    ) -> InviteCodeRecord | None:
        """原子消费一个仍可使用的邀请码。"""
        if cls._can_use_mongo():
            doc = cls._collection().find_one_and_update(
                {
                    "invite_code": invite_code,
                    "status": "active",
                    "expires_at": {"$gt": now},
                    "$expr": {"$lt": ["$used_count", "$max_uses"]},
                },
                {
                    "$inc": {"used_count": 1},
                    "$set": {"updated_at": datetime.now()},
                },
                projection={"_id": 0},
                return_document=True,
            )
            return InviteCodeRecord(**doc) if doc else None

        def mutate(data: dict[str, list[dict[str, Any]]]) -> InviteCodeRecord | None:
            for item in data[cls.collection_name]:
                if item.get("invite_code") != invite_code:
                    continue
                expires_at = item.get("expires_at")
                if isinstance(expires_at, str):
                    try:
                        expires_at = datetime.fromisoformat(expires_at)
                    except ValueError:
                        expires_at = None
                if item.get("status") != "active":
                    return None
                if not expires_at or expires_at <= now:
                    return None
                used_count = int(item.get("used_count", 0))
                max_uses = int(item.get("max_uses", 0))
                if used_count >= max_uses:
                    return None
                item["used_count"] = used_count + 1
                item["updated_at"] = now
                return InviteCodeRecord(**clone_document(item))
            return None

        return demo_store.mutate(mutate)

    @classmethod
    def rollback_usage(cls, invite_id: str) -> None:
        """回滚邀请码使用次数。"""
        if cls._can_use_mongo():
            cls._collection().update_one(
                {"invite_id": invite_id},
                {
                    "$inc": {"used_count": -1},
                    "$set": {"updated_at": datetime.now()},
                },
            )
            return

        def mutate(data: dict[str, list[dict[str, Any]]]) -> None:
            for item in data[cls.collection_name]:
                if item.get("invite_id") == invite_id:
                    item["used_count"] = max(0, int(item.get("used_count", 0)) - 1)
                    item["updated_at"] = datetime.now()
                    return None
            return None

        demo_store.mutate(mutate)

    @classmethod
    def list_all(cls) -> list[InviteCodeRecord]:
        """查询全部邀请码列表。"""
        items, _ = BaseRepository.list_all(
            cls,
            {},
            sort_field="created_at",
            page=1,
            page_size=100_000,
        )
        return [InviteCodeRecord(**doc) for doc in items]

    @classmethod
    def disable(cls, invite_id: str) -> bool:
        """禁用邀请码。"""
        return cls.update_fields(
            "invite_id",
            invite_id,
            {"status": "disabled", "updated_at": datetime.now()},
        )
