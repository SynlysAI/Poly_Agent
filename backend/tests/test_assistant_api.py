"""Assistant API contract tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class AssistantApiTest(ComputationTestCase):
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
        with patch("app.core.llm_client.chat", return_value="模型配置回答"):
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
        self.assertEqual(data["answer_mode"], "llm_project_grounded")
        self.assertIn("model_management", data["grounding_facts"])

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
