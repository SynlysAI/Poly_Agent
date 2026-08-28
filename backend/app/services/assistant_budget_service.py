"""LUI 动态计算预算分类、路由与观测服务。"""

from __future__ import annotations

import hashlib
import math
import time
from collections import Counter
from typing import Any, Mapping

from app.core.config import settings
from app.schemas.assistant_budget import (
    AssistantBudgetDecision,
    AssistantClassificationCategory,
    AssistantEvidenceNeed,
    AssistantModelPurpose,
    AssistantModelTier,
    AssistantQueryComplexity,
    AssistantRetrievalTier,
    AssistantRiskLevel,
    AssistantExecutionTier,
    AssistantUserConstraint,
    BudgetCostEstimate,
    ClassificationInput,
    ClassificationResult,
)
from app.services.assistant_presets import (
    get_assistant_preset,
    resolve_assistant_runtime,
)


EXPLICIT_MODEL_ORIGINS = {"user", "url", "chat", ""}
WEB_SIGNAL_KEYWORDS = ("联网", "互联网", "外部证据", "web", "最新", "最近", "论文")


class AssistantBudgetService:
    """提供无额外模型调用的确定性预算决策。"""

    def decide(
        self,
        text: str,
        *,
        preset_id: str | None,
        context: Mapping[str, Any],
        current_user: Mapping[str, Any] | None = None,
    ) -> AssistantBudgetDecision:
        """生成一次请求的预算建议、实际档位与安全兜底。

        Args:
            text: 用户最新问题；仅在本方法内做规则匹配，不原样进入预算事件。
            preset_id: 当前科研 Preset。
            context: Assistant 请求上下文与会话控制状态。
            current_user: 当前用户，用于灰度分组。

        Returns:
            可序列化且可进入 Execution Trace 的预算决策。
        """
        started = time.perf_counter()
        resolved_preset_id, compatibility_mode = resolve_assistant_runtime(
            preset_id,
            str(context.get("mode") or ""),
        )
        preset = get_assistant_preset(resolved_preset_id)
        try:
            classification = self.classify(
                text,
                preset_id=resolved_preset_id,
                context=context,
            )
            fallback_reason = None
        except Exception:
            classification = self._exception_classification(text)
            fallback_reason = "budget_system_exception"

        release_mode = self._release_mode()
        rollout_eligible = release_mode == "enabled" and self._rollout_eligible(
            context=context,
            preset_id=resolved_preset_id,
            current_user=current_user,
        )
        recommended_model_tier = self._model_tier(
            classification,
            allow_simple_downgrade=preset.budget_policy.allow_deep_simple_downgrade,
        )
        recommended_retrieval_tier = self._retrieval_tier(
            classification,
            context,
            preset.budget_policy.retrieval_tiers[classification.category],
        )
        recommended_execution_tier = preset.budget_policy.execution_tiers[classification.category]

        if release_mode == "enabled" and rollout_eligible:
            effective_model_tier = recommended_model_tier
            effective_retrieval_tier = recommended_retrieval_tier
        else:
            effective_model_tier = self._static_model_tier(compatibility_mode)
            effective_retrieval_tier = "vector"
            if release_mode == "shadow":
                fallback_reason = fallback_reason or "shadow_observation"
            elif release_mode == "disabled":
                fallback_reason = fallback_reason or "budget_disabled"
            else:
                fallback_reason = fallback_reason or "rollout_not_eligible"

        # 执行安全底线不跟随影子/灰度开关降档，只映射既有确认与审批链路。
        effective_execution_tier = (
            "planning_verification_human"
            if classification.risk_level in preset.execution_policy.human_risk_levels
            or classification.category in preset.execution_policy.verification_required
            else (
                recommended_execution_tier
                if release_mode == "enabled" and rollout_eligible
                else ("planning" if compatibility_mode == "deep" else "one_shot")
            )
        )
        effective_model_purpose = self._model_purpose(
            effective_model_tier,
            preset.budget_policy.model_purposes,
        )
        recommended_model_purpose = self._model_purpose(
            recommended_model_tier,
            preset.budget_policy.model_purposes,
        )
        user_overrides = self._user_overrides(context)
        safety_guards = self._safety_guards(
            classification=classification,
            context=context,
            user_overrides=user_overrides,
        )

        return AssistantBudgetDecision(
            preset_id=resolved_preset_id,
            compatibility_mode=compatibility_mode,
            release_mode=release_mode,
            rollout_eligible=rollout_eligible,
            classification=classification,
            recommended_model_tier=recommended_model_tier,
            recommended_model_purpose=recommended_model_purpose,
            recommended_retrieval_tier=recommended_retrieval_tier,
            recommended_execution_tier=recommended_execution_tier,
            effective_model_tier=effective_model_tier,
            effective_model_purpose=effective_model_purpose,
            effective_retrieval_tier=effective_retrieval_tier,
            effective_execution_tier=effective_execution_tier,
            user_overrides=user_overrides,
            safety_guards=safety_guards,
            fallback_reason=fallback_reason,
            decision_duration_ms=max(0, math.ceil((time.perf_counter() - started) * 1000)),
            cost=self._cost_estimate(
                effective_model_tier,
                effective_retrieval_tier,
                effective_execution_tier,
            ),
        )

    def classify(
        self,
        text: str,
        *,
        preset_id: str,
        context: Mapping[str, Any],
    ) -> ClassificationResult:
        """用确定性规则和既有会话状态分类查询。

        Args:
            text: 用户最新问题。
            preset_id: 当前科研 Preset。
            context: 请求上下文，可包含工具选择、Plan Mode 与证据冲突状态。

        Returns:
            含置信度、证据需求与风险等级的分类结果。
        """
        payload = self._classification_input(text, preset_id=preset_id, context=context)
        policy = get_assistant_preset(preset_id).classification_policy
        signals = list(payload.signals)
        high_risk = payload.risk_level == "high"
        category: AssistantClassificationCategory = (
            "high_risk" if high_risk else payload.query_complexity
        )
        confidence = min(0.95, 0.58 + 0.09 * max(0, len(signals) - 1))
        fallback_reason = None
        if not signals:
            confidence = 0.45
            category = policy.uncertain_fallback
            fallback_reason = "classification_uncertain"
        elif high_risk:
            confidence = max(confidence, 0.86)
        elif confidence < policy.minimum_confidence:
            category = policy.uncertain_fallback
            fallback_reason = "classification_confidence_below_threshold"

        return ClassificationResult(
            **payload.model_dump(),
            category=category,
            confidence=round(confidence, 2),
            fallback_reason=fallback_reason,
        )

    def aggregate_decisions(self, events: list[Mapping[str, Any]]) -> dict[str, Any]:
        """聚合预算事件，形成灰度观测看板数据。

        Args:
            events: 统一 assistant 事件，支持 `data` 包装或旧扁平结构。

        Returns:
            分类/档位分布、覆盖率、回退率、耗时与成本估算。
        """
        decisions = [self._event_decision(event) for event in events]
        decisions = [item for item in decisions if item]
        total = len(decisions)
        durations = sorted(
            int(item.get("decision_duration_ms") or 0)
            for item in decisions
            if item.get("decision_duration_ms") is not None
        )

        def percentile(fraction: float) -> int | None:
            if not durations:
                return None
            index = min(len(durations) - 1, math.ceil(fraction * len(durations)) - 1)
            return durations[index]

        def distribution(key: str) -> dict[str, int]:
            return dict(Counter(str(item.get(key) or "unknown") for item in decisions))

        fallback_count = sum(bool(item.get("fallback_reason")) for item in decisions)
        override_count = sum(bool(item.get("user_overrides")) for item in decisions)
        return {
            "total_decisions": total,
            "classification_distribution": distribution("classification_category"),
            "model_tier_distribution": distribution("effective_model_tier"),
            "retrieval_tier_distribution": distribution("effective_retrieval_tier"),
            "execution_tier_distribution": distribution("effective_execution_tier"),
            "user_override_coverage": round(override_count / total, 4) if total else None,
            "fallback_rate": round(fallback_count / total, 4) if total else None,
            "decision_duration_p50_ms": percentile(0.50),
            "decision_duration_p95_ms": percentile(0.95),
            "estimated_model_calls": sum(
                int((item.get("cost") or {}).get("estimated_model_calls") or 0)
                for item in decisions
            ),
            "estimated_retrieval_calls": sum(
                int((item.get("cost") or {}).get("estimated_retrieval_calls") or 0)
                for item in decisions
            ),
            "estimated_web_fetch_pages": sum(
                int((item.get("cost") or {}).get("estimated_web_fetch_pages") or 0)
                for item in decisions
            ),
            "release_gate": {
                "comparison_required": True,
                "can_enable": False,
                "reason": "需要同一 Golden Set 的静态路由与预算路由双档 M1-M8 对比",
                "rollback": "效果或安全事故一票否决；立即切回 ASSISTANT_BUDGET_MODE=shadow",
            },
        }

    def _classification_input(
        self,
        text: str,
        *,
        preset_id: str,
        context: Mapping[str, Any],
    ) -> ClassificationInput:
        """构建分类器最小输入摘要。

        Args:
            text: 用户最新问题。
            preset_id: 当前科研 Preset，用于读取策略关键词。
            context: 请求上下文。

        Returns:
            不包含原始用户文本的分类输入。
        """
        normalized = str(text or "").strip().lower()
        preset = get_assistant_preset(preset_id)
        policy = preset.classification_policy
        session_state = dict(context.get("session_state") or {})
        selected_tool_count = len(
            [item for item in (context.get("selected_tool_ids") or []) if str(item)]
        )
        signals: list[str] = []

        has_simple = self._contains_any(normalized, policy.simple_keywords)
        has_complex = self._contains_any(normalized, policy.complex_keywords)
        has_high_risk = (
            self._contains_any(normalized, policy.high_risk_keywords)
            or selected_tool_count > 0
        )
        explainability = self._contains_any(normalized, policy.explainability_keywords)
        prior_conflict = bool(context.get("prior_evidence_conflict"))
        long_query = len(normalized) > 120
        if has_simple:
            signals.append("simple_keyword")
        if has_complex:
            signals.append("complex_keyword")
        if has_high_risk:
            signals.append("high_risk_signal")
        if selected_tool_count:
            signals.append("selected_tools")
        if explainability:
            signals.append("explainability_required")
        if prior_conflict:
            signals.append("prior_evidence_conflict")
        if long_query:
            signals.append("long_query")

        query_complexity: AssistantQueryComplexity = (
            "complex"
            if has_complex or has_high_risk or prior_conflict or long_query
            else ("simple" if has_simple else "complex")
        )
        risk_level: AssistantRiskLevel = (
            "high"
            if has_high_risk
            else ("medium" if "正式报告" in normalized or "方案" in normalized else "low")
        )
        needs_multi_source = (
            has_complex
            or prior_conflict
            or "多来源" in normalized
            or "冲突" in normalized
        )
        evidence_need: AssistantEvidenceNeed = (
            "multi_source_synthesis"
            if needs_multi_source
            else (
                "entry_fact"
                if has_simple and query_complexity == "simple"
                else "grounded_answer"
            )
        )
        user_constraint = self._user_constraint(normalized, context)
        return ClassificationInput(
            query_digest=hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16],
            query_complexity=query_complexity,
            risk_level=risk_level,
            evidence_need=evidence_need,
            explainability_required=explainability,
            user_constraint=user_constraint,
            prior_evidence_conflict=prior_conflict,
            selected_tool_count=selected_tool_count,
            plan_mode=bool(session_state.get("plan_mode")),
            permission_mode=str(session_state.get("permission_mode") or "workspace_write"),
            signals=tuple(signals),
        )

    @staticmethod
    def _exception_classification(text: str) -> ClassificationResult:
        """预算系统异常时的保守分类。"""
        return ClassificationResult(
            query_digest=hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16],
            category="complex",
            confidence=0.0,
            fallback_reason="budget_system_exception",
        )

    @staticmethod
    def _event_decision(event: Mapping[str, Any]) -> dict[str, Any] | None:
        """兼容统一事件与扁平事件并提取预算决策。"""
        if str(event.get("type") or "") != "budget.decision":
            return None
        data = dict(event.get("data") or event)
        classification = dict(data.get("classification") or {})
        return {
            **data,
            "classification_category": classification.get("category"),
        }

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        """判断文本是否包含任一策略关键词。"""
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _user_constraint(text: str, context: Mapping[str, Any]) -> AssistantUserConstraint:
        """解析用户显式或文本中的预算约束。"""
        configured = str(context.get("budget_constraint") or "").strip().lower()
        if configured in {
            "low_latency", "low_cost", "high_quality", "high_explainability", "balanced"
        }:
            return configured  # type: ignore[return-value]
        if "最快" in text or "低延迟" in text:
            return "low_latency"
        if "省钱" in text or "低成本" in text:
            return "low_cost"
        if "高质量" in text or "更准确" in text:
            return "high_quality"
        if "可解释" in text or "给出依据" in text:
            return "high_explainability"
        return "balanced"

    @staticmethod
    def _release_mode() -> str:
        """解析预算发布模式；仅允许服务端配置控制。"""
        configured = str(getattr(settings, "assistant_budget_mode", "shadow")).strip().lower()
        if configured not in {"disabled", "shadow", "enabled"}:
            return "shadow"
        return configured

    def _rollout_eligible(
        self,
        *,
        context: Mapping[str, Any],
        preset_id: str,
        current_user: Mapping[str, Any] | None,
    ) -> bool:
        """按允许用户与稳定哈希分组判断灰度资格。"""
        actor_id = str(
            (current_user or {}).get("user_id")
            or context.get("created_by")
            or context.get("user_id")
            or ""
        )
        allowed_users = set(getattr(settings, "assistant_budget_allowed_user_ids", []) or [])
        if actor_id and actor_id in allowed_users:
            return True
        percent = max(0, min(100, int(getattr(settings, "assistant_budget_rollout_percent", 0))))
        if percent >= 100:
            return True
        if percent <= 0:
            return False
        seed = f"{actor_id}|{context.get('chat_id') or ''}|{preset_id}"
        bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
        return bucket < percent

    @staticmethod
    def _model_tier(
        classification: ClassificationResult,
        *,
        allow_simple_downgrade: bool,
    ) -> AssistantModelTier:
        """按分类与保护条件选择默认模型档位。"""
        if classification.category == "high_risk":
            return "high_risk"
        if classification.category == "simple" and not allow_simple_downgrade:
            return "complex"
        if classification.category == "simple":
            if classification.user_constraint in {"low_latency", "low_cost"}:
                return "simple"
            if classification.explainability_required or classification.prior_evidence_conflict:
                return "complex"
            return "simple"
        if (
            classification.user_constraint == "low_latency"
            and classification.evidence_need != "multi_source_synthesis"
        ):
            return "simple"
        return "complex"

    @staticmethod
    def _retrieval_tier(
        classification: ClassificationResult,
        context: Mapping[str, Any],
        base_tier: AssistantRetrievalTier,
    ) -> AssistantRetrievalTier:
        """按证据需求与用户联网选择调整检索档位。"""
        if base_tier == "vector":
            if classification.prior_evidence_conflict or classification.explainability_required:
                return "hybrid_reranker"
            return "vector"
        if context.get("use_web_search") is False:
            return "hybrid_reranker"
        text_hint = " ".join(str(context.get("task_content") or "").split()).lower()
        if context.get("use_web_search") is True or any(
            keyword in text_hint for keyword in WEB_SIGNAL_KEYWORDS
        ):
            return "hybrid_reranker_web"
        return base_tier

    @staticmethod
    def _static_model_tier(compatibility_mode: str) -> AssistantModelTier:
        """返回当前静态 qa/deep 路由对应档位。"""
        return "complex" if compatibility_mode == "deep" else "simple"

    @staticmethod
    def _model_purpose(
        tier: AssistantModelTier,
        mapping: dict[AssistantModelTier, AssistantModelPurpose],
    ) -> AssistantModelPurpose:
        """把模型档位映射为既有路由用途。"""
        return mapping.get(tier, "deep")

    @staticmethod
    def _user_overrides(context: Mapping[str, Any]) -> tuple[str, ...]:
        """识别不可被预算策略覆盖的用户显式选择。"""
        overrides: list[str] = []
        requested_model = context.get("model")
        origin = str(context.get("model_selection_origin") or "").strip().lower()
        has_requested_model = isinstance(requested_model, dict) and bool(requested_model)
        if has_requested_model and origin in EXPLICIT_MODEL_ORIGINS:
            overrides.append("model")
        if context.get("use_web_search") is not None:
            overrides.append("retrieval_web")
        if context.get("use_knowledge_base") is not None:
            overrides.append("knowledge_base")
        return tuple(overrides)

    @staticmethod
    def _safety_guards(
        *,
        classification: ClassificationResult,
        context: Mapping[str, Any],
        user_overrides: tuple[str, ...],
    ) -> tuple[str, ...]:
        """列出让系统安全策略优先于预算策略的兜底项。"""
        guards = ["rbac_and_tool_policy_priority"]
        if "model" in user_overrides:
            guards.append("user_model_priority")
        if classification.selected_tool_count:
            guards.extend(["tool_confirmation_priority", "human_verification_required"])
        if classification.plan_mode:
            guards.append("plan_mode_policy_priority")
        if classification.permission_mode == "read_only":
            guards.append("read_only_permission_priority")
        if classification.risk_level == "high":
            guards.extend(["high_risk_no_downgrade", "human_verification_required"])
        return tuple(guards)

    @staticmethod
    def _cost_estimate(
        model_tier: AssistantModelTier,
        retrieval_tier: AssistantRetrievalTier,
        execution_tier: AssistantExecutionTier,
    ) -> BudgetCostEstimate:
        """估算模型调用与检索成本；真实 token 后续由 usage 事件覆盖。"""
        model_calls = {"simple": 1, "complex": 2, "high_risk": 3}.get(model_tier, 2)
        if execution_tier == "planning_verification_human":
            model_calls = max(model_calls, 3)
        retrieval_calls = 2 if retrieval_tier.startswith("hybrid") else 1
        web_pages = 3 if retrieval_tier == "hybrid_reranker_web" else 0
        return BudgetCostEstimate(
            estimated_model_calls=model_calls,
            estimated_retrieval_calls=retrieval_calls,
            estimated_web_fetch_pages=web_pages,
        )


assistant_budget_service = AssistantBudgetService()
