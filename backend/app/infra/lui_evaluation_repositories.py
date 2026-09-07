"""LUI 评测手动运行任务仓储。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import PyMongoError

from app.infra.computation_repositories import BaseRepository, clone_document
from app.infra.mongo import get_lui_evaluation_jobs_collection


_lui_evaluation_job_indexes_ensured = False
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _utcnow() -> datetime:
    """获取当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class LuiEvaluationJobRepository(BaseRepository):
    """LUI 评测任务 MongoDB 仓储。"""

    collection_name = "lui_evaluation_jobs"

    @classmethod
    def _ensure_indexes_once(cls) -> None:
        """确保任务索引只在当前进程内创建一次。"""
        global _lui_evaluation_job_indexes_ensured
        if _lui_evaluation_job_indexes_ensured:
            return
        cls.ensure_indexes()
        _lui_evaluation_job_indexes_ensured = True

    @classmethod
    def _collection(cls):
        """返回 Mongo 集合。"""
        return get_lui_evaluation_jobs_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        """创建任务查询索引。"""
        if not cls._can_use_mongo():
            return
        try:
            collection = cls._collection()
            collection.create_index("job_id", unique=True)
            collection.create_index([("created_at", -1)])
            collection.create_index("status")
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def save_job(cls, document: dict[str, Any]) -> None:
        """创建或更新任务文档。

        Args:
            document: 任务完整文档。
        """
        cls.save("job_id", document)

    @classmethod
    def find_by_job_id(cls, job_id: str) -> dict[str, Any] | None:
        """按任务 ID 查询任务。

        Args:
            job_id: 任务唯一 ID。

        Returns:
            任务文档；不存在时返回 None。
        """
        return cls.find_one({"job_id": job_id})

    @classmethod
    def find_latest(cls) -> dict[str, Any] | None:
        """查询最新任务。

        Returns:
            最新任务文档；不存在时返回 None。
        """
        items, _ = cls.list_jobs(page=1, page_size=1)
        return items[0] if items else None

    @classmethod
    def find_active_job(cls) -> dict[str, Any] | None:
        """查询当前非终态任务。

        Returns:
            首个非终态任务；不存在时返回 None。
        """
        items, _ = cls.list_jobs(page=1, page_size=100)
        return next((item for item in items if item.get("status") not in TERMINAL_JOB_STATUSES), None)

    @classmethod
    def list_jobs(
        cls,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询任务历史。

        Args:
            page: 页码，从 1 开始。
            page_size: 每页数量。

        Returns:
            任务列表与总数。
        """
        return cls.list_all(page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, job_id: str, fields: dict[str, Any]) -> bool:
        """增量更新任务字段。

        Args:
            job_id: 任务唯一 ID。
            fields: 待更新字段。

        Returns:
            是否更新到已有任务。
        """
        payload = clone_document(fields)
        payload["updated_at"] = payload.get("updated_at") or _utcnow()
        if cls._can_use_mongo():
            cls._ensure_indexes_once()
            try:
                result = cls._collection().update_one({"job_id": job_id}, {"$set": payload})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        from app.infra.computation_repositories import demo_store, _apply_update_fields

        def mutate(data: dict[str, list[dict[str, Any]]]) -> bool:
            """更新本地兜底存储中的任务。"""
            for item in data[cls.collection_name]:
                if item.get("job_id") == job_id:
                    _apply_update_fields(item, payload)
                    return True
            return False

        return bool(demo_store.mutate_collection(cls.collection_name, mutate))
