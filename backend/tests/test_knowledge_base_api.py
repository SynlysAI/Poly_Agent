"""Knowledge base API coverage for the WeKnora-backed adapter."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.config import settings
from app.services.knowledge_service import KnowledgeService


class FakeResponse:
    """模拟 httpx 响应对象。"""

    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = "ok"

    def raise_for_status(self):
        """在错误状态码时抛出 httpx 异常。"""
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://weknora.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)
        return None

    def json(self):
        """返回 JSON 响应体。"""
        return self._data


class KnowledgeBaseApiTest(ComputationTestCase):
    """覆盖 PolyAgent 知识库 API 到 WeKnora 契约的映射。"""

    def setUp(self):
        super().setUp()
        self.base_url = "/api/v1/knowledge-bases"
        self.env_keys = (
            "WEKNORA_BASE_URL",
            "WEKNORA_API_KEY",
            "WEKNORA_DEFAULT_KB_ID",
            "KNOWLEDGE_DEFAULT_SYSTEM_ID",
        )
        self.original_env = {key: os.environ.get(key) for key in self.env_keys}
        self.original_settings = {
            "weknora_base_url": settings.weknora_base_url,
            "weknora_api_key": settings.weknora_api_key,
            "weknora_default_kb_id": settings.weknora_default_kb_id,
        }
        for key in self.env_keys:
            os.environ.pop(key, None)
        settings.weknora_base_url = ""
        settings.weknora_api_key = ""
        settings.weknora_default_kb_id = ""

    def tearDown(self):
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in self.original_settings.items():
            setattr(settings, key, value)
        super().tearDown()

    def test_list_systems_is_empty_without_weknora_configuration(self):
        response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)

    def test_list_systems_maps_multiple_weknora_knowledge_bases(self):
        os.environ["WEKNORA_BASE_URL"] = "http://weknora.test"

        class FakeClient:
            """模拟 WeKnora 知识库列表客户端。"""

            def __init__(self, *args, **kwargs):
                self.base_url = str(kwargs.get("base_url") or args[0])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, path):
                assert path == "/knowledge-bases"
                assert self.base_url == "http://weknora.test/api/v1"
                return FakeResponse({"data": [
                    {
                        "id": "kb_photoresist",
                        "name": "KrF",
                        "type": "polymer_lithography",
                        "description": "KrF corpus",
                        "knowledge_count": 2,
                        "chunk_count": 4,
                        "tags": ["photoresist"],
                    },
                    {
                        "id": "kb_empty",
                        "name": "Empty",
                        "type": "general",
                        "knowledge_count": 0,
                    },
                ]})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["system_id"] for item in data["items"]], ["kb_photoresist", "kb_empty"])
        self.assertEqual(data["items"][0]["provider"], "weknora")
        self.assertEqual(data["items"][0]["data_source_id"], "weknora:kb_photoresist")
        self.assertEqual(data["items"][0]["status"], "ready")
        self.assertEqual(data["items"][0]["backend"], "weknora")
        self.assertEqual(data["items"][0]["graph_backend"], "search-synthesis")
        self.assertEqual(data["items"][0]["source_mode"], "weknora-api")
        self.assertEqual(data["items"][1]["status"], "empty")

    def test_health_reports_invalid_weknora_key(self):
        os.environ["WEKNORA_BASE_URL"] = "http://weknora.test"

        class FakeClient:
            """模拟 WeKnora 未授权响应。"""

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, path):
                assert path == "/knowledge-bases"
                return FakeResponse({"error": {"code": "UNAUTHORIZED"}}, status_code=401)

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "warning")
        self.assertFalse(data["configured"])
        self.assertIn("X-API-Key", data["message"])

    def test_default_system_id_uses_weknora_default_kb_id(self):
        os.environ["WEKNORA_DEFAULT_KB_ID"] = "kb_photoresist"
        response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["default_system_id"], "kb_photoresist")

    def test_query_without_weknora_service_returns_unavailable(self):
        response = self.client.post(f"{self.base_url}/query", json={
            "system_id": "any_kb",
            "question": "What controls sensitivity?",
            "top_k": 3,
            "include_graph_context": True,
        })
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("demo", response.text.lower())

    def test_graph_endpoint_requires_query_when_wiki_graph_unavailable(self):
        os.environ["WEKNORA_BASE_URL"] = "http://weknora.test"

        class FakeClient:
            """模拟只有知识库列表可用的 WeKnora 客户端。"""

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, path):
                assert path == "/knowledge-bases"
                return FakeResponse({"data": [{"id": "kb_photoresist", "name": "KrF", "knowledge_count": 1}]})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient), \
             patch.object(KnowledgeService, "_wiki_subgraph", side_effect=RuntimeError("wiki unavailable")):
            response = self.client.get(f"{self.base_url}/kb_photoresist/graph")
        self.assertEqual(response.status_code, 400)

    def test_query_maps_weknora_chat_response_and_hides_key(self):
        os.environ["WEKNORA_BASE_URL"] = "http://weknora.test"
        os.environ["WEKNORA_API_KEY"] = "query-secret"

        class FakeClient:
            """模拟 WeKnora 知识库列表客户端。"""

            def __init__(self, *args, **kwargs):
                self.headers = kwargs.get("headers", {})

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, path):
                assert path == "/knowledge-bases"
                assert self.headers["X-API-Key"] == "query-secret"
                return FakeResponse({"data": [{"id": "kb_photoresist", "name": "KrF", "knowledge_count": 1}]})

        references = [{
            "knowledge_id": "doc_1",
            "id": "chunk_00001",
            "knowledge_title": "KrF PAG paper",
            "content": "PAG evidence",
            "doi": "10.1000/krf",
            "url": "https://doi.org/10.1000/krf",
            "score": 0.9,
            "metadata": {"storage_uri": "blocked", "source_kind": "publisher_oa"},
        }]
        with patch("app.services.knowledge_service.httpx.Client", FakeClient), \
             patch.object(KnowledgeService, "_create_session", return_value="session-1"), \
             patch.object(KnowledgeService, "_consume_chat_stream", return_value=("PAG controls sensitivity.", references)):
            response = self.client.post(f"{self.base_url}/query", json={
                "system_id": "kb_photoresist",
                "question": "What controls sensitivity?",
                "top_k": 2,
                "include_graph_context": False,
            })
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["answer"], "PAG controls sensitivity.")
        self.assertEqual(data["citations"][0]["chunk_id"], "chunk_00001")
        self.assertNotIn("storage_uri", response.text)
        self.assertNotIn("query-secret", response.text)

    def test_query_forwards_chinese_question_to_weknora_chat(self):
        os.environ["WEKNORA_BASE_URL"] = "http://weknora.test"
        captured = {}

        class FakeClient:
            """模拟 WeKnora 知识库列表客户端。"""

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, path):
                assert path == "/knowledge-bases"
                return FakeResponse({"data": [{"id": "kb_photoresist", "name": "KrF", "knowledge_count": 1}]})

        def fake_consume_chat_stream(self, base_url, session_id, payload):
            """记录发送给 WeKnora 会话问答的中文问题。"""
            captured["question"] = payload.question
            return "KrF photoresist evidence.", [{
                "knowledge_id": "doc_1",
                "id": "chunk_zh",
                "knowledge_title": "KrF overview",
                "content": "photoresist",
                "doi": "10.1000/zh",
                "url": "https://doi.org/10.1000/zh",
                "score": 0.8,
            }]

        with patch("app.services.knowledge_service.httpx.Client", FakeClient), \
             patch.object(KnowledgeService, "_create_session", return_value="session-1"), \
             patch.object(KnowledgeService, "_consume_chat_stream", fake_consume_chat_stream):
            response = self.client.post(f"{self.base_url}/query", json={
                "system_id": "kb_photoresist",
                "question": "KrF光刻胶是什么？",
                "top_k": 3,
                "include_graph_context": False,
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["question"], "KrF光刻胶是什么？")
        self.assertEqual(response.json()["data"]["hits"][0]["doi"], "10.1000/zh")

    def test_subgraph_maps_weknora_search_results(self):
        os.environ["WEKNORA_BASE_URL"] = "http://weknora.test"

        class FakeClient:
            """模拟 WeKnora 列表和无总结检索客户端。"""

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, path):
                assert path == "/knowledge-bases"
                return FakeResponse({"data": [{"id": "kb_battery", "name": "Battery Polymer", "knowledge_count": 1}]})

            def post(self, path, json=None):
                assert path == "/knowledge-search"
                assert json["query"] == "polymer electrolyte"
                assert json["knowledge_base_ids"] == ["kb_battery"]
                return FakeResponse({"data": [
                    {
                        "knowledge_id": "doc_1",
                        "id": "chunk_1",
                        "knowledge_title": "Battery paper",
                        "content": "polymer electrolyte ionic conductivity",
                        "score": 0.95,
                        "metadata": {
                            "source_kind": "authorized_upload",
                            "storage_uri": "s3://secret",
                            "embedding": [0.1],
                        },
                    },
                ]})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient), \
             patch.object(KnowledgeService, "_wiki_subgraph", side_effect=RuntimeError("wiki unavailable")):
            response = self.client.get(
                f"{self.base_url}/kb_battery/graph/subgraph",
                params={"query": "polymer electrolyte", "limit": 10},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["nodes"][0]["type"], "Paper")
        self.assertEqual(data["provenance"]["provider"], "weknora")
        self.assertEqual(data["backend"], "weknora")
        self.assertEqual(data["graph_backend"], "search-synthesis")
        self.assertNotIn("storage_uri", response.text)
        self.assertNotIn("embedding", response.text)
