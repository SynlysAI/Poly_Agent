"""Knowledge base API coverage for the standalone literature RAG service."""

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


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = "ok"

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://literature.test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)
        return None

    def json(self):
        return self._data


class KnowledgeBaseApiTest(ComputationTestCase):
    def setUp(self):
        super().setUp()
        self.base_url = "/api/v1/knowledge-bases"
        self.env_keys = (
            "APP_ENV",
            "LITERATURE_RAG_BASE_URL",
            "LITERATURE_RAG_API_KEY",
            "LITERATURE_RAG_QUERY_API_KEY",
            "LITERATURE_RAG_DEFAULT_CORPUS_ID",
            "KNOWLEDGE_RAG_BASE_URL",
            "KNOWLEDGE_RAG_API_KEY",
            "KNOWLEDGE_DEFAULT_SYSTEM_ID",
        )
        self.original_env = {key: os.environ.get(key) for key in self.env_keys}
        for key in self.env_keys:
            os.environ.pop(key, None)
        os.environ["APP_ENV"] = "production"

    def tearDown(self):
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super().tearDown()

    def test_list_systems_is_empty_without_remote_configuration(self):
        response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual(data["total"], 0)

    def test_list_systems_maps_multiple_remote_corpora(self):
        os.environ["LITERATURE_RAG_BASE_URL"] = "http://literature.test"

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                assert path == "/api/v1/corpora"
                return FakeResponse({"data": {"items": [
                    {
                        "corpus_id": "krf_photoresist", "name": "KrF", "domain": "polymer_lithography",
                        "material_family": "photoresist", "description": "KrF corpus",
                        "document_count": 2, "entity_count": 4, "relation_count": 5,
                        "status": "ready", "capabilities": ["query", "streaming", "graph"],
                    },
                    {
                        "corpus_id": "battery_polymer", "name": "Battery Polymer", "domain": "energy",
                        "material_family": "polymer_electrolyte", "description": "Battery corpus",
                        "indexed_document_count": 0, "status": "empty", "capabilities": ["query"],
                    },
                ], "total": 2}})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual([item["system_id"] for item in data["items"]], ["krf_photoresist", "battery_polymer"])
        self.assertEqual(data["items"][0]["provider"], "literature-rag")
        self.assertEqual(data["items"][0]["data_source_id"], "literature-rag:krf_photoresist")
        self.assertEqual(data["items"][0]["status"], "ready")
        self.assertEqual(data["items"][1]["status"], "empty")

    def test_list_systems_auto_discovers_local_literature_rag_in_local_env(self):
        os.environ["APP_ENV"] = "dev"
        os.environ["LITERATURE_RAG_QUERY_API_KEY"] = "query-secret"

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.base_url = str(kwargs.get("base_url") or args[0])
                self.headers = kwargs.get("headers", {})

            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                if path == "/health":
                    return FakeResponse({"data": {"service": "literature-rag", "status": "ready"}})
                assert path == "/api/v1/corpora"
                assert self.base_url == "http://127.0.0.1:8200"
                assert self.headers["Authorization"] == "Bearer query-secret"
                return FakeResponse({"data": {"items": [
                    {"corpus_id": "krf_photoresist", "name": "KrF", "indexed_document_count": 14, "status": "ready"},
                ]}})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["items"][0]["system_id"], "krf_photoresist")
        self.assertEqual(data["items"][0]["status"], "ready")

    def test_health_reports_discovered_service_with_missing_or_invalid_key(self):
        os.environ["APP_ENV"] = "dev"

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                if path == "/health":
                    return FakeResponse({"data": {"service": "literature-rag", "status": "ready"}})
                assert path == "/api/v1/corpora"
                return FakeResponse({"error": {"code": "UNAUTHORIZED"}}, status_code=401)

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["status"], "warning")
        self.assertFalse(data["configured"])
        self.assertIn("API Key", data["message"])

    def test_default_system_id_falls_back_to_literature_default_corpus_id(self):
        os.environ["LITERATURE_RAG_DEFAULT_CORPUS_ID"] = "krf_photoresist"
        response = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["default_system_id"], "krf_photoresist")

    def test_query_without_service_returns_unavailable(self):
        response = self.client.post(f"{self.base_url}/query", json={
            "system_id": "any_corpus", "question": "What controls sensitivity?",
            "top_k": 3, "include_graph_context": True,
        })
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("demo", response.text.lower())

    def test_graph_endpoint_requires_query(self):
        os.environ["LITERATURE_RAG_BASE_URL"] = "http://literature.test"

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                assert path == "/api/v1/corpora"
                return FakeResponse({"data": {"items": [{"corpus_id": "krf_photoresist", "name": "KrF"}]}})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/krf_photoresist/graph")
        self.assertEqual(response.status_code, 400)

    def test_query_maps_literature_service_contract_and_hides_key(self):
        os.environ["LITERATURE_RAG_BASE_URL"] = "http://literature.test"
        os.environ["LITERATURE_RAG_API_KEY"] = "replace-with-query-key"
        os.environ["LITERATURE_RAG_QUERY_API_KEY"] = "query-secret"

        class FakeClient:
            def __init__(self, *args, **kwargs): self.headers = kwargs.get("headers", {})
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                assert path == "/api/v1/corpora"
                assert self.headers["Authorization"] == "Bearer query-secret"
                return FakeResponse({"data": {"items": [{"corpus_id": "krf_photoresist", "name": "KrF"}]}})
            def post(self, path, json=None):
                assert path == "/api/v1/query"
                assert json["corpus_id"] == "krf_photoresist"
                assert self.headers["Authorization"] == "Bearer query-secret"
                return FakeResponse({"data": {
                    "corpus_id": "krf_photoresist", "question": json["question"], "mode": json["mode"],
                    "answer": "PAG controls sensitivity.",
                    "hits": [{"source_id": "doc_1", "title": "KrF PAG paper", "snippet": "evidence",
                              "source": "https://doi.org/10.1000/krf", "doi": "10.1000/krf",
                              "url": "https://doi.org/10.1000/krf", "score": 0.9,
                              "metadata": {"source_kind": "publisher_oa", "storage_uri": "blocked"}}],
                    "citations": [{"source_id": "doc_1", "title": "KrF PAG paper", "doi": "10.1000/krf",
                                   "url": "https://doi.org/10.1000/krf", "chunk_id": "chunk_00001"}],
                    "graph_context": None, "configured": True, "message": "ok",
                }})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.post(f"{self.base_url}/query", json={
                "system_id": "krf_photoresist", "question": "What controls sensitivity?",
                "top_k": 2, "include_graph_context": False,
            })
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["answer"], "PAG controls sensitivity.")
        self.assertEqual(data["citations"][0]["chunk_id"], "chunk_00001")
        self.assertNotIn("storage_uri", response.text)
        self.assertNotIn("query-secret", response.text)

    def test_query_forwards_chinese_question_to_literature_service(self):
        os.environ["LITERATURE_RAG_BASE_URL"] = "http://literature.test"
        os.environ["LITERATURE_RAG_QUERY_API_KEY"] = "query-secret"
        captured = {}

        class FakeClient:
            def __init__(self, *args, **kwargs): self.headers = kwargs.get("headers", {})
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                assert path == "/api/v1/corpora"
                return FakeResponse({"data": {"items": [{"corpus_id": "krf_photoresist", "name": "KrF"}]}})
            def post(self, path, json=None):
                captured.update(json or {})
                return FakeResponse({"data": {
                    "corpus_id": "krf_photoresist", "question": json["question"], "mode": json["mode"],
                    "answer": "KrF photoresist evidence.",
                    "hits": [{"source_id": "doc_1", "title": "KrF overview", "snippet": "photoresist",
                              "doi": "10.1000/zh", "url": "https://doi.org/10.1000/zh", "score": 0.8}],
                    "citations": [{"source_id": "doc_1", "title": "KrF overview", "doi": "10.1000/zh",
                                   "url": "https://doi.org/10.1000/zh", "chunk_id": "chunk_00001"}],
                    "graph_context": None, "configured": True, "message": "ok",
                }})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.post(f"{self.base_url}/query", json={
                "system_id": "krf_photoresist", "question": "KrF光刻胶是什么？",
                "top_k": 3, "include_graph_context": False,
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["question"], "KrF光刻胶是什么？")
        self.assertEqual(response.json()["data"]["hits"][0]["doi"], "10.1000/zh")

    def test_document_inventory_response_remains_sanitized(self):
        os.environ["LITERATURE_RAG_BASE_URL"] = "http://literature.test"
        os.environ["LITERATURE_RAG_QUERY_API_KEY"] = "query-secret"

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path):
                assert path == "/api/v1/corpora"
                return FakeResponse({"data": {"items": [{"corpus_id": "krf_photoresist", "name": "KrF"}]}})
            def post(self, path, json=None):
                return FakeResponse({"data": {
                    "corpus_id": "krf_photoresist", "question": json["question"], "mode": json["mode"],
                    "answer": "- Indexed KrF paper [1]",
                    "hits": [{"source_id": "doc_1", "title": "Indexed KrF paper", "snippet": "DOI: 10.1000/inventory",
                              "doi": "10.1000/inventory", "url": "https://doi.org/10.1000/inventory",
                              "score": 1.0, "metadata": {"storage_uri": "s3://secret", "object_key": "hidden",
                                                        "source_kind": "authorized_upload"}}],
                    "citations": [{"source_id": "doc_1", "title": "Indexed KrF paper", "doi": "10.1000/inventory",
                                   "url": "https://doi.org/10.1000/inventory"}],
                    "graph_context": None, "configured": True, "message": "document_inventory",
                }})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.post(f"{self.base_url}/query", json={
                "system_id": "krf_photoresist", "question": "帮我找全部的文档",
                "top_k": 5, "include_graph_context": False,
            })

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["message"], "document_inventory")
        self.assertEqual(data["hits"][0]["metadata"], {"source_kind": "authorized_upload"})
        self.assertNotIn("storage_uri", response.text)
        self.assertNotIn("object_key", response.text)
        self.assertNotIn("query-secret", response.text)

    def test_subgraph_maps_new_graph_contract(self):
        os.environ["LITERATURE_RAG_BASE_URL"] = "http://literature.test"

        class FakeClient:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path, params=None):
                if path == "/api/v1/corpora":
                    return FakeResponse({"data": {"items": [{"corpus_id": "battery_polymer", "name": "Battery Polymer"}]}})
                assert path == "/api/v1/corpora/battery_polymer/graph/subgraph"
                assert params["query"] == "polymer electrolyte"
                return FakeResponse({"data": {
                    "corpus_id": "battery_polymer",
                    "nodes": [{"id": "paper:1", "label": "Battery paper", "type": "Paper", "score": 1,
                               "properties": {"document_id": "doc_1", "doi": "10.1000/battery"}}],
                    "edges": [],
                    "stats": {"entity_count": 1, "relation_count": 0, "document_count": 1},
                    "configured": True, "message": "ok",
                    "provenance": {"provider": "literature-rag", "query": params["query"]},
                }})

        with patch("app.services.knowledge_service.httpx.Client", FakeClient):
            response = self.client.get(f"{self.base_url}/battery_polymer/graph/subgraph",
                                       params={"query": "polymer electrolyte", "limit": 10})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["nodes"][0]["type"], "Paper")
        self.assertEqual(data["provenance"]["provider"], "literature-rag")

    def test_legacy_environment_variable_remains_supported(self):
        os.environ["KNOWLEDGE_RAG_BASE_URL"] = "http://legacy.test"
        response = self.client.get(f"{self.base_url}/health")
        self.assertEqual(response.status_code, 200)
