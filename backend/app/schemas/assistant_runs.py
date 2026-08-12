"""Persistent assistant run contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunStatus = Literal["queued", "running", "completed", "failed", "canceled"]


class AssistantRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=32_000)
    user_message_id: str | None = Field(default=None, max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, str]] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_new_or_continuation(self):
        if not self.content.strip() and not self.user_message_id:
            raise ValueError("content or user_message_id is required")
        return self


class AssistantRun(BaseModel):
    model_config = ConfigDict(extra="ignore")
    run_id: str
    chat_id: str
    created_by: str
    user_message_id: str
    status: RunStatus
    partial_content: str = ""
    error: dict[str, Any] | None = None
    stage: str = "queued"
    event_seq: int = 0
    assistant_message_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    queue_wait_ms: int | None = None
    duration_ms: int | None = None
    first_token_ms: int | None = None
    provider_id: str | None = None
    model_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    http_status: int | None = None
    rate_limited: bool = False
    reconnect_count: int = 0
    events: list[dict[str, Any]] = Field(default_factory=list)


class AssistantRunListData(BaseModel):
    items: list[AssistantRun]
    active: AssistantRun | None = None
    total: int
