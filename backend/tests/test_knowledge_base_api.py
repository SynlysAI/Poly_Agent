"""Knowledge base RAG/KG API coverage."""

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


class KnowledgeBaseApiTest(ComputationTestCase):
    def setUp(self):
        super().setUp()
        self.base_url = "/api/v1/knowledge-bases"

    def test_list_systems_returns_configurable_ai4s_system(self):
        resp = self.client.get(f"{self.base_url}/systems")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertGreaterEqual(data["total"], 1)
        system_ids = {item["system_id"] for item in data["items"]}
        self.assertIn("ai4s_fluoropolymer", system_ids)
        demo = next(item for item in data["items"] if item["system_id"] == "ai4s_fluoropolymer")
        self.assertFalse(demo["is_demo"])

    def test_query_without_lightrag_returns_service_unavailable(self):
        old_base_url = os.environ.pop("KNOWLEDGE_RAG_BASE_URL", None)
        try:
            resp = self.client.post(
                f"{self.base_url}/query",
                json={
                    "system_id": "ai4s_fluoropolymer",
                    "question": "如何提高氟聚合物介电性能和热稳定性？",
                    "top_k": 3,
                    "include_graph_context": True,
                },
            )
        finally:
            if old_base_url is not None:
                os.environ["KNOWLEDGE_RAG_BASE_URL"] = old_base_url

        self.assertEqual(resp.status_code, 503)
        self.assertNotIn("demo", resp.text.lower())

    def test_graph_endpoint_requires_query(self):
        resp = self.client.get(f"{self.base_url}/ai4s_fluoropolymer/graph")
        self.assertEqual(resp.status_code, 400)

    def test_subgraph_uses_lightrag_and_requires_provenance(self):
        os.environ["KNOWLEDGE_RAG_BASE_URL"] = "http://lightrag.test"

        class FakeResponse:
            def __init__(self, data): self._data = data
            def raise_for_status(self): return None
            def json(self): return self._data

        class FakeClient:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def get(self, path, params=None):
                if path == "/graph/label/search": return FakeResponse(["PVDF"])
                return FakeResponse({
                    "nodes": [
                        {"id": "pvdf", "label": "PVDF", "entity_type": "Polymer", "source_id": "chunk_1"},
                        {"id": "loss", "label": "Dielectric loss", "entity_type": "Property", "source_id": "chunk_2"},
                        {"id": "unverified", "label": "Unverified"},
                    ],
                    "edges": [
                        {"source": "pvdf", "target": "loss", "relation": "HAS_PROPERTY", "chunk_id": "chunk_1"},
                    ],
                })

        try:
            with patch("app.services.knowledge_service.httpx.Client", return_value=FakeClient()):
                resp = self.client.get(
                    f"{self.base_url}/ai4s_fluoropolymer/graph/subgraph",
                    params={"query": "dielectric fluoropolymer", "limit": 4},
                )
        finally:
            os.environ.pop("KNOWLEDGE_RAG_BASE_URL", None)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(len(data["nodes"]), 2)
        self.assertEqual(len(data["edges"]), 1)
        self.assertEqual(data["provenance"]["provider"], "lightrag")

    def test_query_uses_lightrag_when_configured(self):
        os.environ["KNOWLEDGE_RAG_BASE_URL"] = "http://lightrag.test"
        os.environ["KNOWLEDGE_RAG_API_KEY"] = "secret-value"

        class FakeResponse:
            def __init__(self, data):
                self._data = data
                self.status_code = 200
                self.text = "ok"

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, path):
                self.calls.append(("GET", path, None))
                return FakeResponse({"status": "ok"})

            def post(self, path, json=None):
                self.calls.append(("POST", path, json))
                return FakeResponse({
                    "response": "LightRAG answer",
                    "references": [
                        {
                            "reference_id": "doc_1",
                            "file_path": "demo_source",
                            "content": "fluoropolymer dielectric evidence",
                            "doi": "10.1038/srep20952",
                            "url": "https://doi.org/10.1038/srep20952",
                        }
                    ],
                })

        try:
            with patch("app.services.knowledge_service.httpx.Client", FakeClient):
                resp = self.client.post(
                    f"{self.base_url}/query",
                    json={
                        "system_id": "ai4s_fluoropolymer",
                        "question": "fluoropolymer dielectric",
                        "top_k": 2,
                        "include_graph_context": False,
                    },
                )
        finally:
            os.environ.pop("KNOWLEDGE_RAG_BASE_URL", None)
            os.environ.pop("KNOWLEDGE_RAG_API_KEY", None)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["configured"])
        self.assertEqual(data["answer"], "LightRAG answer")
        self.assertEqual(data["hits"][0]["source"], "demo_source")
        self.assertEqual(data["citations"][0]["url"], "https://doi.org/10.1038/srep20952")
        self.assertNotIn("secret-value", resp.text)
