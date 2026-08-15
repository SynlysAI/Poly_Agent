"""对话算法工具目录与策略数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.attribution import AttributionItem
from app.schemas.research_engine import AlgorithmAssetSpec, AlgorithmIOSchema


AgentToolPhase = Literal["available", "disabled", "unavailable"]
AgentToolHealthStatus = Literal["healthy", "unknown", "unavailable"]
AssistantToolCallPhase = Literal[
    "requested",
    "awaiting_input",
    "awaiting_confirmation",
    "queued",
    "running",
    "completed",
    "failed",
    "canceled",
]


class AgentToolPolicy(BaseModel):
    """算法工具的轻量治理策略，不复制算法输入输出 schema。"""

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    allowed_roles: list[Literal["admin", "user"]] = Field(default_factory=lambda: ["admin", "user"])
    requires_confirmation: bool = True
    updated_by: str | None = None
    updated_at: datetime | None = None

    @field_validator("algorithm_id")
    @classmethod
    def normalize_algorithm_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("algorithm_id 不能为空")
        return normalized

    @field_validator("allowed_roles")
    @classmethod
    def normalize_allowed_roles(cls, value: list[str]) -> list[str]:
        roles = list(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip()))
        if not roles:
            raise ValueError("allowed_roles 至少需要一个角色")
        return roles


class AgentToolPolicyUpdate(BaseModel):
    """管理员更新算法工具策略。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    allowed_roles: list[Literal["admin", "user"]] | None = None
    requires_confirmation: bool | None = None

    @field_validator("allowed_roles")
    @classmethod
    def reject_empty_roles(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not value:
            raise ValueError("allowed_roles 至少需要一个角色")
        return list(dict.fromkeys(value)) if value is not None else None


class AgentTool(BaseModel):
    """当前用户可见的算法工具目录项。"""

    model_config = ConfigDict(extra="forbid")

    tool_id: str
    algorithm_id: str
    name: str
    description: str | None = None
    algorithm_family: str
    material_scope: list[str] = Field(default_factory=list)
    tool_type: str
    source: str
    source_kind: str | None = None
    visibility: Literal["private", "public"] = "private"
    active_version_id: str | None = None
    version: str | None = None
    input_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    output_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    function_name: str = ""
    input_json_schema: dict[str, Any] = Field(default_factory=dict)
    schema_digest: str = ""
    presentation: dict[str, Any] = Field(default_factory=dict)
    input_assets: list[AlgorithmAssetSpec] = Field(default_factory=list)
    output_assets: list[AlgorithmAssetSpec] = Field(default_factory=list)
    developer_attribution: AttributionItem | None = None
    framework_attributions: list[AttributionItem] = Field(default_factory=list)
    method_attributions: list[AttributionItem] = Field(default_factory=list)
    policy: AgentToolPolicy
    requires_confirmation: bool
    phase: AgentToolPhase
    health_status: AgentToolHealthStatus
    unavailable_reason: str | None = None


class AgentToolRegistryItem(AgentTool):
    """管理员目录项，包含不可调用算法的治理原因。"""

    owner: str | None = None
    status: str
    deployment_status: str | None = None
    runtime_health: dict = Field(default_factory=dict)


class AgentToolListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AgentTool]
    total: int


class AgentToolRegistryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AgentToolRegistryItem]
    total: int


class AgentToolSyncData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked: int
    available: int
    unavailable: int
    disabled: int
    policies_created: int


class AssistantToolCallCreate(BaseModel):
    """模型或受信任编排器提出一个算法工具调用。"""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(pattern=r"^algorithm:[^:]+$", max_length=120)
    provider_tool_call_id: str | None = Field(default=None, max_length=255)
    chat_id: str | None = Field(default=None, max_length=120)
    message_id: str | None = Field(default=None, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    input_asset_refs: dict[str, Any] = Field(default_factory=dict)
    function_name: str | None = Field(default=None, max_length=64)
    provider_tool_call_index: int | None = Field(default=None, ge=0)
    raw_arguments: str | None = Field(default=None, max_length=100000)
    arguments_parse_error: str | None = Field(default=None, max_length=2000)
    finish_reason: str | None = Field(default=None, max_length=64)
    proposal_route: dict[str, Any] | None = None
    proposal_usage: dict[str, Any] | None = None
    schema_digest: str | None = Field(default=None, min_length=16, max_length=16)
    selection_reason: str | None = Field(default=None, max_length=500)
    selection_confidence: float | None = Field(default=None, ge=0, le=1)


class AssistantToolCallInputUpdate(BaseModel):
    """补充或修正 pending 调用的参数与附件引用。"""

    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)
    input_asset_refs: dict[str, Any] = Field(default_factory=dict)


class AssistantToolCallConfirm(BaseModel):
    """确认时可原子地提交最后一版参数。"""

    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] | None = None
    input_asset_refs: dict[str, Any] | None = None


class AssistantToolCallEvent(BaseModel):
    """可直接写入 Assistant SSE 的工具调用状态事件。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_call"] = "tool_call"
    call_id: str
    provider_tool_call_id: str | None = None
    tool_id: str
    algorithm_id: str
    algorithm_version_id: str | None = None
    tool_name: str
    phase: AssistantToolCallPhase
    arguments: dict[str, Any] = Field(default_factory=dict)
    function_name: str | None = None
    provider_tool_call_index: int | None = None
    raw_arguments: str | None = None
    arguments_parse_error: str | None = None
    finish_reason: str | None = None
    proposal_route: dict[str, Any] | None = None
    proposal_usage: dict[str, Any] | None = None
    schema_digest: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: datetime


class AssistantToolInputRequiredEvent(BaseModel):
    """参数或附件不完整时发送给前端的补充输入事件。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_input_required"] = "tool_input_required"
    call_id: str
    missing_fields: list[str] = Field(default_factory=list)
    field_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    input_json_schema: dict[str, Any] = Field(default_factory=dict)
    presentation: dict[str, Any] = Field(default_factory=dict)
    required_assets: list[AlgorithmAssetSpec] = Field(default_factory=list)
    created_at: datetime


class AssistantToolCall(BaseModel):
    """对话算法工具调用持久化状态。"""

    # 持久化文档可能携带历史/未来扩展字段（如 run_status）；响应侧忽略未知字段，
    # 避免历史会话加载因 schema 演进触发 extra_forbidden 500。请求侧模型仍保持严格。
    model_config = ConfigDict(extra="ignore")

    call_id: str
    provider_tool_call_id: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    tool_id: str
    algorithm_id: str
    algorithm_version_id: str | None = None
    algorithm_version: str | None = None
    tool_name: str
    phase: AssistantToolCallPhase
    field_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    input_json_schema: dict[str, Any] = Field(default_factory=dict)
    presentation: dict[str, Any] = Field(default_factory=dict)
    output_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    attributions: list[AttributionItem] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)
    function_name: str | None = None
    provider_tool_call_index: int | None = None
    raw_arguments: str | None = None
    arguments_parse_error: str | None = None
    finish_reason: str | None = None
    proposal_route: dict[str, Any] | None = None
    proposal_usage: dict[str, Any] | None = None
    schema_digest: str | None = None
    input_asset_refs: dict[str, Any] = Field(default_factory=dict)
    uploaded_assets: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    required_assets: list[AlgorithmAssetSpec] = Field(default_factory=list)
    requires_confirmation: bool = True
    run_id: str | None = None
    selection_reason: str | None = None
    selection_confidence: float | None = None
    task_route: dict[str, Any] | None = None
    source_context: dict[str, Any] | None = None
    run_status: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    canceled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
