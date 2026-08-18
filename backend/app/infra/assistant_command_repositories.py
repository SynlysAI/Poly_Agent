"""Assistant Slash Command 执行与事件仓储。"""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.core.time import utc_now
from app.infra.computation_repositories import BaseRepository, clone_document, demo_store
from app.infra.mongo import (
    get_assistant_chats_collection,
    get_assistant_command_runs_collection,
    get_assistant_events_collection,
    get_assistant_feedback_collection,
)
from app.infra.research_engine_repositories import AssistantEventRepository


class AssistantCommandRunRepository(BaseRepository):
    """持久化命令执行生命周期，并把命令事件镜像到统一事件流。"""

    collection_name = "assistant_command_runs"

    @classmethod
    def _collection(cls):
        return get_assistant_command_runs_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        """创建命令执行与事件回放索引。"""
        if not cls._can_use_mongo():
            return
        try:
            collection = cls._collection()
            collection.create_index("command_id", unique=True)
            collection.create_index([("chat_id", 1), ("created_by", 1), ("created_at", -1)])
            collection.create_index([("status", 1), ("updated_at", -1)])
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def start(cls, document: dict[str, Any]) -> dict[str, Any]:
        """保存命令开始状态。

        Args:
            document: 已包含 command_id 与归属信息的命令文档。

        Returns:
            保存后的命令文档副本。
        """
        payload = clone_document(document)
        cls.ensure_indexes()
        cls.save("command_id", payload)
        return payload

    @classmethod
    def finish(cls, command_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        """关闭命令生命周期。

        Args:
            command_id: 命令执行 ID。
            fields: 结束状态、消息与关联结果字段。

        Returns:
            更新后的命令文档；命令不存在时返回 None。
        """
        now = utc_now()
        payload = {**clone_document(fields), "updated_at": now}
        if cls._can_use_mongo():
            try:
                cls.ensure_indexes()
                document = cls._collection().find_one_and_update(
                    {"command_id": command_id},
                    {"$set": payload},
                    projection={"_id": 0},
                    return_document=ReturnDocument.AFTER,
                )
                return dict(document) if document else None
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for index, item in enumerate(data[cls.collection_name]):
                if item.get("command_id") != command_id:
                    continue
                item.update(payload)
                data[cls.collection_name][index] = clone_document(item)
                return clone_document(item)
            return None

        return demo_store.mutate(mutate)

    @classmethod
    def append_chat_event(
        cls,
        chat: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        """原子递增会话事件序号并镜像事件到 assistant_events。

        Args:
            chat: 所属会话文档，必须包含 chat_id 与 created_by。
            event: 不含 seq/at 的统一事件 payload。

        Returns:
            插入成功时返回 assistant_events 文档。
        """
        now = event.get("at") or utc_now()
        chat_id = str(chat.get("chat_id") or "")
        created_by = str(chat.get("created_by") or "")
        trace_id = str(event.get("trace_id") or event.get("command_id") or event.get("call_id") or "")
        if cls._can_use_mongo():
            try:
                updated = get_assistant_chats_collection().find_one_and_update(
                    {"chat_id": chat_id, "created_by": created_by},
                    {"$inc": {"command_event_seq": 1}},
                    projection={"chat_id": 1, "created_by": 1, "command_event_seq": 1},
                    return_document=ReturnDocument.AFTER,
                )
                if not updated:
                    return None
                payload = {
                    **clone_document(event),
                    "seq": int(updated.get("command_event_seq") or 0),
                    "at": now,
                    "trace_id": trace_id,
                }
                return AssistantEventRepository.append(
                    {
                        "chat_id": chat_id,
                        "run_id": str(event.get("run_id") or ""),
                        "created_by": created_by,
                    },
                    payload,
                )
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data["assistant_chats"]:
                if item.get("chat_id") != chat_id or item.get("created_by") != created_by:
                    continue
                seq = int(item.get("command_event_seq") or 0) + 1
                item["command_event_seq"] = seq
                payload = {
                    **clone_document(event),
                    "seq": seq,
                    "at": now,
                    "trace_id": trace_id,
                }
                document = AssistantEventRepository.build_document(
                    {
                        "chat_id": chat_id,
                        "run_id": str(event.get("run_id") or ""),
                        "created_by": created_by,
                    },
                    payload,
                )
                data[AssistantEventRepository.collection_name].append(document)
                return clone_document(document)
            return None

        return demo_store.mutate(mutate)

    @classmethod
    def list_runs_for_chat(
        cls,
        chat_id: str,
        created_by: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """按会话读取命令执行历史。

        Args:
            chat_id: 会话 ID。
            created_by: 会话 owner。
            page: 页码。
            page_size: 页大小。

        Returns:
            (items,total) 元组。
        """
        return cls.list_all(
            {"chat_id": chat_id, "created_by": created_by},
            sort_field="created_at",
            reverse=True,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def events_after(
        cls,
        chat_id: str,
        created_by: str,
        after_seq: int = 0,
        *,
        event_types: set[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """按会话事件序号增量读取命令相关事件。

        Args:
            chat_id: 会话 ID。
            created_by: 会话 owner。
            after_seq: 回放游标。
            event_types: 可选事件类型白名单。
            limit: 单次最大返回数量。

        Returns:
            按 seq 升序排列的事件文档列表。
        """
        if cls._can_use_mongo():
            filters: dict[str, Any] = {
                "chat_id": chat_id,
                "created_by": created_by,
                "seq": {"$gt": int(after_seq)},
            }
            if event_types:
                filters["type"] = {"$in": sorted(event_types)}
            try:
                cursor = (
                    get_assistant_events_collection()
                    .find(filters, {"_id": 0})
                    .sort([("seq", 1)])
                    .limit(max(1, int(limit)))
                )
                return [dict(item) for item in cursor]
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        data = demo_store.load()
        rows = []
        for item in data[AssistantEventRepository.collection_name]:
            if item.get("chat_id") != chat_id or item.get("created_by") != created_by:
                continue
            if int(item.get("seq", 0)) <= int(after_seq):
                continue
            if event_types and item.get("type") not in event_types:
                continue
            rows.append(clone_document(item))
        rows.sort(key=lambda item: int(item.get("seq", 0)))
        return rows[: max(1, int(limit))]


class AssistantFeedbackRepository(BaseRepository):
    """持久化会话反馈权威记录。"""

    collection_name = "assistant_feedback"

    @classmethod
    def _collection(cls):
        return get_assistant_feedback_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        """创建反馈 ID 与会话查询索引。"""
        if not cls._can_use_mongo():
            return
        try:
            collection = cls._collection()
            collection.create_index("feedback_id", unique=True)
            collection.create_index([("chat_id", 1), ("created_by", 1), ("created_at", -1)])
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def create(cls, document: dict[str, Any]) -> dict[str, Any]:
        """保存一条反馈记录。

        Args:
            document: 已通过 schema 校验的反馈文档。

        Returns:
            保存后的反馈文档副本。
        """
        payload = clone_document(document)
        cls.ensure_indexes()
        cls.save("feedback_id", payload)
        return payload

    @classmethod
    def list_for_chat(
        cls,
        chat_id: str,
        created_by: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按会话读取反馈记录。

        Args:
            chat_id: 会话 ID。
            created_by: 会话 owner。
            limit: 单次最大返回数量。

        Returns:
            按创建时间倒序的反馈文档列表。
        """
        items, _ = cls.list_all(
            {"chat_id": chat_id, "created_by": created_by},
            sort_field="created_at",
            reverse=True,
            page=1,
            page_size=limit,
        )
        return items
