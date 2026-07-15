"""Assistant request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


AssistantAnswerMode = Literal["llm_project_grounded", "web_grounded", "hybrid_grounded", "fallback"]
AssistantAnswerScope = Literal["project", "web", "hybrid", "model", "unknown"]
AssistantRetrievalStatus = Literal["not_needed", "skipped_disabled", "searched", "no_results", "failed"]


class AssistantMessage(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    content: str = Field(default="", max_length=8000)


class AssistantChatRequest(BaseModel):
    messages: list[AssistantMessage] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)


class AssistantAction(BaseModel):
    label: str
    type: str = "route"
    target: str
    description: str | None = None


class AssistantReference(BaseModel):
    label: str
    target: str
    type: str = "doc"


class AssistantChatResponse(BaseModel):
    content: str
    actions: list[AssistantAction] = Field(default_factory=list)
    references: list[AssistantReference] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    grounding_facts: dict = Field(default_factory=dict)
    confidence: str = "medium"
    answer_mode: AssistantAnswerMode = "llm_project_grounded"
    answer_scope: AssistantAnswerScope = "unknown"
    retrieval_status: AssistantRetrievalStatus = "not_needed"
