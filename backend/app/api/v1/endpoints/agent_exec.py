"""Agent 连接器管理 API。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user, require_admin
from app.core.time import utc_now
from app.infra.computation_repositories import AuditEventRepository
from app.infra.agent_exec_repositories import AgentExecRunRepository
from app.schemas.agent_exec import (
    AgentExecAuditRecoveryData,
    AgentExecExecutionRequest,
    AgentExecLuiToolData,
    AgentExecPolicyUpdateRequest,
    AgentExecProviderConnection,
    AgentExecProviderProbeData,
    AgentExecProviderPolicy,
    AgentExecQualitySummaryData,
    AgentExecRunCreateRequest,
    AgentExecRunData,
    AgentExecRunDetailData,
    AgentExecRunListData,
    AgentExecTaskRequest,
)
from app.schemas.common import ApiResponse
from app.services.agent_exec_alert_service import AgentExecAlertService
from app.services.agent_exec_policy_service import AgentExecPolicyRejected
from app.services.agent_exec_service import (
    AgentExecRequestError,
    AgentExecService,
)


router = APIRouter(prefix="/agent-exec", tags=["agent-exec"])
service = AgentExecService()


def _list_runs_for_quality(
    *,
    provider_id: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
) -> list[AgentExecRunData]:
    """分页读取质量统计所需的全量 run。

    Args:
        provider_id: provider 过滤条件。
        created_after: 创建时间下界。
        created_before: 创建时间上界。

    Returns:
        时间窗内的全部 run 列表。
    """
    runs: list = []
    page = 1
    while True:
        items, total = AgentExecRunRepository.list_runs(
            provider_id=provider_id,
            created_after=created_after,
            created_before=created_before,
            page=page,
            page_size=500,
        )
        runs.extend(items)
        if len(runs) >= total:
            return runs
        page += 1


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


def _provider_connection(
    provider,
    *,
    include_policy_actor: bool = True,
) -> AgentExecProviderConnection:
    """把 provider 组装为脱敏连接器卡片。

    Args:
        provider: provider 实例。
        include_policy_actor: 是否返回策略更新者与更新时间。

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
        policy=_policy_for_view(
            service.policy_service.get_policy(provider.provider_id),
            include_actor=include_policy_actor,
        ),
    )


def _policy_for_view(
    policy: AgentExecProviderPolicy,
    *,
    include_actor: bool,
) -> AgentExecProviderPolicy:
    """按视角脱敏策略治理者信息。

    Args:
        policy: 服务端权威策略。
        include_actor: 当前视角是否允许查看策略更新者。

    Returns:
        普通用户视角会清空 updated_by / updated_at，其他视角原样返回。
    """
    if include_actor:
        return policy
    return policy.model_copy(update={"updated_by": "", "updated_at": None})


def _run_for_view(run: AgentExecRunData, *, is_admin: bool) -> AgentExecRunData:
    """按视角脱敏 run 内的策略治理者信息。

    Args:
        run: 服务端权威 run 状态。
        is_admin: 当前视角是否为管理员。

    Returns:
        普通用户视角的脱敏 run 响应。
    """
    if is_admin:
        return run
    policy = _policy_for_view(run.policy_snapshot, include_actor=False)
    return run.model_copy(update={"policy_snapshot": policy})


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
        data.append(_provider_connection(item, include_policy_actor=is_admin))
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/providers/{provider_id}/probe",
    response_model=ApiResponse[AgentExecProviderProbeData],
    dependencies=[Depends(require_admin)],
)
def probe_provider(provider_id: str) -> ApiResponse[AgentExecProviderProbeData]:
    """管理员显式探测连接器二进制版本与 readiness。

    Args:
        provider_id: provider 唯一标识。

    Returns:
        包含 readiness、路径、摘要与版本的探测结果。
    """
    provider = service.registry.get(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail={"reason_code": "provider_not_registered", "message": "连接器不存在"},
        )
    if not hasattr(provider, "probe"):
        raise HTTPException(
            status_code=501,
            detail={"reason_code": "provider_probe_unsupported", "message": "该连接器不支持显式探测"},
        )
    return ApiResponse(code=0, message="ok", data=provider.probe())


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
    _, role = _actor(current_user)
    return ApiResponse(
        code=0,
        message="ok",
        data=_run_for_view(run, is_admin=role == "admin"),
    )


@router.get(
    "/runs",
    response_model=ApiResponse[AgentExecRunListData],
    dependencies=[Depends(require_admin)],
)
def list_runs(
    provider_id: str | None = Query(default=None, min_length=1, max_length=120),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    chat_id: str | None = Query(default=None, min_length=1, max_length=120),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[AgentExecRunListData]:
    """管理员分页查看 run 状态。

    Args:
        provider_id: provider 过滤条件。
        status: run 状态过滤条件。
        chat_id: 会话过滤条件。
        created_after: 创建时间下界。
        created_before: 创建时间上界。
        page: 页码。
        page_size: 每页数量。

    Returns:
        run 分页列表。
    """
    if status is not None and status not in {
        "requested",
        "running",
        "completed",
        "failed",
        "cancelled",
    }:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "status_invalid", "message": "run 状态无效"},
        )
    if created_after is not None and created_before is not None and created_after > created_before:
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "time_window_invalid",
                "message": "created_after 不能晚于 created_before",
            },
        )
    items, total = AgentExecRunRepository.list_runs(
        provider_id=provider_id,
        status=status,
        chat_id=chat_id,
        created_after=created_after,
        created_before=created_before,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(
        code=0,
        message="ok",
        data=AgentExecRunListData(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        ),
    )


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
    "/runs/{run_id}/audit/retry",
    response_model=ApiResponse[AgentExecAuditRecoveryData],
    dependencies=[Depends(require_admin)],
)
def retry_run_audit(run_id: str) -> ApiResponse[AgentExecAuditRecoveryData]:
    """管理员补写缺失的 run 生命周期审计事件。"""
    try:
        run, recovered = service.recover_audit_events(run_id)
    except AgentExecRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"reason_code": exc.reason_code, "message": exc.message},
        ) from exc
    return ApiResponse(
        code=0,
        message="ok",
        data=AgentExecAuditRecoveryData(
            run=run,
            recovered_event_types=recovered,
            recovered_at=utc_now(),
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
def quality_summary(
    provider_id: str | None = Query(default=None, min_length=1, max_length=120),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
) -> ApiResponse[AgentExecQualitySummaryData]:
    """管理员查看连接器 run 质量摘要。

    Args:
        provider_id: provider 过滤条件。
        created_after: 统计窗口下界。
        created_before: 统计窗口上界。

    Returns:
        时间窗与 provider 维度的质量摘要。
    """
    if created_after is not None and created_before is not None and created_after > created_before:
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "time_window_invalid",
                "message": "created_after 不能晚于 created_before",
            },
        )
    runs = _list_runs_for_quality(
        provider_id=provider_id,
        created_after=created_after,
        created_before=created_before,
    )
    completed = sum(1 for item in runs if item.status == "completed")
    failed = sum(1 for item in runs if item.status == "failed")
    cancelled = sum(1 for item in runs if item.status == "cancelled")
    durations = [item.duration_ms for item in runs if item.duration_ms is not None]
    failure_rate = (failed / len(runs)) if runs else 0.0
    timeout_rate = (
        sum(1 for item in runs if item.error_code == "timeout") / len(runs)
        if runs
        else 0.0
    )
    alert_reasons: list[str] = []
    alert_level: str = "none"
    if any(item.audit_error for item in runs):
        alert_reasons.append("audit_error_present")
        alert_level = "critical"
    if failure_rate >= 0.5 or timeout_rate >= 0.3:
        alert_reasons.append("failure_or_timeout_rate_high")
        alert_level = "critical"
    elif failure_rate >= 0.2 or timeout_rate >= 0.1:
        alert_reasons.append("failure_or_timeout_rate_elevated")
        alert_level = "warning"
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
        audit_error_count=sum(1 for item in runs if item.audit_error),
        total_input_bytes=sum(
            item.size_bytes for run in runs for item in run.input_files
        ),
        total_output_bytes=sum(
            item.size_bytes for run in runs for item in run.artifacts
        ),
        avg_duration_ms=(
            int(sum(durations) / len(durations)) if durations else None
        ),
        window_started_at=created_after,
        window_ended_at=created_before,
        provider_id=provider_id,
        alert_level=alert_level,  # type: ignore[arg-type]
        alert_reasons=alert_reasons,
    )
    AgentExecAlertService.emit(
        level=alert_level,
        title="agent_exec run 质量异常",
        reasons=alert_reasons,
        context={
            "provider_id": provider_id,
            "total_runs": summary.total_runs,
            "failure_rate": failure_rate,
            "timeout_rate": timeout_rate,
            "audit_error_count": summary.audit_error_count,
        },
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
