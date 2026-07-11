"""Coverage for ResearchEngine examples and non-mock adapters."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.schemas.research_engine import AlgorithmRunCreate
from app.schemas.knowledge import (
    KnowledgeGraphData,
    KnowledgeGraphNode,
    KnowledgeGraphStats,
    KnowledgeHit,
    KnowledgeQueryResponse,
)
from app.services.knowledge_service import KnowledgeService
from app.services.research_engine_algorithm_runner import get_runner
from app.services.research_engine_service import ResearchEngineService


class ResearchEngineExamplesApiTest(ComputationTestCase):
    def setUp(self):
        super().setUp()
        self.base_url = "/api/v1/research-engine"
        ResearchEngineService().seed_default_algorithms()

    def test_examples_list_and_manual_instantiate(self):
        examples_resp = self.client.get(f"{self.base_url}/examples")
        self.assertEqual(examples_resp.status_code, 200)
        example_ids = {item["example_id"] for item in examples_resp.json()["data"]["items"]}
        self.assertIn("manual-computation-workflow", example_ids)

        instantiate_resp = self.client.post(
            f"{self.base_url}/examples/manual-computation-workflow/instantiate"
        )
        self.assertEqual(instantiate_resp.status_code, 200)
        data = instantiate_resp.json()["data"]
        self.assertEqual(data["execution_decision"]["mode"], "manual_workbench")
        self.assertEqual(data["manual_workflow"]["steps"][0]["algorithm_id"], "computation_submit_adapter")
        bindings = data["manual_workflow"]["steps"][0]["input_bindings"]
        self.assertEqual(bindings["workflow_type"]["value"], "LOCAL_STRUCTURE")
        self.assertEqual(data["navigation"]["query"]["mode"], "manual_workbench")

    def test_autoresearch_example_starts_at_blocked_approval(self):
        resp = self.client.post(
            f"{self.base_url}/examples/autoresearch-approval-demo/instantiate"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        run = data["research_run"]
        self.assertEqual(data["execution_decision"]["mode"], "autoresearch")
        self.assertEqual(run["status"], "blocked_approval")
        self.assertTrue(any(stage["status"] == "blocked_approval" for stage in run["stage_runs"]))
        self.assertEqual(data["navigation"]["query"]["action"], "approve")


class ResearchEngineAdapterTest(ComputationTestCase):
    def setUp(self):
        super().setUp()
        self.service = ResearchEngineService()
        self.service.seed_default_algorithms()

    def test_literature_rag_adapter_rejects_unconfigured_lightrag(self):
        old_base_url = os.environ.pop("KNOWLEDGE_RAG_BASE_URL", None)
        try:
            with self.assertRaises(HTTPException) as ctx:
                self.service.create_algorithm_run(
                    AlgorithmRunCreate(
                        algorithm_id="literature_rag_adapter",
                        input_snapshot={"query": "fluoropolymer dielectric", "top_k": 3},
                    ),
                    actor_user_id="tester",
                )
        finally:
            if old_base_url is not None:
                os.environ["KNOWLEDGE_RAG_BASE_URL"] = old_base_url
        self.assertEqual(ctx.exception.status_code, 503)

    def test_knowledge_graph_adapter_returns_subgraph(self):
        graph = KnowledgeGraphData(
            system_id="ai4s_fluoropolymer",
            nodes=[KnowledgeGraphNode(id="pvdf", label="PVDF", type="Polymer", properties={"source_id": "chunk-1"})],
            edges=[],
            stats=KnowledgeGraphStats(entity_count=1, relation_count=0, document_count=1),
            configured=True,
            provenance={"provider": "lightrag"},
        )
        with patch.object(KnowledgeService, "get_subgraph", return_value=graph):
            run = self.service.create_algorithm_run(
                AlgorithmRunCreate(
                    algorithm_id="knowledge_graph_adapter",
                    input_snapshot={
                        "system_id": "ai4s_fluoropolymer",
                        "query": "fluoropolymer dielectric",
                        "limit": 4,
                    },
                ),
                actor_user_id="tester",
            )
        self.assertEqual(run.status, "completed")
        self.assertTrue(run.output_summary["configured"])
        self.assertLessEqual(len(run.output_summary["nodes"]), 4)
        self.assertIn("stats", run.output_summary)

    def test_literature_rag_adapter_uses_knowledge_service_lightrag_path(self):
        os.environ["KNOWLEDGE_RAG_BASE_URL"] = "http://lightrag.test"

        class FakeResponse:
            def __init__(self, data):
                self._data = data
                self.status_code = 200
                self.text = json.dumps(data)

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

            def post(self, path, json=None):
                self.calls.append((path, json))
                return FakeResponse({
                    "response": "LightRAG adapter answer",
                    "references": [{"reference_id": "ref_1", "content": "fluoropolymer dielectric", "file_path": "demo"}],
                })

        try:
            with patch("app.services.knowledge_service.httpx.Client", FakeClient):
                run = self.service.create_algorithm_run(
                    AlgorithmRunCreate(
                        algorithm_id="literature_rag_adapter",
                        input_snapshot={
                            "query": "fluoropolymer dielectric",
                            "material_family": "fluoropolymer",
                            "top_k": 3,
                            "include_graph_context": False,
                        },
                    ),
                    actor_user_id="tester",
                )
        finally:
            os.environ.pop("KNOWLEDGE_RAG_BASE_URL", None)

        self.assertEqual(run.status, "completed")
        self.assertTrue(run.output_summary["configured"])
        self.assertEqual(run.output_summary["answer"], "LightRAG adapter answer")

    def test_algorithm_registry_contains_knowledge_graph_adapter(self):
        data = self.service.list_algorithms(algorithm_family="knowledge", page=1, page_size=20)
        algorithm_ids = {item.algorithm_id for item in data.items}
        self.assertIn("literature_rag_adapter", algorithm_ids)
        self.assertIn("knowledge_graph_adapter", algorithm_ids)
        graph = next(item for item in data.items if item.algorithm_id == "knowledge_graph_adapter")
        self.assertEqual(graph.type, "retriever")
        self.assertIn("KNOWLEDGE_RETRIEVAL", graph.task_scope)

    def test_literature_rag_adapter_preserves_existing_top_k_contract(self):
        response = KnowledgeQueryResponse(
            system_id="ai4s_fluoropolymer",
            question="fluoropolymer dielectric",
            mode="hybrid",
            answer="Grounded answer",
            hits=[KnowledgeHit(source_id=f"source-{index}", title=f"Hit {index}", snippet="evidence") for index in range(3)],
            configured=True,
        )
        with patch.object(KnowledgeService, "query", return_value=response):
            run = self.service.create_algorithm_run(
                AlgorithmRunCreate(
                    algorithm_id="literature_rag_adapter",
                    input_snapshot={
                        "query": "fluoropolymer dielectric",
                        "material_family": "fluoropolymer",
                        "top_k": 3,
                    },
                ),
                actor_user_id="tester",
            )
        self.assertEqual(run.status, "completed")
        self.assertTrue(run.output_summary["configured"])
        self.assertLessEqual(len(run.output_summary["hits"]), 3)

    def test_vertical_predictor_adapter_requires_service_url(self):
        old_url = os.environ.pop("VERTICAL_PREDICTOR_URL", None)
        try:
            with self.assertRaises(Exception) as ctx:
                self.service.create_algorithm_run(
                    AlgorithmRunCreate(
                        algorithm_id="vertical_predictor_adapter",
                        input_snapshot={
                            "smiles": "C=C(F)F",
                            "target_properties": ["dielectric_constant"],
                        },
                    ),
                    actor_user_id="tester",
                )
            self.assertIn("VERTICAL_PREDICTOR_URL", str(ctx.exception))
        finally:
            if old_url is not None:
                os.environ["VERTICAL_PREDICTOR_URL"] = old_url

    def test_mobo_alchemist_adapter_success_and_bad_response(self):
        runner = get_runner("mobo_alchemist_adapter")
        self.assertIsNotNone(runner)

        class FakeResponse:
            def __init__(self, data, status_code=200):
                self._data = data
                self.status_code = status_code
                self.text = json.dumps(data)

            def raise_for_status(self):
                if self.status_code >= 400:
                    request = httpx.Request("POST", "http://alchemist")
                    response = httpx.Response(self.status_code, request=request, text=self.text)
                    raise httpx.HTTPStatusError("bad", request=request, response=response)

            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def request(self, method, path, json=None):
                self.calls.append((method, path, json))
                if path == "/sessions":
                    return FakeResponse({"session_id": "sess_1"})
                if path.endswith("/model/train"):
                    return FakeResponse({"status": "trained"})
                if path.endswith("/acquisition/suggest"):
                    return FakeResponse({"suggestions": [{"x": {"a": 1}, "acquisition_value": 0.7}]})
                return FakeResponse({"ok": True})

        with patch("app.services.research_engine_algorithm_runner.httpx.Client", FakeClient):
            output = runner.run({
                "objectives": [{"name": "dielectric_constant", "direction": "maximize"}],
                "variables": [{"name": "a", "type": "continuous", "bounds": [0, 1]}],
                "batch_size": 1,
            })
        self.assertEqual(output["session_id"], "sess_1")
        self.assertEqual(len(output["top_k_candidates"]), 1)

        class BadClient(FakeClient):
            def request(self, method, path, json=None):
                if path == "/sessions":
                    return FakeResponse({"session_id": "sess_1"})
                if path.endswith("/model/train"):
                    return FakeResponse({"status": "trained"})
                if path.endswith("/acquisition/suggest"):
                    return FakeResponse({"suggestions": "bad"})
                return FakeResponse({"ok": True})

        with patch("app.services.research_engine_algorithm_runner.httpx.Client", BadClient):
            with self.assertRaises(RuntimeError):
                runner.run({"objectives": [{"name": "dielectric_constant", "direction": "maximize"}]})
