"""Assistant API contract tests."""

from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class AssistantApiTest(ComputationTestCase):
    def _assistant_stream_events(self, payload: dict) -> list[dict]:
        with self.client.stream("POST", "/api/v1/assistant/chat/stream", json=payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = "".join(resp.iter_text())
        events: list[dict] = []
        for line in body.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def test_assistant_chat_project_grounded_uses_llm_and_project_facts(self) -> None:
        with patch("app.core.llm_client.chat", return_value="项目内回答"), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=AssertionError("project grounded question should not search web"),
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "如何查看待审批任务？"},
                    ],
                    "context": {},
                },
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["message"], "ok")
        self.assertEqual(payload["data"]["content"], "项目内回答")
        self.assertEqual(payload["data"]["answer_mode"], "llm_project_grounded")
        self.assertEqual(payload["data"]["answer_scope"], "project")
        self.assertEqual(payload["data"]["retrieval_status"], "not_needed")
        self.assertTrue(payload["data"]["actions"])
        self.assertEqual(
            payload["data"]["actions"][0]["target"],
            "/tasks/center?module_id=research-engine&status=blocked_approval",
        )
        self.assertIn("suggested_questions", payload["data"])

    def test_assistant_chat_hybrid_uses_web_and_project_evidence(self) -> None:
        def fake_search(_service, query: str, *, deep: bool):  # noqa: ANN001
            from app.services.assistant_service import SearchOutcome
            from app.services.assistant_service import WebEvidence

            self.assertIn("Poly Agent", query)
            self.assertIn("Agentic", query)
            self.assertNotIn("怎么", query)
            self.assertNotIn("合成", query)
            self.assertNotIn("synthesis", query.lower())
            self.assertTrue(deep)
            return SearchOutcome(
                status="searched",
                provider="bing_rss",
                query=query,
                results=[
                    WebEvidence(
                        title="Agentic RAG best practices",
                        url="https://example.com/agentic-rag",
                        snippet="A compact overview of hybrid retrieval patterns.",
                        content="Hybrid retrieval combines project facts and external sources.",
                        source="bing_rss",
                        published_at="2026-07-15T00:00:00Z",
                    )
                ],
            )

        def fake_chat(messages, **kwargs):  # noqa: ANN001
            joined = "\n".join(item["content"] for item in messages)
            self.assertIn("ResearchEngine", joined)
            self.assertIn("WEB_EVIDENCE", joined)
            self.assertIn("Agentic RAG best practices", joined)
            return "混合问题的综合答案"

        with patch("app.services.assistant_service.AssistantWebSearchService.search", new=fake_search), patch(
            "app.core.llm_client.chat",
            side_effect=fake_chat,
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "Poly Agent 怎么结合 Agentic RAG 做项目外问答？"},
                    ],
                    "context": {"mode": "deep"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "混合问题的综合答案")
        self.assertEqual(data["answer_mode"], "hybrid_grounded")
        self.assertEqual(data["answer_scope"], "hybrid")
        self.assertEqual(data["retrieval_status"], "searched")
        self.assertTrue(any(ref["type"] == "web" for ref in data["references"]))
        self.assertIn("web_search", data["grounding_facts"])
        self.assertEqual(data["grounding_facts"]["web_search"]["result_count"], 1)

    def test_assistant_chat_can_disable_web_search(self) -> None:
        with patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=AssertionError("web search should be skipped when disabled"),
        ), patch("app.core.llm_client.chat", return_value="离线回答"):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "Poly Agent 怎么结合 Agentic RAG 做项目外问答？"},
                    ],
                    "context": {"mode": "deep", "use_web_search": False},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "离线回答")
        self.assertEqual(data["answer_mode"], "llm_project_grounded")
        self.assertEqual(data["answer_scope"], "project")
        self.assertEqual(data["retrieval_status"], "not_needed")

    def test_assistant_chat_can_force_web_search_for_project_questions(self) -> None:
        def fake_search(_service, query: str, *, deep: bool):  # noqa: ANN001
            from app.services.assistant_service import SearchOutcome
            from app.services.assistant_service import WebEvidence

            self.assertFalse(deep)
            self.assertTrue(query)
            return SearchOutcome(
                status="searched",
                provider="bing_rss",
                query=query,
                results=[
                    WebEvidence(
                        title="ResearchEngine approval workflow",
                        url="https://example.com/researchengine-approval",
                        snippet="Approval workflow notes.",
                        content="ResearchEngine approval workflow notes.",
                        source="bing_rss",
                    )
                ],
            )

        with patch("app.services.assistant_service.AssistantWebSearchService.search", new=fake_search), patch(
            "app.core.llm_client.chat",
            return_value="联网项目回答",
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "如何查看待审批任务？"},
                    ],
                    "context": {"mode": "qa", "use_web_search": True},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "联网项目回答")
        self.assertEqual(data["answer_mode"], "hybrid_grounded")
        self.assertEqual(data["answer_scope"], "hybrid")
        self.assertEqual(data["retrieval_status"], "searched")
        self.assertEqual(data["grounding_facts"]["request_context"]["use_web_search"], True)
        self.assertEqual(data["grounding_facts"]["web_search"]["result_count"], 1)

    def test_assistant_deep_returns_structured_reasoning_summary(self) -> None:
        with patch(
            "app.core.llm_client.chat",
            return_value='{"answer_markdown":"深度回答正文","reasoning_summary":["识别目标约束","结合项目事实形成建议"]}',
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=AssertionError("project grounded question should not search web"),
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "如何查看待审批任务？"},
                    ],
                    "context": {"mode": "deep"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "深度回答正文")
        self.assertEqual(data["reasoning_summary"], ["识别目标约束", "结合项目事实形成建议"])

    def test_assistant_deep_falls_back_when_structured_json_is_missing(self) -> None:
        with patch("app.core.llm_client.chat", return_value="普通深度回答"):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "如何查看待审批任务？"},
                    ],
                    "context": {"mode": "deep"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "普通深度回答")
        self.assertEqual(data["reasoning_summary"], [])

    def test_assistant_deep_streams_reasoning_answer_and_final_response(self) -> None:
        from app.core.config import settings

        calls = []
        original_llm_model = settings.llm_model
        settings.llm_model = "DeepSeek-V4-Flash-w8a8-mtp"

        def fake_stream(messages, **kwargs):  # noqa: ANN001
            calls.append(kwargs)
            joined = "\n".join(item["content"] for item in messages)
            self.assertIn("DEEP_STREAM_RESPONSE_FORMAT", joined)
            yield "深度回答"
            yield "正文"

        try:
            with patch("app.core.llm_client.chat_stream", side_effect=fake_stream, create=True), patch(
                "app.services.assistant_service.AssistantWebSearchService.search",
                side_effect=AssertionError("project grounded question should not search web"),
            ):
                events = self._assistant_stream_events(
                    {
                        "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                        "context": {"mode": "deep"},
                    }
                )
        finally:
            settings.llm_model = original_llm_model

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types[0], "status")
        self.assertIn("reasoning_summary_delta", event_types)
        self.assertIn("answer_delta", event_types)
        self.assertEqual(event_types[-1], "final")
        self.assertEqual("".join(event.get("delta", "") for event in events if event["type"] == "answer_delta"), "深度回答正文")
        final = events[-1]["data"]
        self.assertEqual(final["content"], "深度回答正文")
        self.assertGreaterEqual(len(final["reasoning_summary"]), 2)
        self.assertEqual(calls[0]["purpose"], "deep")
        self.assertTrue(calls[0].get("model"))

    def test_assistant_stream_uses_requested_dialogue_model(self) -> None:
        from app.core.config import settings

        calls = []
        original_llm_model = settings.llm_model
        original_llm_base_url = settings.llm_base_url
        original_llm_api_key = settings.llm_api_key
        original_llm_default_provider = settings.llm_default_provider
        original_llm_default_model = settings.llm_default_model
        original_llm_provider_configs_file = getattr(settings, "llm_provider_configs_file", "")
        original_llm_provider_configs_json = settings.llm_provider_configs_json
        settings.llm_model = "DeepSeek-V4-Flash-w8a8-mtp"
        settings.llm_base_url = "https://fast.example.test/v1"
        settings.llm_api_key = "fast-secret-key"
        settings.llm_default_provider = "default_openai"
        settings.llm_default_model = "DeepSeek-V4-Flash-w8a8-mtp"
        settings.llm_provider_configs_file = ""
        settings.llm_provider_configs_json = "[]"

        def fake_stream(messages, **kwargs):  # noqa: ANN001
            calls.append(kwargs)
            yield "DeepSeek 回答"

        try:
            with patch("app.core.llm_client.chat_stream", side_effect=fake_stream, create=True), patch(
                "app.services.assistant_service.AssistantWebSearchService.search",
                side_effect=AssertionError("project grounded question should not search web"),
            ):
                events = self._assistant_stream_events(
                    {
                        "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                        "context": {
                            "mode": "qa",
                            "model": {
                                "providerId": "default_openai",
                                "modelId": "DeepSeek-V4-Flash-w8a8-mtp",
                            },
                        },
                    }
                )
        finally:
            settings.llm_model = original_llm_model
            settings.llm_base_url = original_llm_base_url
            settings.llm_api_key = original_llm_api_key
            settings.llm_default_provider = original_llm_default_provider
            settings.llm_default_model = original_llm_default_model
            settings.llm_provider_configs_file = original_llm_provider_configs_file
            settings.llm_provider_configs_json = original_llm_provider_configs_json

        self.assertEqual(events[-1]["type"], "final")
        self.assertEqual(calls[0]["purpose"], "qa")
        self.assertEqual(calls[0]["provider_id"], "default_openai")
        self.assertEqual(calls[0]["model"], "DeepSeek-V4-Flash-w8a8-mtp")

    def test_assistant_stream_reports_invalid_requested_model(self) -> None:
        with patch("app.core.llm_client.chat_stream", side_effect=AssertionError("invalid route should not call llm"), create=True):
            events = self._assistant_stream_events(
                {
                    "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                    "context": {
                        "mode": "qa",
                        "model": {
                            "providerId": "missing_provider",
                            "modelId": "missing-model",
                        },
                    },
                }
            )

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "ASSISTANT_STREAM_ERROR")
        self.assertIn("所选 LLM 模型不可用", events[-1]["message"])
        self.assertIn("未知 LLM provider", events[-1]["message"])

    def test_assistant_stream_rejects_partial_requested_model(self) -> None:
        with patch("app.core.llm_client.chat_stream", side_effect=AssertionError("partial route should not call llm"), create=True):
            events = self._assistant_stream_events(
                {
                    "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                    "context": {
                        "mode": "qa",
                        "model": {"providerId": "default_openai"},
                    },
                }
            )

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "ASSISTANT_STREAM_ERROR")
        self.assertIn("providerId 和 modelId 必须同时提供", events[-1]["message"])

    def test_assistant_stream_emits_evidence_for_hybrid_questions(self) -> None:
        def fake_search(_service, query: str, *, deep: bool):  # noqa: ANN001
            from app.services.assistant_service import SearchOutcome
            from app.services.assistant_service import WebEvidence

            self.assertTrue(deep)
            return SearchOutcome(
                status="searched",
                provider="bing_rss",
                query=query,
                results=[
                    WebEvidence(
                        title="Agentic RAG best practices",
                        url="https://example.com/agentic-rag",
                        snippet="Hybrid retrieval patterns.",
                        content="Hybrid retrieval combines project facts and external sources.",
                        source="bing_rss",
                    )
                ],
            )

        with patch("app.services.assistant_service.AssistantWebSearchService.search", new=fake_search), patch(
            "app.core.llm_client.chat_stream",
            return_value=iter(["混合问题答案"]),
            create=True,
        ):
            events = self._assistant_stream_events(
                {
                    "messages": [{"role": "user", "content": "Poly Agent 怎么结合 Agentic RAG 做项目外问答？"}],
                    "context": {"mode": "deep"},
                }
            )

        evidence = next(event for event in events if event["type"] == "evidence")
        self.assertEqual(evidence["status"], "searched")
        self.assertEqual(evidence["references"][0]["type"], "web")
        final = events[-1]["data"]
        self.assertEqual(final["retrieval_status"], "searched")
        self.assertTrue(any(ref["type"] == "web" for ref in final["references"]))

    def test_assistant_stream_can_force_web_search_for_project_questions(self) -> None:
        captured_messages: list[dict] = []

        def fake_stream(messages, **_kwargs):  # noqa: ANN001, ANN003
            captured_messages.extend(messages)
            return iter(["联网项目回答"])

        def fake_search(_service, query: str, *, deep: bool):  # noqa: ANN001
            from app.services.assistant_service import SearchOutcome
            from app.services.assistant_service import WebEvidence

            self.assertFalse(deep)
            self.assertTrue(query)
            return SearchOutcome(
                status="searched",
                provider="bing_rss",
                query=query,
                results=[
                    WebEvidence(
                        title="ResearchEngine approval workflow",
                        url="https://example.com/researchengine-approval",
                        snippet="Approval workflow notes.",
                        content="ResearchEngine approval workflow notes.",
                        source="bing_rss",
                    )
                ],
            )

        with patch("app.services.assistant_service.AssistantWebSearchService.search", new=fake_search), patch(
            "app.core.llm_client.chat_stream",
            side_effect=fake_stream,
            create=True,
        ):
            events = self._assistant_stream_events(
                {
                    "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                    "context": {"mode": "qa", "use_web_search": True},
                }
            )

        event_types = [event["type"] for event in events]
        self.assertIn("status", event_types)
        self.assertIn("context.assembly.started", event_types)
        self.assertIn("retrieval.started", event_types)
        self.assertIn("evidence", event_types)
        self.assertTrue(any(event.get("stage") == "search" for event in events))
        final = events[-1]["data"]
        self.assertEqual(final["content"], "联网项目回答")
        self.assertEqual(final["answer_scope"], "hybrid")
        self.assertEqual(final["retrieval_status"], "searched")
        self.assertEqual(final["grounding_facts"]["request_context"]["use_web_search"], True)
        context_event = next(event for event in events if event.get("type") == "context.assembled")
        self.assertEqual(context_event["manifest"]["request_kind"], "final_answer")
        self.assertEqual(
            context_event["manifest"]["context"]["digest"],
            final["grounding_facts"]["context"]["digest"],
        )
        context_block = next(
            item["content"]
            for item in captured_messages
            if item.get("role") == "system" and "PROJECT_FACTS:" in item.get("content", "")
        )
        self.assertIn("WEB_EVIDENCE:", context_block)
        self.assertIn("CONVERSATION_POLICY:", context_block)

    def test_assistant_stream_returns_error_event_when_llm_stream_fails(self) -> None:
        def failing_stream(*_args, **_kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("stream down")
            yield ""  # pragma: no cover

        with patch("app.core.llm_client.chat_stream", side_effect=failing_stream, create=True):
            events = self._assistant_stream_events(
                {
                    "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                    "context": {"mode": "deep"},
                }
            )

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "ASSISTANT_STREAM_ERROR")
        self.assertIn("stream down", events[-1]["message"])

    def test_assistant_chat_web_grounded_uses_search_results(self) -> None:
        def fake_search(_service, query: str, *, deep: bool):  # noqa: ANN001
            from app.services.assistant_service import SearchOutcome
            from app.services.assistant_service import WebEvidence

            self.assertIn("AI agent", query)
            self.assertIn("web search", query)
            self.assertNotIn("最近", query)
            self.assertNotIn("实践有哪些", query)
            self.assertFalse(deep)
            return SearchOutcome(
                status="searched",
                provider="bing_rss",
                query=query,
                results=[
                    WebEvidence(
                        title="Recent agentic RAG overview",
                        url="https://example.com/agentic-rag-overview",
                        snippet="A current overview of agentic retrieval patterns.",
                        content="Web evidence content.",
                        source="bing_rss",
                        published_at="2026-07-15T00:00:00Z",
                    )
                ],
            )

        with patch("app.services.assistant_service.AssistantWebSearchService.search", new=fake_search), patch(
            "app.core.llm_client.chat",
            return_value="外部问题的综合答案",
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "最近 AI agent 的 web search 实践有哪些？"},
                    ],
                    "context": {"mode": "qa"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "外部问题的综合答案")
        self.assertEqual(data["answer_mode"], "web_grounded")
        self.assertEqual(data["answer_scope"], "web")
        self.assertEqual(data["retrieval_status"], "searched")
        self.assertEqual(data["references"][0]["type"], "web")
        self.assertTrue(data["references"][0]["target"].startswith("https://example.com/"))

    def test_assistant_chat_uses_focused_search_query_for_material_question(self) -> None:
        captured_query = ""

        def fake_search(_service, query: str, *, deep: bool):  # noqa: ANN001
            nonlocal captured_query
            from app.services.assistant_service import SearchOutcome
            from app.services.assistant_service import WebEvidence

            captured_query = query
            self.assertFalse(deep)
            return SearchOutcome(
                status="searched",
                provider="bing_rss",
                query=query,
                results=[
                    WebEvidence(
                        title="High temperature polyimide synthesis",
                        url="https://example.com/polyimide",
                        snippet="Polyimide synthesis and preparation for high heat resistance.",
                        content="Polyimide synthesis uses dianhydrides and diamines.",
                        source="bing_rss",
                    )
                ],
            )

        with patch("app.services.assistant_service.AssistantWebSearchService.search", new=fake_search), patch(
            "app.core.llm_client.chat",
            return_value="高耐热聚酰亚胺回答",
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "我要怎么做一款高耐热聚酰亚胺"},
                    ],
                    "context": {"mode": "qa"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        for noise in ("我", "我要", "怎么", "一款", "做"):
            self.assertNotIn(noise, captured_query)
        self.assertIn("聚酰亚胺", captured_query)
        self.assertIn("polyimide", captured_query.lower())
        self.assertTrue(any(term in captured_query.lower() for term in ("synthesis", "preparation", "合成")))
        self.assertEqual(data["grounding_facts"]["web_search"]["query"], captured_query)
        self.assertEqual(data["grounding_facts"]["web_search"]["original_query"], "我要怎么做一款高耐热聚酰亚胺")
        self.assertIn("query_terms", data["grounding_facts"]["web_search"])

    def test_assistant_chat_falls_back_without_llm(self) -> None:
        with patch("app.core.llm_client.chat", side_effect=RuntimeError("llm unavailable")):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "如何开始一个 ResearchEngine 示例？"},
                    ],
                    "context": {},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertIn("ProblemSpec", data["content"])
        self.assertIn("ExecutionDecision", data["content"])
        self.assertIn("ResearchRun", data["content"])
        self.assertEqual(data["answer_mode"], "fallback")
        self.assertEqual(data["answer_scope"], "project")
        self.assertTrue(any(action["target"] == "/research-engine" for action in data["actions"]))

    def test_assistant_model_questions_use_project_model_facts(self) -> None:
        with patch("app.core.llm_client.chat", side_effect=AssertionError("model management should not call LLM")):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "现在问答使用什么模型？"},
                    ],
                    "context": {"mode": "model"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["answer_scope"], "model")
        self.assertEqual(data["answer_mode"], "fallback")
        self.assertIn("model_management", data["grounding_facts"])
        self.assertTrue(any(action["target"] == "/tools?tab=llm-models" for action in data["actions"]))

    def test_web_search_service_handles_no_results_and_failures(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        try:
            with patch.object(service, "_search_via_bing_rss", return_value=[]):
                no_results = service.search("unlikely query", deep=False)
            self.assertEqual(no_results.status, "no_results")

            with patch.object(service, "_search_via_bing_rss", side_effect=RuntimeError("search down")):
                failed = service.search("unlikely query", deep=False)
            self.assertEqual(failed.status, "failed")
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

    def test_search_query_builder_focuses_polyimide_material_keywords(self) -> None:
        from app.services.assistant_service import AssistantSearchQueryBuilder

        result = AssistantSearchQueryBuilder().build("我要怎么做一款高耐热聚酰亚胺")

        for noise in ("我", "我要", "怎么", "一款", "做"):
            self.assertNotIn(noise, result.query)
            self.assertIn(noise, result.dropped_terms)
        self.assertIn("聚酰亚胺", result.query)
        self.assertIn("polyimide", result.query.lower())
        self.assertTrue(any(term in result.query.lower() for term in ("synthesis", "preparation", "合成")))
        self.assertIn("polyimide", result.query_terms)

    def test_search_query_builder_drops_generic_design_words_for_material_queries(self) -> None:
        from app.services.assistant_service import AssistantSearchQueryBuilder

        result = AssistantSearchQueryBuilder().build("帮我设计一款高耐热聚酰亚胺分子")

        self.assertNotIn("设计", result.query_terms)
        self.assertNotIn("一款", result.query)
        self.assertIn("聚酰亚胺", result.query)
        self.assertIn("polyimide", result.query.lower())
        self.assertIn("设计", result.dropped_terms)

    def test_search_query_builder_expands_generic_new_material_design_question(self) -> None:
        from app.services.assistant_service import AssistantSearchQueryBuilder

        result = AssistantSearchQueryBuilder().build("如何设计新材料")

        self.assertIn("新材料", result.query)
        self.assertIn("new materials", result.query.lower())
        self.assertIn("materials design", result.query.lower())
        self.assertIn("materials discovery", result.query.lower())
        self.assertIn("inverse design", result.query.lower())
        self.assertNotIn("如何", result.query)
        self.assertNotIn("设计", result.query_terms)

    def test_web_search_service_filters_unrelated_results_before_llm_evidence(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService
        from app.services.assistant_service import WebEvidence

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        raw_results = [
            WebEvidence(title="我（汉语汉字）_百度百科", url="https://example.com/me", snippet="我的释义。"),
            WebEvidence(title="欢迎来到 Minecraft 官方网站", url="https://example.com/minecraft", snippet="Minecraft 游戏。"),
            WebEvidence(
                title="High heat resistant polyimide synthesis",
                url="https://example.com/polyimide",
                snippet="Polyimide preparation and high temperature resistant materials.",
            ),
        ]
        try:
            with patch.object(service, "_search_via_bing_rss", return_value=raw_results), patch.object(
                service,
                "_fetch_page_text",
                return_value="Polyimide synthesis and preparation for high heat resistant films.",
            ):
                outcome = service.search("高耐热聚酰亚胺 polyimide synthesis preparation", deep=False)
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

        self.assertEqual(outcome.status, "searched")
        self.assertEqual(len(outcome.results), 1)
        self.assertEqual(outcome.results[0].url, "https://example.com/polyimide")
        self.assertEqual(outcome.raw_result_count, 3)
        self.assertEqual(outcome.filtered_result_count, 1)

    def test_web_search_service_filters_design_platform_results_for_material_query(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService
        from app.services.assistant_service import WebEvidence

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        raw_results = [
            WebEvidence(
                title="Canva可画_在线设计协作平台",
                url="https://example.com/canva",
                snippet="平面设计作图软件、视觉办公套件。",
            ),
            WebEvidence(
                title="花瓣网 - 灵感设计素材",
                url="https://example.com/huaban",
                snippet="创意图片、设计灵感图库、高清图片素材。",
            ),
            WebEvidence(
                title="Molecular design of high-temperature polyimides",
                url="https://example.com/polyimide-design",
                snippet="Polyimide molecular design for heat resistant polymers.",
            ),
        ]
        try:
            with patch.object(service, "_search_via_bing_rss", return_value=raw_results), patch.object(
                service,
                "_fetch_page_text",
                return_value="High-temperature polyimide molecular design and polymer thermal stability.",
            ):
                outcome = service.search("设计 高耐热聚酰亚胺 分子设计 polyimide molecular design", deep=False)
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

        self.assertEqual(outcome.status, "searched")
        self.assertEqual(len(outcome.results), 1)
        self.assertEqual(outcome.results[0].url, "https://example.com/polyimide-design")
        self.assertEqual(outcome.raw_result_count, 3)
        self.assertEqual(outcome.filtered_result_count, 1)

    def test_web_search_service_keeps_generic_new_material_design_results(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService
        from app.services.assistant_service import WebEvidence

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        raw_results = [
            WebEvidence(
                title="Canva可画_在线设计协作平台",
                url="https://example.com/canva",
                snippet="平面设计作图软件、视觉办公套件。",
            ),
            WebEvidence(
                title="Materials by design and accelerated discovery",
                url="https://example.com/materials-design",
                snippet="New materials design, inverse design, and materials discovery workflow.",
            ),
        ]
        try:
            with patch.object(service, "_search_via_bing_rss", return_value=raw_results), patch.object(
                service,
                "_fetch_page_text",
                return_value="New materials design uses inverse design and materials discovery loops.",
            ):
                outcome = service.search("如何设计新材料", deep=False)
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

        self.assertEqual(outcome.status, "searched")
        self.assertEqual(len(outcome.results), 1)
        self.assertEqual(outcome.results[0].url, "https://example.com/materials-design")
        self.assertEqual(outcome.raw_result_count, 2)
        self.assertEqual(outcome.filtered_result_count, 1)

    def test_web_search_service_retries_generic_material_design_when_first_results_are_unrelated(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService
        from app.services.assistant_service import WebEvidence

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        unrelated = [
            WebEvidence(
                title="主页 - BBC News 中文",
                url="https://example.com/bbc",
                snippet="每日更新的新闻资讯。",
            )
        ]
        related = [
            WebEvidence(
                title="Materials design and accelerated discovery",
                url="https://example.com/materials-design",
                snippet="Computational materials design, new materials, and inverse design methods.",
            )
        ]
        try:
            with patch.object(service, "_search_via_bing_rss", side_effect=[unrelated, related]), patch.object(
                service,
                "_fetch_page_text",
                return_value="Materials discovery and inverse design for new materials.",
            ):
                outcome = service.search("如何设计新材料", deep=False)
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

        self.assertEqual(outcome.status, "searched")
        self.assertIn("materials design", outcome.query)
        self.assertEqual(len(outcome.results), 1)
        self.assertEqual(outcome.results[0].url, "https://example.com/materials-design")

    def test_web_search_service_uses_curated_material_design_fallback_when_provider_is_poor(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService
        from app.services.assistant_service import WebEvidence

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        unrelated = [
            WebEvidence(
                title="主页 - BBC News 中文",
                url="https://example.com/bbc",
                snippet="每日更新的新闻资讯。",
            )
        ]
        try:
            with patch.object(service, "_search_via_bing_rss", side_effect=[unrelated, [], [], []]), patch.object(
                service,
                "_fetch_page_text",
                return_value="Materials data for materials design and discovery.",
            ):
                outcome = service.search("如何设计新材料", deep=False)
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

        self.assertEqual(outcome.status, "searched")
        self.assertEqual(outcome.provider, "curated_material_design")
        self.assertTrue(outcome.results)
        self.assertTrue(any("materialsproject.org" in item.url for item in outcome.results))

    def test_web_search_service_returns_no_results_when_all_results_are_unrelated(self) -> None:
        from app.core.config import settings
        from app.services.assistant_service import AssistantWebSearchService
        from app.services.assistant_service import WebEvidence

        service = AssistantWebSearchService()
        original_provider = settings.assistant_web_search_provider
        original_endpoint = settings.assistant_web_search_endpoint
        settings.assistant_web_search_provider = "bing_rss"
        settings.assistant_web_search_endpoint = ""
        raw_results = [
            WebEvidence(title="我（汉语汉字）_百度百科", url="https://example.com/me", snippet="我的释义。"),
            WebEvidence(title="欢迎来到 Minecraft 官方网站", url="https://example.com/minecraft", snippet="Minecraft 游戏。"),
        ]
        try:
            with patch.object(service, "_search_via_bing_rss", return_value=raw_results), patch.object(
                service,
                "_fetch_page_text",
                return_value="",
            ):
                outcome = service.search("高耐热聚酰亚胺 polyimide synthesis preparation", deep=False)
        finally:
            settings.assistant_web_search_provider = original_provider
            settings.assistant_web_search_endpoint = original_endpoint

        self.assertEqual(outcome.status, "no_results")
        self.assertEqual(outcome.results, [])
        self.assertEqual(outcome.raw_result_count, 2)
        self.assertEqual(outcome.filtered_result_count, 0)

    def test_web_search_service_blocks_private_urls_and_limits_html(self) -> None:
        from app.services.assistant_service import AssistantWebSearchService

        service = AssistantWebSearchService()
        self.assertFalse(service._is_safe_http_url("http://127.0.0.1:8000/private"))
        self.assertFalse(service._is_safe_http_url("http://10.0.0.1/private"))
        self.assertFalse(service._is_safe_http_url("file:///tmp/private"))

        text = service._strip_html("<script>ignore me</script><p>" + ("content " * 1000) + "</p>")
        self.assertNotIn("ignore me", text)
        self.assertLessEqual(len(text), 4000)
