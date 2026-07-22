"""Product capability readiness contracts."""

from __future__ import annotations

from datetime import datetime

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
