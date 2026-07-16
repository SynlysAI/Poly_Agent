"""LLM model catalog and routing API tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class LLMModelManagementApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.original_llm_model = settings.llm_model
        self.original_llm_base_url = settings.llm_base_url
        self.original_llm_api_key = settings.llm_api_key
        self.original_llm_default_provider = getattr(settings, "llm_default_provider", "")
        self.original_llm_default_model = getattr(settings, "llm_default_model", "")
        self.original_llm_reasoning_provider = getattr(settings, "llm_reasoning_provider", "")
        self.original_llm_reasoning_model = getattr(settings, "llm_reasoning_model", "")
        self.original_llm_provider_configs_json = getattr(settings, "llm_provider_configs_json", "")
        self.original_report_ollama_model = settings.report_ollama_model
        self.original_report_ollama_base_url = settings.report_ollama_base_url
        self.original_extra_key = os.environ.get("POLY_AGENT_TEST_REASONING_KEY")

        settings.llm_model = "DeepSeek-V4-Flash-w8a8-mtp"
        settings.llm_base_url = "https://fast.example.test/v1"
        settings.llm_api_key = "fast-secret-key"
        settings.llm_default_provider = "default_openai"
        settings.llm_default_model = "DeepSeek-V4-Flash-w8a8-mtp"
        settings.llm_reasoning_provider = "default_openai"
        settings.llm_reasoning_model = "DeepSeek-V4-Flash-w8a8-mtp"
        settings.report_ollama_base_url = "http://127.0.0.1:11434"
        settings.report_ollama_model = "qwen2.5:3b"
        os.environ["POLY_AGENT_TEST_REASONING_KEY"] = "reasoning-secret-key"
        settings.llm_provider_configs_json = json.dumps(
            [
                {
                    "provider_id": "reasoning_primary",
                    "display_name": "Reasoning Primary",
                    "provider_type": "openai_compatible",
                    "base_url": "https://reasoning.example.test/v1",
                    "api_key_env": "POLY_AGENT_TEST_REASONING_KEY",
                    "models": ["Qwen3.6-35B-A3B"],
                    "capabilities": ["chat", "reasoning", "structured_json"],
                    "recommended_for": ["deep"],
                }
            ]
        )

    def tearDown(self) -> None:
        settings.llm_model = self.original_llm_model
        settings.llm_base_url = self.original_llm_base_url
        settings.llm_api_key = self.original_llm_api_key
        settings.llm_default_provider = self.original_llm_default_provider
        settings.llm_default_model = self.original_llm_default_model
        settings.llm_reasoning_provider = self.original_llm_reasoning_provider
        settings.llm_reasoning_model = self.original_llm_reasoning_model
        settings.llm_provider_configs_json = self.original_llm_provider_configs_json
        settings.report_ollama_model = self.original_report_ollama_model
        settings.report_ollama_base_url = self.original_report_ollama_base_url
        if self.original_extra_key is None:
            os.environ.pop("POLY_AGENT_TEST_REASONING_KEY", None)
        else:
            os.environ["POLY_AGENT_TEST_REASONING_KEY"] = self.original_extra_key
        super().tearDown()

    def test_models_endpoint_lists_configured_models_without_secrets(self) -> None:
        resp = self.client.get("/api/v1/llm/models")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        text = json.dumps(data, ensure_ascii=False)
        self.assertIn("DeepSeek-V4-Flash-w8a8-mtp", text)
        self.assertIn("Qwen3.6-35B-A3B", text)
        self.assertIn("qwen2.5:3b", text)
        self.assertNotIn("fast-secret-key", text)
        self.assertNotIn("reasoning-secret-key", text)
        self.assertEqual(data["routing"]["deep"]["provider_id"], "default_openai")
        self.assertEqual(data["routing"]["deep"]["model_id"], "DeepSeek-V4-Flash-w8a8-mtp")
        self.assertTrue(data["routing"]["deep"]["reasoning_model_available"])
        reasoning_provider = next(item for item in data["providers"] if item["provider_id"] == "reasoning_primary")
        self.assertTrue(reasoning_provider["api_key_configured"])
        self.assertEqual(reasoning_provider["api_key_ref"], "POLY_AGENT_TEST_REASONING_KEY")
        reasoning_capabilities = reasoning_provider["models"][0]["capabilities"]
        self.assertIn("reasoning", reasoning_capabilities)
        self.assertIn("structured_json", reasoning_capabilities)
        default_provider = next(item for item in data["providers"] if item["provider_id"] == "default_openai")
        default_capabilities = default_provider["models"][0]["capabilities"]
        self.assertIn("fast", default_capabilities)
        self.assertIn("reasoning", default_capabilities)
        self.assertIn("structured_json", default_capabilities)

    def test_deep_route_falls_back_to_fast_reasoning_default_model(self) -> None:
        settings.llm_reasoning_provider = ""
        settings.llm_reasoning_model = ""
        settings.llm_provider_configs_json = "[]"

        resp = self.client.get("/api/v1/llm/models")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["routing"]["deep"]["provider_id"], "default_openai")
        self.assertEqual(data["routing"]["deep"]["model_id"], "DeepSeek-V4-Flash-w8a8-mtp")
        self.assertTrue(data["routing"]["deep"]["reasoning_model_available"])

    def test_models_check_refreshes_provider_models(self) -> None:
        def fake_get(url, **kwargs):  # noqa: ANN001
            if url.endswith("/api/tags"):
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"models": [{"name": "qwen2.5:3b"}]},
                )
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"data": [{"id": "Qwen3.6-35B-A3B"}]},
            )

        with patch("app.services.llm_model_service.httpx.get", side_effect=fake_get):
            resp = self.client.post("/api/v1/llm/models/check")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        reasoning_provider = next(item for item in data["providers"] if item["provider_id"] == "reasoning_primary")
        self.assertEqual(reasoning_provider["status"], "available")
        self.assertEqual(reasoning_provider["models"][0]["model_id"], "Qwen3.6-35B-A3B")

    def test_legacy_llm_chat_uses_default_route(self) -> None:
        calls = []

        def fake_create(**kwargs):  # noqa: ANN001
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="legacy ok"))])

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
        with patch("app.core.llm_client.OpenAI", return_value=fake_client):
            resp = self.client.post(
                "/api/v1/llm/chat",
                json={"messages": [{"role": "user", "content": "hello"}]},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["content"], "legacy ok")
        self.assertEqual(calls[0]["model"], "DeepSeek-V4-Flash-w8a8-mtp")

    def test_assistant_deep_uses_reasoning_route_metadata(self) -> None:
        def fake_chat(messages, **kwargs):  # noqa: ANN001
            self.assertEqual(kwargs["provider_id"], "default_openai")
            self.assertEqual(kwargs["model"], "DeepSeek-V4-Flash-w8a8-mtp")
            return "深度回答"

        with patch("app.core.llm_client.chat", side_effect=fake_chat):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [{"role": "user", "content": "如何查看待审批任务？"}],
                    "context": {"mode": "deep"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["content"], "深度回答")
        self.assertEqual(data["grounding_facts"]["llm_route"]["model_id"], "DeepSeek-V4-Flash-w8a8-mtp")
        self.assertTrue(data["grounding_facts"]["llm_route"]["reasoning_model_available"])

    def test_assistant_model_mode_returns_model_management_action(self) -> None:
        with patch("app.core.llm_client.chat", side_effect=RuntimeError("should not call llm")):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [{"role": "user", "content": "模型管理"}],
                    "context": {"mode": "model"},
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["answer_scope"], "model")
        self.assertEqual(data["answer_mode"], "fallback")
        self.assertTrue(any(action["target"] == "/tools?tab=llm-models" for action in data["actions"]))
