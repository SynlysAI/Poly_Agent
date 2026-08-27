"""Product capability readiness contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.research_engine import CapabilityLevel


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
