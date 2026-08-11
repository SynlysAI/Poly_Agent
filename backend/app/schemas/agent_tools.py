"""对话算法工具目录与策略数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.attribution import AttributionItem
from app.schemas.research_engine import AlgorithmAssetSpec, AlgorithmIOSchema


AgentToolPhase = Literal["available", "disabled", "unavailable"]
AgentToolHealthStatus = Literal["healthy", "unknown", "unavailable"]


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
