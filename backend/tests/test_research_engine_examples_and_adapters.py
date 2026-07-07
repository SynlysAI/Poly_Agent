"""Coverage for ResearchEngine examples and non-mock adapters."""

from __future__ import annotations

import json
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

from app.schemas.research_engine import AlgorithmRunCreate
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

    def test_literature_rag_adapter_returns_unconfigured_for_missing_index(self):
        run = self.service.create_algorithm_run(
            AlgorithmRunCreate(
                algorithm_id="literature_rag_adapter",
                input_snapshot={"query": "fluoropolymer dielectric", "top_k": 3},
            ),
            actor_user_id="tester",
        )
        self.assertEqual(run.status, "completed")
        self.assertFalse(run.output_summary["configured"])
        self.assertEqual(run.output_summary["hits"], [])

    def test_literature_rag_adapter_returns_hits_from_local_index(self):
        rag_dir = self.runtime_root / "rag"
        rag_dir.mkdir(parents=True, exist_ok=True)
        (rag_dir / "literature_index.json").write_text(
            json.dumps({
                "documents": [
                    {
                        "title": "Fluoropolymer dielectric materials",
                        "abstract": "fluoropolymer dielectric constant and thermal stability data",
                        "source": "local-test",
                    }
                ]
            }),
            encoding="utf-8",
        )
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
        self.assertEqual(len(run.output_summary["hits"]), 1)

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
