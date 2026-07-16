"""Structured assistant API for dashboard tool guidance."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant import AssistantChatResponse
from app.schemas.common import ApiResponse
from app.services.assistant_service import chat_assistant
from app.services.assistant_service import stream_chat_assistant

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/chat", response_model=ApiResponse[AssistantChatResponse])
def assistant_chat(payload: AssistantChatRequest) -> ApiResponse[AssistantChatResponse]:
    """Return assistant content plus structured UI actions."""
    data = chat_assistant(payload)
    return ApiResponse(code=0, message="ok", data=data)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def assistant_chat_stream(payload: AssistantChatRequest) -> StreamingResponse:
    """Stream observable assistant stages, answer chunks, and final structured data."""
    return StreamingResponse(
        (_sse_event(event) for event in stream_chat_assistant(payload)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
