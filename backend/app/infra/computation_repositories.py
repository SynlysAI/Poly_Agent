"""计算智能模块仓储。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument

from app.core.config import settings
from app.infra.demo_store import clone_document, demo_store
from app.infra.mongo import (
    get_audit_events_collection,
    get_computation_artifacts_collection,
    get_computation_runs_collection,
    get_optimization_campaigns_collection,
    get_optimization_candidates_collection,
    get_optimization_observations_collection,
    get_optimization_suggestions_collection,
    get_service_integrations_collection,
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
        if isinstance(expected, dict):
            if "$ne" in expected and value == expected["$ne"]:
                return False
            if "$in" in expected:
                allowed = expected["$in"]
                if isinstance(value, list):
                    if not any(item in value for item in allowed):
                        return False
                elif value not in allowed:
                    return False
        elif isinstance(expected, set):
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


def _set_dotted_field(document: dict[str, Any], key: str, value: Any) -> None:
    """Apply Mongo-style dotted updates to demo-store documents."""
    parts = key.split(".")
    current = document
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = clone_document(value)


def _apply_update_fields(document: dict[str, Any], fields: dict[str, Any]) -> None:
    """Apply update fields while honoring dotted keys in demo storage."""
    for key, value in fields.items():
        if "." in key:
            _set_dotted_field(document, key, value)
        else:
            document[key] = clone_document(value)


def _coerce_datetime(value: Any) -> datetime | None:
    """Convert demo-store datetime strings back to datetime for comparisons."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


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
    def _handle_mongo_error(cls, exc: PyMongoError) -> None:
        """Handle MongoDB errors according to the deployment storage policy."""
        cls._mark_mongo_unavailable()
        if settings.require_mongodb:
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB 不可用，已禁止本地 demo-store 兜底：{exc.__class__.__name__}",
            ) from exc

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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
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
        created_by: str | None = None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询计算任务。"""
        filters: dict[str, Any] = {}
        if created_by:
            filters["created_by"] = created_by
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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def acquire_queued_run(cls, *, worker_id: str, now: datetime) -> dict[str, Any] | None:
        """原子领取一个 queued run。"""
        fields = {
            "status": "running",
            "started_at": now,
            "updated_at": now,
            "external_refs.worker_id": worker_id,
            "external_refs.claimed_at": now,
            "external_refs.heartbeat_at": now,
        }
        if cls._can_use_mongo():
            try:
                doc = cls._collection().find_one_and_update(
                    {"status": "queued"},
                    {"$set": fields},
                    sort=[("created_at", 1)],
                    projection={"_id": 0},
                    return_document=ReturnDocument.AFTER,
                )
                return _without_mongo_id(doc)
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            queued = [
                item for item in data[cls.collection_name]
                if item.get("status") == "queued"
            ]
            queued = _sort_documents(queued, "created_at", reverse=False)
            if not queued:
                return None
            run_id = queued[0].get("run_id")
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id and item.get("status") == "queued":
                    external_refs = dict(item.get("external_refs") or {})
                    external_refs["worker_id"] = worker_id
                    external_refs["claimed_at"] = now
                    external_refs["heartbeat_at"] = now
                    item.update(
                        {
                            "status": "running",
                            "started_at": now,
                            "updated_at": now,
                            "external_refs": external_refs,
                        }
                    )
                    return clone_document(item)
            return None

        return demo_store.mutate(mutate)

    @classmethod
    def list_stale_running(cls, *, stale_before: datetime) -> list[dict[str, Any]]:
        """List running runs whose worker heartbeat is stale."""
        filters = {"status": "running", "external_refs.heartbeat_at": {"$lt": stale_before}}
        if cls._can_use_mongo():
            try:
                cursor = cls._collection().find(filters, {"_id": 0}).sort([("updated_at", 1)])
                return [dict(item) for item in cursor]
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        data = demo_store.load()
        rows: list[dict[str, Any]] = []
        for item in data[cls.collection_name]:
            if item.get("status") != "running":
                continue
            heartbeat_at = _coerce_datetime((item.get("external_refs") or {}).get("heartbeat_at"))
            if heartbeat_at and heartbeat_at < stale_before:
                rows.append(clone_document(item))
        return _sort_documents(rows, "updated_at", reverse=False)

    @classmethod
    def list_wallclock_expired_running(cls, *, safety_factor: float, now: datetime) -> list[dict[str, Any]]:
        """List running runs whose wallclock time exceeds max_wallclock_seconds * safety_factor."""
        from datetime import timedelta

        results: list[dict[str, Any]] = []
        if cls._can_use_mongo():
            try:
                cursor = cls._collection().find(
                    {"status": "running", "started_at": {"$exists": True}},
                    {"_id": 0},
                ).sort([("updated_at", 1)])
                for doc in cursor:
                    resources = doc.get("resources") or {}
                    max_wallclock = int(resources.get("max_wallclock_seconds", 0) or 0)
                    started_at = doc.get("started_at")
                    if max_wallclock <= 0 or started_at is None:
                        continue
                    if started_at + timedelta(seconds=max_wallclock * safety_factor) < now:
                        results.append(dict(doc))
                return results
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        # Demo-store fallback
        data = demo_store.load()
        for item in data[cls.collection_name]:
            if item.get("status") != "running":
                continue
            started_at = _coerce_datetime(item.get("started_at"))
            if started_at is None:
                continue
            resources = item.get("resources") or {}
            max_wallclock = int(resources.get("max_wallclock_seconds", 0) or 0)
            if max_wallclock <= 0:
                continue
            deadline = started_at + timedelta(seconds=max_wallclock * safety_factor)
            if deadline < now:
                results.append(clone_document(item))
        return _sort_documents(results, "updated_at", reverse=False)


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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("campaign_id") == campaign_id:
                    _apply_update_fields(item, fields)
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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("suggestion_id") == suggestion_id:
                    _apply_update_fields(item, fields)
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


class ServiceIntegrationRepository(BaseRepository):
    """外部服务集成配置仓储。"""

    collection_name = "service_integrations"

    @classmethod
    def _collection(cls):
        return get_service_integrations_collection()

    @classmethod
    def list_configs(cls) -> list[dict[str, Any]]:
        """查询全部服务集成配置。"""
        items, _ = cls.list_all({}, sort_field="service_key", reverse=False, page=1, page_size=200)
        return items

    @classmethod
    def update_fields(cls, service_key: str, fields: dict[str, Any]) -> bool:
        """更新集成配置字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"service_key": service_key}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("service_key") == service_key:
                    item.update(clone_document(fields))
                    return True
            return False

        return bool(demo_store.mutate(mutate))


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
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            data[cls.collection_name].append(payload)
            return None

        demo_store.mutate(mutate)

    @classmethod
    def list_events(
        cls,
        *,
        entity_type: str | None,
        entity_id: str | None,
        event_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询审计事件。"""
        filters: dict[str, Any] = {}
        if entity_type:
            filters["entity_type"] = entity_type
        if entity_id:
            filters["entity_id"] = entity_id
        if event_type:
            filters["event_type"] = event_type
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


def utc_now() -> datetime:
    """返回当前 UTC-naive 时间，与现有模型保持 datetime 对象。"""
    return datetime.utcnow()
