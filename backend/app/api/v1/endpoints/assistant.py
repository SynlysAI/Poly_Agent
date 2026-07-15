"""Structured assistant API for dashboard tool guidance."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant import AssistantChatResponse
from app.schemas.common import ApiResponse
from app.services.assistant_service import chat_assistant

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=ApiResponse[AssistantChatResponse])
def assistant_chat(payload: AssistantChatRequest) -> ApiResponse[AssistantChatResponse]:
    """Return assistant content plus structured UI actions."""
    data = chat_assistant(payload)
    return ApiResponse(code=0, message="ok", data=data)
