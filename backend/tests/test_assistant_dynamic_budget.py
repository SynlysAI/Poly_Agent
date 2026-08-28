"""LUI 动态计算预算与分级路由测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.config import settings
from app.schemas.assistant import AssistantChatRequest
from app.schemas.knowledge import KnowledgeHit
from app.services.assistant_budget_service import assistant_budget_service
from app.services.assistant_presets import (
    ASSISTANT_PRESETS,
    resolve_assistant_runtime,
)
from app.services.assistant_service import AssistantService


def _enabled_budget_context(**overrides):
    """构建启用预算测试所需的显式用户上下文。"""
    context = {
        "preset_id": "research_qa",
        "use_knowledge_base": True,
        "knowledge_base_ids": ["kb-main"],
        "model_selection_origin": "user",
        "model": {"providerId": "provider-a", "modelId": "model-a"},
    }
    context.update(overrides)
    return context


class AssistantDynamicBudgetTest(ComputationTestCase):
    """验证预算契约、保守路由、检索分级与安全兜底。"""

    def test_preset_contract_keeps_mode_and_preset_compatibility(self) -> None:
        for preset_id, preset in ASSISTANT_PRESETS.items():
            with self.subTest(preset_id=preset_id):
                self.assertTrue(preset.classification_policy.simple_keywords)
                self.assertTrue(preset.budget_policy.model_purposes)
                self.assertTrue(preset.execution_policy.human_risk_levels)
                resolved_preset, mode = resolve_assistant_runtime(preset_id, None)
                self.assertEqual(resolved_preset, preset_id)
                self.assertEqual(mode, preset.mode)

    def test_deterministic_classifier_covers_simple_complex_and_high_risk(self) -> None:
        simple = assistant_budget_service.classify(
            "入口在哪里？",
            preset_id="research_qa",
            context={},
        )
        complex_query = assistant_budget_service.classify(
            "请比较两种方法并综合多来源证据",
            preset_id="research_qa",
            context={},
        )
        high_risk = assistant_budget_service.classify(
            "执行算法并把结果提交到正式报告",
            preset_id="research_qa",
            context={"selected_tool_ids": ["algorithm:demo"]},
        )

        self.assertEqual(simple.category, "simple")
        self.assertEqual(complex_query.category, "complex")
        self.assertEqual(complex_query.evidence_need, "multi_source_synthesis")
        self.assertEqual(high_risk.category, "high_risk")
        self.assertEqual(high_risk.risk_level, "high")
        self.assertGreaterEqual(simple.confidence, 0.55)
        self.assertGreaterEqual(complex_query.confidence, 0.55)

    def test_shadow_mode_records_advice_without_changing_default_behavior(self) -> None:
        with patch.object(settings, "assistant_budget_mode", "shadow"):
            decision = assistant_budget_service.decide(
                "请比较两种方法并综合多来源证据",
                preset_id="research_qa",
                context={},
            )

        self.assertEqual(decision.release_mode, "shadow")
        self.assertEqual(decision.recommended_model_purpose, "deep")
        self.assertEqual(decision.recommended_retrieval_tier, "hybrid_reranker")
        self.assertEqual(decision.effective_model_purpose, "qa")
        self.assertEqual(decision.effective_retrieval_tier, "vector")
        self.assertEqual(decision.fallback_reason, "shadow_observation")

    def test_request_context_cannot_force_budget_rollout_mode(self) -> None:
        with patch.object(settings, "assistant_budget_mode", "shadow"):
            decision = assistant_budget_service.decide(
                "请比较两种方法并综合多来源证据",
                preset_id="research_qa",
                context={"evaluation_id": "eval-user", "budget_mode": "enabled"},
            )

        self.assertEqual(decision.release_mode, "shadow")
        self.assertEqual(decision.effective_model_purpose, "qa")

    def test_enabled_mode_upgrades_complex_query_and_keeps_user_model_override(self) -> None:
        with patch.object(settings, "assistant_budget_mode", "enabled"), patch.object(
            settings, "assistant_budget_rollout_percent", 100
        ):
            decision = assistant_budget_service.decide(
                "请比较两种方法并综合多来源证据",
                preset_id="research_qa",
                context=_enabled_budget_context(),
                current_user={"user_id": "budget-user"},
            )

        self.assertEqual(decision.release_mode, "enabled")
        self.assertTrue(decision.rollout_eligible)
        self.assertEqual(decision.effective_model_purpose, "deep")
        self.assertIn("model", decision.user_overrides)
        self.assertIn("user_model_priority", decision.safety_guards)

    def test_high_risk_and_read_only_safety_cannot_be_downgraded(self) -> None:
        with patch.object(settings, "assistant_budget_mode", "enabled"), patch.object(
            settings, "assistant_budget_rollout_percent", 100
        ):
            decision = assistant_budget_service.decide(
                "简单运行算法",
                preset_id="research_deep",
                context=_enabled_budget_context(
                    session_state={"plan_mode": True, "permission_mode": "read_only"}
                ),
            )

        self.assertEqual(decision.effective_model_tier, "high_risk")
        self.assertEqual(
            decision.effective_execution_tier,
            "planning_verification_human",
        )
        self.assertIn("plan_mode_policy_priority", decision.safety_guards)
        self.assertIn("read_only_permission_priority", decision.safety_guards)
        self.assertIn("human_verification_required", decision.safety_guards)

    def test_budget_exception_falls_back_to_static_safe_route(self) -> None:
        with patch.object(
            assistant_budget_service,
            "_classification_input",
            side_effect=RuntimeError("classifier broken"),
        ):
            decision = assistant_budget_service.decide(
                "任意问题",
                preset_id="research_deep",
                context={},
            )

        self.assertEqual(decision.classification.category, "complex")
        self.assertEqual(decision.classification.confidence, 0.0)
        self.assertEqual(decision.fallback_reason, "budget_system_exception")
        self.assertEqual(decision.effective_model_purpose, "deep")
        self.assertEqual(decision.effective_retrieval_tier, "vector")
        self.assertEqual(decision.effective_execution_tier, "planning")

    def test_hybrid_retrieval_merges_channels_and_records_rerank(self) -> None:
        service = AssistantService()
        vector_hits = [
            KnowledgeHit(title="向量结果", snippet="alpha beta", source_id="doc-vector", score=0.80),
            KnowledgeHit(title="关键词结果", snippet="poly agent", source_id="doc-keyword", score=0.20),
        ]
        keyword_hits = [
            KnowledgeHit(title="关键词结果", snippet="poly agent", source_id="doc-keyword", score=0.30),
        ]
        request = AssistantChatRequest.model_validate(
            {"messages": [], "context": _enabled_budget_context(use_web_search=False)}
        )
        with patch.object(settings, "assistant_budget_mode", "enabled"), patch.object(
            settings, "assistant_budget_rollout_percent", 100
        ):
            decision = assistant_budget_service.decide(
                "综合比较 poly agent 的多来源证据",
                preset_id="research_qa",
                context=request.context,
            )
            with patch.object(
                service.knowledge_service,
                "search_hits_many",
                side_effect=[vector_hits, keyword_hits],
            ) as search:
                outcome = service._retrieve_knowledge(
                    "综合比较 poly agent 的多来源证据",
                    request,
                    budget_decision=decision,
                )

        self.assertEqual(search.call_count, 2)
        self.assertEqual(outcome.retrieval_tier, "hybrid_reranker")
        self.assertTrue(outcome.rerank_applied)
        self.assertEqual(outcome.results[0].source_id, "doc-keyword")
        self.assertIsNotNone(outcome.results[0].metadata.get("rerank_score"))
        self.assertIn("keyword", outcome.results[0].metadata.get("retrieval_channels", []))

    def test_keyword_recall_failure_falls_back_to_vector_results(self) -> None:
        service = AssistantService()
        vector_hits = [
            KnowledgeHit(title="向量结果", snippet="alpha", source_id="doc-vector", score=0.90),
        ]
        request = AssistantChatRequest.model_validate(
            {"messages": [], "context": _enabled_budget_context(use_web_search=False)}
        )
        with patch.object(settings, "assistant_budget_mode", "enabled"), patch.object(
            settings, "assistant_budget_rollout_percent", 100
        ):
            decision = assistant_budget_service.decide(
                "综合比较 poly agent 的多来源证据",
                preset_id="research_qa",
                context=request.context,
            )
            with patch.object(
                service.knowledge_service,
                "search_hits_many",
                side_effect=[vector_hits, RuntimeError("keyword backend down")],
            ):
                outcome = service._retrieve_knowledge(
                    "综合比较 poly agent 的多来源证据",
                    request,
                    budget_decision=decision,
                )

        self.assertEqual(outcome.status, "searched")
        self.assertEqual(outcome.retrieval_tier, "hybrid_reranker")
        self.assertFalse(outcome.rerank_applied)
        self.assertEqual(outcome.fallback_reason, "keyword_recall_failed")
        self.assertEqual([item.source_id for item in outcome.results], ["doc-vector"])

    def test_llm_route_uses_budget_purpose_and_remains_user_selected(self) -> None:
        service = AssistantService()
        request = AssistantChatRequest.model_validate(
            {"messages": [], "context": _enabled_budget_context()}
        )
        with patch.object(settings, "assistant_budget_mode", "enabled"), patch.object(
            settings, "assistant_budget_rollout_percent", 100
        ):
            decision = assistant_budget_service.decide(
                "请比较两种方法并综合多来源证据",
                preset_id="research_qa",
                context=request.context,
            )
        resolved_route = {
            "purpose": "deep",
            "route_reason": "user_selected",
            "provider_id": "provider-a",
            "model_id": "model-a",
            "capabilities": ["reasoning"],
        }
        with patch.object(
            service.llm_model_service,
            "resolve_route",
            return_value=resolved_route,
        ) as resolve_route:
            route = service._resolve_llm_route(
                mode="qa",
                request=request,
                preset_id="research_qa",
                budget_decision=decision,
            )

        resolve_route.assert_called_once_with(
            purpose="deep",
            requested_model=request.context["model"],
        )
        self.assertEqual(route["model_tier"], "complex")
        self.assertEqual(route["budget"]["classification"]["category"], "complex")
        self.assertIn("model", route["budget"]["user_overrides"])

    def test_budget_trace_event_is_auditable_and_private(self) -> None:
        with patch.object(settings, "assistant_budget_mode", "shadow"):
            decision = assistant_budget_service.decide(
                "这是一段很长的私有用户输入，请比较多个来源并解释依据",
                preset_id="research_qa",
                context={},
            )
        event = AssistantService._budget_trace_event(
            decision,
            route={"provider_id": "provider-a", "model_id": "model-a"},
        )

        self.assertEqual(event["type"], "budget.decision")
        self.assertEqual(event["release_mode"], "shadow")
        self.assertIn("classification", event)
        self.assertIn("query_digest", event["classification"]["input_summary"])
        self.assertNotIn("这是一段很长的私有用户输入", str(event))
        self.assertNotIn("scratchpad", str(event).lower())

    def test_budget_metrics_aggregate_distributions_and_gate(self) -> None:
        events = [
            {
                "type": "budget.decision",
                "data": {
                    "release_mode": "shadow",
                    "classification": {"category": "complex"},
                    "effective_model_tier": "simple",
                    "effective_retrieval_tier": "vector",
                    "effective_execution_tier": "one_shot",
                    "fallback_reason": "shadow_observation",
                    "cost": {"estimated_retrieval_calls": 1},
                },
            }
        ] * 3
        summary = assistant_budget_service.aggregate_decisions(events)

        self.assertEqual(summary["total_decisions"], 3)
        self.assertEqual(summary["classification_distribution"]["complex"], 3)
        self.assertEqual(summary["retrieval_tier_distribution"]["vector"], 3)
        self.assertEqual(summary["fallback_rate"], 1.0)
        self.assertEqual(summary["estimated_retrieval_calls"], 3)
        self.assertTrue(summary["release_gate"]["comparison_required"])

    def test_execution_trace_projects_budget_decision_without_raw_query(self) -> None:
        from app.services.assistant_trace_service import AssistantTraceProjectionService

        event = {
            "event_id": "asevt_budget",
            "run_id": "asrun_budget",
            "seq": 1,
            "type": "budget.decision",
            "at": "2026-08-28T12:00:00+00:00",
            "data": {
                "release_mode": "shadow",
                "classification": {
                    "input_summary": {"query_digest": "digest"},
                    "category": "complex",
                    "confidence": 0.76,
                },
                "effective_model_tier": "simple",
                "effective_retrieval_tier": "vector",
                "effective_execution_tier": "one_shot",
                "fallback_reason": "shadow_observation",
            },
        }
        steps, warnings = AssistantTraceProjectionService()._project_steps(
            "asrun_budget",
            [event],
            [],
        )

        self.assertEqual(warnings, [])
        step = steps[0]
        self.assertEqual(step.type, "control")
        self.assertEqual(step.title, "动态计算预算")
        self.assertEqual(step.details.result_summary["classification"]["category"], "complex")
        self.assertNotIn("query_digest", str(step.details.result_summary["classification"]))
        self.assertNotIn("private", str(step.details.result_summary).lower())

    def test_budget_replay_cases_cover_plan13_alignment_dimensions(self) -> None:
        case_path = (
            Path(__file__).resolve().parents[1]
            / "evaluation"
            / "lui"
            / "budget-routing-cases.json"
        )
        payload = json.loads(case_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["cases"]), 5)
        with patch.object(settings, "assistant_budget_mode", "enabled"), patch.object(
            settings, "assistant_budget_rollout_percent", 100
        ):
            for case in payload["cases"]:
                with self.subTest(case_id=case["case_id"]):
                    decision = assistant_budget_service.decide(
                        case["query"],
                        preset_id=case["preset_id"],
                        context=case["context"],
                    )
                    expected = case["expected"]
                    self.assertEqual(
                        decision.classification.category,
                        expected["category"],
                    )
                    self.assertEqual(decision.effective_model_tier, expected["model_tier"])
                    if "retrieval_tier" in expected:
                        self.assertEqual(
                            decision.effective_retrieval_tier,
                            expected["retrieval_tier"],
                        )
                    if "execution_tier" in expected:
                        self.assertEqual(
                            decision.effective_execution_tier,
                            expected["execution_tier"],
                        )
                    if "user_overrides" in expected:
                        self.assertEqual(
                            list(decision.user_overrides),
                            expected["user_overrides"],
                        )

    def test_quality_metrics_include_budget_dashboard_and_baseline_gate(self) -> None:
        from app.services.assistant_quality_service import build_quality_metrics

        result = build_quality_metrics(use_cache=False)

        self.assertIn("budget", result)
        self.assertIn("classification_distribution", result["budget"])
        self.assertIn("retrieval_tier_distribution", result["budget"])
        self.assertIn("fallback_rate", result["budget"])
        self.assertIn("offline_baseline", result["budget"])
        self.assertTrue(result["budget"]["release_gate"]["comparison_required"])
