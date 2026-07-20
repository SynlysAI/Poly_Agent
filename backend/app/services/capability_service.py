"""Platform capability readiness aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.capabilities import CapabilityStatus, CapabilityStatusData
from app.schemas.research_engine import CapabilityLevel
from app.services.integration_status_service import IntegrationStatusService
from app.services.knowledge_service import KnowledgeService
from app.services.llm_model_service import LLMModelService
from app.services.report_service import ReportService


READY_STATUSES = {"up", "available", "built_in", "ready"}
CONFIGURED_STATUSES = {"up", "available", "built_in", "ready", "degraded", "down", "disabled"}


class CapabilityService:
    """Build a product-facing capability matrix from existing readiness checks."""

    def get_capabilities(self) -> CapabilityStatusData:
        checked_at = datetime.now(timezone.utc)
        integration_items = IntegrationStatusService().get_status().get("items", [])
        by_service = {str(item.get("service")): item for item in integration_items}
        items: list[CapabilityStatus] = []

        items.append(self._knowledge_capability(checked_at))
        items.append(self._llm_capability(checked_at))
        items.append(self._report_capability(checked_at))
        items.extend(
            [
                self._integration_capability(
                    by_service.get("computation-worker"),
                    checked_at=checked_at,
                    module_id="computation",
                    capability_id="computation-engine",
                    label="计算任务执行",
                    demo_fallback=False,
                    next_action="启动 computation worker 或检查 worker 进程。",
                ),
                self._integration_capability(
                    by_service.get("alchemist-backend"),
                    checked_at=checked_at,
                    module_id="research-engine",
                    capability_id="mobo_alchemist_adapter",
                    label="BO/Alchemist 候选推荐",
                    demo_fallback=True,
                    next_action="确认 Alchemist 内置模块或外部优化服务可用。",
                ),
                self._integration_capability(
                    by_service.get("xtb"),
                    checked_at=checked_at,
                    module_id="computation",
                    capability_id="local_xtb",
                    label="本地 xTB 计算",
                    demo_fallback=True,
                    next_action="在运行环境安装 xTB 并确认 XTB_EXECUTABLE。",
                ),
                self._integration_capability(
                    by_service.get("orca"),
                    checked_at=checked_at,
                    module_id="computation",
                    capability_id="orca_compute_engine_laser",
                    label="ORCA/ComputeEngine Laser",
                    demo_fallback=True,
                    next_action="配置 ORCA 可执行文件、许可证和外部执行器。",
                ),
            ]
        )
        return CapabilityStatusData(checked_at=checked_at, items=items)

    def _integration_capability(
        self,
        raw: dict[str, Any] | None,
        *,
        checked_at: datetime,
        module_id: str,
        capability_id: str,
        label: str,
        demo_fallback: bool,
        next_action: str,
    ) -> CapabilityStatus:
        raw_status = str((raw or {}).get("status") or "not_configured")
        healthy = raw_status in READY_STATUSES
        configured = healthy or raw_status in CONFIGURED_STATUSES or bool((raw or {}).get("details", {}).get("configured"))
        level = self._level(configured=configured, healthy=healthy, demo_fallback=demo_fallback and not healthy)
        return CapabilityStatus(
            module_id=module_id,
            capability_id=capability_id,
            label=label,
            level=level,
            configured=configured,
            healthy=healthy,
            demo_fallback=demo_fallback and not healthy,
            last_checked_at=self._parse_checked_at(raw) or checked_at,
            blocking_reason=None if healthy else str((raw or {}).get("details", {}).get("reason") or ""),
            next_action=None if healthy else next_action,
        )

    def _knowledge_capability(self, checked_at: datetime) -> CapabilityStatus:
        try:
            health = KnowledgeService().health()
            healthy = health.status == "ready" and health.configured
            demo_fallback = bool(health.demo_available and not healthy)
            return CapabilityStatus(
                module_id="knowledge",
                capability_id="literature-rag",
                label="文献 RAG / 知识图谱",
                level=self._level(configured=health.configured, healthy=healthy, demo_fallback=demo_fallback),
                configured=health.configured,
                healthy=healthy,
                demo_fallback=demo_fallback,
                provider=health.backend,
                last_checked_at=checked_at,
                blocking_reason=None if healthy else health.message,
                next_action=None if healthy else "配置 LITERATURE_RAG_BASE_URL 和查询 API key，或确认本地 RAG 服务。",
            )
        except Exception as exc:
            return CapabilityStatus(
                module_id="knowledge",
                capability_id="literature-rag",
                label="文献 RAG / 知识图谱",
                level="unavailable",
                configured=False,
                healthy=False,
                demo_fallback=False,
                last_checked_at=checked_at,
                blocking_reason=f"{type(exc).__name__}: {exc}",
                next_action="检查 Literature RAG 服务配置。",
            )

    def _llm_capability(self, checked_at: datetime) -> CapabilityStatus:
        try:
            catalog = LLMModelService().get_catalog(probe=False)
            routing = catalog.routing.get("qa") or catalog.routing.get("deep") or {}
            provider_id = str(routing.get("provider_id") or "")
            model_id = str(routing.get("model_id") or "")
            provider = next((item for item in catalog.providers if item.provider_id == provider_id), None)
            configured = bool(provider and model_id)
            healthy = bool(provider and provider.status == "available")
            level = self._level(configured=configured, healthy=healthy, demo_fallback=False)
            return CapabilityStatus(
                module_id="research-engine",
                capability_id="research-llm",
                label="AutoResearch AI 模型",
                level=level,
                configured=configured,
                healthy=healthy,
                demo_fallback=not configured,
                provider=provider_id or None,
                model=model_id or None,
                last_checked_at=checked_at,
                blocking_reason=None if configured else "LLM provider/model 未配置",
                next_action=None if configured else "配置 LLM_MODEL/LLM_BASE_URL/LLM_API_KEY 或 LLM_PROVIDER_CONFIGS_JSON。",
            )
        except Exception as exc:
            return CapabilityStatus(
                module_id="research-engine",
                capability_id="research-llm",
                label="AutoResearch AI 模型",
                level="unavailable",
                configured=False,
                healthy=False,
                demo_fallback=True,
                last_checked_at=checked_at,
                blocking_reason=f"{type(exc).__name__}: {exc}",
                next_action="检查 LLM 模型路由配置。",
            )

    def _report_capability(self, checked_at: datetime) -> CapabilityStatus:
        readiness = ReportService().get_readiness()
        healthy = bool(readiness.reports_enabled and readiness.provider_ready and readiness.skill_pipeline_ready)
        configured = bool(readiness.reports_enabled and readiness.provider)
        return CapabilityStatus(
            module_id="reports",
            capability_id="report-generation",
            label="智能报告生成",
            level=self._level(configured=configured, healthy=healthy, demo_fallback=readiness.provider == "mock"),
            configured=configured,
            healthy=healthy,
            demo_fallback=readiness.provider == "mock",
            provider=readiness.provider,
            last_checked_at=checked_at,
            blocking_reason=None if healthy else "; ".join(readiness.warnings),
            next_action=None if healthy else "检查报告 LLM provider、skill pipeline 和 PDF 依赖。",
        )

    @staticmethod
    def _level(*, configured: bool, healthy: bool, demo_fallback: bool) -> CapabilityLevel:
        if healthy:
            return "production_ready"
        if demo_fallback:
            return "demo_fallback"
        if configured:
            return "configured_pending_verification"
        return "not_configured"

    @staticmethod
    def _parse_checked_at(raw: dict[str, Any] | None) -> datetime | None:
        value = (raw or {}).get("checked_at")
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None
