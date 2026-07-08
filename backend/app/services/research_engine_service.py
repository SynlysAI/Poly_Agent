"""ResearchEngine 领域业务服务。

实现 ProblemSpec、AlgorithmRegistry 和 AlgorithmRun 的业务逻辑，
包括草稿、冻结、校验、算法清单管理、人工算法运行等。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.infra.computation_repositories import (
    AuditEventRepository,
    OptimizationCampaignRepository,
    utc_now,
)
from app.infra.research_engine_repositories import (
    AlgorithmRegistryRepository,
    AlgorithmRunRepository,
    ExecutionDecisionRepository,
    ManualAlgorithmWorkflowRepository,
    ResearchProblemSpecRepository,
    ResearchRunRepository,
    WorkflowRunRepository,
)
from app.schemas.research_engine import (
    AlgorithmRegistryEntry,
    AlgorithmRegistryListData,
    AlgorithmRun,
    AlgorithmRunCreate,
    AlgorithmRunListData,
    AlgorithmRunTraceability,
    AuditEventItem,
    EntityAuditListData,
    ExecutionDecision,
    ExecutionDecisionCreate,
    ExecutionDecisionListData,
    LinkedComputationRef,
    ManualAlgorithmWorkflow,
    ManualAlgorithmWorkflowCreate,
    ManualAlgorithmWorkflowListData,
    ProblemSpec,
    ProblemSpecCreate,
    ProblemSpecListData,
    ResearchRunTraceability,
    ResearchEngineExampleInstantiateResult,
    ResearchEngineExampleListData,
    ResearchEngineExampleSummary,
    StageRunTraceability,
    WorkflowRun,
    WorkflowRunListData,
    WorkflowStepRun,
)
from app.services.research_engine_access import ensure_research_engine_doc_access
from app.services.research_engine_defaults import (
    build_adapter_algorithm_registry,
    build_default_algorithm_registry,
    build_mock_algorithm_registry,
)


# 合法的 trigger_source 值（公共 canonical 值）
CANONICAL_TRIGGER_MODES: set[str] = {"human_workflow", "autoresearch", "system"}

# 旧值 → 新值的映射
LEGACY_TRIGGER_MODE_MAP: dict[str, str] = {
    "human": "human_workflow",
}


def normalize_trigger_modes(modes: list[str] | None) -> list[str]:
    """规范化 trigger_modes 列表：将旧值映射为 canonical 值，去重并过滤非法值。

    Args:
        modes: 原始的 trigger_modes 列表（可能包含旧值如 "human"）。

    Returns:
        规范化后的 trigger_modes 列表。
    """
    if not modes:
        return ["human_workflow"]
    normalized: list[str] = []
    seen: set[str] = set()
    for m in modes:
        canonical = LEGACY_TRIGGER_MODE_MAP.get(m, m)
        if canonical in CANONICAL_TRIGGER_MODES and canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    if not normalized:
        return ["human_workflow"]
    return normalized


class ResearchEngineService:
    """ResearchEngine 领域服务。

    提供 ProblemSpec 生命周期管理和 AlgorithmRegistry 只读查询能力。
    """

    @staticmethod
    def _ensure_doc_access(
        doc: dict,
        *,
        actor_user_id: str | None,
        is_admin: bool,
        resource_label: str = "ResearchEngine 资源",
    ) -> None:
        """检查当前用户是否可访问 ResearchEngine 资源。"""
        ensure_research_engine_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label=resource_label,
        )

    # ------------------------------------------------------------------
    # ProblemSpec
    # ------------------------------------------------------------------

    def create_problem_spec(
        self,
        payload: ProblemSpecCreate,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> ProblemSpec:
        """创建 ProblemSpec 草稿。

        创建时可选择关联已有 campaign，或自动创建首版 campaign 容器。

        Args:
            payload: ProblemSpec 创建请求。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            创建的 ProblemSpec 完整记录。
        """
        now = utc_now()
        spec_id = f"ps_{uuid4().hex[:12]}"

        # 如果未提供 campaign_id，自动创建一个容器 campaign
        campaign_id = payload.campaign_id
        if not campaign_id:
            try:
                campaign = OptimizationCampaignRepository.save(
                    "campaign_id",
                    {
                        "campaign_id": spec_id,
                        "name": f"[ResearchEngine] {payload.name}",
                        "status": "draft",
                        "description": payload.description or "ResearchEngine 自动创建的容器 campaign",
                        "planner_type": "fallback",
                        "search_space": {"kind": "research_engine_problem_spec", "candidate_count": 0},
                        "objectives": self._problem_objectives_to_optimization(payload),
                        "planner_config": {"batch_size": 1},
                        "source": "research_engine",
                        "linked_problem_spec_id": spec_id,
                        "created_by": actor_user_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                campaign_id = spec_id
            except Exception:
                # 自动创建 campaign 失败不阻塞 ProblemSpec 创建
                campaign_id = None

        doc = {
            "problem_spec_id": spec_id,
            "name": payload.name,
            "material_family": payload.material_family,
            "problem_type": payload.problem_type,
            "allowed_execution_modes": payload.allowed_execution_modes,
            "decision_status": payload.decision_status,
            "variables": [v.model_dump() for v in payload.variables],
            "objectives": [o.model_dump() for o in payload.objectives],
            "constraints": [c.model_dump() for c in payload.constraints],
            "measurements": [m.model_dump() for m in payload.measurements],
            "campaign_id": campaign_id,
            "description": payload.description,
            "schema_version": "0.4",
            "created_by": actor_user_id,
            "owner_id": actor_user_id,
            "project_id": None,
            "status": "draft",
            "frozen_version": 0,
            "created_at": now,
            "updated_at": now,
        }

        ResearchProblemSpecRepository.save("problem_spec_id", doc)

        # 写审计事件
        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="problem_spec",
            entity_id=spec_id,
            event_type="created",
            reason="创建材料研发任务",
            before={},
            after={
                "name": payload.name,
                "allowed_execution_modes": payload.allowed_execution_modes,
                "decision_status": payload.decision_status,
            },
            request_id=request_id,
        )

        return self._doc_to_problem_spec(doc)

    def get_problem_spec(
        self,
        problem_spec_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> ProblemSpec:
        """获取 ProblemSpec 详情。

        Args:
            problem_spec_id: ProblemSpec ID。

        Returns:
            ProblemSpec 完整记录。

        Raises:
            HTTPException: ProblemSpec 不存在。
        """
        doc = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"ProblemSpec '{problem_spec_id}' 不存在")
        self._ensure_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ProblemSpec",
        )
        return self._doc_to_problem_spec(doc)

    def list_problem_specs(
        self,
        *,
        project_id: str | None = None,
        campaign_id: str | None = None,
        created_by: str | None = None,
        status: str | None = None,
        material_family: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ProblemSpecListData:
        """分页查询 ProblemSpec 列表。

        Args:
            project_id: 按项目 ID 过滤。
            campaign_id: 按 campaign ID 过滤。
            created_by: 按创建者过滤。
            status: 按状态过滤。
            material_family: 按材料体系过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            ProblemSpec 分页列表。
        """
        items, total = ResearchProblemSpecRepository.list_problem_specs(
            project_id=project_id,
            campaign_id=campaign_id,
            created_by=created_by,
            status=status,
            include_archived=status == "archived",
            material_family=material_family,
            page=page,
            page_size=page_size,
        )
        specs = [self._doc_to_problem_spec(doc) for doc in items]
        return ProblemSpecListData(items=specs, page=page, page_size=page_size, total=total)

    def archive_problem_spec(
        self,
        problem_spec_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str = "归档材料研发任务",
        request_id: str | None = None,
    ) -> ProblemSpec:
        """软删除/归档 ProblemSpec，保留审计和追溯。"""
        existing = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
        if not existing:
            raise HTTPException(status_code=404, detail=f"ProblemSpec '{problem_spec_id}' 不存在")
        self._ensure_doc_access(
            existing,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ProblemSpec",
        )
        if existing.get("status") == "archived":
            return self._doc_to_problem_spec(existing)

        now = utc_now()
        ResearchProblemSpecRepository.update_fields(
            problem_spec_id,
            {"status": "archived", "updated_at": now},
        )
        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="problem_spec",
            entity_id=problem_spec_id,
            event_type="archived",
            reason=reason,
            before={"status": existing.get("status")},
            after={"status": "archived"},
            request_id=request_id,
        )
        updated = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
        return self._doc_to_problem_spec(updated or existing)

    def update_problem_spec(
        self,
        problem_spec_id: str,
        payload: ProblemSpecCreate,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> ProblemSpec:
        """更新 ProblemSpec 草稿。

        已冻结的 ProblemSpec 不可直接修改，需通过复制新版本更新。

        Args:
            problem_spec_id: ProblemSpec ID。
            payload: 更新内容。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ProblemSpec 完整记录。

        Raises:
            HTTPException: ProblemSpec 不存在或已冻结。
        """
        existing = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
        if not existing:
            raise HTTPException(status_code=404, detail=f"ProblemSpec '{problem_spec_id}' 不存在")
        self._ensure_doc_access(
            existing,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ProblemSpec",
        )

        if existing.get("status") == "frozen":
            raise HTTPException(
                status_code=409,
                detail=f"ProblemSpec '{problem_spec_id}' 已冻结，无法直接修改。请复制为新版本后编辑。",
            )

        now = utc_now()
        before = dict(existing)

        update_fields = {
            "name": payload.name,
            "material_family": payload.material_family,
            "problem_type": payload.problem_type,
            "allowed_execution_modes": payload.allowed_execution_modes,
            "decision_status": payload.decision_status,
            "variables": [v.model_dump() for v in payload.variables],
            "objectives": [o.model_dump() for o in payload.objectives],
            "constraints": [c.model_dump() for c in payload.constraints],
            "measurements": [m.model_dump() for m in payload.measurements],
            "description": payload.description,
            "updated_at": now,
        }

        ResearchProblemSpecRepository.update_fields(problem_spec_id, update_fields)

        updated = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})

        # 写审计事件
        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="problem_spec",
            entity_id=problem_spec_id,
            event_type="updated",
            reason="更新材料研发任务",
            before={
                "name": before.get("name"),
                "allowed_execution_modes": before.get("allowed_execution_modes"),
                "decision_status": before.get("decision_status"),
            },
            after={
                "name": payload.name,
                "allowed_execution_modes": payload.allowed_execution_modes,
                "decision_status": payload.decision_status,
            },
            request_id=request_id,
        )

        return self._doc_to_problem_spec(updated or existing)

    def freeze_problem_spec(
        self,
        problem_spec_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> ProblemSpec:
        """冻结 ProblemSpec。

        冻结后不可直接修改，只能复制新版本。

        Args:
            problem_spec_id: ProblemSpec ID。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            冻结后的 ProblemSpec 完整记录。

        Raises:
            HTTPException: ProblemSpec 不存在或已冻结。
        """
        existing = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
        if not existing:
            raise HTTPException(status_code=404, detail=f"ProblemSpec '{problem_spec_id}' 不存在")
        self._ensure_doc_access(
            existing,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ProblemSpec",
        )

        if existing.get("status") == "frozen":
            raise HTTPException(status_code=409, detail=f"ProblemSpec '{problem_spec_id}' 已经冻结")

        frozen_version = existing.get("frozen_version", 0) + 1
        now = utc_now()

        ResearchProblemSpecRepository.update_fields(
            problem_spec_id,
            {
                "status": "frozen",
                "frozen_version": frozen_version,
                "updated_at": now,
            },
        )

        # 写审计事件
        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="problem_spec",
            entity_id=problem_spec_id,
            event_type="frozen",
            reason="冻结材料研发任务规格",
            before={"status": existing.get("status"), "frozen_version": existing.get("frozen_version", 0)},
            after={"status": "frozen", "frozen_version": frozen_version},
            request_id=request_id,
        )

        updated = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
        return self._doc_to_problem_spec(updated or existing)

    # ------------------------------------------------------------------
    # ExecutionDecision
    # ------------------------------------------------------------------

    def create_execution_decision(
        self,
        problem_spec_id: str,
        payload: ExecutionDecisionCreate,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> ExecutionDecision:
        """为 ProblemSpec 创建显式执行决策。"""
        spec = self.get_problem_spec(problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if payload.mode not in spec.allowed_execution_modes:
            raise HTTPException(
                status_code=422,
                detail=f"ProblemSpec '{problem_spec_id}' 不允许执行模式 '{payload.mode}'",
            )

        active = ExecutionDecisionRepository.find_active(problem_spec_id)
        if active and active.get("mode") == payload.mode:
            raise HTTPException(
                status_code=409,
                detail=f"ProblemSpec '{problem_spec_id}' 已存在 active 的 '{payload.mode}' 执行决策",
            )
        if active:
            ExecutionDecisionRepository.update_fields(
                active["decision_id"],
                {"status": "superseded", "updated_at": utc_now()},
            )

        now = utc_now()
        decision_id = self._new_id("ed")
        doc = {
            "decision_id": decision_id,
            "problem_spec_id": problem_spec_id,
            "problem_spec_version": spec.schema_version,
            "mode": payload.mode,
            "reason": payload.reason,
            "status": "active",
            "initial_context_id": None,
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        ExecutionDecisionRepository.save("decision_id", doc)
        ResearchProblemSpecRepository.update_fields(
            problem_spec_id,
            {"decision_status": "decision_made", "updated_at": now},
        )

        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="execution_decision",
            entity_id=decision_id,
            event_type="created",
            reason=payload.reason,
            before={"previous_active_decision_id": active.get("decision_id") if active else None},
            after={"problem_spec_id": problem_spec_id, "mode": payload.mode},
            request_id=request_id,
        )
        return self._doc_to_execution_decision(doc)

    def get_execution_decision(
        self,
        decision_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> ExecutionDecision:
        """获取 ExecutionDecision 详情。"""
        doc = ExecutionDecisionRepository.find_one({"decision_id": decision_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"ExecutionDecision '{decision_id}' 不存在")
        self._ensure_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ExecutionDecision",
        )
        return self._doc_to_execution_decision(doc)

    def get_active_execution_decision(
        self,
        problem_spec_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> ExecutionDecision:
        """获取 ProblemSpec 当前 active ExecutionDecision。"""
        self.get_problem_spec(problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        doc = ExecutionDecisionRepository.find_active(problem_spec_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"ProblemSpec '{problem_spec_id}' 尚未选择执行模式")
        return self._doc_to_execution_decision(doc)

    def list_execution_decisions(
        self,
        *,
        problem_spec_id: str | None = None,
        mode: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ExecutionDecisionListData:
        """分页查询 ExecutionDecision。"""
        items, total = ExecutionDecisionRepository.list_decisions(
            problem_spec_id=problem_spec_id,
            mode=mode,
            status=status,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        return ExecutionDecisionListData(
            items=[self._doc_to_execution_decision(doc) for doc in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    # ------------------------------------------------------------------
    # ManualAlgorithmWorkflow / WorkflowRun
    # ------------------------------------------------------------------

    def create_manual_workflow(
        self,
        payload: ManualAlgorithmWorkflowCreate,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> ManualAlgorithmWorkflow:
        """创建人工算法 Workflow 定义。"""
        spec = self.get_problem_spec(payload.problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        decision = self.get_execution_decision(
            payload.execution_decision_id,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        if decision.problem_spec_id != payload.problem_spec_id or decision.mode != "manual_workbench":
            raise HTTPException(status_code=409, detail="人工 Workflow 必须关联 manual_workbench 执行决策")

        seen_steps: set[str] = set()
        for step in payload.steps:
            if step.step_id in seen_steps:
                raise HTTPException(status_code=422, detail=f"Workflow step_id '{step.step_id}' 重复")
            seen_steps.add(step.step_id)
            algo_doc = AlgorithmRegistryRepository.find_one({"algorithm_id": step.algorithm_id})
            if not algo_doc:
                raise HTTPException(status_code=404, detail=f"算法 '{step.algorithm_id}' 不存在")
            if "human_workflow" not in normalize_trigger_modes(algo_doc.get("trigger_modes")):
                raise HTTPException(status_code=400, detail=f"算法 '{step.algorithm_id}' 不支持 human_workflow")
            for upstream in step.depends_on:
                if upstream not in seen_steps:
                    raise HTTPException(status_code=422, detail=f"步骤 '{step.step_id}' 依赖未知上游 '{upstream}'")

        now = utc_now()
        workflow_id = self._new_id("maw")
        doc = {
            "workflow_id": workflow_id,
            "problem_spec_id": payload.problem_spec_id,
            "execution_decision_id": payload.execution_decision_id,
            "name": payload.name,
            "steps": [step.model_dump() for step in payload.steps],
            "description": payload.description,
            "status": "active",
            "validation_status": "validated",
            "created_by": actor_user_id,
            "owner_id": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        ManualAlgorithmWorkflowRepository.save("workflow_id", doc)
        if decision.initial_context_id is None:
            ExecutionDecisionRepository.update_fields(
                decision.decision_id,
                {"initial_context_id": workflow_id, "updated_at": now},
            )

        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="manual_algorithm_workflow",
            entity_id=workflow_id,
            event_type="created",
            reason="创建人工算法 Workflow",
            before={},
            after={"problem_spec_id": spec.problem_spec_id, "step_count": len(payload.steps)},
            request_id=request_id,
        )
        return self._doc_to_manual_workflow(doc)

    def get_manual_workflow(
        self,
        workflow_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> ManualAlgorithmWorkflow:
        """获取人工 Workflow 详情。"""
        doc = ManualAlgorithmWorkflowRepository.find_one({"workflow_id": workflow_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"ManualAlgorithmWorkflow '{workflow_id}' 不存在")
        self._ensure_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ManualAlgorithmWorkflow",
        )
        return self._doc_to_manual_workflow(doc)

    def list_manual_workflows(
        self,
        *,
        problem_spec_id: str | None = None,
        execution_decision_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ManualAlgorithmWorkflowListData:
        """分页查询人工 Workflow。"""
        items, total = ManualAlgorithmWorkflowRepository.list_workflows(
            problem_spec_id=problem_spec_id,
            execution_decision_id=execution_decision_id,
            status=status,
            include_archived=status == "archived",
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        return ManualAlgorithmWorkflowListData(
            items=[self._doc_to_manual_workflow(doc) for doc in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def archive_manual_workflow(
        self,
        workflow_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str = "归档人工算法 Workflow",
        request_id: str | None = None,
    ) -> ManualAlgorithmWorkflow:
        """软删除/归档人工 Workflow 定义。"""
        existing = ManualAlgorithmWorkflowRepository.find_one({"workflow_id": workflow_id})
        if not existing:
            raise HTTPException(status_code=404, detail=f"ManualAlgorithmWorkflow '{workflow_id}' 不存在")
        self._ensure_doc_access(
            existing,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ManualAlgorithmWorkflow",
        )
        if existing.get("status") == "archived":
            return self._doc_to_manual_workflow(existing)

        now = utc_now()
        ManualAlgorithmWorkflowRepository.update_fields(
            workflow_id,
            {"status": "archived", "updated_at": now},
        )
        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="manual_algorithm_workflow",
            entity_id=workflow_id,
            event_type="archived",
            reason=reason,
            before={"status": existing.get("status", "active")},
            after={"status": "archived"},
            request_id=request_id,
        )
        updated = ManualAlgorithmWorkflowRepository.find_one({"workflow_id": workflow_id})
        return self._doc_to_manual_workflow(updated or existing)

    def start_workflow_run(
        self,
        workflow_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> WorkflowRun:
        """启动人工 WorkflowRun，按 P0 线性步骤逐个生成 AlgorithmRun。"""
        workflow = self.get_manual_workflow(workflow_id, actor_user_id=actor_user_id, is_admin=is_admin)
        spec = self.get_problem_spec(workflow.problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        now = utc_now()
        workflow_run_id = self._new_id("wfr")
        run_doc = {
            "workflow_run_id": workflow_run_id,
            "workflow_id": workflow.workflow_id,
            "problem_spec_id": workflow.problem_spec_id,
            "execution_decision_id": workflow.execution_decision_id,
            "status": "running",
            "step_runs": [],
            "input_snapshot": workflow.model_dump(),
            "artifact_refs": [],
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "finished_at": None,
        }
        WorkflowRunRepository.save("workflow_run_id", run_doc)

        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="workflow_run",
            entity_id=workflow_run_id,
            event_type="started",
            reason="启动人工 WorkflowRun",
            before={},
            after={"workflow_id": workflow_id},
            request_id=request_id,
        )

        step_outputs: dict[str, dict] = {}
        artifact_refs: list[dict] = []
        final_status = "completed"
        for step in workflow.steps:
            step_run_id = self._new_id("wfs")
            step_started_at = utc_now()
            step_doc = {
                "step_run_id": step_run_id,
                "workflow_run_id": workflow_run_id,
                "step_id": step.step_id,
                "algorithm_id": step.algorithm_id,
                "status": "running",
                "input_snapshot": {},
                "output_summary": {},
                "algorithm_run_id": None,
                "error": None,
                "started_at": step_started_at,
                "finished_at": None,
                "created_at": step_started_at,
                "updated_at": step_started_at,
            }
            try:
                input_snapshot = self._resolve_workflow_input_bindings(
                    step.input_bindings,
                    spec=spec,
                    step_outputs=step_outputs,
                )
                step_doc["input_snapshot"] = input_snapshot
                algorithm_run = self.create_algorithm_run(
                    AlgorithmRunCreate(
                        algorithm_id=step.algorithm_id,
                        trigger_source="human_workflow",
                        trigger_context_id=workflow_run_id,
                        problem_spec_id=workflow.problem_spec_id,
                        campaign_id=spec.campaign_id,
                        workflow_run_id=workflow_run_id,
                        workflow_step_run_id=step_run_id,
                        input_snapshot=input_snapshot,
                        reason=f"Workflow step {step.step_id} 执行算法 {step.algorithm_id}",
                    ),
                    actor_user_id=actor_user_id,
                    is_admin=is_admin,
                    request_id=request_id,
                )
                step_doc.update(
                    {
                        "status": algorithm_run.status,
                        "output_summary": algorithm_run.output_summary,
                        "algorithm_run_id": algorithm_run.run_id,
                        "error": algorithm_run.error,
                        "finished_at": algorithm_run.finished_at,
                        "updated_at": algorithm_run.updated_at,
                    }
                )
                step_outputs[step.step_id] = algorithm_run.output_summary
                artifact_refs.extend(algorithm_run.artifact_refs)
                if algorithm_run.status != "completed":
                    final_status = "failed"
                    break
            except Exception as exc:
                final_status = "failed"
                failed_at = utc_now()
                step_doc.update(
                    {
                        "status": "failed",
                        "error": {"error_type": type(exc).__name__, "message": str(exc), "retryable": False},
                        "finished_at": failed_at,
                        "updated_at": failed_at,
                    }
                )
                run_doc["step_runs"].append(step_doc)
                break

            run_doc["step_runs"].append(step_doc)

        finished_at = utc_now()
        update_fields = {
            "status": final_status,
            "step_runs": run_doc["step_runs"],
            "artifact_refs": artifact_refs,
            "finished_at": finished_at,
            "updated_at": finished_at,
        }
        WorkflowRunRepository.update_fields(workflow_run_id, update_fields)
        run_doc.update(update_fields)

        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="workflow_run",
            entity_id=workflow_run_id,
            event_type=final_status,
            reason=f"人工 WorkflowRun {final_status}",
            before={"status": "running"},
            after={"status": final_status, "step_count": len(run_doc["step_runs"])},
            request_id=request_id,
        )
        return self._doc_to_workflow_run(run_doc)

    def get_workflow_run(
        self,
        workflow_run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> WorkflowRun:
        """获取 WorkflowRun 详情。"""
        doc = WorkflowRunRepository.find_one({"workflow_run_id": workflow_run_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"WorkflowRun '{workflow_run_id}' 不存在")
        self._ensure_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="WorkflowRun",
        )
        return self._doc_to_workflow_run(doc)

    def list_workflow_runs(
        self,
        *,
        workflow_id: str | None = None,
        problem_spec_id: str | None = None,
        execution_decision_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> WorkflowRunListData:
        """分页查询 WorkflowRun。"""
        items, total = WorkflowRunRepository.list_runs(
            workflow_id=workflow_id,
            problem_spec_id=problem_spec_id,
            execution_decision_id=execution_decision_id,
            status=status,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        return WorkflowRunListData(
            items=[self._doc_to_workflow_run(doc) for doc in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    # ------------------------------------------------------------------
    # AlgorithmRegistry
    # ------------------------------------------------------------------

    def seed_default_algorithms(self) -> int:
        """写入默认算法能力清单（幂等）。

        合并计算 workflow 适配器和 mock/preset 算法条目。

        Returns:
            实际写入的条目数。
        """
        entries = []

        # 计算 workflow 适配器（3 个）
        for entry in build_default_algorithm_registry():
            entries.append(entry.model_dump())

        # 真实外部/本地适配器
        for entry in build_adapter_algorithm_registry():
            entries.append(entry.model_dump())

        # Mock/preset 演示算法
        for entry in build_mock_algorithm_registry():
            entries.append(entry.model_dump())

        return AlgorithmRegistryRepository.seed_defaults(entries)

    def get_algorithm(self, algorithm_id: str) -> AlgorithmRegistryEntry:
        """获取单个算法能力条目详情。

        Args:
            algorithm_id: 算法 ID。

        Returns:
            AlgorithmRegistryEntry 记录。

        Raises:
            HTTPException: 算法条目不存在。
        """
        doc = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"算法 '{algorithm_id}' 不存在")
        # 规范化旧 trigger_modes 值（如 "human" -> "human_workflow"）
        doc["trigger_modes"] = normalize_trigger_modes(doc.get("trigger_modes"))
        return AlgorithmRegistryEntry(**doc)

    def list_algorithms(
        self,
        *,
        algorithm_type: str | None = None,
        algorithm_family: str | None = None,
        material_scope: str | None = None,
        trigger_mode: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> AlgorithmRegistryListData:
        """分页查询算法能力清单。

        Args:
            algorithm_type: 按算法类型过滤（retriever/predictor/simulator/optimizer）。
            algorithm_family: 按产品算法族过滤。
            material_scope: 按材料体系过滤。
            trigger_mode: 按触发方式过滤（human_workflow/autoresearch/system）。
            status: 按状态过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            AlgorithmRegistry 分页列表。
        """
        self.seed_default_algorithms()
        items, total = AlgorithmRegistryRepository.list_algorithms(
            algorithm_type=algorithm_type,
            algorithm_family=algorithm_family,
            material_scope=material_scope,
            trigger_mode=trigger_mode,
            status=status,
            page=page,
            page_size=page_size,
        )
        entries = [
            AlgorithmRegistryEntry(
                **{
                    **doc,
                    "trigger_modes": normalize_trigger_modes(doc.get("trigger_modes")),
                }
            )
            for doc in items
        ]
        return AlgorithmRegistryListData(items=entries, page=page, page_size=page_size, total=total)

    # ------------------------------------------------------------------
    # Examples
    # ------------------------------------------------------------------

    def list_examples(self) -> ResearchEngineExampleListData:
        """列出 ResearchEngine 可实例化示例。"""
        return ResearchEngineExampleListData(
            items=[
                ResearchEngineExampleSummary(
                    example_id="manual-computation-workflow",
                    title="人工计算 Workflow 示例",
                    description="创建 ProblemSpec、manual_workbench 执行决策和 computation_submit_adapter Workflow。",
                    mode="manual_workbench",
                    tags=["manual", "workflow", "computation"],
                ),
                ResearchEngineExampleSummary(
                    example_id="autoresearch-approval-demo",
                    title="AutoResearch 审批示例",
                    description="创建并启动 ResearchRun，停在 PROBLEM_SPEC blocked_approval 等待审批。",
                    mode="autoresearch",
                    tags=["autoresearch", "approval", "gate"],
                ),
            ]
        )

    def instantiate_example(
        self,
        example_id: str,
        *,
        actor_user_id: str,
        request_id: str | None = None,
    ) -> ResearchEngineExampleInstantiateResult:
        """实例化示例流程。"""
        if example_id == "manual-computation-workflow":
            return self._instantiate_manual_computation_example(
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        if example_id == "autoresearch-approval-demo":
            return self._instantiate_autoresearch_approval_example(
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        raise HTTPException(status_code=404, detail=f"ResearchEngine 示例 '{example_id}' 不存在")

    def _instantiate_manual_computation_example(
        self,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ResearchEngineExampleInstantiateResult:
        problem_spec = self.create_problem_spec(
            ProblemSpecCreate(
                name="示例：人工计算 Workflow",
                material_family="universal",
                problem_type="structure_property_prediction",
                allowed_execution_modes=["manual_workbench"],
                objectives=[{"name": "structure_generation", "direction": "maximize"}],
                description="一键示例：使用 computation_submit_adapter 提交 LOCAL_STRUCTURE 计算任务。",
            ),
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        decision = self.create_execution_decision(
            problem_spec.problem_spec_id,
            ExecutionDecisionCreate(mode="manual_workbench", reason="实例化人工计算 Workflow 示例"),
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        workflow = self.create_manual_workflow(
            ManualAlgorithmWorkflowCreate(
                problem_spec_id=problem_spec.problem_spec_id,
                execution_decision_id=decision.decision_id,
                name="LOCAL_STRUCTURE 计算任务提交示例",
                description="合法 workflow_type 下拉值示例，避免使用 test1 等非法值。",
                steps=[
                    {
                        "step_id": "step_1",
                        "algorithm_id": "computation_submit_adapter",
                        "input_bindings": {
                            "workflow_type": {"source": "literal", "value": "LOCAL_STRUCTURE"},
                            "smiles": {"source": "literal", "value": "CCO"},
                            "name": {"source": "literal", "value": "ethanol"},
                        },
                        "depends_on": [],
                    }
                ],
            ),
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        return ResearchEngineExampleInstantiateResult(
            example_id="manual-computation-workflow",
            problem_spec=problem_spec,
            execution_decision=decision,
            manual_workflow=workflow,
            navigation={
                "path": "/research-engine",
                "query": {
                    "problem_spec_id": problem_spec.problem_spec_id,
                    "workflow_id": workflow.workflow_id,
                    "mode": "manual_workbench",
                },
            },
            message="已创建人工计算 Workflow 示例，可进入 ResearchEngine 配置并运行。",
        )

    def _instantiate_autoresearch_approval_example(
        self,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ResearchEngineExampleInstantiateResult:
        from app.services.research_engine_orchestrator import ResearchEngineOrchestrator

        problem_spec = self.create_problem_spec(
            ProblemSpecCreate(
                name="示例：AutoResearch 审批演示",
                material_family="fluoropolymer",
                problem_type="formulation_process_optimization",
                allowed_execution_modes=["autoresearch"],
                variables=[
                    {
                        "name": "monomer_smiles",
                        "type": "categorical",
                        "role": "structure",
                        "categories": ["C=CF", "C=C(F)F", "FC(F)=C(F)F"],
                    },
                    {
                        "name": "fluorine_content",
                        "type": "continuous",
                        "role": "formulation",
                        "unit": "percent",
                        "bounds": [0.0, 100.0],
                    },
                ],
                objectives=[
                    {"name": "dielectric_constant", "direction": "maximize"},
                    {"name": "thermal_stability", "direction": "maximize"},
                ],
                constraints=[
                    {"name": "equipment_temperature_limit", "type": "hard", "expression": "fluorine_content <= 90"},
                ],
                description="一键示例：启动后停在 PROBLEM_SPEC gate，等待人工审批。",
            ),
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        decision = self.create_execution_decision(
            problem_spec.problem_spec_id,
            ExecutionDecisionCreate(mode="autoresearch", reason="实例化 AutoResearch 审批示例"),
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        orchestrator = ResearchEngineOrchestrator()
        research_run = orchestrator.create_research_run(
            problem_spec_id=problem_spec.problem_spec_id,
            execution_decision_id=decision.decision_id,
            profile_id="fluoropolymer",
            max_iterations=1,
            batch_size=5,
            description="AutoResearch 审批示例",
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        research_run = orchestrator.start_research_run(
            research_run.run_id,
            actor_user_id=actor_user_id,
            reason="启动 AutoResearch 审批示例",
            request_id=request_id,
        )
        return ResearchEngineExampleInstantiateResult(
            example_id="autoresearch-approval-demo",
            problem_spec=problem_spec,
            execution_decision=decision,
            research_run=research_run,
            navigation={
                "path": "/research-engine",
                "query": {
                    "problem_spec_id": problem_spec.problem_spec_id,
                    "research_run_id": research_run.run_id,
                    "action": "approve",
                    "mode": "autoresearch",
                },
            },
            message="已创建并启动 AutoResearch 示例，当前停在待审批阶段。",
        )

    # ------------------------------------------------------------------
    # AlgorithmRun
    # ------------------------------------------------------------------

    def create_algorithm_run(
        self,
        payload: AlgorithmRunCreate,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> AlgorithmRun:
        """创建并执行算法运行。

        1. 校验 algorithm_id 存在且支持指定 trigger。
        2. 校验输入快照与 input_schema 一致。
        3. 执行 mock runner 或委托给 ComputationService。
        4. 保存 AlgorithmRun 记录并写入审计事件。

        Args:
            payload: AlgorithmRun 创建请求。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            创建并执行完成的 AlgorithmRun 记录。

        Raises:
            HTTPException: algorithm_id 不存在、不支持指定 trigger 或执行失败。
        """
        from app.services.research_engine_algorithm_runner import (
            ComputationSubmitAdapter,
            get_runner,
        )

        # 1. 校验 algorithm_id 存在
        algo_doc = AlgorithmRegistryRepository.find_one({"algorithm_id": payload.algorithm_id})
        if not algo_doc:
            raise HTTPException(
                status_code=404,
                detail=f"算法 '{payload.algorithm_id}' 不存在",
            )
        if payload.problem_spec_id and not is_admin:
            self.get_problem_spec(payload.problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if payload.workflow_run_id and not is_admin:
            self.get_workflow_run(payload.workflow_run_id, actor_user_id=actor_user_id, is_admin=is_admin)

        # 2. 校验算法支持指定 trigger（先规范化旧值）
        trigger_modes = normalize_trigger_modes(algo_doc.get("trigger_modes"))
        if payload.trigger_source not in trigger_modes:
            raise HTTPException(
                status_code=400,
                detail=f"算法 '{payload.algorithm_id}' 不支持 '{payload.trigger_source}' 触发方式，"
                f"支持的触发方式: {trigger_modes}",
            )

        # 3. 创建 AlgorithmRun（初始状态 queued）
        now = utc_now()
        run_id = self._new_id("arun")
        run_doc = {
            "run_id": run_id,
            "algorithm_id": payload.algorithm_id,
            "trigger_source": payload.trigger_source,
            "trigger_context_id": payload.trigger_context_id,
            "problem_spec_id": payload.problem_spec_id,
            "problem_spec_version": None,
            "campaign_id": payload.campaign_id,
            "workflow_run_id": payload.workflow_run_id,
            "workflow_step_run_id": payload.workflow_step_run_id,
            "research_run_id": payload.research_run_id,
            "stage_run_id": payload.stage_run_id,
            "linked_computation_run_id": None,
            "linked_suggestion_id": None,
            "linked_observation_id": None,
            "input_snapshot": payload.input_snapshot,
            "output_summary": {},
            "artifact_refs": [],
            "status": "queued",
            "error": None,
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }

        AlgorithmRunRepository.save("run_id", run_doc)

        # 写入审计事件：创建
        self._write_audit_event(
            actor_user_id=actor_user_id,
            entity_type="algorithm_run",
            entity_id=run_id,
            event_type="created",
            reason=payload.reason or f"人工触发算法 '{payload.algorithm_id}'",
            before={},
            after={
                "algorithm_id": payload.algorithm_id,
                "trigger_source": payload.trigger_source,
                "status": "queued",
            },
            request_id=request_id,
        )

        # 4. 推进到 running 状态并执行
        try:
            # 更新状态为 running
            run_doc["status"] = "running"
            run_doc["started_at"] = now
            run_doc["updated_at"] = now
            AlgorithmRunRepository.update_fields(run_id, {
                "status": "running",
                "started_at": now,
                "updated_at": now,
            })

            # 查找 runner
            runner = get_runner(payload.algorithm_id)
            if runner is None:
                raise HTTPException(
                    status_code=501,
                    detail=f"算法 '{payload.algorithm_id}' 尚未实现执行器",
                )

            # 校验输入
            runner.validate_input(payload.input_snapshot)

            # 执行算法
            output_summary = runner.run(payload.input_snapshot)
            artifact_specs = runner.get_artifact_specs(output_summary)

            # 处理 computation_submit_adapter 的特殊逻辑
            linked_computation_run_id = None
            if isinstance(runner, ComputationSubmitAdapter):
                linked_computation_run_id = self._submit_computation_from_algorithm(
                    input_snapshot=payload.input_snapshot,
                    algorithm_run_id=run_id,
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                )
                if linked_computation_run_id:
                    output_summary["computation_run_id"] = linked_computation_run_id

            # 更新为 completed
            now2 = utc_now()
            update_fields: dict[str, Any] = {
                "status": "completed",
                "output_summary": output_summary,
                "artifact_refs": artifact_specs,
                "finished_at": now2,
                "updated_at": now2,
            }
            if linked_computation_run_id:
                update_fields["linked_computation_run_id"] = linked_computation_run_id

            AlgorithmRunRepository.update_fields(run_id, update_fields)
            run_doc.update(update_fields)

            # 写入审计事件：完成
            self._write_audit_event(
                actor_user_id=actor_user_id,
                entity_type="algorithm_run",
                entity_id=run_id,
                event_type="completed",
                reason=f"算法 '{payload.algorithm_id}' 执行完成",
                before={"status": "running"},
                after={"status": "completed", "output_summary": output_summary},
                request_id=request_id,
            )

        except Exception as exc:
            # 更新为 failed
            now2 = utc_now()
            error_info = {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "retryable": not isinstance(exc, (ValueError, HTTPException)),
            }
            failed_fields: dict[str, Any] = {
                "status": "failed",
                "error": error_info,
                "finished_at": now2,
                "updated_at": now2,
            }
            AlgorithmRunRepository.update_fields(run_id, failed_fields)
            run_doc.update(failed_fields)

            # 写入审计事件：失败
            self._write_audit_event(
                actor_user_id=actor_user_id,
                entity_type="algorithm_run",
                entity_id=run_id,
                event_type="failed",
                reason=f"算法 '{payload.algorithm_id}' 执行失败: {exc}",
                before={"status": "running"},
                after={"status": "failed", "error": error_info},
                request_id=request_id,
            )

            # 重新抛出 HTTP 友好错误
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                status_code=500,
                detail=f"算法 '{payload.algorithm_id}' 执行失败: {exc}",
            ) from exc

        # 返回最终结果
        return self._doc_to_algorithm_run(run_doc)

    def get_algorithm_run(
        self,
        run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> AlgorithmRun:
        """获取 AlgorithmRun 详情。

        Args:
            run_id: 运行 ID。

        Returns:
            AlgorithmRun 完整记录。

        Raises:
            HTTPException: AlgorithmRun 不存在。
        """
        doc = AlgorithmRunRepository.find_one({"run_id": run_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"AlgorithmRun '{run_id}' 不存在")
        self._ensure_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="AlgorithmRun",
        )
        return self._doc_to_algorithm_run(doc)

    def list_algorithm_runs(
        self,
        *,
        problem_spec_id: str | None = None,
        campaign_id: str | None = None,
        workflow_run_id: str | None = None,
        algorithm_id: str | None = None,
        status: str | None = None,
        trigger_source: str | None = None,
        research_run_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AlgorithmRunListData:
        """分页查询 AlgorithmRun 列表。

        Args:
            problem_spec_id: 按 ProblemSpec ID 过滤。
            campaign_id: 按 Campaign ID 过滤。
            workflow_run_id: 按 WorkflowRun ID 过滤。
            algorithm_id: 按算法 ID 过滤。
            status: 按状态过滤。
            trigger_source: 按触发来源过滤。
            research_run_id: 按 ResearchRun ID 过滤。
            created_by: 按创建者过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            AlgorithmRun 分页列表。
        """
        items, total = AlgorithmRunRepository.list_runs(
            problem_spec_id=problem_spec_id,
            campaign_id=campaign_id,
            workflow_run_id=workflow_run_id,
            algorithm_id=algorithm_id,
            status=status,
            trigger_source=trigger_source,
            research_run_id=research_run_id,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        runs = [self._doc_to_algorithm_run(doc) for doc in items]
        return AlgorithmRunListData(items=runs, page=page, page_size=page_size, total=total)

    # ------------------------------------------------------------------
    # Traceability 追溯聚合
    # ------------------------------------------------------------------

    def query_audit_events(
        self,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> EntityAuditListData:
        """按实体类型和 ID 聚合查询审计事件。

        支持按 entity_type、entity_id、event_type 过滤和分页。
        返回内容已脱敏，不暴露本地敏感绝对路径或 secret。

        Args:
            entity_type: 实体类型（problem_spec/algorithm_run/research_run/research_stage_run）。
            entity_id: 实体 ID。
            event_type: 事件类型（created/completed/failed/approved/rejected 等）。
            page: 页码。
            page_size: 每页条数。

        Returns:
            审计事件分页列表。
        """
        from app.infra.computation_repositories import AuditEventRepository

        lookup_page = page
        lookup_size = page_size
        if actor_user_id and not is_admin:
            lookup_page = 1
            lookup_size = 10000
        items, total = AuditEventRepository.list_events(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            page=lookup_page,
            page_size=lookup_size,
        )
        if actor_user_id and not is_admin:
            items = [
                item
                for item in items
                if self._is_audit_event_visible_to_user(item, actor_user_id=actor_user_id)
            ]
            total = len(items)
            start = (page - 1) * page_size
            items = items[start : start + page_size]

        audit_items = [
            AuditEventItem(
                event_id=doc.get("event_id", ""),
                event_type=doc.get("event_type", ""),
                entity_type=doc.get("entity_type", ""),
                entity_id=doc.get("entity_id", ""),
                actor_user_id=doc.get("actor_user_id", "system"),
                actor_role=doc.get("actor_role"),
                reason=(doc.get("metadata") or {}).get("reason"),
                before=doc.get("before", {}),
                after=doc.get("after", {}),
                created_at=doc.get("created_at", utc_now()),
            )
            for doc in items
        ]

        return EntityAuditListData(
            items=audit_items,
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_algorithm_run_traceability(
        self,
        run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> AlgorithmRunTraceability:
        """聚合 AlgorithmRun 完整追溯链。

        返回算法运行记录、关联的计算任务产物和审计事件。

        Args:
            run_id: AlgorithmRun ID。

        Returns:
            AlgorithmRun 完整追溯链。

        Raises:
            HTTPException: AlgorithmRun 不存在。
        """
        algo_run = self.get_algorithm_run(run_id, actor_user_id=actor_user_id, is_admin=is_admin)

        # 查询关联的 computation run
        linked_computation = None
        if algo_run.linked_computation_run_id:
            linked_computation = self._resolve_computation_ref(
                algo_run.linked_computation_run_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )

        # 聚合审计事件（该 AlgorithmRun 的 + 关联 computation 的）
        audit_events: list[AuditEventItem] = []
        audit_result = self.query_audit_events(
            entity_type="algorithm_run",
            entity_id=run_id,
            page=1,
            page_size=100,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        audit_events.extend(audit_result.items)

        # 如果有 computation run，也聚合它的审计事件
        if algo_run.linked_computation_run_id:
            comp_audit = self.query_audit_events(
                entity_type="computation_run",
                entity_id=algo_run.linked_computation_run_id,
                page=1,
                page_size=50,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            audit_events.extend(comp_audit.items)

        # 按时间排序
        audit_events.sort(key=lambda e: e.created_at, reverse=True)

        return AlgorithmRunTraceability(
            algorithm_run=algo_run,
            linked_computation=linked_computation,
            audit_events=audit_events,
        )

    def get_research_run_traceability(
        self,
        run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> ResearchRunTraceability:
        """聚合 ResearchRun 完整追溯链。

        返回 AutoResearch 运行记录、阶段时间线、关联算法运行、
        关联计算任务、关联观测和所有审计事件。

        Args:
            run_id: ResearchRun ID。

        Returns:
            ResearchRun 完整追溯链。

        Raises:
            HTTPException: ResearchRun 不存在。
        """
        from app.services.research_engine_orchestrator import ResearchEngineOrchestrator

        orchestrator = ResearchEngineOrchestrator()
        research_run = orchestrator.get_research_run(run_id, actor_user_id=actor_user_id, is_admin=is_admin)

        # 查询关联的算法运行
        linked_algo_runs: list[AlgorithmRun] = []
        for arun_id in research_run.linked_algorithm_runs:
            try:
                linked_algo_runs.append(self.get_algorithm_run(arun_id, actor_user_id=actor_user_id, is_admin=is_admin))
            except HTTPException:
                pass  # 已被清理的引用跳过

        # 如果 linked_algorithm_runs 为空，通过 research_run_id 查询
        if not linked_algo_runs:
            algo_result = self.list_algorithm_runs(
                research_run_id=run_id,
                page=1,
                page_size=200,
            )
            linked_algo_runs = algo_result.items

        # 收集所有 computation_run_id
        computation_ids: set[str] = set()
        for arun in linked_algo_runs:
            if arun.linked_computation_run_id:
                computation_ids.add(arun.linked_computation_run_id)

        # 查询关联的计算任务
        linked_computations: list[LinkedComputationRef] = []
        for comp_id in computation_ids:
            ref = self._resolve_computation_ref(
                comp_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            if ref:
                linked_computations.append(ref)

        # 聚合观测（通过 campaign 关联或通过 research_run 关联）
        linked_observations: list[dict] = []
        if research_run.campaign_id:
            linked_observations = self._resolve_observations(
                campaign_id=research_run.campaign_id,
                limit=50,
            )

        # 聚合审计事件（ResearchRun + 所有 StageRun + 所有关联 AlgorithmRun）
        all_audit_events: list[AuditEventItem] = []

        # ResearchRun 的审计事件
        rr_audit = self.query_audit_events(
            entity_type="research_run",
            entity_id=run_id,
            page=1,
            page_size=100,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        all_audit_events.extend(rr_audit.items)

        # 每个 StageRun 的审计事件
        for sr in research_run.stage_runs:
            sr_audit = self.query_audit_events(
                entity_type="research_stage_run",
                entity_id=sr.stage_run_id,
                page=1,
                page_size=50,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            all_audit_events.extend(sr_audit.items)

        # 每个关联 AlgorithmRun 的审计事件
        for arun in linked_algo_runs:
            ar_audit = self.query_audit_events(
                entity_type="algorithm_run",
                entity_id=arun.run_id,
                page=1,
                page_size=30,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            all_audit_events.extend(ar_audit.items)

        # 按时间排序
        all_audit_events.sort(key=lambda e: e.created_at, reverse=True)

        return ResearchRunTraceability(
            research_run=research_run,
            linked_algorithm_runs=linked_algo_runs,
            linked_computations=linked_computations,
            linked_observations=linked_observations,
            audit_events=all_audit_events,
        )

    def get_stage_run_traceability(
        self,
        research_run_id: str,
        stage_run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> StageRunTraceability:
        """聚合 StageRun 完整追溯链。

        返回单个阶段的输入输出、关联算法运行和审计事件。

        Args:
            research_run_id: ResearchRun ID。
            stage_run_id: StageRun ID。

        Returns:
            StageRun 完整追溯链。

        Raises:
            HTTPException: ResearchRun 或 StageRun 不存在。
        """
        from app.services.research_engine_orchestrator import ResearchEngineOrchestrator

        orchestrator = ResearchEngineOrchestrator()
        research_run = orchestrator.get_research_run(
            research_run_id,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )

        # 查找目标阶段
        target_sr = None
        for sr in research_run.stage_runs:
            if sr.stage_run_id == stage_run_id:
                target_sr = sr
                break

        if target_sr is None:
            raise HTTPException(
                status_code=404,
                detail=f"StageRun '{stage_run_id}' 在 ResearchRun '{research_run_id}' 中不存在",
            )

        # 查询关联的算法运行
        linked_algo_runs: list[AlgorithmRun] = []
        for arun_id in target_sr.linked_algorithm_runs:
            try:
                linked_algo_runs.append(self.get_algorithm_run(arun_id, actor_user_id=actor_user_id, is_admin=is_admin))
            except HTTPException:
                pass

        # 查询关联的计算任务
        linked_computations: list[LinkedComputationRef] = []
        for arun in linked_algo_runs:
            if arun.linked_computation_run_id:
                ref = self._resolve_computation_ref(
                    arun.linked_computation_run_id,
                    actor_user_id=actor_user_id,
                    is_admin=is_admin,
                )
                if ref:
                    linked_computations.append(ref)

        # 聚合审计事件
        audit_events: list[AuditEventItem] = []
        sr_audit = self.query_audit_events(
            entity_type="research_stage_run",
            entity_id=stage_run_id,
            page=1,
            page_size=100,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        audit_events.extend(sr_audit.items)

        for arun in linked_algo_runs:
            ar_audit = self.query_audit_events(
                entity_type="algorithm_run",
                entity_id=arun.run_id,
                page=1,
                page_size=30,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            audit_events.extend(ar_audit.items)

        audit_events.sort(key=lambda e: e.created_at, reverse=True)

        return StageRunTraceability(
            stage_run=target_sr,
            linked_algorithm_runs=linked_algo_runs,
            linked_computations=linked_computations,
            audit_events=audit_events,
        )

    # ------------------------------------------------------------------
    # Traceability 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_computation_ref(
        computation_run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> LinkedComputationRef | None:
        """解析计算任务引用。

        从 ComputationRun 中提取摘要信息，不暴露本地文件绝对路径。

        Args:
            computation_run_id: ComputationRun ID。

        Returns:
            计算任务摘要引用，不存在则返回 None。
        """
        from app.infra.computation_repositories import ComputationRunRepository
        from app.infra.computation_repositories import ComputationArtifactRepository
        from app.services.computation_service import ComputationService

        try:
            run = ComputationService().get_run(
                computation_run_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            doc = ComputationRunRepository.find_one({"run_id": computation_run_id})
            if not doc:
                return None

            # 获取关联 artifacts（脱敏：不返回 storage_uri 中的本地绝对路径）
            artifact_ids = doc.get("artifact_ids", [])
            sanitized_artifacts: list[dict] = []
            for aid in artifact_ids:
                art_doc = ComputationArtifactRepository.find_one({"artifact_id": aid})
                if art_doc:
                    sanitized_artifacts.append({
                        "artifact_id": art_doc.get("artifact_id", ""),
                        "type": art_doc.get("type", "unknown"),
                        "description": art_doc.get("description", ""),
                        "checksum": art_doc.get("checksum", ""),
                        "created_at": str(art_doc.get("created_at", "")),
                    })

            return LinkedComputationRef(
                run_id=run.run_id,
                workflow_type=run.workflow_type,
                engine=run.engine,
                status=run.status,
                input_snapshot={
                    "smiles": doc.get("molecule", {}).get("smiles", "") if isinstance(doc.get("molecule"), dict) else "",
                    "name": doc.get("molecule", {}).get("name", "") if isinstance(doc.get("molecule"), dict) else "",
                },
                output_summary=doc.get("result_summary", {}),
                artifact_refs=sanitized_artifacts,
                created_at=doc.get("created_at"),
            )
        except Exception:
            return None

    @staticmethod
    def _resolve_observations(
        *,
        campaign_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """解析关联的观测记录。

        Args:
            campaign_id: Campaign ID。
            limit: 最大返回数。

        Returns:
            脱敏后的观测记录列表。
        """
        if not campaign_id:
            return []

        try:
            from app.infra.computation_repositories import OptimizationObservationRepository

            items, _ = OptimizationObservationRepository.list_all(
                {"campaign_id": campaign_id},
                sort_field="created_at",
                reverse=True,
                page=1,
                page_size=limit,
            )
            return [
                {
                    "observation_id": doc.get("observation_id", ""),
                    "campaign_id": doc.get("campaign_id", ""),
                    "suggestion_id": doc.get("suggestion_id"),
                    "candidate_id": doc.get("candidate_id"),
                    "values": doc.get("values", {}),
                    "uncertainty": doc.get("uncertainty"),
                    "source_run_id": doc.get("source_run_id"),
                    "status": doc.get("status", "pending"),
                    "created_at": str(doc.get("created_at", "")),
                }
                for doc in items
            ]
        except Exception:
            return []

    def _is_audit_event_visible_to_user(self, event: dict, *, actor_user_id: str) -> bool:
        """判断审计事件是否属于当前 ResearchEngine 用户可见范围。"""
        if event.get("actor_user_id") == actor_user_id:
            return True

        entity_type = event.get("entity_type")
        entity_id = event.get("entity_id")
        doc: dict | None = None
        if entity_type == "problem_spec":
            doc = ResearchProblemSpecRepository.find_one({"problem_spec_id": entity_id})
        elif entity_type == "execution_decision":
            doc = ExecutionDecisionRepository.find_one({"decision_id": entity_id})
        elif entity_type == "manual_algorithm_workflow":
            doc = ManualAlgorithmWorkflowRepository.find_one({"workflow_id": entity_id})
        elif entity_type == "workflow_run":
            doc = WorkflowRunRepository.find_one({"workflow_run_id": entity_id})
        elif entity_type == "algorithm_run":
            doc = AlgorithmRunRepository.find_one({"run_id": entity_id})
        elif entity_type == "research_run":
            doc = ResearchRunRepository.find_one({"run_id": entity_id})
        elif entity_type == "research_stage_run":
            items, _ = ResearchRunRepository.list_runs(page=1, page_size=10000, include_archived=True)
            for run_doc in items:
                if any(sr.get("stage_run_id") == entity_id for sr in run_doc.get("stage_runs", [])):
                    doc = run_doc
                    break

        if doc and (doc.get("owner_id") or doc.get("created_by")) == actor_user_id:
            return True

        related_ids = event.get("related_ids") or {}
        research_run_id = related_ids.get("research_run_id")
        if research_run_id:
            run = ResearchRunRepository.find_one({"run_id": research_run_id})
            if run and (run.get("owner_id") or run.get("created_by")) == actor_user_id:
                return True
        problem_spec_id = related_ids.get("problem_spec_id")
        if problem_spec_id:
            spec = ResearchProblemSpecRepository.find_one({"problem_spec_id": problem_spec_id})
            if spec and (spec.get("owner_id") or spec.get("created_by")) == actor_user_id:
                return True
        return False

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_workflow_input_bindings(
        input_bindings: dict,
        *,
        spec: ProblemSpec,
        step_outputs: dict[str, dict],
    ) -> dict[str, Any]:
        """解析 P0 Workflow 输入绑定。"""
        resolved: dict[str, Any] = {}
        spec_data = spec.model_dump()
        for field_name, binding in input_bindings.items():
            source = binding.source
            if source in {"manual_input", "literal", "value"}:
                resolved[field_name] = binding.value
            elif source == "problem_spec":
                resolved[field_name] = ResearchEngineService._get_path_value(spec_data, binding.path)
            elif source in {"workflow_step_output", "upstream_step_output"}:
                if not binding.step_id:
                    raise ValueError(f"输入字段 '{field_name}' 缺少上游 step_id")
                upstream_output = step_outputs.get(binding.step_id)
                if upstream_output is None:
                    raise ValueError(f"输入字段 '{field_name}' 引用的上游 step '{binding.step_id}' 尚无输出")
                resolved[field_name] = ResearchEngineService._get_path_value(upstream_output, binding.path)
            else:
                raise ValueError(f"暂不支持输入来源 '{source}'")
        return resolved

    @staticmethod
    def _get_path_value(data: dict[str, Any], path: str | None) -> Any:
        """从 dict/list 中按点路径取值。"""
        if not path:
            return data
        current: Any = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return None
        return current

    def _submit_computation_from_algorithm(
        self,
        input_snapshot: dict,
        algorithm_run_id: str,
        actor_user_id: str,
        request_id: str | None = None,
    ) -> str | None:
        """从 AlgorithmRun 委托给 ComputationService 创建 ComputationRun。

        将 computation_submit_adapter 的输入映射为 ComputationCreateRequest，
        创建 ComputationRun 并返回 run_id。

        Args:
            input_snapshot: 算法运行输入快照。
            algorithm_run_id: AlgorithmRun ID。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            创建的 ComputationRun ID，失败返回 None。
        """
        from app.schemas.computation import ComputationCreateRequest, MoleculeInput
        from app.services.computation_service import ComputationService

        workflow_type = input_snapshot.get("workflow_type", "LOCAL_XTB")
        smiles = input_snapshot.get("smiles", "")
        name = input_snapshot.get("name")

        # 映射 workflow_type -> engine
        engine_map = {
            "LOCAL_STRUCTURE": "LOCAL",
            "LOCAL_XTB": "XTB",
            "ORCA_COMPUTE_ENGINE_LASER": "ORCA",
        }
        engine = input_snapshot.get("engine") or engine_map.get(workflow_type, "XTB")

        # 构建 ComputationCreateRequest
        molecule = MoleculeInput(smiles=smiles)
        if name:
            molecule.name = name

        from app.schemas.computation import ComputationParameters

        params = ComputationParameters()
        if "charge" in input_snapshot:
            params.charge = int(input_snapshot["charge"])
        if "multiplicity" in input_snapshot:
            params.multiplicity = int(input_snapshot["multiplicity"])
        if "method" in input_snapshot:
            params.method = input_snapshot["method"]
        if "solvent" in input_snapshot:
            params.solvent = input_snapshot["solvent"]

        comp_payload = ComputationCreateRequest(
            workflow_type=workflow_type,
            engine=engine,
            molecule=molecule,
            parameters=params,
            source="research_engine",
            campaign_id=input_snapshot.get("campaign_id"),
        )

        computation_service = ComputationService()
        result = computation_service.create_run(
            comp_payload,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        return result.run_id if result else None

    @staticmethod
    def _new_id(prefix: str) -> str:
        """生成带前缀的唯一 ID。

        Args:
            prefix: ID 前缀。

        Returns:
            唯一 ID 字符串。
        """
        return f"{prefix}_{uuid4().hex[:12]}"

    @staticmethod
    def _write_audit_event(
        *,
        actor_user_id: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        reason: str,
        before: dict | None = None,
        after: dict | None = None,
        request_id: str | None = None,
    ) -> None:
        """写审计事件。

        封装 AuditEventRepository.append() 的字典构建逻辑。

        Args:
            actor_user_id: 操作人用户 ID。
            entity_type: 实体类型。
            entity_id: 实体 ID。
            event_type: 事件类型。
            reason: 操作原因。
            before: 变更前状态。
            after: 变更后状态。
            request_id: 请求追踪 ID。
        """
        AuditEventRepository.append(
            {
                "event_id": ResearchEngineService._new_id("audit"),
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "actor_role": "user",
                "request_id": request_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "related_ids": {},
                "before": before or {},
                "after": after or {},
                "metadata": {"source": "poly_agent", "reason": reason},
                "created_at": utc_now(),
            }
        )

    @staticmethod
    def _doc_to_algorithm_run(doc: dict) -> AlgorithmRun:
        """将仓库文档转换为 AlgorithmRun Pydantic 模型。

        Args:
            doc: 仓库中的原始文档。

        Returns:
            AlgorithmRun 模型实例。
        """
        return AlgorithmRun(
            run_id=doc["run_id"],
            algorithm_id=doc.get("algorithm_id", ""),
            trigger_source=doc.get("trigger_source", "human_workflow"),
            trigger_context_id=doc.get("trigger_context_id"),
            problem_spec_id=doc.get("problem_spec_id"),
            problem_spec_version=doc.get("problem_spec_version"),
            campaign_id=doc.get("campaign_id"),
            workflow_run_id=doc.get("workflow_run_id"),
            workflow_step_run_id=doc.get("workflow_step_run_id"),
            research_run_id=doc.get("research_run_id"),
            stage_run_id=doc.get("stage_run_id"),
            linked_computation_run_id=doc.get("linked_computation_run_id"),
            linked_suggestion_id=doc.get("linked_suggestion_id"),
            linked_observation_id=doc.get("linked_observation_id"),
            input_snapshot=doc.get("input_snapshot", {}),
            output_summary=doc.get("output_summary", {}),
            artifact_refs=doc.get("artifact_refs", []),
            status=doc.get("status", "queued"),
            error=doc.get("error"),
            created_by=doc.get("created_by", "system"),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
            started_at=doc.get("started_at"),
            finished_at=doc.get("finished_at"),
        )

    @staticmethod
    def _doc_to_problem_spec(doc: dict) -> ProblemSpec:
        """将仓库文档转换为 ProblemSpec Pydantic 模型。

        Args:
            doc: 仓库中的原始文档。

        Returns:
            ProblemSpec 模型实例。
        """
        return ProblemSpec(
            problem_spec_id=doc["problem_spec_id"],
            name=doc.get("name", ""),
            material_family=doc.get("material_family", "fluoropolymer"),
            problem_type=doc.get("problem_type", "formulation_process_optimization"),
            allowed_execution_modes=doc.get("allowed_execution_modes", ["manual_workbench", "autoresearch"]),
            decision_status=doc.get("decision_status", "pending_execution_decision"),
            variables=doc.get("variables", []),
            objectives=doc.get("objectives", []),
            constraints=doc.get("constraints", []),
            measurements=doc.get("measurements", []),
            campaign_id=doc.get("campaign_id"),
            description=doc.get("description"),
            schema_version=doc.get("schema_version", "0.4"),
            created_by=doc.get("created_by", "system"),
            owner_id=doc.get("owner_id"),
            project_id=doc.get("project_id"),
            status=doc.get("status", "draft"),
            frozen_version=doc.get("frozen_version", 0),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )

    @staticmethod
    def _doc_to_execution_decision(doc: dict) -> ExecutionDecision:
        """将仓库文档转换为 ExecutionDecision。"""
        return ExecutionDecision(
            decision_id=doc["decision_id"],
            problem_spec_id=doc.get("problem_spec_id", ""),
            problem_spec_version=doc.get("problem_spec_version", "0.4"),
            mode=doc.get("mode", "manual_workbench"),
            reason=doc.get("reason", ""),
            status=doc.get("status", "active"),
            initial_context_id=doc.get("initial_context_id"),
            created_by=doc.get("created_by", "system"),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )

    @staticmethod
    def _doc_to_manual_workflow(doc: dict) -> ManualAlgorithmWorkflow:
        """将仓库文档转换为 ManualAlgorithmWorkflow。"""
        return ManualAlgorithmWorkflow(
            workflow_id=doc["workflow_id"],
            problem_spec_id=doc.get("problem_spec_id", ""),
            execution_decision_id=doc.get("execution_decision_id", ""),
            name=doc.get("name", ""),
            steps=doc.get("steps", []),
            description=doc.get("description"),
            status=doc.get("status", "active"),
            validation_status=doc.get("validation_status", "validated"),
            created_by=doc.get("created_by", "system"),
            owner_id=doc.get("owner_id"),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )

    @staticmethod
    def _doc_to_workflow_run(doc: dict) -> WorkflowRun:
        """将仓库文档转换为 WorkflowRun。"""
        return WorkflowRun(
            workflow_run_id=doc["workflow_run_id"],
            workflow_id=doc.get("workflow_id", ""),
            problem_spec_id=doc.get("problem_spec_id", ""),
            execution_decision_id=doc.get("execution_decision_id", ""),
            status=doc.get("status", "queued"),
            step_runs=[WorkflowStepRun(**item) for item in doc.get("step_runs", [])],
            input_snapshot=doc.get("input_snapshot", {}),
            artifact_refs=doc.get("artifact_refs", []),
            created_by=doc.get("created_by", "system"),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
            started_at=doc.get("started_at"),
            finished_at=doc.get("finished_at"),
        )

    @staticmethod
    def _problem_objectives_to_optimization(payload: ProblemSpecCreate) -> list[dict[str, Any]]:
        """将 ProblemSpec 目标映射为 OptimizationCampaign 目标契约。"""
        direction_map = {"maximize": "max", "minimize": "min"}
        return [
            {
                "name": objective.name,
                "direction": direction_map.get(objective.direction, "max"),
                "unit": objective.unit,
                "required": True,
            }
            for objective in payload.objectives
        ]
