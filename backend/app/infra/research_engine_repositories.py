"""ResearchEngine 领域仓储。

按现有 BaseRepository 模式扩展持久化层，实现 Mongo-first + demo JSON 双模存储。
新增仓储类继承 BaseRepository，遵循 computation_repositories.py 的风格。
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.infra.computation_repositories import (
    BaseRepository,
    _apply_update_fields,
    _matches,
    _sort_documents,
    _without_mongo_id,
    clone_document,
    demo_store,
)
from app.infra.mongo import (
    get_algorithm_packages_collection,
    get_algorithm_registry_entries_collection,
    get_agent_tool_policies_collection,
    get_algorithm_handoffs_collection,
    get_algorithm_resources_collection,
    get_algorithm_runs_collection,
    get_algorithm_versions_collection,
    get_assistant_chats_collection,
    get_assistant_messages_collection,
    get_assistant_runs_collection,
    get_assistant_tool_calls_collection,
    get_execution_decisions_collection,
    get_manual_algorithm_workflows_collection,
    get_research_problem_specs_collection,
    get_research_runs_collection,
    get_workflow_runs_collection,
)


class ResearchProblemSpecRepository(BaseRepository):
    """ProblemSpec 仓储。

    支持 create/get/list/update/freeze，
    按 project_id、campaign_id、created_by 过滤。
    """

    collection_name = "research_problem_specs"

    @classmethod
    def _collection(cls):
        return get_research_problem_specs_collection()

    @classmethod
    def list_problem_specs(
        cls,
        *,
        project_id: str | None = None,
        campaign_id: str | None = None,
        created_by: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        material_family: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 ProblemSpec。

        Args:
            project_id: 按项目 ID 过滤。
            campaign_id: 按 campaign ID 过滤。
            created_by: 按创建者过滤。
            status: 按状态过滤。
            material_family: 按材料体系过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if project_id:
            filters["project_id"] = project_id
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if created_by:
            filters["created_by"] = created_by
        if status:
            filters["status"] = status
        elif not include_archived:
            filters["status"] = {"$ne": "archived"}
        if material_family:
            filters["material_family"] = material_family

        if cls._can_use_mongo():
            return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

        demo_filters = dict(filters)
        exclude_archived = demo_filters.get("status") == {"$ne": "archived"}
        if exclude_archived:
            demo_filters.pop("status", None)
        items, total = cls.list_all(demo_filters, sort_field="created_at", reverse=True, page=1, page_size=10000)
        if exclude_archived:
            items = [item for item in items if item.get("status") != "archived"]
            total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

    @classmethod
    def update_fields(cls, problem_spec_id: str, fields: dict[str, Any]) -> bool:
        """更新 ProblemSpec 字段。

        Args:
            problem_spec_id: ProblemSpec ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"problem_spec_id": problem_spec_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("problem_spec_id") == problem_spec_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def find_by_campaign(cls, campaign_id: str) -> list[dict[str, Any]]:
        """按 campaign_id 查询关联的 ProblemSpec。

        Args:
            campaign_id: Campaign ID。

        Returns:
            ProblemSpec 文档列表。
        """
        items, _ = cls.list_all(
            {"campaign_id": campaign_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=100,
        )
        return items


class AlgorithmRegistryRepository(BaseRepository):
    """AlgorithmRegistry 仓储。

    支持只读清单查询，按 type、material_scope、trigger_mode、status 过滤。
    """

    collection_name = "algorithm_registry_entries"

    @classmethod
    def _collection(cls):
        return get_algorithm_registry_entries_collection()

    @classmethod
    def list_algorithms(
        cls,
        *,
        algorithm_type: str | None = None,
        algorithm_family: str | None = None,
        material_scope: str | None = None,
        trigger_mode: str | None = None,
        status: str | None = None,
        source: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法能力清单。

        Args:
            algorithm_type: 按算法类型过滤（retriever/predictor/simulator/optimizer）。
            algorithm_family: 按产品算法族过滤。
            material_scope: 按材料体系过滤。
            trigger_mode: 按触发方式过滤（human_workflow/autoresearch/system）。
            status: 按状态过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if algorithm_type:
            filters["type"] = algorithm_type
        if algorithm_family:
            filters["algorithm_family"] = algorithm_family
        if material_scope:
            filters["material_scope"] = {"$in": [material_scope]}
        if trigger_mode:
            # 兼容旧数据：查询 "human_workflow" 时也匹配旧值 "human"
            if trigger_mode == "human_workflow":
                filters["trigger_modes"] = {"$in": ["human_workflow", "human"]}
            else:
                filters["trigger_modes"] = {"$in": [trigger_mode]}
        if status:
            filters["status"] = status
        if source:
            filters["source"] = source

        skip = (page - 1) * page_size
        if cls._can_use_mongo():
            try:
                collection = cls._collection()
                total = int(collection.count_documents(filters))
                cursor = (
                    collection.find(filters, {"_id": 0})
                    .sort([("algorithm_id", 1)])
                    .skip(skip)
                    .limit(page_size)
                )
                return [dict(item) for item in cursor], total
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        # Demo store: 先用简单相等条件过滤，再对数组字段做后置过滤
        simple_filters: dict[str, Any] = {}
        if algorithm_type:
            simple_filters["type"] = algorithm_type
        if algorithm_family:
            simple_filters["algorithm_family"] = algorithm_family
        if status:
            simple_filters["status"] = status
        if source:
            simple_filters["source"] = source

        data_demo = demo_store.load()
        rows = [
            clone_document(item)
            for item in data_demo[cls.collection_name]
            if _matches(item, simple_filters)
        ]

        # 后置过滤：material_scope（检查值是否包含在 material_scope 列表中）
        if material_scope:
            rows = [
                row for row in rows
                if material_scope in (row.get("material_scope") or [])
            ]

        # 后置过滤：trigger_modes（检查值是否包含在 trigger_modes 列表中）
        # 兼容旧数据：查询 "human_workflow" 时也匹配旧值 "human"
        if trigger_mode:
            if trigger_mode == "human_workflow":
                rows = [
                    row for row in rows
                    if "human_workflow" in (row.get("trigger_modes") or [])
                    or "human" in (row.get("trigger_modes") or [])
                ]
            else:
                rows = [
                    row for row in rows
                    if trigger_mode in (row.get("trigger_modes") or [])
                ]

        rows = _sort_documents(rows, "algorithm_id", reverse=False)
        return rows[skip : skip + page_size], len(rows)

    @classmethod
    def seed_defaults(cls, entries: list[dict[str, Any]]) -> int:
        """写入默认算法能力清单条目（幂等：已存在的跳过）。

        同时修复已存在条目中的旧 trigger_modes 值（如 "human" -> "human_workflow"）。

        Args:
            entries: 算法条目字典列表。

        Returns:
            实际写入的条目数。
        """
        count = 0
        for entry in entries:
            existing = cls.find_one({"algorithm_id": entry["algorithm_id"]})
            if existing is None:
                cls.save("algorithm_id", entry)
                count += 1
            else:
                patch_fields = {
                    key: entry[key]
                    for key in (
                        "name",
                        "type",
                        "algorithm_family",
                        "material_scope",
                        "task_scope",
                        "input_schema",
                        "output_schema",
                        "call_method",
                        "trigger_modes",
                        "runtime_dependency",
                        "version",
                        "validation_metric",
                        "owner",
                        "status",
                        "description",
                        "active_version_id",
                        "source",
                        "deployment_status",
                        "integration_kind",
                        "capability_group",
                        "contributors",
                        "developer_attribution",
                        "framework_attributions",
                        "method_attributions",
                        "implementation_notes",
                    )
                    if key in entry and entry.get(key) != existing.get(key)
                }
                if patch_fields:
                    cls.update_fields(entry["algorithm_id"], patch_fields)
        return count

    @classmethod
    def update_fields(cls, algorithm_id: str, fields: dict[str, Any]) -> bool:
        """更新算法条目字段。

        Args:
            algorithm_id: 算法 ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"algorithm_id": algorithm_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("algorithm_id") == algorithm_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete(cls, algorithm_id: str) -> bool:
        """删除算法注册表条目。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"algorithm_id": algorithm_id})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item for item in data[cls.collection_name] if item.get("algorithm_id") != algorithm_id
            ]
            return len(data[cls.collection_name]) != before

        return bool(demo_store.mutate(mutate))


class AgentToolPolicyRepository(BaseRepository):
    """算法工具策略仓储。"""

    collection_name = "agent_tool_policies"

    @classmethod
    def _collection(cls):
        return get_agent_tool_policies_collection()

    @classmethod
    def list_policies(cls) -> list[dict[str, Any]]:
        """返回全部策略，按 algorithm_id 稳定排序。"""
        items, _ = cls.list_all({}, sort_field="algorithm_id", reverse=False, page=1, page_size=10000)
        return items

    @classmethod
    def ensure_default(cls, algorithm_id: str) -> tuple[dict[str, Any], bool]:
        """读取策略，不存在时写入安全默认值。"""
        existing = cls.find_one({"algorithm_id": algorithm_id})
        if existing:
            return existing, False
        document = {
            "algorithm_id": algorithm_id,
            "enabled": True,
            "allowed_roles": ["admin", "user"],
            "requires_confirmation": True,
            "updated_by": None,
            "updated_at": None,
        }
        cls.save("algorithm_id", document)
        return document, True

    @classmethod
    def update_fields(cls, algorithm_id: str, fields: dict[str, Any]) -> bool:
        """更新策略字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"algorithm_id": algorithm_id}, {"$set": fields}, upsert=True
                )
                return result.matched_count > 0 or result.upserted_id is not None
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("algorithm_id") == algorithm_id:
                    _apply_update_fields(item, fields)
                    return True
            data[cls.collection_name].append(
                {"algorithm_id": algorithm_id, **clone_document(fields)}
            )
            return True

        return bool(demo_store.mutate(mutate))


class AssistantToolCallRepository(BaseRepository):
    """对话算法工具调用及状态事件仓储。"""

    collection_name = "assistant_tool_calls"

    @classmethod
    def _collection(cls):
        return get_assistant_tool_calls_collection()

    @classmethod
    def update_fields(cls, call_id: str, fields: dict[str, Any]) -> bool:
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"call_id": call_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("call_id") == call_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def append_event(cls, call_id: str, event: dict[str, Any]) -> bool:
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"call_id": call_id},
                    {"$push": {"events": {"$each": [clone_document(event)], "$slice": -200}}},
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("call_id") == call_id:
                    events = item.setdefault("events", [])
                    events.append(clone_document(event))
                    item["events"] = events[-200:]
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def update_if_phase(
        cls,
        call_id: str,
        expected_phases: set[str],
        fields: dict[str, Any],
    ) -> bool:
        """原子认领调用，避免并发重复确认创建多个 AlgorithmRun。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"call_id": call_id, "phase": {"$in": sorted(expected_phases)}},
                    {"$set": fields},
                )
                return result.modified_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("call_id") == call_id and item.get("phase") in expected_phases:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_events(cls, call_id: str) -> list[dict[str, Any]]:
        document = cls.find_one({"call_id": call_id})
        return list(document.get("events") or []) if document else []

    @classmethod
    def list_for_chat(cls, chat_id: str, *, created_by: str | None = None) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {"chat_id": chat_id}
        if created_by is not None:
            filters["created_by"] = created_by
        items, _ = cls.list_all(filters, sort_field="created_at", reverse=False, page=1, page_size=10000)
        return items

    @classmethod
    def delete_for_chat(cls, chat_id: str, *, created_by: str | None = None) -> int:
        filters: dict[str, Any] = {"chat_id": chat_id}
        if created_by is not None:
            filters["created_by"] = created_by
        if cls._can_use_mongo():
            try:
                return int(cls._collection().delete_many(filters).deleted_count)
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [item for item in data[cls.collection_name] if not _matches(item, filters)]
            return before - len(data[cls.collection_name])

        return int(demo_store.mutate(mutate))

    @classmethod
    def delete_for_message(cls, message_id: str, chat_id: str, *, created_by: str) -> int:
        filters = {"message_id": message_id, "chat_id": chat_id, "created_by": created_by}
        if cls._can_use_mongo():
            try:
                return int(cls._collection().delete_many(filters).deleted_count)
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [item for item in data[cls.collection_name] if not _matches(item, filters)]
            return before - len(data[cls.collection_name])

        return int(demo_store.mutate(mutate))


class AssistantChatRepository(BaseRepository):
    """按用户隔离的 assistant chat 仓储。"""

    collection_name = "assistant_chats"

    @classmethod
    def _collection(cls):
        return get_assistant_chats_collection()

    @classmethod
    def list_chats(
        cls,
        *,
        created_by: str,
        query: str | None = None,
        archived: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        filters: dict[str, Any] = {"created_by": created_by, "archived": archived}
        if query:
            safe_query = re.escape(query)
            filters["$or"] = [
                {"title": {"$regex": safe_query, "$options": "i"}},
                {"search_text": {"$regex": safe_query, "$options": "i"}},
            ]
        if cls._can_use_mongo():
            try:
                collection = cls._collection()
                total = int(collection.count_documents(filters))
                cursor = (
                    collection.find(filters, {"_id": 0})
                    .sort([("updated_at", -1)])
                    .skip((page - 1) * page_size)
                    .limit(page_size)
                )
                return [dict(item) for item in cursor], total
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        data = demo_store.load()
        rows = []
        needle = query.lower() if query else None
        for item in data[cls.collection_name]:
            if item.get("created_by") != created_by or bool(item.get("archived", False)) != archived:
                continue
            if needle and needle not in str(item.get("search_text") or item.get("title") or "").lower():
                continue
            rows.append(clone_document(item))
        rows = _sort_documents(rows, "updated_at", reverse=True)
        start = (page - 1) * page_size
        return rows[start : start + page_size], len(rows)

    @classmethod
    def update_owned(cls, chat_id: str, created_by: str, fields: dict[str, Any]) -> bool:
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"chat_id": chat_id, "created_by": created_by}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("chat_id") == chat_id and item.get("created_by") == created_by:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete_owned(cls, chat_id: str, created_by: str) -> bool:
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"chat_id": chat_id, "created_by": created_by})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item
                for item in data[cls.collection_name]
                if not (item.get("chat_id") == chat_id and item.get("created_by") == created_by)
            ]
            return before != len(data[cls.collection_name])

        return bool(demo_store.mutate(mutate))


class AssistantMessageRepository(BaseRepository):
    """按会话和用户隔离的 assistant message 仓储。"""

    collection_name = "assistant_messages"

    @classmethod
    def _collection(cls):
        return get_assistant_messages_collection()

    @classmethod
    def list_for_chat(
        cls,
        chat_id: str,
        created_by: str,
        *,
        page: int = 1,
        page_size: int = 200,
    ) -> tuple[list[dict[str, Any]], int]:
        return cls.list_all(
            {"chat_id": chat_id, "created_by": created_by},
            sort_field="created_at",
            reverse=False,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def update_owned(cls, message_id: str, chat_id: str, created_by: str, fields: dict[str, Any]) -> bool:
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"message_id": message_id, "chat_id": chat_id, "created_by": created_by},
                    {"$set": fields},
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if (
                    item.get("message_id") == message_id
                    and item.get("chat_id") == chat_id
                    and item.get("created_by") == created_by
                ):
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete_owned(cls, message_id: str, chat_id: str, created_by: str) -> bool:
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one(
                    {"message_id": message_id, "chat_id": chat_id, "created_by": created_by}
                )
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item
                for item in data[cls.collection_name]
                if not (
                    item.get("message_id") == message_id
                    and item.get("chat_id") == chat_id
                    and item.get("created_by") == created_by
                )
            ]
            return before != len(data[cls.collection_name])

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete_for_chat(cls, chat_id: str, created_by: str) -> int:
        if cls._can_use_mongo():
            try:
                return int(
                    cls._collection().delete_many({"chat_id": chat_id, "created_by": created_by}).deleted_count
                )
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item
                for item in data[cls.collection_name]
                if not (item.get("chat_id") == chat_id and item.get("created_by") == created_by)
            ]
            return before - len(data[cls.collection_name])

        return int(demo_store.mutate(mutate))


class AssistantRunRepository(BaseRepository):
    """持久化 LUI assistant run 及其可回放事件。"""

    collection_name = "assistant_runs"

    @classmethod
    def _collection(cls):
        return get_assistant_runs_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        if not cls._can_use_mongo():
            return
        try:
            collection = cls._collection()
            collection.create_index("run_id", unique=True)
            collection.create_index(
                "created_by",
                unique=True,
                name="one_active_assistant_run_per_user",
                partialFilterExpression={"active": True},
            )
            collection.create_index([("chat_id", 1), ("created_at", -1)])
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def create_active(cls, document: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """原子创建用户唯一活动 run；冲突时返回现有活动 run。"""
        payload = clone_document(document)
        if cls._can_use_mongo():
            try:
                cls.ensure_indexes()
                cls._collection().insert_one(payload)
                return True, payload
            except DuplicateKeyError:
                return False, cls.find_active_for_user(payload["created_by"]) or {}
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("created_by") == payload["created_by"] and item.get("status") in {"queued", "running"}:
                    return False, clone_document(item)
            data[cls.collection_name].append(payload)
            return True, clone_document(payload)
        return demo_store.mutate(mutate)

    @classmethod
    def find_active_for_user(cls, created_by: str) -> dict[str, Any] | None:
        filters = {"created_by": created_by, "status": {"$in": ["queued", "running"]}}
        if cls._can_use_mongo():
            try:
                return _without_mongo_id(cls._collection().find_one(filters, {"_id": 0}, sort=[("created_at", 1)]))
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        data = demo_store.load()
        rows = [clone_document(x) for x in data[cls.collection_name] if _matches(x, filters)]
        return sorted(rows, key=lambda x: str(x.get("created_at", "")))[0] if rows else None

    @classmethod
    def find_active_for_chat(cls, chat_id: str, created_by: str) -> dict[str, Any] | None:
        filters = {"chat_id": chat_id, "created_by": created_by, "status": {"$in": ["queued", "running"]}}
        return cls.find_one(filters)

    @classmethod
    def update_if_status(cls, run_id: str, statuses: list[str], fields: dict[str, Any]) -> bool:
        filters = {"run_id": run_id, "status": {"$in": statuses}}
        if cls._can_use_mongo():
            try:
                return cls._collection().update_one(filters, {"$set": fields}).matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            for item in data[cls.collection_name]:
                if _matches(item, filters):
                    _apply_update_fields(item, fields)
                    return True
            return False
        return bool(demo_store.mutate(mutate))

    @classmethod
    def update_claim(cls, run_id: str, worker_id: str, fields: dict[str, Any]) -> bool:
        filters = {"run_id": run_id, "status": "running", "worker_id": worker_id}
        if cls._can_use_mongo():
            try:
                return cls._collection().update_one(filters, {"$set": fields}).matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            for item in data[cls.collection_name]:
                if _matches(item, filters):
                    _apply_update_fields(item, fields)
                    return True
            return False
        return bool(demo_store.mutate(mutate))

    @classmethod
    def increment_metric(cls, run_id: str, field: str) -> None:
        if cls._can_use_mongo():
            try:
                cls._collection().update_one({"run_id": run_id}, {"$inc": {field: 1}})
                return
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id:
                    item[field] = int(item.get(field, 0)) + 1
                    return
        demo_store.mutate(mutate)

    @classmethod
    def claim_next(cls, worker_id: str, now: datetime) -> dict[str, Any] | None:
        fields = {"status": "running", "worker_id": worker_id, "started_at": now, "heartbeat_at": now, "updated_at": now}
        if cls._can_use_mongo():
            try:
                document = cls._collection().find_one_and_update(
                    {"status": "queued", "user_message_id": {"$ne": ""}},
                    {"$set": fields},
                    sort=[("created_at", 1)],
                    projection={"_id": 0},
                    return_document=ReturnDocument.AFTER,
                )
                return _without_mongo_id(document)
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            queued = [
                item for item in data[cls.collection_name]
                if item.get("status") == "queued" and item.get("user_message_id")
            ]
            if not queued:
                return None
            selected = sorted(queued, key=lambda x: str(x.get("created_at", "")))[0]
            _apply_update_fields(selected, fields)
            return clone_document(selected)
        return demo_store.mutate(mutate)

    @classmethod
    def requeue_stale(cls, stale_before: datetime, now: datetime) -> list[str]:
        if cls._can_use_mongo():
            try:
                run_ids = [
                    item["run_id"]
                    for item in cls._collection().find(
                        {"status": "running", "heartbeat_at": {"$lt": stale_before}}, {"_id": 0, "run_id": 1}
                    )
                ]
                result = cls._collection().update_many(
                    {"run_id": {"$in": run_ids}, "status": "running"},
                    {"$set": {
                        "status": "queued", "stage": "queued", "worker_id": None, "started_at": None,
                        "heartbeat_at": None, "partial_content": "", "first_token_ms": None, "updated_at": now,
                    }},
                )
                return run_ids[: int(result.modified_count)]
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            run_ids = []
            for item in data[cls.collection_name]:
                heartbeat = item.get("heartbeat_at")
                if item.get("status") == "running" and heartbeat and str(heartbeat) < stale_before.isoformat():
                    _apply_update_fields(item, {
                        "status": "queued", "stage": "queued", "worker_id": None, "started_at": None,
                        "heartbeat_at": None, "partial_content": "", "first_token_ms": None, "updated_at": now,
                    })
                    run_ids.append(item["run_id"])
            return run_ids
        return list(demo_store.mutate(mutate))

    @classmethod
    def append_event(cls, run_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
        if cls._can_use_mongo():
            try:
                current = cls._collection().find_one_and_update(
                    {"run_id": run_id},
                    {"$inc": {"event_seq": 1}},
                    projection={"event_seq": 1},
                    return_document=False,
                )
                if not current:
                    return None
                seq = int(current.get("event_seq", 0)) + 1
                payload = {"seq": seq, **clone_document(event)}
                cls._collection().update_one(
                    {"run_id": run_id},
                    {"$push": {"events": {"$each": [payload], "$slice": -500}}, "$set": {"updated_at": event.get("at")}},
                )
                return payload
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id:
                    seq = int(item.get("event_seq", 0)) + 1
                    item["event_seq"] = seq
                    payload = {"seq": seq, **clone_document(event)}
                    item.setdefault("events", []).append(payload)
                    item["events"] = item["events"][-500:]
                    return payload
            return None
        return demo_store.mutate(mutate)

    @classmethod
    def events_after(cls, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        document = cls.find_one({"run_id": run_id}) or {}
        return [clone_document(e) for e in document.get("events", []) if int(e.get("seq", 0)) > after_seq]

    @classmethod
    def list_for_chat(cls, chat_id: str, created_by: str, page: int = 1, page_size: int = 20):
        return cls.list_all({"chat_id": chat_id, "created_by": created_by}, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class AlgorithmManagedResourceRepository(BaseRepository):
    """算法大资源登记仓储。"""

    collection_name = "algorithm_resources"

    @classmethod
    def _collection(cls):
        return get_algorithm_resources_collection()

    @classmethod
    def update_fields(cls, resource_id: str, fields: dict[str, Any]) -> bool:
        """更新算法大资源字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"resource_id": resource_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("resource_id") == resource_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_resources(
        cls,
        *,
        algorithm_id: str | None = None,
        asset_key: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法大资源。"""
        filters: dict[str, Any] = {}
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if asset_key:
            filters["asset_key"] = asset_key
        if status:
            filters["status"] = status
        return cls.list_all(filters, sort_field="updated_at", reverse=True, page=page, page_size=page_size)


class AlgorithmPackageRepository(BaseRepository):
    """上传算法包仓储。"""

    collection_name = "algorithm_packages"

    @classmethod
    def _collection(cls):
        return get_algorithm_packages_collection()

    @classmethod
    def update_fields(cls, package_id: str, fields: dict[str, Any]) -> bool:
        """更新算法包字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"package_id": package_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("package_id") == package_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete(cls, package_id: str) -> bool:
        """删除算法包记录。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"package_id": package_id})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item for item in data[cls.collection_name] if item.get("package_id") != package_id
            ]
            return len(data[cls.collection_name]) != before

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_packages(
        cls,
        *,
        algorithm_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法上传包。"""
        filters: dict[str, Any] = {}
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class AlgorithmVersionRepository(BaseRepository):
    """上传算法版本仓储。"""

    collection_name = "algorithm_versions"

    @classmethod
    def _collection(cls):
        return get_algorithm_versions_collection()

    @classmethod
    def update_fields(cls, version_id: str, fields: dict[str, Any]) -> bool:
        """更新算法版本字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"version_id": version_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("version_id") == version_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete(cls, version_id: str) -> bool:
        """删除算法版本记录。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"version_id": version_id})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item for item in data[cls.collection_name] if item.get("version_id") != version_id
            ]
            return len(data[cls.collection_name]) != before

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_versions(
        cls,
        *,
        algorithm_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法版本。"""
        filters: dict[str, Any] = {}
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class AlgorithmHandoffRepository(BaseRepository):
    """算法对接任务仓储。"""

    collection_name = "algorithm_handoffs"

    @classmethod
    def _collection(cls):
        return get_algorithm_handoffs_collection()

    @classmethod
    def update_fields(cls, handoff_id: str, fields: dict[str, Any]) -> bool:
        """更新算法对接任务字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"handoff_id": handoff_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("handoff_id") == handoff_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_handoffs(
        cls,
        *,
        status: str | None = None,
        example_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法对接任务。"""
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if example_id:
            filters["example_id"] = example_id
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class ExecutionDecisionRepository(BaseRepository):
    """ExecutionDecision 仓储。"""

    collection_name = "execution_decisions"

    @classmethod
    def _collection(cls):
        return get_execution_decisions_collection()

    @classmethod
    def list_decisions(
        cls,
        *,
        problem_spec_id: str | None = None,
        mode: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 ExecutionDecision。"""
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if mode:
            filters["mode"] = mode
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def find_active(cls, problem_spec_id: str) -> dict[str, Any] | None:
        """查询 ProblemSpec 当前 active decision。"""
        return cls.find_one({"problem_spec_id": problem_spec_id, "status": "active"})

    @classmethod
    def update_fields(cls, decision_id: str, fields: dict[str, Any]) -> bool:
        """更新 ExecutionDecision 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"decision_id": decision_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("decision_id") == decision_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class ManualAlgorithmWorkflowRepository(BaseRepository):
    """ManualAlgorithmWorkflow 仓储。"""

    collection_name = "manual_algorithm_workflows"

    @classmethod
    def _collection(cls):
        return get_manual_algorithm_workflows_collection()

    @classmethod
    def list_workflows(
        cls,
        *,
        problem_spec_id: str | None = None,
        execution_decision_id: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询人工 Workflow。"""
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if execution_decision_id:
            filters["execution_decision_id"] = execution_decision_id
        if created_by:
            filters["created_by"] = created_by
        if status:
            filters["status"] = status
        elif not include_archived:
            filters["status"] = {"$ne": "archived"}
        if cls._can_use_mongo():
            return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

        demo_filters = dict(filters)
        exclude_archived = demo_filters.get("status") == {"$ne": "archived"}
        if exclude_archived:
            demo_filters.pop("status", None)
        items, total = cls.list_all(demo_filters, sort_field="created_at", reverse=True, page=1, page_size=10000)
        if exclude_archived:
            items = [item for item in items if item.get("status") != "archived"]
            total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

    @classmethod
    def update_fields(cls, workflow_id: str, fields: dict[str, Any]) -> bool:
        """更新人工 Workflow 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"workflow_id": workflow_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("workflow_id") == workflow_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class WorkflowRunRepository(BaseRepository):
    """WorkflowRun 仓储。"""

    collection_name = "workflow_runs"

    @classmethod
    def _collection(cls):
        return get_workflow_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        workflow_id: str | None = None,
        problem_spec_id: str | None = None,
        execution_decision_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 WorkflowRun。"""
        filters: dict[str, Any] = {}
        if workflow_id:
            filters["workflow_id"] = workflow_id
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if execution_decision_id:
            filters["execution_decision_id"] = execution_decision_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, workflow_run_id: str, fields: dict[str, Any]) -> bool:
        """更新 WorkflowRun 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"workflow_run_id": workflow_run_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("workflow_run_id") == workflow_run_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class AlgorithmRunRepository(BaseRepository):
    """AlgorithmRun 仓储。

    支持 create/get/list，
    按 problem_spec_id、campaign_id、algorithm_id、status、trigger_source 过滤。
    """

    collection_name = "algorithm_runs"

    @classmethod
    def _collection(cls):
        return get_algorithm_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        problem_spec_id: str | None = None,
        campaign_id: str | None = None,
        workflow_run_id: str | None = None,
        algorithm_id: str | None = None,
        status: str | None = None,
        trigger_source: str | None = None,
        research_run_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 AlgorithmRun。

        Args:
            problem_spec_id: 按 ProblemSpec ID 过滤。
            campaign_id: 按 Campaign ID 过滤。
            workflow_run_id: 按 WorkflowRun ID 过滤。
            algorithm_id: 按算法 ID 过滤。
            status: 按运行状态过滤。
            trigger_source: 按触发来源过滤。
            research_run_id: 按 ResearchRun ID 过滤。
            created_by: 按创建者过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if workflow_run_id:
            filters["workflow_run_id"] = workflow_run_id
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if status:
            filters["status"] = status
        if trigger_source:
            filters["trigger_source"] = trigger_source
        if research_run_id:
            filters["research_run_id"] = research_run_id
        if created_by:
            filters["created_by"] = created_by

        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, run_id: str, fields: dict[str, Any]) -> bool:
        """更新 AlgorithmRun 字段。

        Args:
            run_id: 运行 ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"run_id": run_id}, {"$set": fields}
                )
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
    def claim_queued(cls, run_id: str, worker_id: str, now: datetime) -> bool:
        """Atomically reserve a queued run for one executor."""
        filters = {"run_id": run_id, "status": "queued", "execution_claimed_by": {"$in": [None, ""]}}
        fields = {"execution_claimed_by": worker_id, "execution_claimed_at": now, "updated_at": now}
        if cls._can_use_mongo():
            try:
                return cls._collection().update_one(filters, {"$set": fields}).matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            for item in data[cls.collection_name]:
                if _matches(item, filters):
                    _apply_update_fields(item, fields)
                    return True
            return False
        return bool(demo_store.mutate(mutate))

    @classmethod
    def claim_next_queued(cls, worker_id: str, now: datetime) -> dict[str, Any] | None:
        if cls._can_use_mongo():
            try:
                return _without_mongo_id(cls._collection().find_one_and_update(
                    {"status": "queued", "execution_claimed_by": {"$in": [None, ""]}},
                    {"$set": {"execution_claimed_by": worker_id, "execution_claimed_at": now, "updated_at": now}},
                    sort=[("created_at", 1)], projection={"_id": 0}, return_document=ReturnDocument.AFTER,
                ))
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)
        def mutate(data):
            queued = [item for item in data[cls.collection_name] if item.get("status") == "queued" and not item.get("execution_claimed_by")]
            if not queued:
                return None
            item = sorted(queued, key=lambda row: str(row.get("created_at", "")))[0]
            _apply_update_fields(item, {"execution_claimed_by": worker_id, "execution_claimed_at": now, "updated_at": now})
            return clone_document(item)
        return demo_store.mutate(mutate)

    @classmethod
    def list_by_research_run(cls, research_run_id: str) -> list[dict[str, Any]]:
        """查询 ResearchRun 关联的所有 AlgorithmRun。

        Args:
            research_run_id: ResearchRun ID。

        Returns:
            AlgorithmRun 文档列表。
        """
        items, _ = cls.list_all(
            {"research_run_id": research_run_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=500,
        )
        return items


class ResearchRunRepository(BaseRepository):
    """ResearchRun 仓储。

    支持 create/get/list/update，
    按 problem_spec_id、campaign_id、status 过滤。
    """

    collection_name = "research_runs"

    @classmethod
    def _collection(cls):
        return get_research_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        problem_spec_id: str | None = None,
        campaign_id: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        created_by: str | None = None,
        project_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 ResearchRun。

        Args:
            problem_spec_id: 按 ProblemSpec ID 过滤。
            campaign_id: 按 Campaign ID 过滤。
            status: 按状态过滤。
            created_by: 按创建者过滤。
            project_id: 按项目 ID 过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if status:
            filters["status"] = status
        elif not include_archived:
            filters["status"] = {"$ne": "archived"}
        if created_by:
            filters["created_by"] = created_by
        if project_id:
            filters["project_id"] = project_id

        if cls._can_use_mongo():
            return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

        demo_filters = dict(filters)
        exclude_archived = demo_filters.get("status") == {"$ne": "archived"}
        if exclude_archived:
            demo_filters.pop("status", None)
        items, total = cls.list_all(demo_filters, sort_field="created_at", reverse=True, page=1, page_size=10000)
        if exclude_archived:
            items = [item for item in items if item.get("status") != "archived"]
            total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

    @classmethod
    def update_fields(cls, run_id: str, fields: dict[str, Any]) -> bool:
        """更新 ResearchRun 字段。

        Args:
            run_id: 运行 ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"run_id": run_id}, {"$set": fields}
                )
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
    def list_by_problem_spec(cls, problem_spec_id: str) -> list[dict[str, Any]]:
        """查询 ProblemSpec 关联的所有 ResearchRun。

        Args:
            problem_spec_id: ProblemSpec ID。

        Returns:
            ResearchRun 文档列表。
        """
        items, _ = cls.list_all(
            {"problem_spec_id": problem_spec_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=100,
        )
        return items
