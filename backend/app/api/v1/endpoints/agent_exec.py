"""Agent 连接器管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user, require_admin
from app.infra.computation_repositories import AuditEventRepository
from app.infra.agent_exec_repositories import AgentExecRunRepository
from app.schemas.agent_exec import (
    AgentExecExecutionRequest,
    AgentExecLuiToolData,
    AgentExecPolicyUpdateRequest,
    AgentExecProviderConnection,
    AgentExecProviderPolicy,
    AgentExecQualitySummaryData,
    AgentExecRunCreateRequest,
    AgentExecRunData,
    AgentExecRunDetailData,
    AgentExecTaskRequest,
)
from app.schemas.common import ApiResponse
from app.services.agent_exec_policy_service import AgentExecPolicyRejected
from app.services.agent_exec_service import (
    AgentExecRequestError,
    AgentExecService,
)


router = APIRouter(prefix="/agent-exec", tags=["agent-exec"])
service = AgentExecService()


def _actor(current_user: dict[str, str] | None) -> tuple[str, str]:
    """解析当前操作人。

    Args:
        current_user: 当前登录用户。

    Returns:
        (user_id, role) 元组。
    """
    if not current_user:
        return "system", "admin"
    return str(current_user.get("user_id") or "system"), str(
        current_user.get("role") or "user"
    )


def _provider_connection(provider) -> AgentExecProviderConnection:
    """把 provider 组装为脱敏连接器卡片。

    Args:
        provider: provider 实例。

    Returns:
        连接器卡片数据。
    """
    return AgentExecProviderConnection(
        provider_id=provider.provider_id,
        display_name=provider.display_name,
        description=getattr(provider, "description", ""),
        supported_task_types=list(provider.supported_task_types),
        sandbox_summary=(
            provider.sandbox_summary()
            if hasattr(provider, "sandbox_summary")
            else ""
        ),
        config_source=(
            provider.config_source() if hasattr(provider, "config_source") else ""
        ),
        attribution=getattr(provider, "attribution", ""),
        readiness=provider.readiness(),
        policy=service.policy_service.get_policy(provider.provider_id),
    )


@router.get(
    "/providers",
    response_model=ApiResponse[list[AgentExecProviderConnection]],
)
def list_providers(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[list[AgentExecProviderConnection]]:
    """按当前角色查看脱敏 Agent 连接器卡片。

    Args:
        current_user: 当前登录用户；本地演示模式按管理员处理。

    Returns:
        管理员全量、普通用户按启用策略过滤后的连接器卡片。
    """
    _, role = _actor(current_user)
    is_admin = role == "admin"
    data = []
    for item in service.registry.list_providers():
        policy = service.policy_service.get_policy(item.provider_id)
        if not is_admin and not (policy.enabled and role in policy.allowed_roles):
            continue
        data.append(_provider_connection(item))
    return ApiResponse(code=0, message="ok", data=data)


@router.patch(
    "/providers/{provider_id}/policy",
    response_model=ApiResponse[AgentExecProviderPolicy],
    dependencies=[Depends(require_admin)],
)
def update_provider_policy(
    provider_id: str,
    payload: AgentExecPolicyUpdateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentExecProviderPolicy]:
    """管理员更新连接器调用策略。"""
    provider = service.registry.get(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail={"reason_code": "provider_not_registered", "message": "连接器不存在"},
        )
    actor_user_id, actor_role = _actor(current_user)
    try:
        _, updated = service.policy_service.update_policy(
            provider,
            payload,
            updated_by=actor_user_id,
            actor_role=actor_role,
        )
    except AgentExecPolicyRejected as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code, "message": exc.message},
        ) from exc
    return ApiResponse(code=0, message="ok", data=updated)


@router.post(
    "/runs",
    response_model=ApiResponse[AgentExecRunData],
)
def create_run(
    payload: AgentExecRunCreateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentExecRunData]:
    """发起由服务端策略治理的受控连接器 run。"""
    actor_user_id, actor_role = _actor(current_user)
    request = AgentExecExecutionRequest(
        provider_id=payload.provider_id,
        task=AgentExecTaskRequest(
            task_type=payload.task_type,
            prompt=payload.prompt,
            input_files=payload.input_files,
            output_schema=payload.output_schema,
            timeout_seconds=payload.timeout_seconds,
        ),
        actor_user_id=actor_user_id,
        actor_role=actor_role,  # type: ignore[arg-type]
        confirmed=payload.confirmed,
        chat_id=payload.chat_id,
        assistant_tool_call_id=payload.assistant_tool_call_id,
    )
    try:
        run = service.execute(request)
    except AgentExecRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code, "message": exc.message},
        ) from exc
    return ApiResponse(code=0, message="ok", data=run)


@router.get(
    "/runs/{run_id}",
    response_model=ApiResponse[AgentExecRunDetailData],
    dependencies=[Depends(require_admin)],
)
def get_run(run_id: str) -> ApiResponse[AgentExecRunDetailData]:
    """管理员查看脱敏 run 状态、事件与策略摘要。"""
    try:
        run = service.get_run(run_id)
    except AgentExecRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code, "message": exc.message},
        ) from exc
    events, _ = AuditEventRepository.list_events(
        entity_type="agent_exec_run",
        entity_id=run_id,
        event_type=None,
        page=1,
        page_size=100,
    )
    policy = run.policy_snapshot
    return ApiResponse(
        code=0,
        message="ok",
        data=AgentExecRunDetailData(
            run=run,
            events=events,
            policy_summary={
                "enabled": policy.enabled,
                "allowed_roles": policy.allowed_roles,
                "allowed_task_types": policy.allowed_task_types,
                "requires_confirmation": policy.requires_confirmation,
            },
        ),
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=ApiResponse[AgentExecRunData],
    dependencies=[Depends(require_admin)],
)
def cancel_run(run_id: str) -> ApiResponse[AgentExecRunData]:
    """管理员取消未结束 run。"""
    try:
        run = service.cancel(run_id)
    except AgentExecRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code, "message": exc.message},
        ) from exc
    return ApiResponse(code=0, message="ok", data=run)


@router.get(
    "/quality",
    response_model=ApiResponse[AgentExecQualitySummaryData],
    dependencies=[Depends(require_admin)],
)
def quality_summary() -> ApiResponse[AgentExecQualitySummaryData]:
    """管理员查看连接器 run 质量摘要。"""
    runs, _ = AgentExecRunRepository.list_runs(page=1, page_size=1000)
    completed = sum(1 for item in runs if item.status == "completed")
    failed = sum(1 for item in runs if item.status == "failed")
    cancelled = sum(1 for item in runs if item.status == "cancelled")
    durations = [item.duration_ms for item in runs if item.duration_ms is not None]
    summary = AgentExecQualitySummaryData(
        total_runs=len(runs),
        completed=completed,
        failed=failed,
        cancelled=cancelled,
        success_rate=(completed / len(runs)) if runs else None,
        unavailable_count=sum(
            1 for item in runs if item.error_code == "provider_unavailable"
        ),
        timeout_count=sum(1 for item in runs if item.error_code == "timeout"),
        total_input_bytes=sum(
            item.size_bytes for run in runs for item in run.input_files
        ),
        total_output_bytes=sum(
            item.size_bytes for run in runs for item in run.artifacts
        ),
        avg_duration_ms=(
            int(sum(durations) / len(durations)) if durations else None
        ),
    )
    return ApiResponse(code=0, message="ok", data=summary)


@router.get(
    "/lui-tool",
    response_model=ApiResponse[AgentExecLuiToolData | None],
)
def get_lui_tool(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AgentExecLuiToolData | None]:
    """返回默认关闭的 LUI 外部 Agent 文件任务描述符。"""
    role = str(current_user.get("role") or "admin") if current_user else "admin"
    return ApiResponse(code=0, message="ok", data=service.lui_tool(role=role))
