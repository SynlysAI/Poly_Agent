"""Structured assistant API for dashboard tool guidance."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user
from app.schemas.agent_tools import (
    AssistantToolCall,
    AssistantToolCallConfirm,
    AssistantToolCallCreate,
    AssistantToolCallInputUpdate,
)
from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant import AssistantChatResponse
from app.schemas.assistant_chats import (
    AssistantChat,
    AssistantChatCreate,
    AssistantChatListData,
    AssistantChatUpdate,
    AssistantMessage,
    AssistantMessageCreate,
    AssistantMessageListData,
    AssistantMessageUpdate,
)
from app.schemas.common import ApiResponse
from app.services.assistant_service import chat_assistant
from app.services.assistant_service import stream_chat_assistant
from app.services.assistant_tool_service import assistant_tool_call_service
from app.services.assistant_chat_service import assistant_chat_service

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/chats", response_model=ApiResponse[AssistantChatListData])
def list_assistant_chats(
    query: str | None = Query(default=None, max_length=200),
    archived: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChatListData]:
    data = assistant_chat_service.list(
        query=query,
        archived=archived,
        page=page,
        page_size=page_size,
        current_user=current_user,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/chats", response_model=ApiResponse[AssistantChat])
def create_assistant_chat(
    payload: AssistantChatCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChat]:
    return ApiResponse(code=0, message="created", data=assistant_chat_service.create(payload, current_user))


@router.get("/chats/{chat_id}", response_model=ApiResponse[AssistantChat])
def get_assistant_chat(
    chat_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChat]:
    return ApiResponse(code=0, message="ok", data=assistant_chat_service.get(chat_id, current_user))


@router.patch("/chats/{chat_id}", response_model=ApiResponse[AssistantChat])
def update_assistant_chat(
    chat_id: str,
    payload: AssistantChatUpdate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChat]:
    return ApiResponse(code=0, message="updated", data=assistant_chat_service.update(chat_id, payload, current_user))


@router.delete("/chats/{chat_id}", response_model=ApiResponse[None])
def delete_assistant_chat(
    chat_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[None]:
    assistant_chat_service.delete(chat_id, current_user)
    return ApiResponse(code=0, message="deleted", data=None)


@router.get("/chats/{chat_id}/messages", response_model=ApiResponse[AssistantMessageListData])
def list_assistant_messages(
    chat_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=500),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantMessageListData]:
    return ApiResponse(
        code=0,
        message="ok",
        data=assistant_chat_service.list_messages(
            chat_id,
            page=page,
            page_size=page_size,
            current_user=current_user,
        ),
    )


@router.post("/chats/{chat_id}/messages", response_model=ApiResponse[AssistantMessage])
def create_assistant_message(
    chat_id: str,
    payload: AssistantMessageCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantMessage]:
    return ApiResponse(
        code=0,
        message="created",
        data=assistant_chat_service.create_message(chat_id, payload, current_user),
    )


@router.patch("/chats/{chat_id}/messages/{message_id}", response_model=ApiResponse[AssistantMessage])
def update_assistant_message(
    chat_id: str,
    message_id: str,
    payload: AssistantMessageUpdate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantMessage]:
    return ApiResponse(
        code=0,
        message="updated",
        data=assistant_chat_service.update_message(chat_id, message_id, payload, current_user),
    )


@router.delete("/chats/{chat_id}/messages/{message_id}", response_model=ApiResponse[None])
def delete_assistant_message(
    chat_id: str,
    message_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[None]:
    assistant_chat_service.delete_message(chat_id, message_id, current_user)
    return ApiResponse(code=0, message="deleted", data=None)


@router.post("/chat", response_model=ApiResponse[AssistantChatResponse])
def assistant_chat(
    payload: AssistantChatRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChatResponse]:
    """Return assistant content plus structured UI actions."""
    data = chat_assistant(payload, current_user)
    return ApiResponse(code=0, message="ok", data=data)


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(jsonable_encoder(payload), ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def assistant_chat_stream(
    payload: AssistantChatRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> StreamingResponse:
    """Stream observable assistant stages, answer chunks, and final structured data."""
    return StreamingResponse(
        (_sse_event(event) for event in stream_chat_assistant(payload, current_user)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tool-calls", response_model=ApiResponse[AssistantToolCall])
def create_assistant_tool_call(
    payload: AssistantToolCallCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantToolCall]:
    """创建 pending 算法工具调用，并返回参数补充或确认状态。"""
    return ApiResponse(code=0, message="ok", data=assistant_tool_call_service.create(payload, current_user))


@router.get("/tool-calls/{call_id}", response_model=ApiResponse[AssistantToolCall])
def get_assistant_tool_call(
    call_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantToolCall]:
    return ApiResponse(code=0, message="ok", data=assistant_tool_call_service.get(call_id, current_user))


@router.patch("/tool-calls/{call_id}/input", response_model=ApiResponse[AssistantToolCall])
def update_assistant_tool_call_input(
    call_id: str,
    payload: AssistantToolCallInputUpdate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantToolCall]:
    """补充算法必填参数或已有 artifact 引用。"""
    data = assistant_tool_call_service.update_input(call_id, payload, current_user)
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/tool-calls/{call_id}/input:multipart", response_model=ApiResponse[AssistantToolCall])
async def upload_assistant_tool_call_input(
    call_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantToolCall]:
    """上传 pending 调用声明的文件输入，复用 AlgorithmRun 的输入资产校验。"""
    form = await request.form()
    uploads: dict[str, dict] = {}
    for key, value in form.multi_items():
        if not hasattr(value, "read"):
            continue
        content = await value.read(50 * 1024 * 1024 + 1)
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="输入文件超过平台上传上限")
        uploads[key] = {
            "filename": getattr(value, "filename", None) or key,
            "content_type": getattr(value, "content_type", None) or "application/octet-stream",
            "content": content,
        }
    data = assistant_tool_call_service.upload_input_assets(call_id, uploads, current_user)
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/tool-calls/{call_id}/confirm", response_model=ApiResponse[AssistantToolCall])
def confirm_assistant_tool_call(
    call_id: str,
    payload: AssistantToolCallConfirm | None = None,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantToolCall]:
    """确认并执行算法工具调用；已完成调用重复确认保持幂等。"""
    data = assistant_tool_call_service.confirm(
        call_id,
        payload or AssistantToolCallConfirm(),
        current_user,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/tool-calls/{call_id}/cancel", response_model=ApiResponse[AssistantToolCall])
def cancel_assistant_tool_call(
    call_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantToolCall]:
    """取消尚未执行的算法工具调用。"""
    return ApiResponse(code=0, message="ok", data=assistant_tool_call_service.cancel(call_id, current_user))


@router.get("/tool-calls/{call_id}/events")
def stream_assistant_tool_call_events(
    call_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> StreamingResponse:
    """通过 SSE 重放调用状态，便于页面断线后恢复状态。"""
    events = list(assistant_tool_call_service.stream_events(call_id, current_user))
    return StreamingResponse(
        (_sse_event(event) for event in events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
