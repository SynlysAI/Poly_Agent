"""LLM model catalog and routing API tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
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
        self.original_llm_provider_configs_file = getattr(settings, "llm_provider_configs_file", "")
        self.original_llm_provider_configs_json = getattr(settings, "llm_provider_configs_json", "")
        self.original_report_ollama_model = settings.report_ollama_model
        self.original_report_ollama_base_url = settings.report_ollama_base_url
        self.original_llm_api_key_env = os.environ.get("LLM_API_KEY")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider_config_path = Path(self.temp_dir.name) / "llm.providers.json"

        settings.llm_model = ""
        settings.llm_base_url = ""
        settings.llm_api_key = ""
        settings.llm_default_provider = ""
        settings.llm_default_model = ""
        settings.llm_reasoning_provider = ""
        settings.llm_reasoning_model = ""
        settings.report_ollama_base_url = "http://127.0.0.1:11434"
        settings.report_ollama_model = "qwen2.5:3b"
        os.environ["LLM_API_KEY"] = "reasoning-secret-key"
        settings.llm_provider_configs_file = str(self.provider_config_path)
        settings.llm_provider_configs_json = ""
        self.provider_config_path.write_text(
            json.dumps(
                [
                    {
                        "provider_id": "default_openai",
                        "display_name": "Default chat model",
                        "provider_type": "openai_compatible",
                        "base_url": "https://fast.example.test/v1",
                        "api_key_env": "LLM_API_KEY",
                        "models": ["DeepSeek-V4-Flash-w8a8-mtp"],
                        "capabilities": ["chat", "structured_json"],
                        "recommended_for": ["qa", "deep"],
                    },
                    {
                        "provider_id": "qwen_reasoning_primary",
                        "display_name": "Reasoning Primary",
                        "provider_type": "openai_compatible",
                        "base_url": "https://reasoning.example.test/v1",
                        "api_key_env": "LLM_API_KEY",
                        "models": ["Qwen3.6-35B-A3B"],
                        "capabilities": ["chat", "reasoning", "structured_json"],
                        "recommended_for": ["deep"],
                    },
                ],
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        settings.llm_model = self.original_llm_model
        settings.llm_base_url = self.original_llm_base_url
        settings.llm_api_key = self.original_llm_api_key
        settings.llm_default_provider = self.original_llm_default_provider
        settings.llm_default_model = self.original_llm_default_model
        settings.llm_reasoning_provider = self.original_llm_reasoning_provider
        settings.llm_reasoning_model = self.original_llm_reasoning_model
        settings.llm_provider_configs_file = self.original_llm_provider_configs_file
        settings.llm_provider_configs_json = self.original_llm_provider_configs_json
        settings.report_ollama_model = self.original_report_ollama_model
        settings.report_ollama_base_url = self.original_report_ollama_base_url
        if self.original_llm_api_key_env is None:
            os.environ.pop("LLM_API_KEY", None)
        else:
            os.environ["LLM_API_KEY"] = self.original_llm_api_key_env
        self.temp_dir.cleanup()
        super().tearDown()

    def test_models_endpoint_lists_configured_models_without_secrets(self) -> None:
        resp = self.client.get("/api/v1/llm/models")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        text = json.dumps(data, ensure_ascii=False)
        self.assertIn("DeepSeek-V4-Flash-w8a8-mtp", text)
        self.assertIn("Qwen3.6-35B-A3B", text)
        self.assertIn("qwen2.5:3b", text)
        self.assertNotIn("reasoning-secret-key", text)
        self.assertEqual(data["routing"]["deep"]["provider_id"], "default_openai")
        self.assertEqual(data["routing"]["deep"]["model_id"], "DeepSeek-V4-Flash-w8a8-mtp")
        self.assertTrue(data["routing"]["deep"]["reasoning_model_available"])
        reasoning_provider = next(item for item in data["providers"] if item["provider_id"] == "qwen_reasoning_primary")
        self.assertTrue(reasoning_provider["api_key_configured"])
        self.assertEqual(reasoning_provider["api_key_ref"], "LLM_API_KEY")
        reasoning_capabilities = reasoning_provider["models"][0]["capabilities"]
        self.assertIn("reasoning", reasoning_capabilities)
        self.assertIn("structured_json", reasoning_capabilities)
        default_provider = next(item for item in data["providers"] if item["provider_id"] == "default_openai")
        default_capabilities = default_provider["models"][0]["capabilities"]
        self.assertIn("fast", default_capabilities)
        self.assertIn("reasoning", default_capabilities)
        self.assertIn("structured_json", default_capabilities)

    def test_deep_route_falls_back_to_fast_reasoning_default_model(self) -> None:
        settings.llm_provider_configs_file = str(self.provider_config_path)

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
        reasoning_provider = next(item for item in data["providers"] if item["provider_id"] == "qwen_reasoning_primary")
        self.assertEqual(reasoning_provider["status"], "available")
        self.assertEqual(reasoning_provider["models"][0]["model_id"], "Qwen3.6-35B-A3B")

    def test_per_model_config_and_probe_inferred_capabilities(self) -> None:
        """对象模型配置保留能力细节，探测新模型不再继承工具能力。"""
        self.provider_config_path.write_text(
            json.dumps(
                [
                    {
                        "provider_id": "default_openai",
                        "display_name": "Default chat model",
                        "provider_type": "openai_compatible",
                        "base_url": "https://fast.example.test/v1",
                        "api_key_env": "LLM_API_KEY",
                        "models": [
                            "legacy-chat-model",
                            {
                                "model_id": "deepseek-v4-flash",
                                "display_name": "DeepSeek V4 Flash",
                                "capabilities": ["chat", "structured_json", "tool_calling"],
                                "recommended_for": ["qa", "deep"],
                                "context_window": 131072,
                                "max_output_tokens": 8192,
                                "tool_protocol": "openai_chat_tools",
                                "supports_parallel_tool_calls": True,
                            },
                        ],
                    }
                ],
            ),
            encoding="utf-8",
        )

        def fake_get(url, **kwargs):  # noqa: ANN001
            if url.endswith("/api/tags"):
                return SimpleNamespace(
                    raise_for_status=lambda: None,
                    json=lambda: {"models": [{"name": "qwen2.5:3b"}]},
                )
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"data": [{"id": "deepseek-v4-flash"}, {"id": "remote-only-model"}]},
            )

        with patch("app.services.llm_model_service.httpx.get", side_effect=fake_get):
            resp = self.client.post("/api/v1/llm/models/check")

        self.assertEqual(resp.status_code, 200, resp.text)
        providers = resp.json()["data"]["providers"]
        provider = next(item for item in providers if item["provider_id"] == "default_openai")
        models = {model["model_id"]: model for model in provider["models"]}
        configured = models["deepseek-v4-flash"]
        self.assertEqual(configured["display_name"], "DeepSeek V4 Flash")
        self.assertIn("tool_calling", configured["capabilities"])
        self.assertEqual(configured["capability_source"], "configured")
        self.assertEqual(configured["context_window"], 131072)
        self.assertEqual(configured["max_output_tokens"], 8192)
        self.assertEqual(configured["tool_protocol"], "openai_chat_tools")
        self.assertTrue(configured["supports_parallel_tool_calls"])

        inferred = models["remote-only-model"]
        self.assertEqual(inferred["capability_source"], "inferred")
        self.assertIn("chat", inferred["capabilities"])
        self.assertNotIn("tool_calling", inferred["capabilities"])
        self.assertEqual(inferred["recommended_for"], [])

    def test_assistant_route_reports_requested_and_resolved_model(self) -> None:
        """用户显式选择的模型返回 user_selected 路由元数据。"""
        def fake_chat(messages, **kwargs):  # noqa: ANN001
            self.assertEqual(kwargs["provider_id"], "qwen_reasoning_primary")
            self.assertEqual(kwargs["model"], "Qwen3.6-35B-A3B")
            return "用户选择回答"

        with patch("app.core.llm_client.chat", side_effect=fake_chat):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [{"role": "user", "content": "解释模型路由"}],
                    "context": {
                        "mode": "qa",
                        "model": {"providerId": "qwen_reasoning_primary", "modelId": "Qwen3.6-35B-A3B"},
                    },
                },
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        route = resp.json()["data"]["grounding_facts"]["llm_route"]
        self.assertEqual(route["route_reason"], "user_selected")
        self.assertEqual(route["requested_provider_id"], "qwen_reasoning_primary")
        self.assertEqual(route["requested_model_id"], "Qwen3.6-35B-A3B")
        self.assertEqual(route["provider_id"], "qwen_reasoning_primary")
        self.assertEqual(route["model_id"], "Qwen3.6-35B-A3B")
        self.assertEqual(route["capability_source"], "configured")

    def test_routing_can_restore_qa_and_deep_to_default_deepseek(self) -> None:
        qwen_payload = {
            "qa": {"provider_id": "qwen_reasoning_primary", "model_id": "Qwen3.6-35B-A3B"},
            "deep": {"provider_id": "qwen_reasoning_primary", "model_id": "Qwen3.6-35B-A3B"},
        }
        resp = self.client.put("/api/v1/llm/routing", json=qwen_payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["qa"]["provider_id"], "qwen_reasoning_primary")

        deepseek_payload = {
            "qa": {"provider_id": "default_openai", "model_id": "DeepSeek-V4-Flash-w8a8-mtp"},
            "deep": {"provider_id": "default_openai", "model_id": "DeepSeek-V4-Flash-w8a8-mtp"},
        }
        resp = self.client.put("/api/v1/llm/routing", json=deepseek_payload)

        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(data["qa"]["provider_id"], "default_openai")
        self.assertEqual(data["qa"]["model_id"], "DeepSeek-V4-Flash-w8a8-mtp")
        self.assertEqual(data["deep"]["provider_id"], "default_openai")
        self.assertEqual(data["deep"]["model_id"], "DeepSeek-V4-Flash-w8a8-mtp")

    def test_legacy_llm_chat_uses_default_route(self) -> None:
        calls = []

        def fake_create(**kwargs):  # noqa: ANN001
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="legacy ok"))])

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
        with patch("app.services.llm_model_service.OpenAI", return_value=fake_client):
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
