"""ALchemist 实验设计模块 MongoDB 仓储。"""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument

from app.core.time import utc_now
from app.infra.mongo import (
    get_alchemist_sessions_collection,
)


class AlchemistSessionRepository:
    """ALchemist Session 仓储。"""

    COLLECTION = "alchemist_sessions"

    @staticmethod
    def _collection():
        return get_alchemist_sessions_collection()

    @staticmethod
    def save(session_doc: dict[str, Any]) -> None:
        """保存或更新 Session 文档。

        Args:
            session_doc: Session 完整文档。
        """
        session_doc["updated_at"] = utc_now()
        get_alchemist_sessions_collection().update_one(
            {"session_id": session_doc["session_id"]},
            {"$set": session_doc},
            upsert=True,
        )

    @staticmethod
    def find_by_id(session_id: str) -> dict[str, Any] | None:
        """按 session_id 查询。

        Args:
            session_id: Session 标识符。

        Returns:
            Session 文档或 None。
        """
        doc = get_alchemist_sessions_collection().find_one(
            {"session_id": session_id}, {"_id": 0}
        )
        return dict(doc) if doc else None

    @staticmethod
    def delete(session_id: str) -> bool:
        """删除 Session。

        Args:
            session_id: Session 标识符。

        Returns:
            是否成功删除。
        """
        result = get_alchemist_sessions_collection().delete_one({"session_id": session_id})
        return result.deleted_count > 0

    @staticmethod
    def list_by_user(
        created_by: str | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 Session 列表。

        Args:
            created_by: 按创建者过滤（None 表示不过滤）。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (文档列表, 总数)。
        """
        filters: dict[str, Any] = {}
        if created_by:
            filters["created_by"] = created_by

        collection = get_alchemist_sessions_collection()
        total = int(collection.count_documents(filters))
        skip = (page - 1) * page_size
        cursor = (
            collection.find(filters, {"_id": 0})
            .sort([("updated_at", -1)])
            .skip(skip)
            .limit(page_size)
        )
        return [dict(item) for item in cursor], total

    @staticmethod
    def update_fields(session_id: str, fields: dict[str, Any]) -> bool:
        """更新 Session 部分字段。

        Args:
            session_id: Session 标识符。
            fields: 待更新的字段字典。

        Returns:
            是否命中并更新。
        """
        fields["updated_at"] = utc_now()
        result = get_alchemist_sessions_collection().update_one(
            {"session_id": session_id}, {"$set": fields}
        )
        return result.matched_count > 0
