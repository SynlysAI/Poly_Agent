"""ResearchEngine AutoResearch 材料版编排器。

实现材料研发专用 ResearchRun 和 Stage/Gate 状态机，
包括创建、启动、阶段推进、gate 审批、暂停恢复和 checkpoint 管理。
P0 只做固定阶段序列、mock 阶段推进、候选 gate 审批和现有 computation/optimization 复用。
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
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
    ResearchProblemSpecRepository,
    ResearchRunRepository,
)
from app.schemas.research_engine import (
    AlgorithmRunCreate,
    GateDecision,
    ResearchRun,
    ResearchRunCreate,
    ResearchRunListData,
    ResearchRunStatus,
    ResearchStageRun,
    ResearchStageKey,
    ResearchStageStatus,
    StageApprovalRequest,
    StageGate,
    StageGateDecision,
    TriggerSource,
    validate_research_run_transition,
    validate_stage_transition,
)
from app.services.research_engine_access import ensure_research_engine_doc_access
from app.services.research_engine_defaults import (
    DEFAULT_STAGE_CONTRACTS,
    DEFAULT_STAGE_SEQUENCE,
    DEFAULT_MATERIAL_PROFILES,
    P0_GATE_STAGES,
    get_default_stage_contract,
    is_p0_gate_stage,
)


class ResearchEngineOrchestrator:
    """AutoResearch 材料版编排器。

    管理 ResearchRun 生命周期：创建、启动、阶段推进、gate 审批、暂停恢复。
    与 ResearchEngineService 分工：
    - ResearchEngineService: ProblemSpec、AlgorithmRegistry、AlgorithmRun（人工通道）
    - ResearchEngineOrchestrator: ResearchRun、Stage/Gate（自动编排通道）
    """

    @staticmethod
    def _ensure_run_access(
        doc: dict,
        *,
        actor_user_id: str | None,
        is_admin: bool,
    ) -> None:
        """检查当前用户是否可访问 ResearchRun。"""
        ensure_research_engine_doc_access(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="ResearchRun",
        )

    # ------------------------------------------------------------------
    # ResearchRun 创建与查询
    # ------------------------------------------------------------------

    def create_research_run(
        self,
        problem_spec_id: str,
        *,
        execution_decision_id: str | None = None,
        campaign_id: str | None = None,
        profile_id: str = "fluoropolymer",
        max_iterations: int = 5,
        batch_size: int = 10,
        description: str | None = None,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> ResearchRun:
        """基于 ProblemSpec 创建 ResearchRun 草稿。

        生成默认 stage_runs 并关联 ProblemSpec、Campaign、Profile。

        Args:
            problem_spec_id: ProblemSpec ID（必填）。
            execution_decision_id: 关联的 autoresearch 执行决策 ID。
            campaign_id: 关联的 Campaign ID。
            profile_id: 材料 profile ID。
            max_iterations: 最大迭代次数。
            batch_size: 候选批次大小。
            description: 运行描述。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            创建的 ResearchRun 完整记录。

        Raises:
            HTTPException: ProblemSpec 不存在。
        """
        # 1. 校验 ProblemSpec 存在
        from app.services.research_engine_service import ResearchEngineService
        svc = ResearchEngineService()
        ps = svc.get_problem_spec(problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        decision = (
            svc.get_execution_decision(execution_decision_id, actor_user_id=actor_user_id, is_admin=is_admin)
            if execution_decision_id
            else svc.get_active_execution_decision(problem_spec_id, actor_user_id=actor_user_id, is_admin=is_admin)
        )
        if decision.problem_spec_id != problem_spec_id or decision.mode != "autoresearch":
            raise HTTPException(status_code=409, detail="ResearchRun 必须关联 autoresearch 执行决策")
        execution_decision_id = decision.decision_id

        now = utc_now()
        run_id = self._new_id("rr")

        # 生成默认 stage_runs
        stage_runs = self._generate_default_stage_runs(
            research_run_id=run_id,
            problem_spec_id=problem_spec_id,
            profile_id=profile_id,
            batch_size=batch_size,
        )

        doc = {
            "run_id": run_id,
            "project_id": ps.project_id,
            "problem_spec_id": problem_spec_id,
            "execution_decision_id": execution_decision_id,
            "campaign_id": campaign_id or ps.campaign_id,
            "profile_id": profile_id,
            "status": "draft",
            "current_stage": None,
            "stage_runs": [sr.model_dump() for sr in stage_runs],
            "linked_algorithm_runs": [],
            "linked_experiment_runs": [],
            "checkpoint": {},
            "summary": {},
            "max_iterations": max_iterations,
            "batch_size": batch_size,
            "created_by": actor_user_id,
            "owner_id": actor_user_id,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }

        ResearchRunRepository.save("run_id", doc)

        # 写审计事件
        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="created",
            reason=description or f"创建 AutoResearch 运行 (profile={profile_id})",
            before={},
            after={
                "problem_spec_id": problem_spec_id,
                "execution_decision_id": execution_decision_id,
                "profile_id": profile_id,
                "max_iterations": max_iterations,
                "stage_count": len(stage_runs),
            },
            request_id=request_id,
        )

        if decision.initial_context_id is None:
            from app.infra.research_engine_repositories import ExecutionDecisionRepository

            ExecutionDecisionRepository.update_fields(
                execution_decision_id,
                {"initial_context_id": run_id, "updated_at": now},
            )

        return self._doc_to_research_run(doc)

    def get_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> ResearchRun:
        """获取 ResearchRun 详情。

        Args:
            run_id: ResearchRun ID。

        Returns:
            ResearchRun 完整记录。

        Raises:
            HTTPException: ResearchRun 不存在。
        """
        doc = ResearchRunRepository.find_one({"run_id": run_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"ResearchRun '{run_id}' 不存在")
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        return self._doc_to_research_run(doc)

    def list_research_runs(
        self,
        *,
        problem_spec_id: str | None = None,
        campaign_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        project_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ResearchRunListData:
        """分页查询 ResearchRun 列表。

        Args:
            problem_spec_id: 按 ProblemSpec ID 过滤。
            campaign_id: 按 Campaign ID 过滤。
            status: 按状态过滤。
            created_by: 按创建者过滤。
            project_id: 按项目 ID 过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            ResearchRun 分页列表。
        """
        items, total = ResearchRunRepository.list_runs(
            problem_spec_id=problem_spec_id,
            campaign_id=campaign_id,
            status=status,
            include_archived=status == "archived",
            created_by=created_by,
            project_id=project_id,
            page=page,
            page_size=page_size,
        )
        runs = [self._doc_to_research_run(doc) for doc in items]
        return ResearchRunListData(items=runs, page=page, page_size=page_size, total=total)

    def archive_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str = "归档 AutoResearch 运行",
        request_id: str | None = None,
    ) -> ResearchRun:
        """软删除/归档 ResearchRun，保留阶段、审计和追溯信息。"""
        doc = self._get_run_doc(run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        current_status = doc.get("status", "draft")
        if current_status == "archived":
            return self._doc_to_research_run(doc)

        now = utc_now()
        ResearchRunRepository.update_fields(run_id, {
            "status": "archived",
            "updated_at": now,
        })
        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="archived",
            reason=reason,
            before={"status": current_status},
            after={"status": "archived"},
            request_id=request_id,
        )
        return self._doc_to_research_run(self._get_run_doc(run_id))

    # ------------------------------------------------------------------
    # 启动与阶段推进
    # ------------------------------------------------------------------

    def start_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str = "启动 AutoResearch 运行",
        request_id: str | None = None,
    ) -> ResearchRun:
        """启动 ResearchRun，从 draft 转为 running 并开始推进阶段。

        仅 draft 状态可启动。从 blocked_approval 继续推进应使用 advance_research_run。

        Args:
            run_id: ResearchRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 操作原因。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。

        Raises:
            HTTPException: ResearchRun 不存在或状态不允许启动。
        """
        doc = self._get_run_doc(run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        current_status = doc.get("status", "draft")

        if current_status != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"ResearchRun '{run_id}' 当前状态为 '{current_status}'，"
                f"不允许启动（仅 draft 状态可启动）",
            )

        now = utc_now()
        ResearchRunRepository.update_fields(run_id, {
            "status": "running",
            "started_at": now,
            "updated_at": now,
        })

        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="started",
            reason=reason,
            before={"status": current_status},
            after={"status": "running"},
            request_id=request_id,
        )

        # 重新获取并推进阶段
        doc = self._get_run_doc(run_id)
        doc = self._advance_stages(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            request_id=request_id,
        )

        # 重新获取最新状态
        return self._doc_to_research_run(self._get_run_doc(run_id))

    def advance_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str = "继续推进 AutoResearch 阶段",
        request_id: str | None = None,
    ) -> ResearchRun:
        """继续推进 ResearchRun 的阶段（从 blocked_approval 或 paused 恢复后调用）。

        Args:
            run_id: ResearchRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 操作原因。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。

        Raises:
            HTTPException: ResearchRun 不存在或状态不允许推进。
        """
        doc = self._get_run_doc(run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        current_status = doc.get("status", "draft")

        if current_status not in ("running", "blocked_approval"):
            raise HTTPException(
                status_code=409,
                detail=f"ResearchRun '{run_id}' 当前状态为 '{current_status}'，不允许推进阶段",
            )

        # 确保 status 为 running
        if current_status != "running":
            ResearchRunRepository.update_fields(run_id, {
                "status": "running",
                "updated_at": utc_now(),
            })

        doc = self._get_run_doc(run_id)
        doc = self._advance_stages(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            request_id=request_id,
        )

        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="advanced",
            reason=reason,
            before={"status": current_status},
            after={"status": doc.get("status")},
            request_id=request_id,
        )

        return self._doc_to_research_run(self._get_run_doc(run_id))

    def _advance_stages(
        self,
        doc: dict,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> dict:
        """推进阶段：自动完成非 gate 阶段，在 gate 阶段阻塞。

        从当前 pending 或 running 阶段开始，
        对非 gate 阶段用 mock runner 自动生成输出，
        遇到 gate 阶段时进入 blocked_approval 并停止。

        Args:
            doc: ResearchRun 文档。
            actor_user_id: 操作人用户 ID。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun 文档。
        """
        run_id = doc["run_id"]
        stage_runs: list[dict] = doc.get("stage_runs", [])

        # 找到当前 pending 或 running 的阶段
        # 如果当前已有 blocked_approval 阶段，中断推进等待审批
        current_idx = None
        for i, sr in enumerate(stage_runs):
            if sr.get("status") == "blocked_approval":
                # 已有 gate 阻塞，不再推进
                return self._get_run_doc(run_id)
            if sr.get("status") in ("pending", "running"):
                current_idx = i
                break

        if current_idx is None:
            # 所有阶段已完成
            self._check_run_completed(run_id)
            return self._get_run_doc(run_id)

        problem_spec = doc.get("problem_spec_id", "")

        # 从当前阶段开始推进
        while current_idx is not None and current_idx < len(stage_runs):
            sr = stage_runs[current_idx]
            stage_key = sr["stage_key"]
            stage_status = sr.get("status", "pending")

            # 更新阶段状态为 running
            if stage_status == "pending":
                now = utc_now()
                sr["status"] = "running"
                sr["started_at"] = now.isoformat() if isinstance(now, datetime) else str(now)
                sr["updated_at"] = now.isoformat() if isinstance(now, datetime) else str(now)
                self._save_stage_runs(run_id, stage_runs)

            # 需要先产出候选/计算结果的 gate 阶段，先执行再等待审批。
            if self._stage_algorithm_id(stage_key) is not None:
                try:
                    stage_output = self._run_stage_algorithm(
                        doc=doc,
                        stage_run=sr,
                        actor_user_id=actor_user_id,
                        is_admin=is_admin,
                        request_id=request_id,
                    )
                    sr["output_summary"] = stage_output
                    self._save_stage_runs(run_id, stage_runs)
                except Exception as exc:
                    sr["status"] = "failed"
                    sr["error"] = {
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                        "retryable": False,
                    }
                    sr["finished_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                    sr["updated_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                    self._save_stage_runs(run_id, stage_runs)
                    ResearchRunRepository.update_fields(run_id, {
                        "status": "failed",
                        "current_stage": stage_key,
                        "updated_at": utc_now(),
                    })
                    self._write_audit(
                        actor_user_id="system",
                        entity_type="research_stage_run",
                        entity_id=sr["stage_run_id"],
                        event_type="failed",
                        reason=f"阶段 '{stage_key}' 执行失败: {exc}",
                        before={"status": "running"},
                        after={"status": "failed", "error": str(exc)},
                        request_id=request_id,
                    )
                    return self._get_run_doc(run_id)

            # 检查是否是 gate 阶段
            if is_p0_gate_stage(stage_key):
                # gate 阶段：进入 blocked_approval
                sr["status"] = "blocked_approval"
                sr["updated_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                self._save_stage_runs(run_id, stage_runs)
                ResearchRunRepository.update_fields(run_id, {
                    "status": "blocked_approval",
                    "current_stage": stage_key,
                    "updated_at": utc_now(),
                })
                self._write_audit(
                    actor_user_id="system",
                    entity_type="research_stage_run",
                    entity_id=sr["stage_run_id"],
                    event_type="blocked_approval",
                    reason=f"阶段 '{stage_key}' 需要人工审批",
                    before={"status": "running"},
                    after={"status": "blocked_approval"},
                    request_id=request_id,
                )
                self._save_checkpoint(run_id)
                return self._get_run_doc(run_id)

            # 非 gate 阶段：自动完成
            try:
                mock_output = sr.get("output_summary") or self._run_mock_stage(sr, problem_spec)
                sr["status"] = "completed"
                sr["output_summary"] = mock_output
                sr["finished_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                sr["updated_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                self._save_stage_runs(run_id, stage_runs)
                self._write_audit(
                    actor_user_id="system",
                    entity_type="research_stage_run",
                    entity_id=sr["stage_run_id"],
                    event_type="completed",
                    reason=f"阶段 '{stage_key}' 自动完成",
                    before={"status": "running"},
                    after={"status": "completed", "output_summary_keys": list(mock_output.keys())},
                    request_id=request_id,
                )
            except Exception as exc:
                sr["status"] = "failed"
                sr["error"] = {
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                sr["finished_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                sr["updated_at"] = utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now())
                self._save_stage_runs(run_id, stage_runs)
                ResearchRunRepository.update_fields(run_id, {
                    "status": "failed",
                    "current_stage": stage_key,
                    "updated_at": utc_now(),
                })
                self._write_audit(
                    actor_user_id="system",
                    entity_type="research_stage_run",
                    entity_id=sr["stage_run_id"],
                    event_type="failed",
                    reason=f"阶段 '{stage_key}' 执行失败: {exc}",
                    before={"status": "running"},
                    after={"status": "failed", "error": str(exc)},
                    request_id=request_id,
                )
                return self._get_run_doc(run_id)

            # 查找下一个 pending 阶段
            current_idx = None
            for j in range(current_idx + 1 if current_idx is not None else 0, len(stage_runs)):
                if stage_runs[j].get("status") in ("pending",):
                    current_idx = j
                    break

        # 所有阶段已完成
        self._check_run_completed(run_id)
        self._save_checkpoint(run_id)
        return self._get_run_doc(run_id)

    def _run_mock_stage(self, stage_run: dict, problem_spec_id: str) -> dict:
        """为 mock 阶段生成确定性输出。

        根据 stage_key 映射到相应的 mock runner 并生成输出。

        Args:
            stage_run: 阶段运行文档。
            problem_spec_id: ProblemSpec ID。

        Returns:
            Mock 阶段输出摘要。
        """
        from app.services.research_engine_algorithm_runner import get_runner

        stage_key = stage_run["stage_key"]

        # 阶段到 mock runner 的映射
        stage_to_runner: dict[str, str] = {
            "KNOWLEDGE_RETRIEVAL": "literature_mock",
            "STRUCTURE_FEATURE": "polymer_descriptor_mock",
            "COMPUTE_PREDICT": "property_predictor_mock",
            "RECOMMENDATION_ASK": "mobo_mock",
        }

        runner_id = stage_to_runner.get(stage_key)
        if runner_id is None:
            # 无对应 mock runner 的阶段（PROBLEM_SPEC、RESULT_TELL 等）
            # 生成基础阶段输出
            return {
                "status": "auto_completed",
                "stage_key": stage_key,
                "execution_mode": "mock_fallback",
                "message": f"阶段 '{stage_key}' 已自动完成（无 mock runner）",
                "completed_at": utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now()),
            }

        runner = get_runner(runner_id)
        if runner is None:
            return {
                "status": "auto_completed",
                "stage_key": stage_key,
                "execution_mode": "mock_fallback",
                "message": f"阶段 '{stage_key}' 的 mock runner '{runner_id}' 未注册",
            }

        # 根据阶段类型构建输入
        input_snapshot: dict = {"problem_spec_id": problem_spec_id}
        if stage_key == "KNOWLEDGE_RETRIEVAL":
            input_snapshot.update({
                "keywords": f"高分子材料 优化",
                "material_family": "fluoropolymer",
                "target_properties": ["dielectric_constant", "thermal_stability"],
            })
        elif stage_key == "STRUCTURE_FEATURE":
            input_snapshot.update({
                "smiles": "C=CF",
                "polymer_type": "homopolymer",
            })
        elif stage_key == "COMPUTE_PREDICT":
            input_snapshot.update({
                "smiles": "C=C(F)F",
                "target_properties": ["dielectric_constant", "thermal_stability"],
                "fluorine_content": 45.0,
                "polymerization_temperature": 120.0,
            })
        elif stage_key == "RECOMMENDATION_ASK":
            input_snapshot.update({
                "objectives": [
                    {"name": "dielectric_constant", "direction": "maximize"},
                    {"name": "thermal_stability", "direction": "maximize"},
                ],
            })

        runner.validate_input(input_snapshot)
        output = runner.run(input_snapshot)
        output["execution_mode"] = "mock_fallback"
        return output

    def _stage_algorithm_id(self, stage_key: str) -> str | None:
        """返回 AutoResearch 阶段对应的算法能力 ID。"""
        if stage_key == "RECOMMENDATION_ASK" and not self._is_alchemist_adapter_ready():
            return "mobo_mock"
        return {
            "KNOWLEDGE_RETRIEVAL": "literature_rag_adapter",
            "STRUCTURE_FEATURE": "polymer_descriptor_mock",
            "COMPUTE_PREDICT": "computation_submit_adapter",
            "RECOMMENDATION_ASK": "mobo_alchemist_adapter",
        }.get(stage_key)

    @staticmethod
    def _is_alchemist_adapter_ready() -> bool:
        """快速判断 Alchemist adapter 是否值得进入真实调用路径。"""
        raw_url = os.getenv("ALCHEMIST_BACKEND_URL", "").strip()
        if not raw_url:
            return False
        parsed = urlparse(raw_url)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        timeout = float(os.getenv("RESEARCH_ENGINE_PREFLIGHT_TIMEOUT_SECONDS", "0.5"))
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _run_stage_algorithm(
        self,
        *,
        doc: dict,
        stage_run: dict,
        actor_user_id: str,
        is_admin: bool = False,
        request_id: str | None = None,
    ) -> dict:
        """通过 AlgorithmRun 执行 AutoResearch 阶段并回写追溯关联。"""
        from app.services.research_engine_service import ResearchEngineService

        service = ResearchEngineService()
        service.seed_default_algorithms()

        stage_key = stage_run["stage_key"]
        algorithm_id = self._stage_algorithm_id(stage_key)
        if algorithm_id is None:
            return self._run_mock_stage(stage_run, doc.get("problem_spec_id", ""))

        input_snapshot = self._build_stage_algorithm_input(doc, stage_run, algorithm_id)
        try:
            algorithm_run = service.create_algorithm_run(
                AlgorithmRunCreate(
                    algorithm_id=algorithm_id,
                    trigger_source="autoresearch",
                    trigger_context_id=doc["run_id"],
                    problem_spec_id=doc.get("problem_spec_id"),
                    campaign_id=doc.get("campaign_id"),
                    research_run_id=doc["run_id"],
                    stage_run_id=stage_run["stage_run_id"],
                    input_snapshot=input_snapshot,
                    reason=f"AutoResearch stage {stage_key} 执行算法 {algorithm_id}",
                ),
                actor_user_id=actor_user_id,
                is_admin=is_admin,
                request_id=request_id,
            )
            self._link_algorithm_run(doc, stage_run, algorithm_run.run_id)
            output = dict(algorithm_run.output_summary or {})
            output.setdefault(
                "execution_mode",
                "mock_fallback" if algorithm_id.endswith("_mock") else "adapter",
            )
            if output.get("configured") is False:
                fallback = self._run_mock_stage(stage_run, doc.get("problem_spec_id", ""))
                fallback.update(
                    {
                        "execution_mode": "mock_fallback",
                        "adapter_configured": False,
                        "adapter_algorithm_id": algorithm_id,
                        "adapter_message": output.get("message") or f"算法 '{algorithm_id}' 未配置",
                    }
                )
                AlgorithmRunRepository.update_fields(
                    algorithm_run.run_id,
                    {"output_summary": fallback, "updated_at": utc_now()},
                )
                return fallback
            return output
        except Exception as exc:
            self._link_latest_algorithm_run(doc, stage_run, algorithm_id)
            if not algorithm_id.endswith("_mock"):
                fallback = self._run_mock_stage(stage_run, doc.get("problem_spec_id", ""))
                fallback.update(
                    {
                        "execution_mode": "mock_fallback",
                        "adapter_configured": False,
                        "adapter_algorithm_id": algorithm_id,
                        "adapter_message": str(exc),
                    }
                )
                return fallback
            raise

    def _build_stage_algorithm_input(
        self,
        doc: dict,
        stage_run: dict,
        algorithm_id: str,
    ) -> dict:
        """根据 ProblemSpec 和阶段上下文生成算法输入。"""
        from app.services.research_engine_service import ResearchEngineService

        service = ResearchEngineService()
        problem_spec = service.get_problem_spec(doc["problem_spec_id"])
        objectives = [item.model_dump() for item in problem_spec.objectives]
        variables = [item.model_dump() for item in problem_spec.variables]
        target_properties = [item["name"] for item in objectives if item.get("name")]
        material_family = problem_spec.material_family
        smiles = self._infer_stage_smiles(problem_spec.model_dump())
        base = {
            "problem_spec_id": problem_spec.problem_spec_id,
            "campaign_id": doc.get("campaign_id"),
            "material_family": material_family,
            "target_properties": target_properties,
            "batch_size": doc.get("batch_size", 10),
        }

        if algorithm_id == "literature_rag_adapter":
            query_parts = [problem_spec.name, material_family, *(target_properties or [])]
            return {
                **base,
                "query": " ".join(str(part) for part in query_parts if part),
                "top_k": 5,
            }
        if algorithm_id == "polymer_descriptor_mock":
            return {
                **base,
                "smiles": smiles,
                "polymer_type": "copolymer" if "." in smiles else "homopolymer",
            }
        if algorithm_id == "computation_submit_adapter":
            return {
                **base,
                "workflow_type": "LOCAL_STRUCTURE",
                "smiles": smiles,
                "charge": 0,
                "multiplicity": 1,
                "name": f"{problem_spec.problem_spec_id}-{stage_run['stage_key']}",
            }
        if algorithm_id in {"mobo_alchemist_adapter", "mobo_mock"}:
            return {
                **base,
                "variables": variables,
                "objectives": objectives,
                "historical_observations": [],
                "session_name": f"ResearchEngine {problem_spec.name}",
            }
        return base

    @staticmethod
    def _infer_stage_smiles(problem_spec: dict) -> str:
        """从 ProblemSpec 中尽量提取 SMILES；没有则使用演示氟聚合物单体。"""
        for variable in problem_spec.get("variables", []):
            name = str(variable.get("name", "")).lower()
            if "smiles" in name:
                categories = variable.get("categories") or []
                if categories:
                    return str(categories[0])
                description = variable.get("description")
                if description:
                    return str(description)
        return "C=C(F)F"

    def _link_algorithm_run(self, doc: dict, stage_run: dict, algorithm_run_id: str) -> None:
        """把 AlgorithmRun ID 写入 ResearchRun 和 StageRun 追溯字段。"""
        stage_links = stage_run.setdefault("linked_algorithm_runs", [])
        if algorithm_run_id not in stage_links:
            stage_links.append(algorithm_run_id)

        run_links = list(doc.get("linked_algorithm_runs") or [])
        if algorithm_run_id not in run_links:
            run_links.append(algorithm_run_id)
            doc["linked_algorithm_runs"] = run_links
            ResearchRunRepository.update_fields(doc["run_id"], {
                "linked_algorithm_runs": run_links,
                "updated_at": utc_now(),
            })

    def _link_latest_algorithm_run(self, doc: dict, stage_run: dict, algorithm_id: str) -> None:
        """失败时找回刚落库的 AlgorithmRun，保证 Stage 追溯不丢。"""
        items, _ = AlgorithmRunRepository.list_runs(
            research_run_id=doc["run_id"],
            algorithm_id=algorithm_id,
            page=1,
            page_size=10,
        )
        for item in items:
            if item.get("stage_run_id") == stage_run.get("stage_run_id"):
                self._link_algorithm_run(doc, stage_run, item["run_id"])
                return

    def _check_run_completed(self, run_id: str) -> None:
        """检查 ResearchRun 是否所有阶段已完成，若完成则更新状态。

        Args:
            run_id: ResearchRun ID。
        """
        doc = self._get_run_doc(run_id)
        stage_runs: list[dict] = doc.get("stage_runs", [])
        all_done = all(
            sr.get("status") in ("completed", "skipped")
            for sr in stage_runs
        )
        if all_done and stage_runs:
            now = utc_now()
            ResearchRunRepository.update_fields(run_id, {
                "status": "completed",
                "current_stage": None,
                "finished_at": now,
                "updated_at": now,
                "summary": {
                    "total_stages": len(stage_runs),
                    "completed_stages": len(stage_runs),
                    "failed_stages": 0,
                },
            })

    # ------------------------------------------------------------------
    # Gate 审批
    # ------------------------------------------------------------------

    def approve_stage(
        self,
        research_run_id: str,
        stage_run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str,
        modified_candidates: list[dict] | None = None,
        request_id: str | None = None,
    ) -> ResearchRun:
        """批准 gate 阶段。

        批准后 ResearchRun 从 blocked_approval 转为 running 并继续推进后续阶段。

        Args:
            research_run_id: ResearchRun ID。
            stage_run_id: StageRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 审批原因。
            modified_candidates: 修改后的候选列表（可选）。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。

        Raises:
            HTTPException: ResearchRun 不存在、StageRun 不存在或状态不允许审批。
        """
        doc = self._get_run_doc(research_run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        sr = self._find_stage_run(doc, stage_run_id)

        if sr.get("status") != "blocked_approval":
            raise HTTPException(
                status_code=409,
                detail=f"StageRun '{stage_run_id}' 当前状态为 '{sr.get('status')}'，"
                f"不允许审批（仅 blocked_approval 状态可审批）",
            )

        stage_key = sr["stage_key"]
        now = utc_now()

        # 记录审批决策
        decision = StageGateDecision(
            stage_key=stage_key,
            decision="approved",
            actor_user_id=actor_user_id,
            reason=reason,
            modified_candidates=modified_candidates or [],
            decided_at=now,
        )

        decisions: list[dict] = sr.get("decisions", [])
        decisions.append(decision.model_dump())

        # 更新阶段为 completed
        sr["status"] = "completed"
        sr["decisions"] = decisions
        sr["finished_at"] = now.isoformat() if isinstance(now, datetime) else str(now)
        sr["updated_at"] = now.isoformat() if isinstance(now, datetime) else str(now)

        self._save_stage_runs(research_run_id, doc.get("stage_runs", []))

        # 写审计
        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_stage_run",
            entity_id=stage_run_id,
            event_type="approved",
            reason=reason,
            before={"status": "blocked_approval"},
            after={"status": "completed", "decision": "approved"},
            request_id=request_id,
        )

        # 恢复 ResearchRun 状态并继续推进
        ResearchRunRepository.update_fields(research_run_id, {
            "status": "running",
            "updated_at": now,
        })

        # 继续推进后续阶段
        doc = self._get_run_doc(research_run_id)
        doc = self._advance_stages(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            request_id=request_id,
        )

        return self._doc_to_research_run(self._get_run_doc(research_run_id))

    def reject_stage(
        self,
        research_run_id: str,
        stage_run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str,
        request_id: str | None = None,
    ) -> ResearchRun:
        """拒绝 gate 阶段。

        拒绝后 StageRun 标记为 failed，ResearchRun 标记为 failed。

        Args:
            research_run_id: ResearchRun ID。
            stage_run_id: StageRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 拒绝原因。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。

        Raises:
            HTTPException: ResearchRun 不存在、StageRun 不存在或状态不允许审批。
        """
        doc = self._get_run_doc(research_run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        sr = self._find_stage_run(doc, stage_run_id)

        if sr.get("status") != "blocked_approval":
            raise HTTPException(
                status_code=409,
                detail=f"StageRun '{stage_run_id}' 当前状态为 '{sr.get('status')}'，"
                f"不允许审批（仅 blocked_approval 状态可审批）",
            )

        stage_key = sr["stage_key"]
        now = utc_now()

        # 记录审批决策
        decision = StageGateDecision(
            stage_key=stage_key,
            decision="rejected",
            actor_user_id=actor_user_id,
            reason=reason,
            decided_at=now,
        )

        decisions: list[dict] = sr.get("decisions", [])
        decisions.append(decision.model_dump())

        # 更新阶段为 failed
        sr["status"] = "failed"
        sr["error"] = {
            "error_type": "GateRejected",
            "message": f"阶段 '{stage_key}' 被用户 '{actor_user_id}' 拒绝: {reason}",
        }
        sr["decisions"] = decisions
        sr["finished_at"] = now.isoformat() if isinstance(now, datetime) else str(now)
        sr["updated_at"] = now.isoformat() if isinstance(now, datetime) else str(now)

        self._save_stage_runs(research_run_id, doc.get("stage_runs", []))

        # 更新 ResearchRun 为 failed
        ResearchRunRepository.update_fields(research_run_id, {
            "status": "failed",
            "current_stage": stage_key,
            "finished_at": now,
            "updated_at": now,
            "summary": {
                "failure_reason": reason,
                "failed_stage": stage_key,
                "actor": actor_user_id,
            },
        })

        # 写审计
        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_stage_run",
            entity_id=stage_run_id,
            event_type="rejected",
            reason=reason,
            before={"status": "blocked_approval"},
            after={"status": "failed", "decision": "rejected"},
            request_id=request_id,
        )

        self._save_checkpoint(research_run_id)
        return self._doc_to_research_run(self._get_run_doc(research_run_id))

    # ------------------------------------------------------------------
    # 暂停与恢复
    # ------------------------------------------------------------------

    def pause_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str,
        request_id: str | None = None,
    ) -> ResearchRun:
        """暂停 ResearchRun。

        running 或 blocked_approval 状态的运行可暂停。

        Args:
            run_id: ResearchRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 暂停原因。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。

        Raises:
            HTTPException: ResearchRun 不存在或状态不允许暂停。
        """
        doc = self._get_run_doc(run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        current_status = doc.get("status", "draft")

        if not validate_research_run_transition(current_status, "paused"):
            raise HTTPException(
                status_code=409,
                detail=f"ResearchRun '{run_id}' 当前状态为 '{current_status}'，"
                f"不允许暂停（仅 running 或 blocked_approval 状态可暂停）",
            )

        now = utc_now()
        ResearchRunRepository.update_fields(run_id, {
            "status": "paused",
            "updated_at": now,
        })

        self._save_checkpoint(run_id)

        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="paused",
            reason=reason,
            before={"status": current_status},
            after={"status": "paused"},
            request_id=request_id,
        )

        return self._doc_to_research_run(self._get_run_doc(run_id))

    def resume_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str,
        request_id: str | None = None,
    ) -> ResearchRun:
        """恢复 ResearchRun。

        paused 状态的运行可恢复。

        Args:
            run_id: ResearchRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 恢复原因。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。

        Raises:
            HTTPException: ResearchRun 不存在或状态不允许恢复。
        """
        doc = self._get_run_doc(run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        current_status = doc.get("status", "draft")

        if current_status != "paused":
            raise HTTPException(
                status_code=409,
                detail=f"ResearchRun '{run_id}' 当前状态为 '{current_status}'，"
                f"不允许恢复（仅 paused 状态可恢复）",
            )

        now = utc_now()
        ResearchRunRepository.update_fields(run_id, {
            "status": "running",
            "updated_at": now,
        })

        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="resumed",
            reason=reason,
            before={"status": "paused"},
            after={"status": "running"},
            request_id=request_id,
        )

        # 恢复后重新推进阶段
        doc = self._get_run_doc(run_id)
        doc = self._advance_stages(
            doc,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            request_id=request_id,
        )

        return self._doc_to_research_run(self._get_run_doc(run_id))

    def fail_research_run(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        is_admin: bool = False,
        reason: str,
        request_id: str | None = None,
    ) -> ResearchRun:
        """手动标记 ResearchRun 为失败。

        任何非终态的运行都可标记为失败。

        Args:
            run_id: ResearchRun ID。
            actor_user_id: 操作人用户 ID。
            reason: 失败原因。
            request_id: 请求追踪 ID。

        Returns:
            更新后的 ResearchRun。
        """
        doc = self._get_run_doc(run_id)
        self._ensure_run_access(doc, actor_user_id=actor_user_id, is_admin=is_admin)
        current_status = doc.get("status", "draft")

        if current_status in ("completed", "failed", "archived"):
            raise HTTPException(
                status_code=409,
                detail=f"ResearchRun '{run_id}' 已处于终态 '{current_status}'，不可标记为失败",
            )

        now = utc_now()
        ResearchRunRepository.update_fields(run_id, {
            "status": "failed",
            "finished_at": now,
            "updated_at": now,
        })

        self._save_checkpoint(run_id)

        self._write_audit(
            actor_user_id=actor_user_id,
            entity_type="research_run",
            entity_id=run_id,
            event_type="failed",
            reason=reason,
            before={"status": current_status},
            after={"status": "failed"},
            request_id=request_id,
        )

        return self._doc_to_research_run(self._get_run_doc(run_id))

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _generate_default_stage_runs(
        self,
        research_run_id: str,
        problem_spec_id: str,
        profile_id: str,
        batch_size: int = 10,
    ) -> list[ResearchStageRun]:
        """根据 DEFAULT_STAGE_SEQUENCE 生成默认 stage_runs。

        Args:
            research_run_id: ResearchRun ID。
            problem_spec_id: ProblemSpec ID。
            profile_id: 材料 profile ID。
            batch_size: 候选批次大小。

        Returns:
            ResearchStageRun 模型列表。
        """
        now = utc_now()
        stage_runs: list[ResearchStageRun] = []

        for stage_key in DEFAULT_STAGE_SEQUENCE:
            stage_contract = get_default_stage_contract(stage_key)
            sr = ResearchStageRun(
                stage_run_id=self._new_id("srun"),
                research_run_id=research_run_id,
                stage_key=stage_key,
                status="pending",
                gate=stage_contract,
                input_snapshot={
                    "problem_spec_id": problem_spec_id,
                    "profile_id": profile_id,
                    "batch_size": batch_size,
                },
                created_at=now,
                updated_at=now,
            )
            stage_runs.append(sr)

        return stage_runs

    def _get_run_doc(self, run_id: str) -> dict:
        """获取 ResearchRun 文档，若不存在则抛异常。

        Args:
            run_id: ResearchRun ID。

        Returns:
            ResearchRun 文档。

        Raises:
            HTTPException: ResearchRun 不存在。
        """
        doc = ResearchRunRepository.find_one({"run_id": run_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"ResearchRun '{run_id}' 不存在")
        return doc

    def _find_stage_run(self, doc: dict, stage_run_id: str) -> dict:
        """在 ResearchRun 文档中查找指定的 StageRun。

        Args:
            doc: ResearchRun 文档。
            stage_run_id: StageRun ID。

        Returns:
            StageRun 文档。

        Raises:
            HTTPException: StageRun 不存在。
        """
        for sr in doc.get("stage_runs", []):
            if sr.get("stage_run_id") == stage_run_id:
                return sr
        raise HTTPException(
            status_code=404,
            detail=f"StageRun '{stage_run_id}' 在 ResearchRun '{doc.get('run_id')}' 中不存在",
        )

    def _save_stage_runs(self, run_id: str, stage_runs: list[dict]) -> None:
        """更新 ResearchRun 的 stage_runs 数组。

        Args:
            run_id: ResearchRun ID。
            stage_runs: 更新后的 stage_runs 数组。
        """
        ResearchRunRepository.update_fields(run_id, {
            "stage_runs": stage_runs,
            "updated_at": utc_now(),
        })

    def _save_checkpoint(self, run_id: str) -> None:
        """保存 ResearchRun checkpoint 快照。

        Args:
            run_id: ResearchRun ID。
        """
        doc = self._get_run_doc(run_id)
        checkpoint = {
            "status": doc.get("status"),
            "current_stage": doc.get("current_stage"),
            "stage_runs_snapshot": [
                {
                    "stage_run_id": sr.get("stage_run_id"),
                    "stage_key": sr.get("stage_key"),
                    "status": sr.get("status"),
                }
                for sr in doc.get("stage_runs", [])
            ],
            "saved_at": utc_now().isoformat() if isinstance(utc_now(), datetime) else str(utc_now()),
        }
        ResearchRunRepository.update_fields(run_id, {"checkpoint": checkpoint})

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
    def _write_audit(
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
                "event_id": ResearchEngineOrchestrator._new_id("audit"),
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
    def _doc_to_research_run(doc: dict) -> ResearchRun:
        """将仓库文档转换为 ResearchRun Pydantic 模型。

        Args:
            doc: 仓库中的原始文档。

        Returns:
            ResearchRun 模型实例。
        """
        stage_runs_raw = doc.get("stage_runs", [])
        stage_runs = [
            ResearchStageRun(
                stage_run_id=sr.get("stage_run_id", ""),
                research_run_id=sr.get("research_run_id", ""),
                stage_key=sr.get("stage_key", "PROBLEM_SPEC"),
                status=sr.get("status", "pending"),
                gate=StageGate(**sr["gate"]) if sr.get("gate") else None,
                input_snapshot=sr.get("input_snapshot", {}),
                output_summary=sr.get("output_summary", {}),
                error=sr.get("error"),
                decisions=[
                    StageGateDecision(**d) for d in sr.get("decisions", [])
                ],
                linked_algorithm_runs=sr.get("linked_algorithm_runs", []),
                linked_experiment_runs=sr.get("linked_experiment_runs", []),
                artifact_ids=sr.get("artifact_ids", []),
                checkpoint_data=sr.get("checkpoint_data", {}),
                started_at=sr.get("started_at"),
                finished_at=sr.get("finished_at"),
                created_at=sr.get("created_at", utc_now()),
                updated_at=sr.get("updated_at", utc_now()),
            )
            for sr in stage_runs_raw
        ]

        return ResearchRun(
            run_id=doc.get("run_id", ""),
            project_id=doc.get("project_id"),
            problem_spec_id=doc.get("problem_spec_id", ""),
            execution_decision_id=doc.get("execution_decision_id"),
            campaign_id=doc.get("campaign_id"),
            profile_id=doc.get("profile_id", "fluoropolymer"),
            status=doc.get("status", "draft"),
            current_stage=doc.get("current_stage"),
            stage_runs=stage_runs,
            linked_algorithm_runs=doc.get("linked_algorithm_runs", []),
            linked_experiment_runs=doc.get("linked_experiment_runs", []),
            checkpoint=doc.get("checkpoint", {}),
            summary=doc.get("summary", {}),
            max_iterations=doc.get("max_iterations", 5),
            batch_size=doc.get("batch_size", 10),
            created_by=doc.get("created_by", "system"),
            owner_id=doc.get("owner_id"),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
            started_at=doc.get("started_at"),
            finished_at=doc.get("finished_at"),
        )
