"""AutoResearch startup readiness checks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.research_engine import (
    CapabilityLevel,
    ResearchEngineReadinessData,
    ResearchEngineReadinessItem,
    ResearchEngineStageReadiness,
)
from app.services.integration_status_service import IntegrationStatusService
from app.services.knowledge_service import KnowledgeService
from app.services.llm_model_service import LLMModelService


class ResearchEngineReadinessService:
    """Build a product-facing readiness summary for AutoResearch."""

    def get_readiness(self) -> ResearchEngineReadinessData:
        checked_at = datetime.now(timezone.utc)
        integration_items = IntegrationStatusService().get_status().get("items", [])
        by_service = {str(item.get("service")): item for item in integration_items}

        rag_item = self._rag_readiness()
        computation_item = self._integration_readiness(
            by_service.get("computation-worker"),
            service="computation-engine",
            label="计算引擎",
            capability_id="computation-engine",
            required=True,
            up_statuses={"up", "available", "built_in"},
            unavailable_message="计算 Worker 不可用，AutoResearch 无法提交计算任务。",
            next_action="启动 computation worker 或检查 worker 进程。",
        )
        alchemist_item = self._integration_readiness(
            by_service.get("alchemist-backend"),
            service="alchemist-backend",
            label="BO/Alchemist",
            capability_id="mobo_alchemist_adapter",
            required=False,
            demo_fallback=True,
            up_statuses={"up", "available", "built_in"},
            unavailable_message="Alchemist 未连接，候选推荐将使用 demo fallback。",
            next_action="确认 Alchemist 内置模块或外部优化服务可用。",
        )
        artifact_item = self._integration_readiness(
            by_service.get("artifact-store"),
            service="artifact-store",
            label="Artifact Store",
            capability_id="artifact-store",
            required=True,
            up_statuses={"up", "available", "built_in"},
            unavailable_message="Artifact Store 不可用，运行产物无法保存。",
            next_action="检查 POLY_AGENT_OUTPUT_ROOT 或对象存储挂载。",
        )
        llm_item = self._llm_readiness()
        items = [
            rag_item,
            computation_item,
            alchemist_item,
            artifact_item,
            llm_item,
        ]
        can_start = all(not item.blocking for item in items)
        return ResearchEngineReadinessData(
            ready=all(item.status == "ready" for item in items),
            can_start=can_start,
            checked_at=checked_at,
            items=items,
            stage_modes=self._stage_modes(
                rag=rag_item,
                computation=computation_item,
                alchemist=alchemist_item,
                llm=llm_item,
                speclabos_configured=bool(
                    by_service.get("speclabos", {}).get("status") == "available"
                ),
            ),
        )

    def _integration_readiness(
        self,
        raw: dict[str, Any] | None,
        *,
        service: str,
        label: str,
        capability_id: str,
        required: bool,
        up_statuses: set[str],
        unavailable_message: str,
        next_action: str,
        demo_fallback: bool = False,
    ) -> ResearchEngineReadinessItem:
        raw_status = str((raw or {}).get("status") or "unknown")
        is_ready = raw_status in up_statuses
        status = "ready" if is_ready else ("warning" if demo_fallback else "unavailable")
        item_demo_fallback = demo_fallback and not is_ready
        return ResearchEngineReadinessItem(
            service=service,
            label=label,
            status=status,
            capability_id=capability_id,
            level=self._capability_level(
                configured=is_ready or raw_status not in {"unknown", "not_configured", "not_available"},
                healthy=is_ready,
                demo_fallback=item_demo_fallback,
            ),
            required=required,
            blocking=required and not is_ready,
            demo_fallback=item_demo_fallback,
            configured=is_ready or raw_status not in {"unknown", "not_configured", "not_available"},
            healthy=is_ready,
            execution_mode="adapter" if is_ready else ("demo_fallback" if item_demo_fallback else "not_configured"),
            fallback_reason=None if is_ready else unavailable_message,
            next_action=None if is_ready else next_action,
            message="可用" if is_ready else unavailable_message,
            details={
                "integration_status": raw_status,
                **dict((raw or {}).get("details") or {}),
            },
        )

    def _rag_readiness(self) -> ResearchEngineReadinessItem:
        health = KnowledgeService().health()
        details: dict[str, Any] = {"systems": health.systems}
        if health.configured:
            healthy = health.status == "ready"
            return ResearchEngineReadinessItem(
                service="literature-rag",
                label="知识库 RAG",
                status="ready" if healthy else "warning",
                capability_id="literature-rag",
                level=self._capability_level(
                    configured=True,
                    healthy=healthy,
                    demo_fallback=health.demo_available and not healthy,
                ),
                required=False,
                blocking=False,
                demo_fallback=health.demo_available and not healthy,
                configured=True,
                healthy=healthy,
                provider=health.backend,
                execution_mode="adapter" if healthy else "demo_fallback",
                fallback_reason=None if healthy else health.message,
                next_action=None if healthy else "检查 Literature RAG corpus 与图谱索引状态。",
                message=health.message,
                details=details,
            )
        return ResearchEngineReadinessItem(
            service="literature-rag",
            label="知识库 RAG",
            status="warning",
            capability_id="literature-rag",
            level=self._capability_level(
                configured=False,
                healthy=False,
                demo_fallback=health.demo_available,
            ),
            required=False,
            blocking=False,
            demo_fallback=health.demo_available,
            configured=False,
            healthy=False,
            provider=health.backend,
            execution_mode="demo_fallback" if health.demo_available else "not_configured",
            fallback_reason=health.message,
            next_action="配置 LITERATURE_RAG_BASE_URL 和查询 API key，或启动本地 RAG 服务。",
            message=health.message,
            details=details,
        )

    def _llm_readiness(self) -> ResearchEngineReadinessItem:
        try:
            catalog = LLMModelService().get_catalog(probe=False)
            routing = catalog.routing.get("deep") or catalog.routing.get("qa") or {}
            provider_id = str(routing.get("provider_id") or "")
            model_id = str(routing.get("model_id") or "")
            provider = next((item for item in catalog.providers if item.provider_id == provider_id), None)
            configured = bool(provider and model_id)
            healthy = bool(provider and provider.status == "available")
            status = "ready" if healthy else ("warning" if configured else "warning")
            return ResearchEngineReadinessItem(
                service="research-llm",
                label="AutoResearch AI 模型",
                status=status,
                capability_id="research-llm",
                level=self._capability_level(
                    configured=configured,
                    healthy=healthy,
                    demo_fallback=not configured,
                ),
                required=False,
                blocking=False,
                demo_fallback=not configured,
                configured=configured,
                healthy=healthy,
                provider=provider_id or None,
                model=model_id or None,
                execution_mode="llm" if configured else "demo_fallback",
                fallback_reason=None if configured else "LLM provider/model 未配置",
                next_action=None if configured else "配置 `backend/config/llm.providers.json`、`LLM_PROVIDER_CONFIGS_FILE` 或旧版 `LLM_PROVIDER_CONFIGS_JSON`。",
                message="AI 模型已配置，连通性待模型检查确认。" if configured else "AI 模型未配置，AutoResearch 将保留 demo/mock 路径提示。",
                details={
                    "provider_status": provider.status if provider else "not_configured",
                    "warnings": catalog.warnings,
                },
            )
        except Exception as exc:
            return ResearchEngineReadinessItem(
                service="research-llm",
                label="AutoResearch AI 模型",
                status="warning",
                capability_id="research-llm",
                level="unavailable",
                required=False,
                blocking=False,
                demo_fallback=True,
                configured=False,
                healthy=False,
                execution_mode="demo_fallback",
                fallback_reason=str(exc),
                next_action="检查 LLM 模型路由配置。",
                message=f"AI 模型状态检查失败：{type(exc).__name__}",
                details={"error": str(exc)},
            )

    def _stage_modes(
        self,
        *,
        rag: ResearchEngineReadinessItem,
        computation: ResearchEngineReadinessItem,
        alchemist: ResearchEngineReadinessItem,
        llm: ResearchEngineReadinessItem,
        speclabos_configured: bool,
    ) -> list[ResearchEngineStageReadiness]:
        return [
            self._stage("PROBLEM_SPEC", "任务定义审批", "human_gate", "human_approval", "production_ready"),
            self._stage_from_item("KNOWLEDGE_RETRIEVAL", "知识检索", rag),
            self._stage("STRUCTURE_FEATURE", "结构特征生成", "polymer_descriptor_mock", "mock_fallback", "demo_fallback", demo=True, reason="P0 阶段仍使用内置描述符 mock runner。"),
            self._stage_from_item("COMPUTE_PREDICT", "计算/预测", computation, capability_id="computation_submit_adapter"),
            self._stage_from_item("RECOMMENDATION_ASK", "候选推荐", alchemist),
            self._stage("HUMAN_REVIEW", "候选人工评审", "human_gate", "human_approval", "production_ready"),
            self._stage(
                "EXPERIMENT_EXECUTION",
                "实验执行",
                "speclabos",
                "external_experiment_dispatch" if speclabos_configured else "not_configured",
                "configured_pending_verification" if speclabos_configured else "not_configured",
                reason=(
                    "已支持将实验批次下发至 SpecLabOS 并接收登记；"
                    "真实设备执行与结果回填待接入。"
                    if speclabos_configured
                    else "未配置 SpecLabOS 外部实验任务下发。"
                ),
            ),
            self._stage("RESULT_TELL", "结果回填", "manual_observation", "manual_or_adapter", "configured_pending_verification"),
            self._stage("MODEL_UPDATE", "模型更新", "research-llm", "llm" if llm.configured else "demo_fallback", llm.level, provider=llm.provider, model=llm.model, demo=llm.demo_fallback, reason=llm.fallback_reason),
            self._stage("ARCHIVE_LEARNING", "归档学习", "traceability", "system", "production_ready"),
        ]

    def _stage_from_item(
        self,
        stage_key: str,
        label: str,
        item: ResearchEngineReadinessItem,
        *,
        capability_id: str | None = None,
    ) -> ResearchEngineStageReadiness:
        return self._stage(
            stage_key,
            label,
            capability_id or item.capability_id or item.service,
            item.execution_mode or ("adapter" if item.healthy else "demo_fallback"),
            item.level,
            provider=item.provider,
            model=item.model,
            demo=item.demo_fallback,
            reason=item.fallback_reason,
        )

    @staticmethod
    def _stage(
        stage_key: str,
        label: str,
        capability_id: str,
        execution_mode: str,
        level: CapabilityLevel,
        *,
        provider: str | None = None,
        model: str | None = None,
        demo: bool = False,
        reason: str | None = None,
    ) -> ResearchEngineStageReadiness:
        return ResearchEngineStageReadiness(
            stage_key=stage_key,  # type: ignore[arg-type]
            label=label,
            capability_id=capability_id,
            execution_mode=execution_mode,
            level=level,
            provider=provider,
            model=model,
            demo_fallback=demo,
            fallback_reason=reason,
        )

    @staticmethod
    def _capability_level(*, configured: bool, healthy: bool, demo_fallback: bool) -> CapabilityLevel:
        if healthy:
            return "production_ready"
        if demo_fallback:
            return "demo_fallback"
        if configured:
            return "configured_pending_verification"
        return "not_configured"
