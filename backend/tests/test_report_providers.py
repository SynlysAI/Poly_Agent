"""Report provider tests."""

from __future__ import annotations

import sys
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.report_providers.codex_exec import CodexExecReportProvider
from app.services.report_providers.custom_http import CustomHttpReportProvider
from app.services.report_providers.local_ollama import LocalOllamaReportProvider
from app.services.report_providers.mock import MockReportProvider
from app.services.report_providers.openai_compatible import OpenAICompatibleReportProvider
from app.services.report_providers.openai_responses import OpenAIResponsesReportProvider
from app.services.report_providers.registry import ReportProviderRegistry


REPORT_SCHEMA = {
    "type": "object",
    "required": ["title", "abstract", "key_findings", "methods", "results", "limitations", "next_steps"],
}


class ReportProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_report_llm_provider = settings.report_llm_provider
        self.original_report_llm_api_key = settings.report_llm_api_key
        self.original_report_llm_base_url = settings.report_llm_base_url
        self.original_report_llm_model = settings.report_llm_model
        self.original_report_ollama_model = settings.report_ollama_model
        self.original_report_codex_bin = settings.report_codex_bin
        self.original_report_codex_api_key = settings.report_codex_api_key
        settings.report_llm_provider = "mock"
        settings.report_llm_api_key = "test-key"
        settings.report_llm_base_url = "https://llm.example.test/v1"
        settings.report_llm_model = "test-model"
        settings.report_ollama_model = "llama-test"
        settings.report_codex_bin = "codex"
        settings.report_codex_api_key = "codex-test-key"

    def tearDown(self) -> None:
        settings.report_llm_provider = self.original_report_llm_provider
        settings.report_llm_api_key = self.original_report_llm_api_key
        settings.report_llm_base_url = self.original_report_llm_base_url
        settings.report_llm_model = self.original_report_llm_model
        settings.report_ollama_model = self.original_report_ollama_model
        settings.report_codex_bin = self.original_report_codex_bin
        settings.report_codex_api_key = self.original_report_codex_api_key

    def test_mock_provider_returns_structured_report(self) -> None:
        provider = MockReportProvider(model="mock-report-model")

        result = provider.complete_json(
            messages=[{"role": "user", "content": "Generate report"}],
            schema=REPORT_SCHEMA,
            options={"context": {"subject": {"subject_type": "algorithm_run", "subject_id": "ar_1"}}},
        )

        self.assertEqual(result["title"], "研发运行报告")
        self.assertTrue(result["abstract"])
        self.assertIsInstance(result["key_findings"], list)
        for key in REPORT_SCHEMA["required"]:
            self.assertIn(key, result)

    def test_registry_returns_configured_mock_provider(self) -> None:
        provider = ReportProviderRegistry().get_provider()

        self.assertIsInstance(provider, MockReportProvider)

    def test_registry_rejects_unknown_provider(self) -> None:
        settings.report_llm_provider = "unknown"

        with self.assertRaises(ValueError):
            ReportProviderRegistry().get_provider()

    def test_openai_compatible_provider_parses_chat_json(self) -> None:
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"title":"T","abstract":"A","key_findings":[],"methods":[],"results":[],"limitations":[],"next_steps":[]}'
                        )
                    )
                ]
            )

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=fake_create
                )
            )
        )
        with patch("app.services.report_providers.openai_compatible.OpenAI", return_value=fake_client):
            result = OpenAICompatibleReportProvider().complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={},
            )

        self.assertEqual(result["title"], "T")
        self.assertEqual(len(calls), 1)

    def test_openai_compatible_provider_retries_invalid_json_once(self) -> None:
        responses = iter(
            [
                "not-json",
                '{"title":"T2","abstract":"A","key_findings":[],"methods":[],"results":[],"limitations":[],"next_steps":[]}',
            ]
        )
        calls = []
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: (
                        calls.append(kwargs)
                        or SimpleNamespace(
                            choices=[
                                SimpleNamespace(message=SimpleNamespace(content=next(responses)))
                            ]
                        )
                    )
                )
            )
        )
        with patch("app.services.report_providers.openai_compatible.OpenAI", return_value=fake_client):
            result = OpenAICompatibleReportProvider().complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={"max_retries": 1},
            )

        self.assertEqual(result["title"], "T2")
        self.assertEqual(len(calls), 2)
        self.assertIn("上一轮输出不是符合 schema", calls[1]["messages"][-1]["content"])

    def test_openai_responses_provider_parses_response_output_text(self) -> None:
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    output_text='{"title":"R","abstract":"A","key_findings":[],"methods":[],"results":[],"limitations":[],"next_steps":[]}'
                )
            )
        )
        with patch("app.services.report_providers.openai_responses.OpenAI", return_value=fake_client):
            result = OpenAIResponsesReportProvider().complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={},
            )

        self.assertEqual(result["title"], "R")

    def test_openai_responses_provider_retries_missing_required_field(self) -> None:
        responses = iter(
            [
                '{"title":"R"}',
                '{"title":"R2","abstract":"A","key_findings":[],"methods":[],"results":[],"limitations":[],"next_steps":[]}',
            ]
        )
        calls = []
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(
                create=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(output_text=next(responses))
            )
        )
        with patch("app.services.report_providers.openai_responses.OpenAI", return_value=fake_client):
            result = OpenAIResponsesReportProvider().complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={"max_retries": 1},
            )

        self.assertEqual(result["title"], "R2")
        self.assertEqual(len(calls), 2)

    def test_registry_returns_real_provider_types(self) -> None:
        self.assertIsInstance(ReportProviderRegistry().get_provider("openai_compatible"), OpenAICompatibleReportProvider)
        self.assertIsInstance(ReportProviderRegistry().get_provider("openai_responses"), OpenAIResponsesReportProvider)
        self.assertIsInstance(ReportProviderRegistry().get_provider("local_ollama"), LocalOllamaReportProvider)
        self.assertIsInstance(ReportProviderRegistry().get_provider("codex_exec"), CodexExecReportProvider)
        self.assertIsInstance(ReportProviderRegistry().get_provider("custom_http"), CustomHttpReportProvider)

    def test_local_ollama_provider_parses_response_json(self) -> None:
        fake_response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "response": '{"title":"O","abstract":"A","key_findings":[],"methods":[],"results":[],"limitations":[],"next_steps":[]}'
            },
        )
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def post(self, *args, **kwargs):
                return fake_response

        with patch("app.services.report_providers.local_ollama.httpx.Client", return_value=FakeClient()):
            result = LocalOllamaReportProvider().complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={},
            )

        self.assertEqual(result["title"], "O")

    def test_custom_http_provider_parses_nested_report_json(self) -> None:
        fake_response = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "data": {
                    "title": "H",
                    "abstract": "A",
                    "key_findings": [],
                    "methods": [],
                    "results": [],
                    "limitations": [],
                    "next_steps": [],
                }
            },
        )

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def post(self, *args, **kwargs):
                self.last_request = kwargs
                return fake_response

        fake_client = FakeClient()
        with patch("app.services.report_providers.custom_http.httpx.Client", return_value=fake_client):
            result = CustomHttpReportProvider(endpoint_url="https://llm.example.test/report").complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={},
            )

        self.assertEqual(result["title"], "H")
        self.assertNotIn("test-key", str(result))

    def test_custom_http_provider_retries_schema_invalid_response(self) -> None:
        responses = iter(
            [
                {"data": {"title": "missing-required"}},
                {
                    "data": {
                        "title": "H2",
                        "abstract": "A",
                        "key_findings": [],
                        "methods": [],
                        "results": [],
                        "limitations": [],
                        "next_steps": [],
                    }
                },
            ]
        )

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.requests = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def post(self, *args, **kwargs):
                self.requests.append(kwargs)
                return FakeResponse(next(responses))

        fake_client = FakeClient()
        with patch("app.services.report_providers.custom_http.httpx.Client", return_value=fake_client):
            result = CustomHttpReportProvider(endpoint_url="https://llm.example.test/report").complete_json(
                messages=[{"role": "user", "content": "x"}],
                schema=REPORT_SCHEMA,
                options={"max_retries": 1},
            )

        self.assertEqual(result["title"], "H2")
        self.assertEqual(len(fake_client.requests), 2)

    def test_codex_exec_provider_reads_output_file(self) -> None:
        class FakeCompleted:
            returncode = 0
            stdout = "{}"
            stderr = ""

        os.environ["UNRELATED_SECRET_FOR_REPORT_TEST"] = "must-not-leak"

        def fake_run(command, cwd, env, text, capture_output, timeout, check):
            self.assertNotIn("UNRELATED_SECRET_FOR_REPORT_TEST", env)
            self.assertEqual(env.get("CODEX_API_KEY"), "codex-test-key")
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_text(
                '{"title":"C","abstract":"A","key_findings":[],"methods":[],"results":[],"limitations":[],"next_steps":[]}',
                encoding="utf-8",
            )
            return FakeCompleted()

        try:
            with patch("app.services.report_providers.codex_exec.subprocess.run", side_effect=fake_run):
                result = CodexExecReportProvider().complete_json(
                    messages=[{"role": "user", "content": "x"}],
                    schema=REPORT_SCHEMA,
                    options={},
                )
        finally:
            os.environ.pop("UNRELATED_SECRET_FOR_REPORT_TEST", None)

        self.assertEqual(result["title"], "C")
