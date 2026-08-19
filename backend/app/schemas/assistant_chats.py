"""Schemas for user-scoped assistant chat history."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_tools import AssistantToolCall
from app.schemas.assistant_commands import (
    CompactionSnapshot,
    PermissionMode,
    SessionGoal,
    SessionTodo,
)
from app.schemas.assistant import AssistantPresetId


ChatMessageRole = Literal["system", "user", "assistant", "tool"]


class AssistantMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ChatMessageRole
    content: str = Field(default="", max_length=32_000)
    references: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_summary: list[str] = Field(default_factory=list)
    answer_mode: str | None = Field(default=None, max_length=80)
    answer_scope: str | None = Field(default=None, max_length=80)
    retrieval_status: str | None = Field(default=None, max_length=80)
    tool_call_ids: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, max_length=32_000)
    references: list[dict[str, Any]] | None = None
    reasoning_summary: list[str] | None = None
    answer_mode: str | None = Field(default=None, max_length=80)
    answer_scope: str | None = Field(default=None, max_length=80)
    retrieval_status: str | None = Field(default=None, max_length=80)
    tool_call_ids: list[str] | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] | None = None


class AssistantMessage(AssistantMessageCreate):
    # 响应侧忽略历史文档中的未知字段，避免 schema 演进导致历史会话加载 500。
    model_config = ConfigDict(extra="ignore")

    message_id: str
    chat_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)


class AssistantChatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    model: dict[str, Any] = Field(default_factory=dict)
    mode: str = Field(default="qa", max_length=40)
    preset_id: AssistantPresetId | None = Field(default=None, max_length=40)
    knowledge_base_ids: list[str] = Field(default_factory=list, max_length=100)
    knowledge_base_names: list[str] = Field(default_factory=list, max_length=100)
    use_web_search: bool = False
    selected_tool_ids: list[str] = Field(default_factory=list, max_length=100)
    messages: list[AssistantMessageCreate] = Field(default_factory=list, max_length=200)


class AssistantChatUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    model: dict[str, Any] | None = None
    mode: str | None = Field(default=None, max_length=40)
    preset_id: AssistantPresetId | None = Field(default=None, max_length=40)
    knowledge_base_ids: list[str] | None = Field(default=None, max_length=100)
    knowledge_base_names: list[str] | None = Field(default=None, max_length=100)
    use_web_search: bool | None = None
    selected_tool_ids: list[str] | None = Field(default=None, max_length=100)
    archived: bool | None = None


class AssistantChat(AssistantChatCreate):
    # 响应侧忽略历史文档中的未知字段，请求侧 Create 模型仍保持严格校验。
    model_config = ConfigDict(extra="ignore")

    chat_id: str
    title: str
    created_by: str
    preset_id: AssistantPresetId = "research_qa"
    archived: bool = False
    plan_mode: bool = False
    permission_mode: PermissionMode = "workspace_write"
    goal: SessionGoal | None = None
    todos: list[SessionTodo] = Field(default_factory=list)
    compaction: CompactionSnapshot | None = None
    command_event_seq: int = 0
    created_at: datetime
    updated_at: datetime
    messages: list[AssistantMessage] = Field(default_factory=list)
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)


class AssistantChatSummary(BaseModel):
    """历史会话列表摘要，仅返回侧栏渲染所需字段。

    列表接口不加载完整消息和工具调用，避免每个会话逐条拉取
    messages/tool_calls 造成历史栏刷新卡顿。
    """

    model_config = ConfigDict(extra="ignore")

    chat_id: str
    title: str
    created_by: str
    preset_id: AssistantPresetId = "research_qa"
    archived: bool = False
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class AssistantChatListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AssistantChat]
    total: int
    page: int
    page_size: int


class AssistantChatSummaryListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AssistantChatSummary]
    total: int
    page: int
    page_size: int


class AssistantMessageListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AssistantMessage]
    total: int
    page: int
    page_size: int
