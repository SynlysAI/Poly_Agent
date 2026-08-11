"""对话算法工具目录与管理员策略接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import get_current_user
from app.schemas.agent_tools import (
    AgentToolListData,
    AgentToolPolicyUpdate,
    AgentToolRegistryData,
    AgentToolRegistryItem,
    AgentToolSyncData,
)
from app.schemas.common import ApiResponse
from app.services.agent_tool_service import agent_tool_service


router = APIRouter(prefix="/agent-tools", tags=["agent-tools"])


def _require_admin(current_user: dict[str, str] | None) -> str:
    if current_user is None:
        return "demo_user"
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以管理算法工具")
    return current_user.get("user_id", "")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


@router.get("", response_model=ApiResponse[AgentToolListData])
def list_agent_tools(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentToolListData]:
    """返回当前用户可以在对话中调用的算法工具。"""
    return ApiResponse(code=0, message="ok", data=agent_tool_service.list_tools(current_user))


@router.get("/registry", response_model=ApiResponse[AgentToolRegistryData])
def list_agent_tool_registry(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentToolRegistryData]:
    """管理员查看所有垂类算法及工具策略。"""
    _require_admin(current_user)
    return ApiResponse(code=0, message="ok", data=agent_tool_service.list_registry())


@router.patch("/{algorithm_id}/policy", response_model=ApiResponse[AgentToolRegistryItem])
def update_agent_tool_policy(
    algorithm_id: str,
    payload: AgentToolPolicyUpdate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentToolRegistryItem]:
    """管理员更新算法工具启用、角色和确认策略。"""
    actor_user_id = _require_admin(current_user)
    data = agent_tool_service.update_policy(
        algorithm_id,
        payload,
        actor_user_id=actor_user_id,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/sync", response_model=ApiResponse[AgentToolSyncData])
def sync_agent_tools(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentToolSyncData]:
    """管理员执行工具策略与算法注册表一致性检查。"""
    _require_admin(current_user)
    return ApiResponse(code=0, message="ok", data=agent_tool_service.sync())
