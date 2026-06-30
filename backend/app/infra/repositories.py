"""MongoDB 仓储封装。"""

from __future__ import annotations

from datetime import datetime

from app.infra.mongo import (
    get_invite_codes_collection,
    get_users_collection,
)
from app.schemas.identity_runtime import InviteCodeRecord, UserRecord


class UserRepository:
    """用户仓储。"""

    @staticmethod
    def save(user_record: UserRecord) -> None:
        """保存用户记录。

        Args:
            user_record: 待保存的用户运行态实体。
        """
        get_users_collection().update_one(
            {"user_id": user_record.user_id},
            {"$set": user_record.model_dump(mode="python")},
            upsert=True,
        )

    @staticmethod
    def find_by_username(username: str) -> UserRecord | None:
        """按用户名查询用户记录。

        Args:
            username: 用户名。

        Returns:
            命中的用户记录；若不存在则返回 None。
        """
        doc = get_users_collection().find_one({"username": username}, {"_id": 0})
        return UserRecord(**doc) if doc else None

    @staticmethod
    def find_by_user_id(user_id: str) -> UserRecord | None:
        """按用户 ID 查询用户记录。

        Args:
            user_id: 用户 ID。

        Returns:
            命中的用户记录；若不存在则返回 None。
        """
        doc = get_users_collection().find_one({"user_id": user_id}, {"_id": 0})
        return UserRecord(**doc) if doc else None

    @staticmethod
    def update_last_login(user_id: str) -> None:
        """更新用户最近登录时间。

        Args:
            user_id: 用户 ID。
        """
        get_users_collection().update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "last_login_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
            },
        )

    @staticmethod
    def list_all() -> list[UserRecord]:
        """查询全部用户列表。

        Returns:
            用户记录列表。
        """
        cursor = get_users_collection().find({}, {"_id": 0}).sort([("created_at", -1)])
        return [UserRecord(**doc) for doc in cursor]

    @staticmethod
    def update_status(user_id: str, status: str) -> bool:
        """更新用户状态。

        Args:
            user_id: 用户 ID。
            status: 用户状态。

        Returns:
            是否成功命中并更新用户。
        """
        result = get_users_collection().update_one(
            {"user_id": user_id},
            {"$set": {"status": status, "updated_at": datetime.now()}},
        )
        return result.matched_count > 0

    @staticmethod
    def count_active_admins() -> int:
        """统计启用中的管理员数量。

        Returns:
            当前状态为 active 的管理员数量。
        """
        return int(
            get_users_collection().count_documents(
                {
                    "role": "admin",
                    "status": "active",
                }
            )
        )


class InviteCodeRepository:
    """邀请码仓储。"""

    @staticmethod
    def save(invite_record: InviteCodeRecord) -> None:
        """保存邀请码记录。

        Args:
            invite_record: 待保存的邀请码运行态实体。
        """
        get_invite_codes_collection().update_one(
            {"invite_id": invite_record.invite_id},
            {"$set": invite_record.model_dump(mode="python")},
            upsert=True,
        )

    @staticmethod
    def find_by_code(invite_code: str) -> InviteCodeRecord | None:
        """按邀请码查询记录。

        Args:
            invite_code: 邀请码。

        Returns:
            命中的邀请码记录；若不存在则返回 None。
        """
        doc = get_invite_codes_collection().find_one({"invite_code": invite_code}, {"_id": 0})
        return InviteCodeRecord(**doc) if doc else None

    @staticmethod
    def consume_available_code(invite_code: str, now: datetime) -> InviteCodeRecord | None:
        """原子消费一个仍可使用的邀请码。

        Args:
            invite_code: 邀请码。
            now: 当前时间。

        Returns:
            消费成功后的邀请码记录；若不可用则返回 None。
        """
        doc = get_invite_codes_collection().find_one_and_update(
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

    @staticmethod
    def rollback_usage(invite_id: str) -> None:
        """回滚邀请码使用次数。

        Args:
            invite_id: 邀请码 ID。
        """
        get_invite_codes_collection().update_one(
            {"invite_id": invite_id},
            {
                "$inc": {"used_count": -1},
                "$set": {"updated_at": datetime.now()},
            },
        )

    @staticmethod
    def list_all() -> list[InviteCodeRecord]:
        """查询全部邀请码列表。

        Returns:
            邀请码记录列表。
        """
        cursor = get_invite_codes_collection().find({}, {"_id": 0}).sort([("created_at", -1)])
        return [InviteCodeRecord(**doc) for doc in cursor]

    @staticmethod
    def disable(invite_id: str) -> bool:
        """禁用邀请码。

        Args:
            invite_id: 邀请码 ID。

        Returns:
            是否成功命中并更新邀请码。
        """
        result = get_invite_codes_collection().update_one(
            {"invite_id": invite_id},
            {"$set": {"status": "disabled", "updated_at": datetime.now()}},
        )
        return result.matched_count > 0
