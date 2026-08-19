"""Assistant 会话控制状态与工具执行门禁工具。"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.research_engine_repositories import AssistantChatRepository
from app.schemas.assistant_commands import SessionControlState


PERMISSION_MODES = ("read_only", "workspace_write", "full_access")
PERMISSION_LABELS = {
    "read_only": "只读模式",
    "workspace_write": "工作区写入模式",
    "full_access": "完全访问模式",
}


def control_state(chat: dict[str, Any]) -> SessionControlState:
    """从历史或新建会话文档构造带默认值的控制状态。

    Args:
        chat: assistant_chats 集合文档。

    Returns:
        旧字段缺失时自动补默认值的 SessionControlState。
    """
    return SessionControlState(
        chat_id=str(chat.get("chat_id") or ""),
        plan_mode=bool(chat.get("plan_mode", False)),
        permission_mode=str(chat.get("permission_mode") or "workspace_write"),
        goal=chat.get("goal"),
        todos=list(chat.get("todos") or []),
        compaction=chat.get("compaction"),
        command_event_seq=int(chat.get("command_event_seq") or 0),
        model=dict(chat.get("model") or {}),
    )


def tool_execution_block_reason(chat: dict[str, Any]) -> str | None:
    """判断当前会话控制状态是否阻断算法工具执行。

    Args:
        chat: assistant_chats 集合文档。

    Returns:
        阻断原因代码；允许执行时返回 None。
    """
    if bool(chat.get("plan_mode", False)):
        return "plan_mode_blocked"
    if str(chat.get("permission_mode") or "workspace_write") == "read_only":
        return "read_only_blocked"
    return None


def ensure_tool_confirmation_allowed(
    call: dict[str, Any],
    owner_id: str,
) -> None:
    """在工具确认执行前应用会话级权限和 Plan Mode 门禁。

    Args:
        call: Assistant tool call 文档。
        owner_id: 当前会话 owner，用于防止跨用户读取控制状态。

    Raises:
        HTTPException: read-only 或 Plan Mode 阻断执行。
    """
    chat_id = str(call.get("chat_id") or "")
    if not chat_id:
        return
    chat = AssistantChatRepository.find_one({"chat_id": chat_id, "created_by": owner_id})
    if not chat:
        return
    reason = tool_execution_block_reason(chat)
    if reason is None:
        return
    AssistantCommandRunRepository.append_chat_event(
        chat,
        {
            "type": "permission.decision",
            "call_id": str(call.get("call_id") or ""),
            "trace_id": str(
                call.get("trace_id")
                or call.get("assistant_run_id")
                or call.get("call_id")
                or ""
            ),
            "decision": "denied",
            "reason": reason,
            "mode": str(chat.get("permission_mode") or "workspace_write"),
            "plan_mode": bool(chat.get("plan_mode", False)),
        },
    )
    message = (
        "Plan Mode 已阻断工具执行"
        if reason == "plan_mode_blocked"
        else "只读模式已阻断工具执行"
    )
    raise HTTPException(status_code=403, detail={"code": reason, "message": message})
