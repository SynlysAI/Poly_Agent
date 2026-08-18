"""Persistence and ownership service for assistant chat history."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.core.time import utc_now
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantMessageRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant_chats import (
    AssistantChat,
    AssistantChatCreate,
    AssistantChatListData,
    AssistantChatSummary,
    AssistantChatSummaryListData,
    AssistantChatUpdate,
    AssistantMessage,
    AssistantMessageCreate,
    AssistantMessageListData,
    AssistantMessageUpdate,
)
from app.services.agent_tool_service import agent_tool_service


def actor_id(current_user: dict[str, str] | None) -> str:
    """Resolve the local demo actor or the authenticated user ID."""
    return (current_user or {}).get("user_id") or "demo_user"


def _title_from_messages(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        content = " ".join(str(message.get("content") or "").split())
        if content:
            return content[:80]
    return "新对话"


class AssistantChatService:
    """Create, update, delete and restore user-owned assistant chats."""

    @staticmethod
    def _validate_selected_tools(tool_ids: list[str], current_user: dict[str, str] | None) -> None:
        user_id = actor_id(current_user)
        role = (current_user or {}).get("role", "admin")
        is_admin = role == "admin"
        for tool_id in tool_ids:
            if not tool_id.startswith("algorithm:"):
                raise HTTPException(status_code=422, detail=f"无效的算法工具 ID: {tool_id}")
            algorithm_id = tool_id.removeprefix("algorithm:")
            if not algorithm_id or not agent_tool_service.resolve_callable(
                algorithm_id,
                user_id=user_id,
                role=role,
                is_admin=is_admin,
            ):
                raise HTTPException(status_code=403, detail=f"算法工具不可用或当前用户无权限调用: {tool_id}")

    @staticmethod
    def _owned_chat(chat_id: str, owner_id: str) -> dict[str, Any]:
        chat = AssistantChatRepository.find_one({"chat_id": chat_id})
        if not chat:
            raise HTTPException(status_code=404, detail=f"会话 '{chat_id}' 不存在")
        if chat.get("created_by") != owner_id:
            raise HTTPException(status_code=403, detail="无权限访问该会话")
        return chat

    @staticmethod
    def _public_call(document: dict[str, Any]) -> dict[str, Any]:
        public = {key: value for key, value in document.items() if not key.startswith("_")}
        public["uploaded_assets"] = [
            {key: value for key, value in item.items() if key != "_path"}
            for item in (public.get("uploaded_assets") or [])
        ]
        public["events"] = [
            {
                key: value
                for key, value in event.items()
                if key != "_path"
            }
            for event in (public.get("events") or [])
        ]
        return public

    @classmethod
    def _message(
        cls,
        document: dict[str, Any],
        owner_id: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> AssistantMessage:
        calls = []
        source_calls = tool_calls
        if source_calls is None:
            source_calls = AssistantToolCallRepository.list_for_chat(
                document["chat_id"], created_by=owner_id
            )
        for call in source_calls:
            if call.get("message_id") == document["message_id"]:
                calls.append(cls._public_call(call))
        payload = {**document, "tool_calls": calls}
        return AssistantMessage.model_validate(payload)

    @classmethod
    def _chat(cls, document: dict[str, Any], owner_id: str) -> AssistantChat:
        messages, _ = AssistantMessageRepository.list_for_chat(document["chat_id"], owner_id, page_size=200)
        raw_calls = AssistantToolCallRepository.list_for_chat(document["chat_id"], created_by=owner_id)
        public_messages = [cls._message(item, owner_id, raw_calls) for item in messages]
        calls = [cls._public_call(call) for call in raw_calls]
        payload = {**document, "messages": public_messages, "tool_calls": calls}
        payload.pop("search_text", None)
        return AssistantChat.model_validate(payload)

    @classmethod
    def create(cls, payload: AssistantChatCreate, current_user: dict[str, str] | None) -> AssistantChat:
        owner_id = actor_id(current_user)
        cls._validate_selected_tools(payload.selected_tool_ids, current_user)
        now = utc_now()
        initial_messages = [item.model_dump(mode="python") for item in payload.messages]
        chat_id = f"chat_{uuid4().hex[:16]}"
        document = {
            "chat_id": chat_id,
            "title": (payload.title or "").strip() or _title_from_messages(initial_messages),
            "search_text": " ".join(
                [
                    (payload.title or "").strip(),
                    *[str(item.get("content") or "") for item in initial_messages],
                ]
            ).strip(),
            "created_by": owner_id,
            "archived": False,
            "model": payload.model,
            "mode": payload.mode,
            "knowledge_base_ids": payload.knowledge_base_ids,
            "knowledge_base_names": payload.knowledge_base_names,
            "use_web_search": payload.use_web_search,
            "selected_tool_ids": payload.selected_tool_ids,
            "plan_mode": False,
            "permission_mode": "workspace_write",
            "goal": None,
            "todos": [],
            "compaction": None,
            "command_event_seq": 0,
            "created_at": now,
            "updated_at": now,
        }
        AssistantChatRepository.save("chat_id", document)
        for message in payload.messages:
            cls._create_message_document(chat_id, owner_id, message)
        persisted = AssistantChatRepository.find_one({"chat_id": chat_id, "created_by": owner_id}) or document
        return cls._chat(persisted, owner_id)

    @classmethod
    def list(
        cls,
        *,
        query: str | None,
        archived: bool,
        page: int,
        page_size: int,
        current_user: dict[str, str] | None,
    ) -> AssistantChatListData:
        owner_id = actor_id(current_user)
        items, total = AssistantChatRepository.list_chats(
            created_by=owner_id,
            query=query,
            archived=archived,
            page=page,
            page_size=page_size,
        )
        return AssistantChatListData(
            items=[cls._chat(item, owner_id) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def _summary(cls, document: dict[str, Any], message_count: int) -> AssistantChatSummary:
        """将会话文档转换为历史栏摘要。"""
        return AssistantChatSummary.model_validate({
            **document,
            "message_count": int(message_count),
        })

    @classmethod
    def list_summaries(
        cls,
        *,
        query: str | None,
        archived: bool,
        page: int,
        page_size: int,
        current_user: dict[str, str] | None,
    ) -> AssistantChatSummaryListData:
        """返回轻量历史会话摘要，避免列表接口加载完整消息与工具调用。"""
        owner_id = actor_id(current_user)
        items, total = AssistantChatRepository.list_chats(
            created_by=owner_id,
            query=query,
            archived=archived,
            page=page,
            page_size=page_size,
        )
        message_counts = AssistantMessageRepository.count_for_chats(
            [str(item.get("chat_id") or "") for item in items],
            owner_id,
        )
        return AssistantChatSummaryListData(
            items=[
                cls._summary(item, message_counts.get(str(item.get("chat_id") or ""), 0))
                for item in items
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def get(cls, chat_id: str, current_user: dict[str, str] | None) -> AssistantChat:
        owner_id = actor_id(current_user)
        return cls._chat(cls._owned_chat(chat_id, owner_id), owner_id)

    @classmethod
    def update(
        cls,
        chat_id: str,
        payload: AssistantChatUpdate,
        current_user: dict[str, str] | None,
    ) -> AssistantChat:
        owner_id = actor_id(current_user)
        current = cls._owned_chat(chat_id, owner_id)
        requested = payload.model_dump(exclude_unset=True)
        if "selected_tool_ids" in requested:
            cls._validate_selected_tools(requested["selected_tool_ids"] or [], current_user)
        requested["updated_at"] = utc_now()
        if "title" in requested:
            requested["title"] = (requested["title"] or "").strip() or current.get("title") or "新对话"
            requested["search_text"] = " ".join(
                [requested["title"], str(current.get("search_text") or "")]
            ).strip()
        AssistantChatRepository.update_owned(chat_id, owner_id, requested)
        current.update(requested)
        return cls._chat(current, owner_id)

    @classmethod
    def delete(cls, chat_id: str, current_user: dict[str, str] | None) -> None:
        owner_id = actor_id(current_user)
        cls._owned_chat(chat_id, owner_id)
        calls = AssistantToolCallRepository.list_for_chat(chat_id, created_by=owner_id)
        if not AssistantChatRepository.delete_owned(chat_id, owner_id):
            raise HTTPException(status_code=404, detail=f"会话 '{chat_id}' 不存在")
        AssistantMessageRepository.delete_for_chat(chat_id, owner_id)
        AssistantToolCallRepository.delete_for_chat(chat_id, created_by=owner_id)
        for call in calls:
            root = (settings.runtime_root / "assistant-tool-calls" / call["call_id"]).resolve()
            for asset in call.get("uploaded_assets") or []:
                raw_path = asset.get("_path")
                if not raw_path:
                    continue
                path = Path(raw_path).resolve()
                if path.is_relative_to(root):
                    path.unlink(missing_ok=True)
            try:
                root.rmdir()
            except OSError:
                pass

    @classmethod
    def _create_message_document(
        cls,
        chat_id: str,
        owner_id: str,
        payload: AssistantMessageCreate,
    ) -> dict[str, Any]:
        for call_id in payload.tool_call_ids:
            call = AssistantToolCallRepository.find_one(
                {"call_id": call_id, "chat_id": chat_id, "created_by": owner_id}
            )
            if call is None:
                raise HTTPException(status_code=422, detail=f"工具调用 '{call_id}' 不属于该会话")
        now = utc_now()
        document = {
            "message_id": f"msg_{uuid4().hex[:16]}",
            "chat_id": chat_id,
            "created_by": owner_id,
            **payload.model_dump(mode="python"),
            "created_at": now,
            "updated_at": now,
        }
        AssistantMessageRepository.save("message_id", document)
        chat = AssistantChatRepository.find_one({"chat_id": chat_id, "created_by": owner_id}) or {}
        search_text = " ".join(
            [str(chat.get("search_text") or ""), str(payload.content or "")]
        ).strip()
        AssistantChatRepository.update_owned(
            chat_id,
            owner_id,
            {"updated_at": now, "search_text": search_text},
        )
        return document

    @classmethod
    def create_message(
        cls,
        chat_id: str,
        payload: AssistantMessageCreate,
        current_user: dict[str, str] | None,
    ) -> AssistantMessage:
        owner_id = actor_id(current_user)
        chat = cls._owned_chat(chat_id, owner_id)
        document = cls._create_message_document(chat_id, owner_id, payload)
        if chat.get("title") in {None, "", "新对话"} and payload.role == "user" and payload.content.strip():
            title = _title_from_messages([payload.model_dump(mode="python")])
            AssistantChatRepository.update_owned(
                chat_id,
                owner_id,
                {"title": title, "search_text": f"{title} {chat.get('search_text') or ''}".strip(), "updated_at": utc_now()},
            )
        return cls._message(document, owner_id)

    @classmethod
    def list_messages(
        cls,
        chat_id: str,
        *,
        page: int,
        page_size: int,
        current_user: dict[str, str] | None,
    ) -> AssistantMessageListData:
        owner_id = actor_id(current_user)
        cls._owned_chat(chat_id, owner_id)
        items, total = AssistantMessageRepository.list_for_chat(chat_id, owner_id, page=page, page_size=page_size)
        return AssistantMessageListData(
            items=[cls._message(item, owner_id) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    @classmethod
    def update_message(
        cls,
        chat_id: str,
        message_id: str,
        payload: AssistantMessageUpdate,
        current_user: dict[str, str] | None,
    ) -> AssistantMessage:
        owner_id = actor_id(current_user)
        cls._owned_chat(chat_id, owner_id)
        current = AssistantMessageRepository.find_one(
            {"message_id": message_id, "chat_id": chat_id, "created_by": owner_id}
        )
        if not current:
            raise HTTPException(status_code=404, detail=f"消息 '{message_id}' 不存在")
        fields = payload.model_dump(exclude_unset=True)
        fields["updated_at"] = utc_now()
        AssistantMessageRepository.update_owned(message_id, chat_id, owner_id, fields)
        current.update(fields)
        AssistantChatRepository.update_owned(chat_id, owner_id, {"updated_at": fields["updated_at"]})
        return cls._message(current, owner_id)

    @classmethod
    def delete_message(
        cls,
        chat_id: str,
        message_id: str,
        current_user: dict[str, str] | None,
    ) -> None:
        owner_id = actor_id(current_user)
        cls._owned_chat(chat_id, owner_id)
        if not AssistantMessageRepository.delete_owned(message_id, chat_id, owner_id):
            raise HTTPException(status_code=404, detail=f"消息 '{message_id}' 不存在")
        AssistantToolCallRepository.delete_for_message(message_id, chat_id, created_by=owner_id)
        AssistantChatRepository.update_owned(chat_id, owner_id, {"updated_at": utc_now()})


assistant_chat_service = AssistantChatService()
