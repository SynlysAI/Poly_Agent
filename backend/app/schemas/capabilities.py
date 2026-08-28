"""Product capability readiness contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.attribution import AttributionItem
from app.schemas.research_engine import CapabilityLevel


CapabilityViewerRole = Literal["admin", "user"]
CapabilityReadinessStatus = Literal["available", "degraded", "disabled", "unavailable"]
CapabilityGroupStatus = Literal["available", "partial", "unavailable"]


class CapabilityStatus(BaseModel):
    """A product-facing capability status item."""

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1, max_length=120)
    capability_id: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=200)
    level: CapabilityLevel
    configured: bool = False
    healthy: bool = False
    demo_fallback: bool = False
    provider: str | None = None
    model: str | None = None
    last_checked_at: datetime | None = None
    blocking_reason: str | None = None
    next_action: str | None = None


class CapabilityStatusData(BaseModel):
    """Aggregated platform capability response."""

    model_config = ConfigDict(extra="forbid")

    checked_at: datetime
    items: list[CapabilityStatus] = Field(default_factory=list)


class CapabilityPolicySummary(BaseModel):
    """能力中心卡片中的安全策略摘要。"""

    model_config = ConfigDict(extra="forbid")

    allowed_roles: list[CapabilityViewerRole] = Field(default_factory=list)
    requires_confirmation: bool = True
    viewer_can_invoke: bool = False
    scope_note: str = ""


class CapabilityInvocation(BaseModel):
    """能力中心卡片中的调用入口描述。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["dialogue_tool", "agent_connector", "report_skill", "llm_model"]
    method: Literal["navigate", "api"]
    target: str


class CapabilityCatalogItem(BaseModel):
    """能力中心只读目录卡片。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    module_id: str = Field(min_length=1, max_length=120)
    status: CapabilityReadinessStatus
    reason: str | None = Field(default=None, max_length=500)
    policy: CapabilityPolicySummary
    invocation: CapabilityInvocation
    config_path: str = ""
    attributions: list[AttributionItem] = Field(default_factory=list)


class CapabilityCatalogGroup(BaseModel):
    """能力中心固定分组。"""

    model_config = ConfigDict(extra="forbid")

    group_id: Literal["dialogue_tools", "agent_connectors", "report_skills", "llm_capabilities"]
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    status: CapabilityGroupStatus
    total_count: int = Field(default=0, ge=0)
    invocable_count: int = Field(default=0, ge=0)
    unavailable_reason: str | None = Field(default=None, max_length=500)
    items: list[CapabilityCatalogItem] = Field(default_factory=list)


class CapabilityCatalogData(BaseModel):
    """当前用户视角下的能力中心目录。"""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    viewer_role: CapabilityViewerRole
    is_admin: bool
    dialogue_tools: CapabilityCatalogGroup
    agent_connectors: CapabilityCatalogGroup
    report_skills: CapabilityCatalogGroup
    llm_capabilities: CapabilityCatalogGroup


class CapabilityRelevanceItem(BaseModel):
    """单个能力与当前任务的相关性评估结果。"""

    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(min_length=1, max_length=160)
    capability_kind: Literal[
        "computation_adapter",
        "dispatch_profile",
        "knowledge_base",
    ]
    relevant: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str | None = Field(default=None, max_length=500)
    selected: bool = False
    schema_token_estimate: int = Field(default=0, ge=0)


class CapabilityRelevanceAssessment(BaseModel):
    """一次助手请求的能力相关性评估与注入决策。"""

    model_config = ConfigDict(extra="forbid")

    task_summary: str = Field(default="", max_length=4000)
    items: list[CapabilityRelevanceItem] = Field(default_factory=list)
    assessed_at: datetime
    selection_mode: Literal[
        "explicit_only",
        "dynamic_with_explicit_priority",
        "budget_trimmed",
    ] = "dynamic_with_explicit_priority"
    selected_capability_ids: list[str] = Field(default_factory=list)
    omitted_capability_ids: list[str] = Field(default_factory=list)
    token_budget_used: int = Field(default=0, ge=0)
    token_budget_limit: int = Field(default=0, ge=0)
