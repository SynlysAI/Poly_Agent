"""ResearchEngine API 端点。

暴露 ProblemSpec、AlgorithmRegistry、AlgorithmRun、ResearchRun 和 Stage/Gate 的 REST API。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.research_engine import (
    AlgorithmRegistryEntry,
    AlgorithmRegistryListData,
    AlgorithmRun,
    AlgorithmRunCreate,
    AlgorithmRunListData,
    AlgorithmRunTraceability,
    EntityAuditListData,
    ExecutionDecision,
    ExecutionDecisionCreate,
    ExecutionDecisionListData,
    ManualAlgorithmWorkflow,
    ManualAlgorithmWorkflowCreate,
    ManualAlgorithmWorkflowListData,
    ProblemSpec,
    ProblemSpecCreate,
    ProblemSpecListData,
    ResearchRun,
    ResearchRunCreate,
    ResearchRunListData,
    ResearchRunStatusChangeRequest,
    ResearchRunTraceability,
    StageApprovalRequest,
    StageRunTraceability,
    WorkflowRun,
    WorkflowRunListData,
)
from app.services.research_engine_orchestrator import ResearchEngineOrchestrator
from app.services.research_engine_service import ResearchEngineService

router = APIRouter(prefix="/research-engine", tags=["research-engine"])
service = ResearchEngineService()
orchestrator = ResearchEngineOrchestrator()


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    """解析当前操作人。"""
    return current_user["user_id"] if current_user else "demo_user"


def _request_id(request: Request) -> str | None:
    """读取请求追踪 ID。"""
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


# =============================================================================
# ProblemSpec API
# =============================================================================


@router.post("/problem-specs", response_model=ApiResponse[ProblemSpec])
def create_problem_spec(
    payload: ProblemSpecCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """创建 ProblemSpec 草稿。

    支持定义材料研发任务的变量、目标、约束和可选执行路径。
    创建时可选择关联已有 campaign 或自动创建首版容器 campaign。
    """
    data = service.create_problem_spec(
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/problem-specs", response_model=ApiResponse[ProblemSpecListData])
def list_problem_specs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    project_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    material_family: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpecListData]:
    """查询 ProblemSpec 列表。

    支持按项目、campaign、状态、材料体系过滤和分页。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=service.list_problem_specs(
            project_id=project_id,
            campaign_id=campaign_id,
            created_by=current_user["user_id"] if current_user else None,
            status=status,
            material_family=material_family,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/problem-specs/{problem_spec_id}", response_model=ApiResponse[ProblemSpec])
def get_problem_spec(
    problem_spec_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """获取 ProblemSpec 详情。"""
    data = service.get_problem_spec(problem_spec_id)
    return ApiResponse(code=0, message="ok", data=data)


@router.patch("/problem-specs/{problem_spec_id}", response_model=ApiResponse[ProblemSpec])
def update_problem_spec(
    problem_spec_id: str,
    payload: ProblemSpecCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """更新 ProblemSpec 草稿。

    已冻结的 ProblemSpec 不可直接修改，需复制为新版本。
    """
    data = service.update_problem_spec(
        problem_spec_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/problem-specs/{problem_spec_id}/freeze", response_model=ApiResponse[ProblemSpec])
def freeze_problem_spec(
    problem_spec_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """冻结 ProblemSpec。

    冻结后不可直接修改，只能复制为新版本后编辑。
    """
    data = service.freeze_problem_spec(
        problem_spec_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ExecutionDecision API
# =============================================================================


@router.post(
    "/problem-specs/{problem_spec_id}/execution-decisions",
    response_model=ApiResponse[ExecutionDecision],
)
def create_execution_decision(
    problem_spec_id: str,
    payload: ExecutionDecisionCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExecutionDecision]:
    """为 ProblemSpec 显式选择 manual_workbench 或 autoresearch。"""
    data = service.create_execution_decision(
        problem_spec_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/problem-specs/{problem_spec_id}/execution-decisions",
    response_model=ApiResponse[ExecutionDecisionListData],
)
def list_execution_decisions(
    problem_spec_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExecutionDecisionListData]:
    """查询 ProblemSpec 的执行决策历史。"""
    data = service.list_execution_decisions(
        problem_spec_id=problem_spec_id,
        mode=mode,
        status=status,
        created_by=current_user["user_id"] if current_user else None,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/problem-specs/{problem_spec_id}/execution-decisions/active",
    response_model=ApiResponse[ExecutionDecision],
)
def get_active_execution_decision(
    problem_spec_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExecutionDecision]:
    """查询 ProblemSpec 当前 active 执行决策。"""
    data = service.get_active_execution_decision(problem_spec_id)
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# AlgorithmRegistry API
# =============================================================================


@router.get("/algorithms", response_model=ApiResponse[AlgorithmRegistryListData])
def list_algorithms(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    type: str | None = Query(default=None, alias="type"),
    algorithm_family: str | None = Query(default=None),
    material_scope: str | None = Query(default=None),
    trigger_mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRegistryListData]:
    """查询算法能力清单。

    支持按类型、材料体系、触发方式、状态过滤和分页。
    响应字段足够前端渲染算法卡和 schema drawer。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=service.list_algorithms(
            algorithm_type=type,
            algorithm_family=algorithm_family,
            material_scope=material_scope,
            trigger_mode=trigger_mode,
            status=status,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/algorithms/{algorithm_id}", response_model=ApiResponse[AlgorithmRegistryEntry])
def get_algorithm(
    algorithm_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRegistryEntry]:
    """获取单个算法能力条目详情。

    包含算法名称、类型、材料范围、输入输出 schema 等完整信息。
    """
    data = service.get_algorithm(algorithm_id)
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ManualWorkflow / WorkflowRun / AlgorithmRun API
# =============================================================================


@router.post("/manual-workflows", response_model=ApiResponse[ManualAlgorithmWorkflow])
def create_manual_workflow(
    payload: ManualAlgorithmWorkflowCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflow]:
    """创建人工算法 Workflow。"""
    data = service.create_manual_workflow(
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/manual-workflows", response_model=ApiResponse[ManualAlgorithmWorkflowListData])
def list_manual_workflows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    problem_spec_id: str | None = Query(default=None),
    execution_decision_id: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflowListData]:
    """查询人工算法 Workflow 列表。"""
    data = service.list_manual_workflows(
        problem_spec_id=problem_spec_id,
        execution_decision_id=execution_decision_id,
        created_by=current_user["user_id"] if current_user else None,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/manual-workflows/{workflow_id}", response_model=ApiResponse[ManualAlgorithmWorkflow])
def get_manual_workflow(
    workflow_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflow]:
    """获取人工算法 Workflow 详情。"""
    data = service.get_manual_workflow(workflow_id)
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/manual-workflows/{workflow_id}/runs", response_model=ApiResponse[WorkflowRun])
def start_workflow_run(
    workflow_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[WorkflowRun]:
    """启动人工 WorkflowRun。"""
    data = service.start_workflow_run(
        workflow_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/workflow-runs", response_model=ApiResponse[WorkflowRunListData])
def list_workflow_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    workflow_id: str | None = Query(default=None),
    problem_spec_id: str | None = Query(default=None),
    execution_decision_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[WorkflowRunListData]:
    """查询 WorkflowRun 列表。"""
    data = service.list_workflow_runs(
        workflow_id=workflow_id,
        problem_spec_id=problem_spec_id,
        execution_decision_id=execution_decision_id,
        status=status,
        created_by=current_user["user_id"] if current_user else None,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/workflow-runs/{workflow_run_id}", response_model=ApiResponse[WorkflowRun])
def get_workflow_run(
    workflow_run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[WorkflowRun]:
    """获取 WorkflowRun 详情。"""
    data = service.get_workflow_run(workflow_run_id)
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-runs", response_model=ApiResponse[AlgorithmRun])
def create_algorithm_run(
    payload: AlgorithmRunCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRun]:
    """创建并执行算法运行。

    v0.4 产品主路径中，人工模式应由 ManualAlgorithmWorkflow / WorkflowRun 创建节点运行；
    该端点保留给兼容调用和 AutoResearch 内部编排。
    系统校验算法是否支持对应 trigger_source，执行 mock runner 并记录完整运行产物。
    运行产物包含 input_snapshot、output_summary、artifact_refs 和审计事件。
    """
    data = service.create_algorithm_run(
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-runs", response_model=ApiResponse[AlgorithmRunListData])
def list_algorithm_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    problem_spec_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    workflow_run_id: str | None = Query(default=None),
    algorithm_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    trigger_source: str | None = Query(default=None),
    research_run_id: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRunListData]:
    """查询 AlgorithmRun 列表。

    支持按 ProblemSpec、Campaign、算法、状态、触发来源、ResearchRun 过滤和分页。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=service.list_algorithm_runs(
            problem_spec_id=problem_spec_id,
            campaign_id=campaign_id,
            workflow_run_id=workflow_run_id,
            algorithm_id=algorithm_id,
            status=status,
            trigger_source=trigger_source,
            research_run_id=research_run_id,
            created_by=current_user["user_id"] if current_user else None,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/algorithm-runs/{run_id}", response_model=ApiResponse[AlgorithmRun])
def get_algorithm_run(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRun]:
    """获取 AlgorithmRun 详情。

    响应包含 input_snapshot、output_summary、artifact_refs、错误信息和审计事件引用。
    """
    data = service.get_algorithm_run(run_id)
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ResearchRun API
# =============================================================================


@router.post("/research-runs", response_model=ApiResponse[ResearchRun])
def create_research_run(
    payload: ResearchRunCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """创建 ResearchRun 草稿。

    基于 ProblemSpec 创建 AutoResearch 运行，自动生成默认阶段序列。
    创建后状态为 draft，需要调用 start 端点启动。
    """
    data = orchestrator.create_research_run(
        problem_spec_id=payload.problem_spec_id,
        execution_decision_id=payload.execution_decision_id,
        campaign_id=payload.campaign_id,
        profile_id=payload.profile_id,
        max_iterations=payload.max_iterations,
        batch_size=payload.batch_size,
        description=payload.description,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/research-runs", response_model=ApiResponse[ResearchRunListData])
def list_research_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    problem_spec_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRunListData]:
    """查询 ResearchRun 列表。

    支持按 ProblemSpec、Campaign、状态、项目过滤和分页。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=orchestrator.list_research_runs(
            problem_spec_id=problem_spec_id,
            campaign_id=campaign_id,
            status=status,
            created_by=current_user["user_id"] if current_user else None,
            project_id=project_id,
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/research-runs/{run_id}", response_model=ApiResponse[ResearchRun])
def get_research_run(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """获取 ResearchRun 详情。

    包含完整阶段序列、当前阶段状态、gate 审批记录和 checkpoint 信息。
    """
    data = orchestrator.get_research_run(run_id)
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ResearchRun 状态操作 API
# =============================================================================


@router.post("/research-runs/{run_id}/start", response_model=ApiResponse[ResearchRun])
def start_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """启动 ResearchRun。

    从 draft 状态转为 running，自动推进非 gate 阶段。
    gate 阶段（PROBLEM_SPEC、RECOMMENDATION_ASK、EXPERIMENT_EXECUTION）
    进入 blocked_approval 等待人工审批。
    """
    data = orchestrator.start_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/advance", response_model=ApiResponse[ResearchRun])
def advance_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """继续推进 ResearchRun 阶段。

    从 blocked_approval 或 paused 恢复后继续推进后续阶段。
    """
    data = orchestrator.advance_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/pause", response_model=ApiResponse[ResearchRun])
def pause_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """暂停 ResearchRun。

    running 或 blocked_approval 状态的运行可暂停，暂停前保存 checkpoint。
    """
    data = orchestrator.pause_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/resume", response_model=ApiResponse[ResearchRun])
def resume_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """恢复 ResearchRun。

    paused 状态的运行可恢复，恢复后继续推进后续阶段。
    """
    data = orchestrator.resume_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/fail", response_model=ApiResponse[ResearchRun])
def fail_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """手动标记 ResearchRun 为失败。

    任何非终态的运行都可标记为失败。
    """
    data = orchestrator.fail_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# Stage/Gate 审批 API
# =============================================================================


@router.post(
    "/research-runs/{run_id}/stages/{stage_run_id}/approve",
    response_model=ApiResponse[ResearchRun],
)
def approve_stage(
    run_id: str,
    stage_run_id: str,
    payload: StageApprovalRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """批准 gate 阶段。

    批准后 ResearchRun 从 blocked_approval 转为 running 并继续推进后续阶段。
    决策必须包含 reason（审批原因）。
    """
    data = orchestrator.approve_stage(
        research_run_id=run_id,
        stage_run_id=stage_run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/research-runs/{run_id}/stages/{stage_run_id}/reject",
    response_model=ApiResponse[ResearchRun],
)
def reject_stage(
    run_id: str,
    stage_run_id: str,
    payload: StageApprovalRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """拒绝 gate 阶段。

    拒绝后 StageRun 和 ResearchRun 标记为 failed。
    决策必须包含 reason（拒绝原因）。
    """
    data = orchestrator.reject_stage(
        research_run_id=run_id,
        stage_run_id=stage_run_id,
        actor_user_id=_actor_user_id(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# Traceability 追溯 API
# =============================================================================


@router.get("/audit", response_model=ApiResponse[EntityAuditListData])
def query_audit_events(
    entity_type: str | None = Query(default=None, description="实体类型: problem_spec/algorithm_run/research_run/research_stage_run"),
    entity_id: str | None = Query(default=None, description="实体 ID"),
    event_type: str | None = Query(default=None, description="事件类型: created/completed/failed/approved/rejected"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[EntityAuditListData]:
    """查询审计事件。

    按实体类型和 ID 聚合关键审计事件，支持分页。
    返回内容已脱敏，不暴露本地敏感绝对路径或 secret。
    """
    data = service.query_audit_events(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/algorithm-runs/{run_id}/traceability",
    response_model=ApiResponse[AlgorithmRunTraceability],
)
def get_algorithm_run_traceability(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRunTraceability]:
    """获取 AlgorithmRun 完整追溯链。

    聚合算法运行记录、自有 artifact、关联计算任务产物和审计事件。
    """
    data = service.get_algorithm_run_traceability(run_id)
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/research-runs/{run_id}/traceability",
    response_model=ApiResponse[ResearchRunTraceability],
)
def get_research_run_traceability(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRunTraceability]:
    """获取 ResearchRun 完整追溯链。

    聚合 AutoResearch 运行记录、阶段时间线、关联算法运行、
    关联计算任务、关联观测和所有审计事件。
    """
    data = service.get_research_run_traceability(run_id)
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/research-runs/{run_id}/stages/{stage_run_id}/traceability",
    response_model=ApiResponse[StageRunTraceability],
)
def get_stage_run_traceability(
    run_id: str,
    stage_run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[StageRunTraceability]:
    """获取 StageRun 完整追溯链。

    聚合单个阶段的输入输出、关联算法运行和审计事件。
    """
    data = service.get_stage_run_traceability(
        research_run_id=run_id,
        stage_run_id=stage_run_id,
    )
    return ApiResponse(code=0, message="ok", data=data)
