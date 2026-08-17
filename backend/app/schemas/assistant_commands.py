"""Assistant Slash Command 与会话控制状态数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_tools import AssistantToolCall
from app.schemas.assistant_runs import AssistantRun


CommandCategory = Literal["system", "agent", "skill", "tool", "custom"]
CommandInputMode = Literal["none", "text", "single_choice", "tool_schema"]
CommandStatus = Literal["running", "success", "interaction", "failed"]
PermissionMode = Literal["read_only", "workspace_write", "full_access"]
SessionGoalStatus = Literal["active", "completed"]
SessionTodoStatus = Literal["pending", "in_progress", "completed"]


class CommandVariant(BaseModel):
    """命令的一种参数形态，仅用于前端展示，不重复注册处理器。"""

    model_config = ConfigDict(extra="forbid")

    usage: str
    description: str


class CommandChoice(BaseModel):
    """单选交互中的一个选项。"""

    model_config = ConfigDict(extra="forbid")

    value: str
    label: str
    description: str = ""
    selected: bool = False


class CommandDescriptor(BaseModel):
    """Handler-free 的命令目录描述符。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_-]*$")
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    usage: str = Field(min_length=2, max_length=200)
    category: CommandCategory
    source: str = Field(min_length=1, max_length=160)
    source_kind: str = Field(default="builtin", max_length=80)
    enabled: bool = True
    available: bool = True
    unavailable_reason: str | None = None
    input_mode: CommandInputMode
    argument_hint: str | None = Field(default=None, max_length=200)
    variants: list[CommandVariant] = Field(default_factory=list)
    choices: list[CommandChoice] = Field(default_factory=list)
    tool_id: str | None = Field(default=None, max_length=200)
    requires_confirmation: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"


class SessionGoal(BaseModel):
    """会话内当前长期目标。"""

    model_config = ConfigDict(extra="forbid")

    goal_id: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=2_000)
    status: SessionGoalStatus = "active"
    created_by: str = Field(min_length=1, max_length=120)
    created_at: datetime
    updated_at: datetime


class SessionTodo(BaseModel):
    """会话内待办事项。"""

    model_config = ConfigDict(extra="forbid")

    todo_id: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=1_000)
    status: SessionTodoStatus = "pending"
    created_at: datetime
    updated_at: datetime


class CompactionSnapshot(BaseModel):
    """一次会话上下文压缩的可回放快照。"""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=80)
    cutoff_message_id: str | None = Field(default=None, max_length=80)
    summary: str = Field(default="", max_length=20_000)
    summary_digest: str = Field(default="", max_length=120)
    token_estimate: int = Field(default=0, ge=0)
    original_token_estimate: int = Field(default=0, ge=0)
    created_at: datetime


class SessionControlState(BaseModel):
    """随会话持久保存的 Agent 控制状态。"""

    model_config = ConfigDict(extra="forbid")

    chat_id: str
    plan_mode: bool = False
    permission_mode: PermissionMode = "workspace_write"
    goal: SessionGoal | None = None
    todos: list[SessionTodo] = Field(default_factory=list)
    compaction: CompactionSnapshot | None = None
    command_event_seq: int = Field(default=0, ge=0)
    model: dict[str, Any] = Field(default_factory=dict)


class CommandCatalogData(BaseModel):
    """当前会话可发现命令目录与控制状态。"""

    model_config = ConfigDict(extra="forbid")

    items: list[CommandDescriptor]
    total: int
    session_state: SessionControlState
    catalog_version: str


class CommandExecuteRequest(BaseModel):
    """Slash Command 执行请求。"""

    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(min_length=1, max_length=80)
    line: str = Field(min_length=1, max_length=8_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandInteraction(BaseModel):
    """命令返回的直接 UI 交互，不进入模型历史。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["choice", "form", "confirmation"]
    prompt: str = Field(min_length=1, max_length=500)
    choices: list[CommandChoice] = Field(default_factory=list)


class CommandExecution(BaseModel):
    """一次命令执行的直接结果。"""

    model_config = ConfigDict(extra="ignore")

    command_id: str
    chat_id: str
    name: str
    status: CommandStatus
    message: str
    state_after: SessionControlState
    interaction: CommandInteraction | None = None
    run: AssistantRun | None = None
    tool_call: AssistantToolCall | None = None
    download_url: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class CommandEventListData(BaseModel):
    """会话级命令事件回放数据。"""

    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    total: int
    next_after_seq: int
