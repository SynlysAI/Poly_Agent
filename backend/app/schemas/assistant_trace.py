"""LUI Execution Trace 对外数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AssistantTraceStatus = Literal[
    "planning",
    "running",
    "waiting_approval",
    "recovering",
    "completed",
    "failed",
    "canceled",
]
AssistantTraceStepType = Literal[
    "context",
    "think",
    "command",
    "control",
    "tool_call",
    "tool_result",
    "read",
    "write",
    "edit",
    "approval",
    "export",
    "feedback",
    "error",
    "final",
]
AssistantTraceStepStatus = Literal["running", "success", "failed", "waiting"]
AssistantTraceToolType = Literal["llm", "retrieval", "algorithm", "asset", "file", "other"]


class AssistantTraceSourceRef(BaseModel):
    """指向一条真实 assistant 事件的只读引用。"""

    model_config = ConfigDict(extra="forbid")

    stream: Literal["assistant_event", "embedded_event"] = "assistant_event"
    event_id: str
    run_id: str = ""
    call_id: str = ""
    seq: int = 0
    chat_seq: int = 0


class AssistantTraceStepDetails(BaseModel):
    """Trace 步骤的白名单详情，不承载完整 prompt 或原始日志。"""

    model_config = ConfigDict(extra="allow")

    duration_known: bool = False
    source_event_refs: list[AssistantTraceSourceRef] = Field(default_factory=list)
    next_action: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    request_kind: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    argument_keys: list[str] = Field(default_factory=list)
    schema_digest: str | None = None
    algorithm_id: str | None = None
    algorithm_version: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    event_type: str | None = None
    event_types: list[str] = Field(default_factory=list)
    command_id: str | None = None
    command_name: str | None = None
    chat_seq: int = 0
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    retry_scheduled: bool | None = None


class AssistantTraceStep(BaseModel):
    """一条面向用户展示的真实执行步骤投影。"""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    step_id: str
    timestamp: datetime
    type: AssistantTraceStepType
    title: str
    summary: str
    tool_name: str = ""
    tool_type: AssistantTraceToolType = "other"
    status: AssistantTraceStepStatus
    duration_ms: int = Field(default=0, ge=0)
    details: AssistantTraceStepDetails = Field(default_factory=AssistantTraceStepDetails)
    parent_step_id: str | None = None


class AssistantTraceSummary(BaseModel):
    """一轮用户请求的执行统计。"""

    model_config = ConfigDict(extra="forbid")

    total_steps: int = Field(default=0, ge=0)
    commands: int = Field(default=0, ge=0)
    control_changes: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    llm_calls: int = Field(default=0, ge=0)
    retrievals: int = Field(default=0, ge=0)
    approvals: int = Field(default=0, ge=0)
    file_reads: int = Field(default=0, ge=0)
    file_writes: int = Field(default=0, ge=0)
    file_edits: int = Field(default=0, ge=0)
    artifacts: int = Field(default=0, ge=0)
    exports: int = Field(default=0, ge=0)
    feedback: int = Field(default=0, ge=0)
    compactions: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    recoveries: int = Field(default=0, ge=0)
    replay_warnings: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    duration_known: bool = False


class AssistantTraceRun(BaseModel):
    """Trace 关联的 AssistantRun 摘要。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    request_kind: str = "final_answer"
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AssistantTraceToolCall(BaseModel):
    """Trace 关联的算法工具调用摘要。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    algorithm_id: str
    tool_name: str
    phase: str
    run_id: str | None = None


class AssistantTraceCommand(BaseModel):
    """Trace 关联的 Slash Command 摘要。"""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    name: str
    status: str
    run_id: str | None = None
    call_id: str | None = None


class AssistantTraceData(BaseModel):
    """一条用户请求的完整 Execution Trace 快照。"""

    model_config = ConfigDict(extra="forbid")

    trace_id: str
    chat_id: str
    user_message_id: str
    root_run_id: str
    status: AssistantTraceStatus
    created_at: datetime
    updated_at: datetime
    runs: list[AssistantTraceRun] = Field(default_factory=list)
    tool_calls: list[AssistantTraceToolCall] = Field(default_factory=list)
    steps: list[AssistantTraceStep] = Field(default_factory=list)
    summary: AssistantTraceSummary = Field(default_factory=AssistantTraceSummary)
    cursor: str = ""
    replay_warnings: list[str] = Field(default_factory=list)


class AssistantChatTraceData(BaseModel):
    """一个会话内命令、模型、工具与控制事件的统一 Trace 快照。"""

    model_config = ConfigDict(extra="forbid")

    chat_id: str
    status: AssistantTraceStatus
    created_at: datetime
    updated_at: datetime
    runs: list[AssistantTraceRun] = Field(default_factory=list)
    tool_calls: list[AssistantTraceToolCall] = Field(default_factory=list)
    commands: list[AssistantTraceCommand] = Field(default_factory=list)
    steps: list[AssistantTraceStep] = Field(default_factory=list)
    summary: AssistantTraceSummary = Field(default_factory=AssistantTraceSummary)
    next_after_seq: int = Field(default=0, ge=0)
    total_events: int = Field(default=0, ge=0)
    replay_warnings: list[str] = Field(default_factory=list)
