"""能力中心只读聚合服务。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from app.core.time import utc_now
from app.schemas.agent_exec import AgentExecProviderReadiness
from app.schemas.attribution import AttributionItem
from app.schemas.capabilities import (
    CapabilityCatalogData,
    CapabilityCatalogGroup,
    CapabilityCatalogItem,
    CapabilityInvocation,
    CapabilityPolicySummary,
)
from app.schemas.llm_models import LLMModelCatalogData, LLMProviderInfo
from app.schemas.reports import ReportReadinessData
from app.services.agent_exec_service import AgentExecService
from app.services.agent_tool_service import AgentToolService
from app.services.llm_model_service import LLMModelService
from app.services.report_service import SUPPORTED_PIPELINES, ReportService
from app.services.report_skill_orchestrator import ReportSkillOrchestrator


REPORT_PIPELINE_DESCRIPTIONS = {
    "nature_research_report_zh": "生成中文科研运行总结报告。",
    "nature_research_report_with_citations_zh": "生成包含文献背景与引用整理的中文科研报告。",
    "nature_research_report_with_figures_zh": "生成包含图表数据的中文科研报告。",
    "research_run_failure_analysis_zh": "生成科研运行失败原因分析报告。",
}

REPORT_PROVIDER_LABELS = {
    "codex_exec": "Codex CLI",
    "openai_compatible": "OpenAI-compatible provider",
    "openai_responses": "OpenAI Responses API",
    "local_ollama": "Ollama",
    "custom_http": "Custom HTTP provider",
    "mock": "PolyAgent Mock provider",
}

LLM_PROVIDER_LABELS = {
    "openai_compatible": "OpenAI-compatible provider",
    "ollama": "Ollama",
    "custom_http": "Custom HTTP provider",
}


class CapabilityCatalogService:
    """从各模块事实源实时构建只读能力目录。"""

    def __init__(
        self,
        *,
        agent_tool_service: AgentToolService | None = None,
        agent_exec_service: AgentExecService | None = None,
        report_service: ReportService | None = None,
        llm_model_service: LLMModelService | None = None,
    ) -> None:
        self.agent_tool_service = agent_tool_service or AgentToolService()
        self.agent_exec_service = agent_exec_service or AgentExecService()
        self.report_service = report_service or ReportService()
        self.llm_model_service = llm_model_service or LLMModelService()

    def get_catalog(self, current_user: dict[str, str] | None) -> CapabilityCatalogData:
        """构建当前用户可见的能力中心目录。

        Args:
            current_user: 当前登录用户；本地演示模式为空并按管理员处理。

        Returns:
            四个固定能力分组组成的安全目录。
        """
        role = "admin" if not current_user else str(current_user.get("role") or "user")
        if role not in {"admin", "user"}:
            role = "user"
        is_admin = role == "admin"
        return CapabilityCatalogData(
            generated_at=utc_now(),
            viewer_role=role,  # type: ignore[arg-type]
            is_admin=is_admin,
            dialogue_tools=self._safe_group(
                "dialogue_tools",
                lambda: self._dialogue_group(current_user, role=role, is_admin=is_admin),
            ),
            agent_connectors=self._safe_group(
                "agent_connectors",
                lambda: self._agent_connector_group(role=role, is_admin=is_admin),
            ),
            report_skills=self._safe_group(
                "report_skills",
                lambda: self._report_skill_group(is_admin=is_admin),
            ),
            llm_capabilities=self._safe_group(
                "llm_capabilities",
                lambda: self._llm_group(is_admin=is_admin),
            ),
        )

    def _safe_group(
        self,
        group_id: str,
        builder: Callable[[], CapabilityCatalogGroup],
    ) -> CapabilityCatalogGroup:
        """隔离单个事实源异常，避免一个模块失败阻断整个目录。

        Args:
            group_id: 固定分组 ID。
            builder: 分组构建函数。

        Returns:
            正常分组或安全降级后的 unavailable 分组。
        """
        try:
            return builder()
        except Exception as exc:
            return self._unavailable_group(group_id, f"能力源读取失败：{type(exc).__name__}")

    def _dialogue_group(
        self,
        current_user: dict[str, str] | None,
        *,
        role: str,
        is_admin: bool,
    ) -> CapabilityCatalogGroup:
        """从算法工具事实源构建对话工具目录。

        Args:
            current_user: 当前用户上下文。
            role: 当前角色。
            is_admin: 是否管理员。

        Returns:
            对话工具能力分组。
        """
        raw_items = (
            self.agent_tool_service.list_registry().items
            if is_admin
            else self.agent_tool_service.list_tools(current_user).items
        )
        items = [self._dialogue_item(item, role=role, is_admin=is_admin) for item in raw_items]
        return self._group(
            "dialogue_tools",
            "对话工具",
            "从研发引擎派生并可进入问答对话调用的算法工具。",
            items,
        )

    @staticmethod
    def _dialogue_item(item: Any, *, role: str, is_admin: bool) -> CapabilityCatalogItem:
        """把算法工具目录项转换为脱敏能力卡片。

        Args:
            item: AgentTool 或 AgentToolRegistryItem。
            role: 当前用户角色。
            is_admin: 是否管理员。

        Returns:
            对话工具能力卡片。
        """
        policy = item.policy
        enabled = bool(policy.enabled)
        status = "available" if enabled and item.phase == "available" else (
            "disabled" if not enabled else "unavailable"
        )
        can_invoke = status == "available" and role in policy.allowed_roles
        attributions = [
            item.developer_attribution,
            *item.framework_attributions,
            *item.method_attributions,
        ]
        return CapabilityCatalogItem(
            id=str(item.tool_id),
            name=str(item.name),
            description=str(item.description or item.tool_id),
            module_id="agent-tools",
            status=status,  # type: ignore[arg-type]
            reason=str(item.unavailable_reason or "") or None if status != "available" else None,
            policy=CapabilityPolicySummary(
                allowed_roles=list(policy.allowed_roles),
                requires_confirmation=bool(policy.requires_confirmation),
                viewer_can_invoke=can_invoke,
                scope_note="公开工具全员可见；私有工具仅 owner 和管理员可见。",
            ),
            invocation=CapabilityInvocation(
                kind="dialogue_tool",
                method="navigate",
                target=f"/dialogue?{urlencode({'toolIds': item.tool_id})}",
            ),
            config_path="/tools?tab=agent-tools" if is_admin else "",
            attributions=[source for source in attributions if source],
        )

    def _agent_connector_group(self, *, role: str, is_admin: bool) -> CapabilityCatalogGroup:
        """从 Plan 15 provider registry 构建外部连接器目录。

        Args:
            role: 当前用户角色。
            is_admin: 是否管理员。

        Returns:
            外部 Agent 连接器分组。
        """
        items: list[CapabilityCatalogItem] = []
        for provider in self.agent_exec_service.registry.list_providers():
            policy = self.agent_exec_service.policy_service.get_policy(provider.provider_id)
            if not is_admin and not (policy.enabled and role in policy.allowed_roles):
                continue
            readiness = provider.readiness()
            items.append(
                self._agent_connector_item(
                    provider,
                    readiness=readiness,
                    policy=policy,
                    role=role,
                    is_admin=is_admin,
                )
            )
        return self._group(
            "agent_connectors",
            "外部 Agent 连接器",
            "由 Plan 15 安全内核治理的受控结构化文件任务入口。",
            items,
        )

    @staticmethod
    def _agent_connector_item(
        provider: Any,
        *,
        readiness: AgentExecProviderReadiness,
        policy: Any,
        role: str,
        is_admin: bool,
    ) -> CapabilityCatalogItem:
        """把外部 provider 组装为脱敏能力卡片。

        Args:
            provider: provider 实例。
            readiness: provider readiness。
            policy: provider 调用策略。
            role: 当前用户角色。
            is_admin: 是否管理员。

        Returns:
            外部连接器能力卡片。
        """
        if not policy.enabled:
            status = "disabled"
            reason = "连接器策略未启用"
        elif not readiness.available:
            status = "unavailable"
            reason = readiness.message or readiness.reason_code or "provider 未就绪"
        else:
            status = "available"
            reason = None
        requires_confirmation = bool(policy.requires_confirmation) or role == "user"
        can_invoke = status == "available" and role in policy.allowed_roles
        source_name = "Codex CLI" if str(provider.provider_id) == "codex" else str(provider.display_name)
        return CapabilityCatalogItem(
            id=str(provider.provider_id),
            name=str(provider.display_name),
            description=str(getattr(provider, "description", "") or provider.provider_id),
            module_id="agent-exec",
            status=status,  # type: ignore[arg-type]
            reason=reason,
            policy=CapabilityPolicySummary(
                allowed_roles=list(policy.allowed_roles),
                requires_confirmation=requires_confirmation,
                viewer_can_invoke=can_invoke,
                scope_note="普通用户即使策略免确认，也必须逐次显式确认。",
            ),
            invocation=CapabilityInvocation(
                kind="agent_connector",
                method="api",
                target="agent-exec/runs",
            ),
            config_path="/tools?tab=agent-connectors" if is_admin else "",
            attributions=[
                AttributionItem(
                    name=source_name,
                    role="implementation_source",
                    description=str(getattr(provider, "attribution", "") or source_name),
                    visibility="prominent",
                )
            ],
        )

    def _report_skill_group(self, *, is_admin: bool) -> CapabilityCatalogGroup:
        """从服务端 pipeline allowlist 构建报告 Skill 目录。

        Args:
            is_admin: 是否管理员。

        Returns:
            报告 Skill 能力分组。
        """
        readiness = self.report_service.get_readiness()
        items = [
            self._report_skill_item(pipeline_id, readiness=readiness, is_admin=is_admin)
            for pipeline_id in sorted(SUPPORTED_PIPELINES)
        ]
        if not is_admin:
            items = [item for item in items if item.status == "available"]
        return self._group(
            "report_skills",
            "报告 Skill",
            "仅展示服务端声明的报告 pipeline 与 skill allowlist。",
            items,
        )

    def _report_skill_item(
        self,
        pipeline_id: str,
        *,
        readiness: ReportReadinessData,
        is_admin: bool,
    ) -> CapabilityCatalogItem:
        """构建一个报告 pipeline 的安全能力卡片。

        Args:
            pipeline_id: 服务端 pipeline ID。
            readiness: 报告模块 readiness。
            is_admin: 是否管理员。

        Returns:
            报告 Skill 能力卡片。
        """
        warnings: list[str] = []
        allowed = True
        try:
            plan = ReportSkillOrchestrator().build_plan(
                report_request={"skill_pipeline_id": pipeline_id, "scope": {}},
                context={"subject": {"subject_type": "readiness", "subject_id": "readiness"}},
            )
            skill_ids = [str(step.get("skill_id")) for step in plan.get("steps", [])]
        except Exception as exc:
            allowed = False
            skill_ids = []
            warnings.append(f"allowlist 校验失败：{type(exc).__name__}")
        if not readiness.reports_enabled:
            status = "disabled"
            warnings.insert(0, "报告功能未启用")
        elif not (readiness.provider_ready and readiness.skill_pipeline_ready and allowed):
            status = "unavailable"
            warnings.extend(readiness.warnings)
        else:
            status = "available"
        reason = "；".join(dict.fromkeys(item for item in warnings if item)) or None
        source_name = REPORT_PROVIDER_LABELS.get(readiness.provider, readiness.provider)
        item = CapabilityCatalogItem(
            id=pipeline_id,
            name=REPORT_PIPELINE_DESCRIPTIONS.get(pipeline_id, pipeline_id),
            description=f"步骤：{', '.join(skill_ids) if skill_ids else '未解析'}",
            module_id="reports",
            status=status,  # type: ignore[arg-type]
            reason=reason,
            policy=CapabilityPolicySummary(
                allowed_roles=["admin", "user"],
                requires_confirmation=False,
                viewer_can_invoke=status == "available",
                scope_note="只使用服务端 pipeline；不读取或安装本地 Skill。",
            ),
            invocation=CapabilityInvocation(
                kind="report_skill",
                method="navigate",
                target=f"/research-engine?{urlencode({'skillPipelineId': pipeline_id})}",
            ),
            config_path="/tools?tab=status" if is_admin else "",
            attributions=[
                AttributionItem(
                    name=source_name,
                    role="dependency",
                    description="报告 pipeline 的外部模型或执行能力来源。",
                    visibility="prominent",
                )
            ],
        )
        if not is_admin and status != "available":
            return item.model_copy(update={"policy": item.policy.model_copy(update={"viewer_can_invoke": False})})
        return item

    def _llm_group(self, *, is_admin: bool) -> CapabilityCatalogGroup:
        """从脱敏 LLM 目录构建模型能力分组。

        Args:
            is_admin: 是否管理员。

        Returns:
            LLM 能力分组。
        """
        catalog: LLMModelCatalogData = self.llm_model_service.get_catalog(probe=False)
        items = [
            self._llm_item(
                provider,
                model_id=str(model.model_id),
                display_name=str(model.display_name),
                is_admin=is_admin,
            )
            for provider in catalog.providers
            for model in provider.models
        ]
        if not is_admin:
            items = [item for item in items if item.status in {"available", "degraded"}]
        return self._group(
            "llm_capabilities",
            "LLM 能力",
            "面向问答与报告路由的脱敏 provider 与模型能力。",
            items,
        )

    @staticmethod
    def _llm_item(
        provider: LLMProviderInfo,
        *,
        model_id: str,
        display_name: str,
        is_admin: bool,
    ) -> CapabilityCatalogItem:
        """构建一个 LLM 模型能力卡片。

        Args:
            provider: 脱敏 provider 元数据。
            model_id: 模型 ID。
            display_name: 模型展示名。
            is_admin: 是否管理员。

        Returns:
            LLM 能力卡片。
        """
        if provider.status == "available":
            status = "available"
            reason = None
        elif provider.status == "degraded":
            status = "degraded"
            reason = "；".join(provider.warnings) or "provider 处于降级状态"
        elif provider.status == "not_configured":
            status = "disabled"
            reason = "；".join(provider.warnings) or "provider 未配置"
        else:
            status = "unavailable"
            reason = "；".join(provider.warnings) or "provider 不可用"
        source_name = LLM_PROVIDER_LABELS.get(provider.provider_type, provider.display_name)
        return CapabilityCatalogItem(
            id=f"{provider.provider_id}:{model_id}",
            name=f"{provider.display_name} / {display_name}",
            description="模型路由能力，用于问答、深度分析、报告与摘要。",
            module_id="llm-models",
            status=status,  # type: ignore[arg-type]
            reason=reason,
            policy=CapabilityPolicySummary(
                allowed_roles=["admin", "user"],
                requires_confirmation=False,
                viewer_can_invoke=status in {"available", "degraded"},
                scope_note="provider 配置保持脱敏；模型选择进入问答对话。",
            ),
            invocation=CapabilityInvocation(
                kind="llm_model",
                method="navigate",
                target=f"/dialogue?{urlencode({'providerId': provider.provider_id, 'modelId': model_id})}",
            ),
            config_path="/tools?tab=llm-models" if is_admin else "",
            attributions=[
                AttributionItem(
                    name=source_name,
                    role="dependency",
                    description="模型服务协议或运行时来源。",
                    visibility="prominent",
                )
            ],
        )

    @staticmethod
    def _group(
        group_id: str,
        title: str,
        description: str,
        items: list[CapabilityCatalogItem],
    ) -> CapabilityCatalogGroup:
        """聚合一组能力卡片状态。

        Args:
            group_id: 固定分组 ID。
            title: 分组标题。
            description: 分组说明。
            items: 分组内卡片。

        Returns:
            聚合后的能力分组。
        """
        available_count = sum(1 for item in items if item.status == "available")
        invocable_count = sum(
            1 for item in items if item.status == "available" and item.policy.viewer_can_invoke
        )
        if items and available_count == len(items):
            status = "available"
            reason = None
        elif available_count:
            status = "partial"
            reason = "部分能力当前不可用"
        else:
            status = "unavailable"
            reason = "当前没有可用能力" if items else "该能力源暂无条目"
        return CapabilityCatalogGroup(
            group_id=group_id,  # type: ignore[arg-type]
            title=title,
            description=description,
            status=status,  # type: ignore[arg-type]
            total_count=len(items),
            invocable_count=invocable_count,
            unavailable_reason=reason,
            items=items,
        )

    @staticmethod
    def _unavailable_group(group_id: str, reason: str) -> CapabilityCatalogGroup:
        """构建读取失败时的安全降级分组。

        Args:
            group_id: 固定分组 ID。
            reason: 不包含内部细节的原因摘要。

        Returns:
            unavailable 分组。
        """
        return CapabilityCatalogGroup(
            group_id=group_id,  # type: ignore[arg-type]
            title={
                "dialogue_tools": "对话工具",
                "agent_connectors": "外部 Agent 连接器",
                "report_skills": "报告 Skill",
                "llm_capabilities": "LLM 能力",
            }.get(group_id, group_id),
            description="该分组读取失败，已与其他能力源隔离。",
            status="unavailable",
            total_count=0,
            invocable_count=0,
            unavailable_reason=reason,
            items=[],
        )
