"""Structured assistant API for dashboard tool guidance."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user, get_current_user_with_query_token, require_admin
from app.core.config import settings
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
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
    AssistantChatSummaryListData,
    AssistantChatUpdate,
    AssistantMessage,
    AssistantMessageCreate,
    AssistantMessageListData,
    AssistantMessageUpdate,
)
from app.schemas.assistant_commands import (
    CommandCatalogData,
    CommandEventListData,
    CommandExecuteRequest,
    CommandExecution,
    SessionControlState,
)
from app.schemas.assistant_runs import AssistantRun, AssistantRunCreate, AssistantRunListData
from app.schemas.assistant_trace import (
    AssistantChatTraceData,
    AssistantTraceBatchData,
    AssistantTraceData,
)
from app.schemas.common import ApiResponse
from app.services.assistant_service import chat_assistant
from app.services.assistant_service import stream_chat_assistant
from app.services.assistant_command_service import assistant_command_service
from app.services.assistant_tool_service import assistant_tool_call_service
from app.services.assistant_chat_service import assistant_chat_service
from app.services.assistant_quality_service import build_quality_metrics
from app.services.assistant_run_service import assistant_run_service
from app.services.assistant_trace_service import assistant_trace_service
from app.services.lui_evaluation_service import load_baseline_summary

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/commands", response_model=ApiResponse[CommandCatalogData])
def list_assistant_commands(
    chat_id: str = Query(min_length=1, max_length=80),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CommandCatalogData]:
    """返回当前会话可发现的 Slash Command 目录。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=assistant_command_service.catalog(chat_id, current_user),
    )


@router.post("/commands/execute", response_model=ApiResponse[CommandExecution])
def execute_assistant_command(
    payload: CommandExecuteRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CommandExecution]:
    """在命令平面执行一行 Slash Command。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=assistant_command_service.execute(payload, current_user),
    )


@router.get("/commands/{command_id}/download")
def download_assistant_command_export(
    command_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user_with_query_token),
) -> FileResponse:
    """以原生浏览器下载方式返回会话导出文件。

    Args:
        command_id: 导出命令 ID。
        current_user: 当前登录用户。

    Returns:
        受管导出文件响应。
    """
    owner_id = (current_user or {}).get("user_id") or "demo_user"
    command = AssistantCommandRunRepository.find_one(
        {"command_id": command_id, "created_by": owner_id}
    )
    if not command or command.get("name") != "export" or command.get("status") != "success":
        raise HTTPException(status_code=404, detail="导出文件不存在")
    filename = str(command.get("download_filename") or "")
    extension = Path(filename).suffix.lower()
    extension_map = {
        ".json": "application/json",
        ".md": "text/markdown; charset=utf-8",
        ".zip": "application/zip",
    }
    if extension not in extension_map:
        raise HTTPException(status_code=404, detail="导出文件不存在")
    expected_path = (
        settings.runtime_root / "assistant-exports" / f"{command_id}{extension}"
    ).resolve()
    if not expected_path.is_file():
        raise HTTPException(status_code=404, detail="导出文件已过期或不存在")
    return FileResponse(
        expected_path,
        media_type=extension_map[extension],
        filename=filename,
    )


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


@router.get("/chat-summaries", response_model=ApiResponse[AssistantChatSummaryListData])
def list_assistant_chat_summaries(
    query: str | None = Query(default=None, max_length=200),
    archived: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChatSummaryListData]:
    data = assistant_chat_service.list_summaries(
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


@router.get("/chats/{chat_id}/session-state", response_model=ApiResponse[SessionControlState])
def get_assistant_session_state(
    chat_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[SessionControlState]:
    """读取带旧数据默认值的会话控制状态。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=assistant_command_service.session_state(chat_id, current_user),
    )


@router.get("/chats/{chat_id}/command-events", response_model=ApiResponse[CommandEventListData])
def list_assistant_command_events(
    chat_id: str,
    after_seq: int = Query(default=0, ge=0),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CommandEventListData]:
    """按会话事件序号回放命令生命周期事件。"""
    items, next_after_seq = assistant_command_service.command_events(
        chat_id,
        current_user,
        after_seq,
    )
    return ApiResponse(
        code=0,
        message="ok",
        data=CommandEventListData(items=items, total=len(items), next_after_seq=next_after_seq),
    )


@router.get("/chats/{chat_id}/trace", response_model=ApiResponse[AssistantChatTraceData])
def get_assistant_chat_trace(
    chat_id: str,
    after_seq: int = Query(default=0, ge=0),
    event_types: list[str] | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantChatTraceData]:
    """读取会话级命令、模型、工具与控制事件统一 Trace。"""
    normalized_types = {
        item.strip()
        for item in (event_types or [])
        if item.strip()
    } or None
    return ApiResponse(
        code=0,
        message="ok",
        data=assistant_trace_service.get_chat(
            chat_id,
            current_user,
            after_seq=after_seq,
            event_types=normalized_types,
        ),
    )


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


@router.post("/chats/{chat_id}/runs", response_model=ApiResponse[AssistantRun])
def create_assistant_run(
    chat_id: str,
    payload: AssistantRunCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantRun]:
    return ApiResponse(code=0, message="queued", data=assistant_run_service.create(chat_id, payload, current_user))


@router.get("/chats/{chat_id}/runs", response_model=ApiResponse[AssistantRunListData])
def list_assistant_runs(
    chat_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantRunListData]:
    data = assistant_run_service.list_for_chat(chat_id, current_user, page=page, page_size=page_size)
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/runs/{run_id}", response_model=ApiResponse[AssistantRun])
def get_assistant_run(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantRun]:
    return ApiResponse(code=0, message="ok", data=assistant_run_service.get(run_id, current_user))


@router.get("/runs-active/current", response_model=ApiResponse[AssistantRun | None])
def get_active_assistant_run(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantRun | None]:
    return ApiResponse(code=0, message="ok", data=assistant_run_service.get_active(current_user))


@router.get("/traces/batch", response_model=ApiResponse[AssistantTraceBatchData])
def list_assistant_traces_batch(
    trace_ids: list[str] = Query(default=[]),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantTraceBatchData]:
    """批量恢复当前会话中的多条 Execution Trace。"""
    if len(trace_ids) > 200:
        raise HTTPException(status_code=422, detail="trace_ids 单次最多 200 个")
    return ApiResponse(
        code=0,
        message="ok",
        data=AssistantTraceBatchData(
            items=assistant_trace_service.get_many(trace_ids, current_user)
        ),
    )


@router.get("/traces/{trace_id}", response_model=ApiResponse[AssistantTraceData])
def get_assistant_trace(
    trace_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantTraceData]:
    """读取一条用户请求的完整 Execution Trace 快照。"""
    return ApiResponse(code=0, message="ok", data=assistant_trace_service.get(trace_id, current_user))


@router.get("/traces/{trace_id}/events")
def stream_assistant_trace_events(
    trace_id: str,
    after_event_id: str | None = Query(default=None, max_length=120),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> StreamingResponse:
    """通过 SSE 实时输出 Execution Trace 步骤。"""
    return StreamingResponse(
        (
            _sse_event(event)
            for event in assistant_trace_service.events(trace_id, current_user, after_event_id)
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/events")
def stream_assistant_run_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        (_sse_event(event) for event in assistant_run_service.events(run_id, current_user, after_seq)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel", response_model=ApiResponse[AssistantRun])
def cancel_assistant_run(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AssistantRun]:
    return ApiResponse(code=0, message="ok", data=assistant_run_service.cancel(run_id, current_user))


@router.get("/run-metrics/summary", response_model=ApiResponse[dict], dependencies=[Depends(require_admin)])
def assistant_run_metrics(
    created_by: str | None = Query(default=None),
    provider_id: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> ApiResponse[dict]:
    data = assistant_run_service.metrics(
        created_by=created_by, provider_id=provider_id, model_id=model_id, status=status,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/quality-metrics/summary", response_model=ApiResponse[dict], dependencies=[Depends(require_admin)])
def assistant_quality_metrics(
    since: str | None = Query(default=None),
    until: str | None = Query(default=None),
) -> ApiResponse[dict]:
    """聚合 LUI 路由、工具提案、执行与续答质量指标。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=build_quality_metrics(since=since, until=until, use_cache=True),
    )


@router.get("/lui-evaluation/summary", response_model=ApiResponse[dict], dependencies=[Depends(require_admin)])
def lui_evaluation_baseline_summary(
    mode: str = Query(default="smoke", pattern="^(smoke|full)$"),
) -> ApiResponse[dict]:
    """读取受控 LUI 评测基线的任务级 M1–M8 汇总。

    与 `/quality-metrics/summary` 的区别：质量接口聚合生产链路侧
    指标；本接口读取离线 Golden Set 评测基线，反映任务级结果质量。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=load_baseline_summary(mode=mode),
    )


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
    after_seq: int = Query(default=0, ge=0),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> StreamingResponse:
    """通过 SSE 重放调用状态，便于页面断线后恢复状态。"""
    events = list(assistant_tool_call_service.stream_events(call_id, current_user, after_seq))
    return StreamingResponse(
        (_sse_event(event) for event in events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
