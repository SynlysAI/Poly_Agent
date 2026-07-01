"""计算智能模块仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo.errors import PyMongoError

from app.infra.demo_store import clone_document, demo_store
from app.infra.mongo import (
    get_audit_events_collection,
    get_computation_artifacts_collection,
    get_computation_runs_collection,
    get_optimization_campaigns_collection,
    get_optimization_candidates_collection,
    get_optimization_observations_collection,
    get_optimization_suggestions_collection,
)

_mongo_unavailable = False


def _without_mongo_id(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """去掉 MongoDB 内部 ID。"""
    if not document:
        return None
    cleaned = dict(document)
    cleaned.pop("_id", None)
    return cleaned


def _matches(document: dict[str, Any], filters: dict[str, Any]) -> bool:
    """判断 demo 存储文档是否匹配过滤条件。"""
    for key, expected in filters.items():
        if expected is None:
            continue
        value: Any = document
        for part in key.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if isinstance(expected, set):
            if value not in expected:
                return False
        elif isinstance(expected, str) and expected.startswith("__contains__:"):
            needle = expected.removeprefix("__contains__:").lower()
            haystack = " ".join(
                str(document.get(field, ""))
                for field in ("run_id", "campaign_id", "suggestion_id")
            )
            molecule = document.get("molecule") or {}
            haystack = f"{haystack} {molecule.get('name', '')} {molecule.get('smiles', '')}".lower()
            if needle not in haystack:
                return False
        elif value != expected:
            return False
    return True


def _sort_documents(documents: list[dict[str, Any]], field: str, reverse: bool = True) -> list[dict[str, Any]]:
    """按字段排序 demo 文档。"""
    return sorted(documents, key=lambda item: str(item.get(field, "")), reverse=reverse)


class BaseRepository:
    """Mongo 优先、本地 JSON 兜底的仓储基类。"""

    collection_name: str

    @classmethod
    def _can_use_mongo(cls) -> bool:
        """判断当前进程是否继续尝试 MongoDB。"""
        return not _mongo_unavailable

    @classmethod
    def _mark_mongo_unavailable(cls) -> None:
        """标记 MongoDB 当前不可用。"""
        global _mongo_unavailable
        _mongo_unavailable = True

    @classmethod
    def _collection(cls):
        raise NotImplementedError

    @classmethod
    def save(cls, key_field: str, document: dict[str, Any]) -> None:
        """保存单条文档。"""
        payload = clone_document(document)
        if cls._can_use_mongo():
            try:
                cls._collection().update_one({key_field: payload[key_field]}, {"$set": payload}, upsert=True)
                return
            except PyMongoError:
                cls._mark_mongo_unavailable()

        def mutate(data):
            rows = data[cls.collection_name]
            for index, item in enumerate(rows):
                if item.get(key_field) == payload[key_field]:
                    rows[index] = payload
                    return None
            rows.append(payload)
            return None

        demo_store.mutate(mutate)

    @classmethod
    def find_one(cls, filters: dict[str, Any]) -> dict[str, Any] | None:
        """查询单条文档。"""
        if cls._can_use_mongo():
            try:
                doc = cls._collection().find_one(filters, {"_id": 0})
                return _without_mongo_id(doc)
            except PyMongoError:
                cls._mark_mongo_unavailable()
        data = demo_store.load()
        for item in data[cls.collection_name]:
            if _matches(item, filters):
                return clone_document(item)
        return None

    @classmethod
    def list_all(
        cls,
        filters: dict[str, Any] | None = None,
        *,
        sort_field: str = "created_at",
        reverse: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询文档。"""
        filters = filters or {}
        skip = (page - 1) * page_size
        if cls._can_use_mongo():
            try:
                collection = cls._collection()
                total = int(collection.count_documents(filters))
                cursor = collection.find(filters, {"_id": 0}).sort([(sort_field, -1 if reverse else 1)]).skip(skip).limit(page_size)
                return [dict(item) for item in cursor], total
            except PyMongoError:
                cls._mark_mongo_unavailable()
        data = demo_store.load()
        rows = [clone_document(item) for item in data[cls.collection_name] if _matches(item, filters)]
        rows = _sort_documents(rows, sort_field, reverse=reverse)
        return rows[skip : skip + page_size], len(rows)


class ComputationRunRepository(BaseRepository):
    """计算任务仓储。"""

    collection_name = "computation_runs"

    @classmethod
    def _collection(cls):
        return get_computation_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        status: str | None,
        workflow_type: str | None,
        engine: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询计算任务。"""
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if workflow_type:
            filters["workflow_type"] = workflow_type
        if engine:
            filters["engine"] = engine
        if keyword:
            filters["$or"] = [
                {"run_id": {"$regex": keyword, "$options": "i"}},
                {"molecule.name": {"$regex": keyword, "$options": "i"}},
                {"molecule.smiles": {"$regex": keyword, "$options": "i"}},
            ]
            demo_filters = dict(filters)
            demo_filters.pop("$or", None)
            demo_filters["keyword"] = f"__contains__:{keyword}"
        else:
            demo_filters = filters

        skip = (page - 1) * page_size
        if cls._can_use_mongo():
            try:
                collection = cls._collection()
                total = int(collection.count_documents(filters))
                cursor = collection.find(filters, {"_id": 0}).sort([("created_at", -1)]).skip(skip).limit(page_size)
                return [dict(item) for item in cursor], total
            except PyMongoError:
                cls._mark_mongo_unavailable()
        data = demo_store.load()
        rows = [clone_document(item) for item in data[cls.collection_name] if _matches(item, demo_filters)]
        rows = _sort_documents(rows, "created_at", reverse=True)
        return rows[skip : skip + page_size], len(rows)

    @classmethod
    def update_fields(cls, run_id: str, fields: dict[str, Any]) -> bool:
        """更新计算任务字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"run_id": run_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError:
                cls._mark_mongo_unavailable()

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id:
                    item.update(clone_document(fields))
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class ComputationArtifactRepository(BaseRepository):
    """计算 artifact 仓储。"""

    collection_name = "computation_artifacts"

    @classmethod
    def _collection(cls):
        return get_computation_artifacts_collection()

    @classmethod
    def list_by_run(cls, run_id: str) -> list[dict[str, Any]]:
        """按 run_id 查询 artifact。"""
        items, _ = cls.list_all({"run_id": run_id}, sort_field="created_at", page=1, page_size=200)
        return items


class OptimizationCampaignRepository(BaseRepository):
    """优化 campaign 仓储。"""

    collection_name = "optimization_campaigns"

    @classmethod
    def _collection(cls):
        return get_optimization_campaigns_collection()

    @classmethod
    def update_fields(cls, campaign_id: str, fields: dict[str, Any]) -> bool:
        """更新 campaign 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"campaign_id": campaign_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError:
                cls._mark_mongo_unavailable()

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("campaign_id") == campaign_id:
                    item.update(clone_document(fields))
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class OptimizationCandidateRepository(BaseRepository):
    """优化 candidate 仓储。"""

    collection_name = "optimization_candidates"

    @classmethod
    def _collection(cls):
        return get_optimization_candidates_collection()

    @classmethod
    def list_by_campaign(cls, campaign_id: str) -> list[dict[str, Any]]:
        """查询 campaign 下的候选。"""
        items, _ = cls.list_all({"campaign_id": campaign_id}, sort_field="candidate_key", reverse=False, page=1, page_size=1000)
        return items


class OptimizationSuggestionRepository(BaseRepository):
    """优化 suggestion 仓储。"""

    collection_name = "optimization_suggestions"

    @classmethod
    def _collection(cls):
        return get_optimization_suggestions_collection()

    @classmethod
    def list_by_campaign(cls, campaign_id: str) -> list[dict[str, Any]]:
        """查询 campaign 下的推荐。"""
        items, _ = cls.list_all({"campaign_id": campaign_id}, sort_field="iteration_index", reverse=False, page=1, page_size=1000)
        return items

    @classmethod
    def update_fields(cls, suggestion_id: str, fields: dict[str, Any]) -> bool:
        """更新推荐字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"suggestion_id": suggestion_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError:
                cls._mark_mongo_unavailable()

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("suggestion_id") == suggestion_id:
                    item.update(clone_document(fields))
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class OptimizationObservationRepository(BaseRepository):
    """优化 observation 仓储。"""

    collection_name = "optimization_observations"

    @classmethod
    def _collection(cls):
        return get_optimization_observations_collection()

    @classmethod
    def list_by_campaign(cls, campaign_id: str) -> list[dict[str, Any]]:
        """查询 campaign 下的 observation。"""
        items, _ = cls.list_all({"campaign_id": campaign_id}, sort_field="created_at", reverse=False, page=1, page_size=1000)
        return items


class AuditEventRepository(BaseRepository):
    """审计事件仓储。"""

    collection_name = "audit_events"

    @classmethod
    def _collection(cls):
        return get_audit_events_collection()

    @classmethod
    def append(cls, document: dict[str, Any]) -> None:
        """写入审计事件。"""
        payload = clone_document(document)
        if cls._can_use_mongo():
            try:
                cls._collection().insert_one(payload)
                return
            except PyMongoError:
                cls._mark_mongo_unavailable()

        def mutate(data):
            data[cls.collection_name].append(payload)
            return None

        demo_store.mutate(mutate)


def utc_now() -> datetime:
    """返回当前 UTC-naive 时间，与现有模型保持 datetime 对象。"""
    return datetime.utcnow()
