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
    def test_assistant_chat_uses_unified_api_response(self) -> None:
        with patch("app.api.v1.endpoints.assistant.chat", side_effect=RuntimeError("llm unavailable")):
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
        self.assertIn("AutoResearch", payload["data"]["content"])
        self.assertTrue(payload["data"]["actions"])
        self.assertEqual(
            payload["data"]["actions"][0]["target"],
            "/tasks/center?module_id=research-engine&status=blocked_approval",
        )
        self.assertIn("suggested_questions", payload["data"])

    def test_assistant_lists_grounded_research_engine_adapters_without_llm(self) -> None:
        with patch("app.api.v1.endpoints.assistant.chat", side_effect=RuntimeError("llm unavailable")):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "哪些算法是真实适配器？"},
                    ],
                    "context": {},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        content = data["content"]

        self.assertIn("literature_rag_adapter", content)
        self.assertIn("vertical_predictor_adapter", content)
        self.assertIn("mobo_alchemist_adapter", content)
        self.assertIn("local_structure_adapter", content)
        self.assertIn("local_xtb_adapter", content)
        self.assertIn("orca_compute_engine_laser_adapter", content)
        self.assertIn("演示", content)
        self.assertIn("answer_mode", data)
        self.assertEqual(data["answer_mode"], "deterministic")
        self.assertIn("grounding_facts", data)

        forbidden_names = [
            "BayesianOptimizer",
            "RandomSearch",
            "GridSearch",
            "MultiFidelityOptimizer",
        ]
        for name in forbidden_names:
            self.assertNotIn(name, content)

    def test_assistant_start_research_engine_example_without_llm(self) -> None:
        with patch("app.api.v1.endpoints.assistant.chat", side_effect=RuntimeError("llm unavailable")):
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
        self.assertTrue(any(action["target"] == "/research-engine" for action in data["actions"]))
