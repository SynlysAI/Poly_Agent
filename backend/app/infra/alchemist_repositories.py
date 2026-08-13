"""ALchemist 实验设计模块仓储。

与主业务仓储一致：本地环境使用 SQLite，生产环境使用 MongoDB。
"""

from __future__ import annotations

from typing import Any

from app.core.time import utc_now
from app.infra.computation_repositories import BaseRepository
from app.infra.mongo import get_alchemist_sessions_collection


class AlchemistSessionRepository(BaseRepository):
    """ALchemist Session 仓储。"""

    collection_name = "alchemist_sessions"

    @classmethod
    def _collection(cls):
        return get_alchemist_sessions_collection()

    @classmethod
    def save(cls, session_doc: dict[str, Any]) -> None:
        """保存或更新 Session 文档。"""
        payload = dict(session_doc)
        payload["updated_at"] = utc_now()
        super().save("session_id", payload)

    @classmethod
    def find_by_id(cls, session_id: str) -> dict[str, Any] | None:
        """按 session_id 查询。"""
        return cls.find_one({"session_id": session_id})

    @classmethod
    def delete(cls, session_id: str) -> bool:
        """删除 Session。"""
        return cls.delete_one("session_id", session_id)

    @classmethod
    def list_by_user(
        cls,
        created_by: str | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 Session 列表。"""
        filters: dict[str, Any] = {}
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(
            filters,
            sort_field="updated_at",
            reverse=True,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def update_fields(cls, session_id: str, fields: dict[str, Any]) -> bool:
        """更新 Session 部分字段。"""
        payload = dict(fields)
        payload["updated_at"] = utc_now()
        return super().update_fields("session_id", session_id, payload)
