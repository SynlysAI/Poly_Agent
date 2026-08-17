"""Assistant 流式协议中的算法工具编排测试。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.config import settings
from app.core.auth import get_current_user
from app.core.llm_context import record_message_metadata
from app.infra.computation_repositories import utc_now
from app.infra.llm_repositories import LLMRoutingRepository
from app.infra.research_engine_repositories import (
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
    AssistantEventRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.main import app
from app.schemas.assistant import AssistantChatRequest
from app.services.assistant_service import AssistantService, SearchOutcome
from app.services.assistant_run_service import assistant_run_service
from app.services.assistant_tool_contract import build_json_schema, safe_function_name
from app.services.agent_tool_service import agent_tool_service


class AssistantToolOrchestrationApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._isolate_llm_config()
        self.user = {"user_id": "user-1", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user
        now = utc_now()
        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": "vertical-tool",
                "name": "Vertical Tool",
                "description": "预测分子属性",
                "type": "predictor",
                "algorithm_family": "vertical_prediction",
                "capability_group": "vertical_algorithm",
                "visibility": "public",
                "owner": "owner-1",
                "status": "active",
                "deployment_status": "active",
                "active_version_id": "vertical-tool-v1",
                "input_schema": {
                    "fields": {"smiles": "string - SMILES 结构", "temperature": "number - 温度"},
                    "required": ["smiles"],
                    "constraints": {"temperature": {"minimum": 0, "maximum": 500}},
                },
                "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
                "input_assets": [],
                "output_assets": [],
                "created_at": now,
                "updated_at": now,
            },
        )
        AlgorithmVersionRepository.save(
            "version_id",
            {
                "version_id": "vertical-tool-v1",
                "algorithm_id": "vertical-tool",
                "version": "1.0.0",
                "status": "active",
                "input_schema": {
                    "fields": {"smiles": "string - SMILES 结构", "temperature": "number - 温度"},
                    "required": ["smiles"],
                    "constraints": {"temperature": {"minimum": 0, "maximum": 500}},
                },
                "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
                "input_assets": [],
                "output_assets": [],
                "created_by": "owner-1",
                "created_at": now,
                "updated_at": now,
            },
        )

        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": "list-tool",
                "name": "List Tool",
                "description": "接收配方对象列表并返回预测结果",
                "type": "predictor",
                "algorithm_family": "vertical_prediction",
                "capability_group": "vertical_algorithm",
                "visibility": "public",
                "owner": "owner-1",
                "status": "active",
                "deployment_status": "active",
                "active_version_id": "list-tool-v1",
                "input_schema": {
                    "fields": {"formulations": "list"},
                    "required": ["formulations"],
                },
                "output_schema": {"fields": {"results": "list"}, "required": ["results"]},
                "input_assets": [],
                "output_assets": [],
                "created_at": now,
                "updated_at": now,
            },
        )
        AlgorithmVersionRepository.save(
            "version_id",
            {
                "version_id": "list-tool-v1",
                "algorithm_id": "list-tool",
                "version": "1.0.0",
                "status": "active",
                "input_schema": {
                    "fields": {"formulations": "list"},
                    "required": ["formulations"],
                },
                "output_schema": {"fields": {"results": "list"}, "required": ["results"]},
                "input_assets": [],
                "output_assets": [],
                "created_by": "owner-1",
                "created_at": now,
                "updated_at": now,
            },
        )

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        self._restore_llm_config()
        super().tearDown()

    def _isolate_llm_config(self) -> None:
        """使用自带 tool-capable 模型，隔离环境中的 LLM 配置。"""
        self.original_llm_settings = {
            "llm_model": settings.llm_model,
            "llm_base_url": settings.llm_base_url,
            "llm_api_key": settings.llm_api_key,
            "llm_default_provider": getattr(settings, "llm_default_provider", ""),
            "llm_default_model": getattr(settings, "llm_default_model", ""),
            "llm_reasoning_provider": getattr(settings, "llm_reasoning_provider", ""),
            "llm_reasoning_model": getattr(settings, "llm_reasoning_model", ""),
            "llm_provider_configs_file": getattr(settings, "llm_provider_configs_file", ""),
            "llm_provider_configs_json": getattr(settings, "llm_provider_configs_json", ""),
            "report_ollama_base_url": settings.report_ollama_base_url,
            "report_ollama_model": settings.report_ollama_model,
        }
        self.llm_temp_dir = tempfile.TemporaryDirectory()
        provider_path = Path(self.llm_temp_dir.name) / "providers.json"
        provider_path.write_text(
            json.dumps(
                [
                    {
                        "provider_id": "tool_calling_primary",
                        "display_name": "Tool Calling Primary",
                        "provider_type": "openai_compatible",
                        "base_url": "https://tool-calling.example.test/v1",
                        "models": [
                            {
                                "model_id": "tool-calling-model",
                                "display_name": "Tool Calling Model",
                                "capabilities": ["chat", "tool_calling"],
                                "recommended_for": ["qa", "deep"],
                                "tool_protocol": "openai_chat_tools",
                            },
                            {
                                "model_id": "plain-model",
                                "display_name": "Plain Model",
                                "capabilities": ["chat"],
                                "recommended_for": ["qa"],
                            },
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )
        settings.llm_model = ""
        settings.llm_base_url = ""
        settings.llm_api_key = ""
        settings.llm_default_provider = ""
        settings.llm_default_model = ""
        settings.llm_reasoning_provider = ""
        settings.llm_reasoning_model = ""
        settings.llm_provider_configs_file = str(provider_path)
        settings.llm_provider_configs_json = ""
        settings.report_ollama_base_url = ""
        settings.report_ollama_model = ""
        self.original_routing = LLMRoutingRepository.find_one({"config_id": "global"})
        selection = {"provider_id": "tool_calling_primary", "model_id": "tool-calling-model"}
        LLMRoutingRepository.save(
            "config_id",
            {"config_id": "global", "routing": {"qa": selection, "deep": selection, "report": selection}},
        )

    def _restore_llm_config(self) -> None:
        """恢复测试前的 LLM 环境配置。"""
        for key, value in self.original_llm_settings.items():
            setattr(settings, key, value)
        restored_routing = self.original_routing or {"config_id": "global", "routing": {}}
        LLMRoutingRepository.save("config_id", restored_routing)
        self.llm_temp_dir.cleanup()

    def _chat_and_message(self) -> tuple[str, str]:
        created = self.client.post(
            "/api/v1/assistant/chats",
            json={"title": "工具编排", "selected_tool_ids": ["algorithm:vertical-tool"]},
        )
        chat_id = created.json()["data"]["chat_id"]
        message = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/messages",
            json={"role": "user", "content": "预测 CCO 的属性"},
        ).json()["data"]
        return chat_id, message["message_id"]

    def _stream_events(self, payload: dict) -> list[dict]:
        with self.client.stream("POST", "/api/v1/assistant/chat/stream", json=payload) as resp:
            self.assertEqual(resp.status_code, 200)
            body = "".join(resp.iter_text())
        events: list[dict] = []
        for line in body.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def _no_web_search(self, query: str, *, deep: bool):
        return SearchOutcome(
            status="no_results",
            provider="test",
            query=query,
            results=[],
        )

    def _fake_message(self, tool_calls: list | None = None, content: str | None = None):
        return type(
            "FakeMessage",
            (),
            {"content": content, "tool_calls": tool_calls},
        )()

    def _tool_call(self, name: str, arguments: str, call_id: str | None = None):
        function = type("FakeFunction", (), {"name": name, "arguments": arguments})()
        return type("FakeToolCall", (), {"id": call_id, "type": "function", "function": function})()

    @staticmethod
    def _function_name(tool_id: str) -> str:
        return safe_function_name(tool_id)

    def test_stream_preserves_malformed_raw_arguments_and_proposal_metadata(self) -> None:
        chat_id, message_id = self._chat_and_message()

        def fake_chat_message(messages, **kwargs):
            record_message_metadata(
                {
                    "finish_reason": "tool_calls",
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
                }
            )
            return self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"smiles": "CCO", "temperature":',
                        call_id="provider-call-malformed",
                    )
                ],
            )

        with patch("app.core.llm_client.chat_message", side_effect=fake_chat_message), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        final = events[-1]
        self.assertEqual(final["type"], "final")
        call = final["data"]["tool_calls"][0]
        self.assertEqual(call["phase"], "awaiting_input")
        self.assertEqual(call["missing_fields"], ["smiles"])
        self.assertEqual(call["raw_arguments"], '{"smiles": "CCO", "temperature":')
        self.assertTrue(call["arguments_parse_error"])
        self.assertTrue(call["function_name"].startswith("algorithm_vertical-tool_"))
        self.assertEqual(call["finish_reason"], "tool_calls")
        self.assertEqual(call["proposal_usage"]["total_tokens"], 16)
        persisted = AssistantToolCallRepository.find_one({"call_id": call["call_id"]})
        self.assertEqual(persisted["provider_tool_call_id"], "provider-call-malformed")
        self.assertEqual(persisted["raw_arguments"], '{"smiles": "CCO", "temperature":')
        self.assertTrue(persisted["arguments_parse_error"])
        self.assertRegex(persisted["schema_digest"], r"^[0-9a-f]{16}$")

    def test_stream_reports_provider_error_without_claiming_unsupported_capability(self) -> None:
        chat_id, message_id = self._chat_and_message()

        class AuthenticationError(Exception):
            status_code = 401

        with patch(
            "app.core.llm_client.chat_message",
            side_effect=AuthenticationError("invalid api key"),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        final = events[-1]
        self.assertEqual(final["type"], "final")
        self.assertIn("模型服务鉴权失败", final["data"]["content"])
        self.assertFalse(
            any(
                event.get("type") == "status" and "不支持算法工具调用" in event.get("message", "")
                for event in events
            )
        )

    def test_selected_tool_overrides_plain_model_route(self) -> None:
        plain_selection = {"provider_id": "tool_calling_primary", "model_id": "plain-model"}
        LLMRoutingRepository.save(
            "config_id",
            {
                "config_id": "global",
                "routing": {
                    "qa": plain_selection,
                    "deep": {"provider_id": "tool_calling_primary", "model_id": "tool-calling-model"},
                    "report": plain_selection,
                },
            },
        )
        request = AssistantChatRequest.model_validate(
            {
                "messages": [{"role": "user", "content": "预测 CCO"}],
                "context": {
                    "selected_tool_ids": ["algorithm:vertical-tool"],
                    "model": plain_selection,
                },
            }
        )
        route = AssistantService()._resolve_llm_route(mode="qa", request=request)
        self.assertEqual(route["route_reason"], "tool_capability_override")
        self.assertEqual(route["requested_model_id"], "plain-model")
        self.assertEqual(route["model_id"], "tool-calling-model")
        self.assertIn("tool_calling", route["capabilities"])

    def test_stream_proposes_tool_call_and_persists_pending_call(self) -> None:
        chat_id, message_id = self._chat_and_message()
        captured: dict = {}

        def fake_chat_message(messages, **kwargs):
            captured["tools"] = kwargs.get("tools")
            captured["messages"] = messages
            return self._fake_message(
                tool_calls=[self._tool_call(self._function_name("algorithm:vertical-tool"), '{"smiles": "CCO"}')],
            )

        with patch("app.core.llm_client.chat_message", side_effect=fake_chat_message), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "run_id": "asrun-context-stream",
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        self.assertEqual(
            captured["tools"][0]["function"]["name"],
            self._function_name("algorithm:vertical-tool"),
        )
        self.assertEqual(
            captured["tools"][0]["function"]["parameters"]["required"],
            ["smiles"],
        )
        self.assertEqual(
            captured["tools"][0]["function"]["parameters"]["properties"]["temperature"]["type"],
            "number",
        )
        tool_rules = next(
            item["content"]
            for item in captured["messages"]
            if item.get("role") == "system" and "TOOL_USE_RULES" in item.get("content", "")
        )
        self.assertIn("一次只提出一个", tool_rules)
        self.assertNotIn("一次可以提出多个", tool_rules)
        catalog_event = next(event for event in events if event.get("type") == "tool.catalog.resolved")
        self.assertEqual(catalog_event["tools"], [{"tool_id": "algorithm:vertical-tool"}])
        schema_event = next(event for event in events if event.get("type") == "tool.schema.rendered")
        self.assertEqual(schema_event["tools"][0]["tool_id"], "algorithm:vertical-tool")
        self.assertRegex(schema_event["tools"][0]["schema_digest"], r"^[0-9a-f]{16}$")
        header_event = next(event for event in events if event.get("type") == "request.header")
        context_event = next(event for event in events if event.get("type") == "context.assembled")
        self.assertEqual(header_event["manifest"], context_event["manifest"])
        self.assertLess(events.index(header_event), events.index(context_event))
        manifest = context_event["manifest"]
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["request_kind"], "tool_proposal")
        self.assertEqual(manifest["run_id"], "asrun-context-stream")
        self.assertEqual(manifest["tools"][0]["tool_id"], "algorithm:vertical-tool")
        self.assertEqual(
            manifest["tools"][0]["function_name"],
            self._function_name("algorithm:vertical-tool"),
        )
        self.assertRegex(manifest["tools"][0]["schema_digest"], r"^[0-9a-f]{16}$")
        context_block = next(
            item["content"]
            for item in captured["messages"]
            if item.get("role") == "system" and "PROJECT_FACTS:" in item.get("content", "")
        )
        self.assertIn("SELECTED_TOOLS:", context_block)
        self.assertNotIn("input_json_schema", context_block)
        tool_events = [event for event in events if event.get("type") == "tool_call"]
        self.assertEqual(
            [event["phase"] for event in tool_events],
            ["requested", "awaiting_confirmation"],
        )
        unified_tool_events, _ = AssistantEventRepository.list_all(
            {"call_id": tool_events[0]["call_id"]},
            sort_field="seq",
            reverse=False,
            page=1,
            page_size=100,
        )
        self.assertTrue(unified_tool_events)
        self.assertTrue(all(event["run_id"] == "asrun-context-stream" for event in unified_tool_events))
        final = events[-1]
        self.assertEqual(final["type"], "final")
        self.assertEqual(
            final["data"]["grounding_facts"]["context"]["digest"],
            manifest["context"]["digest"],
        )
        self.assertEqual(final["data"]["tool_calls"][0]["tool_id"], "algorithm:vertical-tool")
        call_id = final["data"]["tool_calls"][0]["call_id"]
        persisted = AssistantToolCallRepository.find_one({"call_id": call_id})
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["chat_id"], chat_id)
        self.assertEqual(persisted["message_id"], message_id)
        self.assertEqual(
            persisted["source_context"]["original_user_message_id"],
            message_id,
        )
        self.assertEqual(
            persisted["source_context"]["selected_tool_ids"],
            ["algorithm:vertical-tool"],
        )
        self.assertIn("tool-calling-model", str(persisted["source_context"]["route_snapshot"]))
        self.assertTrue(persisted["source_context"]["context_manifest_digest"])

    def test_json_schema_maps_bare_list_and_dict(self) -> None:
        tool = agent_tool_service.resolve_callable(
            "list-tool",
            user_id="user-1",
            role="user",
            is_admin=False,
        )
        self.assertIsNotNone(tool)
        properties = build_json_schema(tool)["properties"]
        self.assertEqual(properties["formulations"]["type"], "array")
        self.assertNotIn("items", properties["formulations"])

    def test_stream_wraps_single_object_into_bare_list_field(self) -> None:
        chat_id, message_id = self._chat_and_message()
        captured: dict = {}

        def fake_chat_message(messages, **kwargs):
            captured["tools"] = kwargs.get("tools")
            return self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:list-tool"),
                        '{"formulations": {"lithium_salt": "LiTFSI"}}',
                    )
                ],
            )

        with patch("app.core.llm_client.chat_message", side_effect=fake_chat_message), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测这个配方"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:list-tool"],
                    },
                }
            )

        properties = captured["tools"][0]["function"]["parameters"]["properties"]
        self.assertEqual(properties["formulations"]["type"], "array")
        self.assertNotIn("items", properties["formulations"])
        final = events[-1]
        self.assertEqual(final["type"], "final")
        calls = final["data"]["tool_calls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["arguments"]["formulations"],
            [{"lithium_salt": "LiTFSI"}],
        )
        self.assertEqual(calls[0]["phase"], "awaiting_confirmation")

    def test_stream_prefers_version_model_proposal_over_provider_arguments(self) -> None:
        """active 版本显式模型模板应覆盖 provider 根据用户上下文生成的参数。"""
        AlgorithmVersionRepository.update_fields(
            "vertical-tool-v1",
            {"model_proposal": {"smiles": "C=C(F)F", "temperature": 320}},
        )
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"smiles": "O=C1OC(=O)c2cc3C(=O)OC(=O)c3cc12", "temperature": 298}',
                    ),
                ],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测这个分子的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        final = events[-1]
        self.assertEqual(final["type"], "final")
        calls = final["data"]["tool_calls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["arguments"], {"smiles": "C=C(F)F", "temperature": 320})
        persisted = AssistantToolCallRepository.find_one({"call_id": calls[0]["call_id"]})
        self.assertEqual(persisted["arguments"], {"smiles": "C=C(F)F", "temperature": 320})
        self.assertEqual(
            json.loads(persisted["raw_arguments"]),
            {"smiles": "C=C(F)F", "temperature": 320},
        )
        self.assertEqual(
            persisted["source_context"]["argument_sources"],
            {"smiles": "version_model_proposal", "temperature": "version_model_proposal"},
        )

    def test_stream_uses_explicit_version_model_proposal_for_reactivity_rows(self) -> None:
        """active 版本显式模板应覆盖 provider 自由生成的英文行契约。"""
        schema = {
            "fields": {"data_rows": "list", "conversion_error_pct": "number"},
            "required": ["data_rows"],
            "field_defaults": {"conversion_error_pct": 1},
            "ui_hints": {
                "data_rows": {"label": "实验数据", "columns": ["比例", "转化率1", "转化率2"]},
            },
        }
        proposal = {
            "data_rows": [
                {"比例": 0.2, "转化率1": 0.0035, "转化率2": 0.0177},
                {"比例": 0.3, "转化率1": 0.0045, "转化率2": 0.0338},
            ],
            "conversion_error_pct": 0.05,
        }
        AlgorithmRegistryRepository.update_fields("vertical-tool", {"input_schema": schema})
        AlgorithmVersionRepository.update_fields(
            "vertical-tool-v1",
            {"input_schema": schema, "model_proposal": proposal},
        )
        chat_id, message_id = self._chat_and_message()
        provider_arguments = {
            "data_rows": [
                {"ratio": 0.2, "conversion1": 0.0177, "conversion2": 0.0035},
                {"ratio": 0.3, "conversion1": 0.0338, "conversion2": 0.0045},
            ]
        }
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        json.dumps(provider_arguments, ensure_ascii=False),
                    ),
                ],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "算算这个比例转化率1转化率2"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        calls = events[-1]["data"]["tool_calls"]
        self.assertEqual(calls[0]["arguments"], proposal)
        persisted = AssistantToolCallRepository.find_one({"call_id": calls[0]["call_id"]})
        self.assertEqual(persisted["arguments"], proposal)
        self.assertEqual(json.loads(persisted["raw_arguments"]), proposal)
        self.assertEqual(
            persisted["source_context"]["argument_sources"],
            {"data_rows": "version_model_proposal", "conversion_error_pct": "version_model_proposal"},
        )

    def test_stream_overrides_wrong_provider_arguments_with_version_model_proposal(self) -> None:
        """显式版本模板应覆盖明显异常的 provider 值。"""
        AlgorithmVersionRepository.update_fields(
            "vertical-tool-v1",
            {"model_proposal": {"smiles": "C=C(F)F", "temperature": 320}},
        )
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"smiles": "WRONG"}',
                    ),
                ],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测这个分子的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        calls = events[-1]["data"]["tool_calls"]
        self.assertEqual(calls[0]["arguments"], {"smiles": "C=C(F)F", "temperature": 320})

    def test_stream_completes_missing_provider_input_from_version_model_proposal(self) -> None:
        """显式版本模板应补足 provider 缺失的必填字段。"""
        AlgorithmVersionRepository.update_fields(
            "vertical-tool-v1",
            {"model_proposal": {"smiles": "C=C(F)F", "temperature": 320}},
        )
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"temperature": 298}',
                    ),
                ],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测这个分子的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        calls = events[-1]["data"]["tool_calls"]
        self.assertEqual(calls[0]["phase"], "awaiting_confirmation")
        self.assertEqual(calls[0]["missing_fields"], [])
        self.assertEqual(calls[0]["arguments"], {"smiles": "C=C(F)F", "temperature": 320})

    def test_stream_recovers_malformed_provider_arguments_with_version_model_proposal(self) -> None:
        """显式版本模板应恢复 provider malformed JSON 导致的缺失参数。"""
        AlgorithmVersionRepository.update_fields(
            "vertical-tool-v1",
            {"model_proposal": {"smiles": "C=C(F)F", "temperature": 320}},
        )
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"smiles": "CCO", "temperature":',
                    ),
                ],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        calls = events[-1]["data"]["tool_calls"]
        self.assertEqual(calls[0]["phase"], "awaiting_confirmation")
        self.assertEqual(calls[0]["missing_fields"], [])
        self.assertEqual(calls[0]["arguments"], {"smiles": "C=C(F)F", "temperature": 320})
        self.assertEqual(
            json.loads(calls[0]["raw_arguments"]),
            {"smiles": "C=C(F)F", "temperature": 320},
        )

    def test_stream_surfaces_tool_proposal_validation_error(self) -> None:
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"smiles": "CCO", "bogus": 1}',
                    ),
                ],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        final = events[-1]
        self.assertEqual(final["type"], "final")
        self.assertIn("未能生成算法调用卡片", final["data"]["content"])
        self.assertIn("bogus", final["data"]["content"])
        self.assertEqual(final["data"]["tool_calls"], [])

    def test_stream_continuation_injects_real_run_result(self) -> None:
        chat_id, message_id = self._chat_and_message()
        call = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={
                "tool_id": "algorithm:vertical-tool",
                "chat_id": chat_id,
                "message_id": message_id,
                "arguments": {"smiles": "CCO", "temperature": 300},
            },
        ).json()["data"]
        call_id = call["call_id"]

        def fake_run(_service, payload, *, actor_user_id, is_admin=False, request_id=None, input_asset_uploads=None):
            return type(
                "FakeRun",
                (),
                {
                    "run_id": "arun-orchestrator-1",
                    "algorithm_id": payload.algorithm_id,
                    "algorithm_version_id": payload.algorithm_version_id,
                    "status": "completed",
                    "output_summary": {"score": 0.88},
                    "artifact_refs": [{"artifact_id": "artifact-x", "name": "result.json"}],
                    "error": None,
                },
            )()

        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        captured: dict = {}

        def fake_stream(messages, **kwargs):
            captured["messages"] = messages
            yield "基于运行结果：分数 0.88。"

        with patch("app.core.llm_client.chat_stream", side_effect=fake_stream), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "tool_call_ids": [call_id],
                    },
                }
            )

        tool_events = [event for event in events if event.get("type") == "tool_call"]
        self.assertTrue(tool_events)
        self.assertEqual(tool_events[-1]["phase"], "completed")
        self.assertIn("result_summary", str(captured["messages"]))
        self.assertIn("arun-orchestrator-1", str(captured["messages"]))
        self.assertTrue(
            any(
                item.get("role") == "tool" and item.get("tool_call_id") == call_id
                for item in captured["messages"]
            )
        )
        final = events[-1]
        self.assertEqual(final["type"], "final")
        self.assertIn("0.88", final["data"]["content"])

    def test_continuation_reuses_provider_tool_call_id(self) -> None:
        chat_id, message_id = self._chat_and_message()
        captured: dict = {}

        def fake_chat_message(messages, **kwargs):
            return self._fake_message(
                tool_calls=[
                    self._tool_call(
                        self._function_name("algorithm:vertical-tool"),
                        '{"smiles": "CCO"}',
                        call_id="provider-call-123",
                    )
                ],
            )

        with patch("app.core.llm_client.chat_message", side_effect=fake_chat_message), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        call_id = events[-1]["data"]["tool_calls"][0]["call_id"]
        persisted = AssistantToolCallRepository.find_one({"call_id": call_id})
        self.assertEqual(persisted["provider_tool_call_id"], "provider-call-123")

        def fake_run(_service, payload, *, actor_user_id, is_admin=False, request_id=None, input_asset_uploads=None):
            return type(
                "FakeRun",
                (),
                {
                    "run_id": "arun-provider-id-1",
                    "algorithm_id": payload.algorithm_id,
                    "algorithm_version_id": payload.algorithm_version_id,
                    "status": "completed",
                    "output_summary": {"score": 0.88},
                    "artifact_refs": [],
                    "error": None,
                },
            )()

        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        second = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={
                "tool_id": "algorithm:vertical-tool",
                "chat_id": chat_id,
                "message_id": message_id,
                "arguments": {"smiles": "CCN", "temperature": 310},
            },
        ).json()["data"]
        second_call_id = second["call_id"]
        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=fake_run,
        ):
            second_confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{second_call_id}/confirm")
        self.assertEqual(second_confirmed.status_code, 200, second_confirmed.text)

        def fake_stream(messages, **kwargs):
            captured["messages"] = messages
            yield "基于运行结果：分数 0.88。"

        with patch("app.core.llm_client.chat_stream", side_effect=fake_stream), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            continuation = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "tool_call_ids": [call_id, second_call_id],
                    },
                }
            )

        assistant_message = next(item for item in captured["messages"] if item.get("tool_calls"))
        tool_message = next(item for item in captured["messages"] if item.get("role") == "tool")
        assistant_tool_call = assistant_message["tool_calls"][0]
        self.assertEqual(assistant_tool_call["id"], "provider-call-123")
        self.assertEqual(tool_message["tool_call_id"], "provider-call-123")
        self.assertEqual(len(assistant_message["tool_calls"]), 2)
        self.assertEqual(
            len([item for item in captured["messages"] if item.get("role") == "tool"]),
            2,
        )
        self.assertEqual(continuation[-1]["type"], "final")

    def test_server_continuation_is_scheduled_and_idempotent(self) -> None:
        chat_id, message_id = self._chat_and_message()
        call = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={
                "tool_id": "algorithm:vertical-tool",
                "chat_id": chat_id,
                "message_id": message_id,
                "arguments": {"smiles": "CCO", "temperature": 300},
            },
        ).json()["data"]
        call_id = call["call_id"]

        def fake_run(_service, payload, *, actor_user_id, is_admin=False, request_id=None, input_asset_uploads=None):
            return type(
                "FakeRun",
                (),
                {
                    "run_id": "arun-server-continuation-1",
                    "algorithm_id": payload.algorithm_id,
                    "algorithm_version_id": payload.algorithm_version_id,
                    "status": "completed",
                    "output_summary": {"score": 0.91},
                    "artifact_refs": [{"artifact_id": "artifact-x", "name": "result.json"}],
                    "error": None,
                },
            )()

        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        persisted = AssistantToolCallRepository.find_one({"call_id": call_id})
        self.assertEqual(persisted["phase"], "completed")
        self.assertEqual(persisted["continuation_state"], "pending")
        events = AssistantToolCallRepository.list_events(call_id)
        self.assertTrue(any(event["type"] == "tool.continuation.scheduled" for event in events))

        self.assertEqual(assistant_run_service.process_continuations("continuation-worker"), 1)
        run_doc = AssistantRunRepository.find_by_continuation_key(call_id)
        self.assertIsNotNone(run_doc)
        run_context = run_doc["request_snapshot"]["context"]
        self.assertEqual(run_context["tool_call_ids"], [call_id])
        self.assertEqual(run_context["continuation_key"], call_id)
        self.assertEqual(run_context["continuation_source"]["original_user_message_id"], message_id)

        self.assertEqual(assistant_run_service.process_continuations("continuation-worker"), 0)
        persisted = AssistantToolCallRepository.find_one({"call_id": call_id})
        self.assertEqual(persisted["continuation_run_id"], run_doc["run_id"])
        self.assertEqual(persisted["continuation_state"], "scheduled")

        chat = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        self.assertEqual([item["role"] for item in chat["messages"]], ["user"])

    def test_server_continuation_executes_and_finalizes_tool_call(self) -> None:
        chat_id, message_id = self._chat_and_message()
        call = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={
                "tool_id": "algorithm:vertical-tool",
                "chat_id": chat_id,
                "message_id": message_id,
                "arguments": {"smiles": "CCO", "temperature": 300},
            },
        ).json()["data"]
        call_id = call["call_id"]

        def fake_run(_service, payload, *, actor_user_id, is_admin=False, request_id=None, input_asset_uploads=None):
            return type(
                "FakeRun",
                (),
                {
                    "run_id": "arun-server-continuation-2",
                    "algorithm_id": payload.algorithm_id,
                    "algorithm_version_id": payload.algorithm_version_id,
                    "status": "completed",
                    "output_summary": {"score": 0.92},
                    "artifact_refs": [],
                    "error": None,
                },
            )()

        with patch(
            "app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run",
            new=fake_run,
        ):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        self.assertEqual(assistant_run_service.process_continuations("continuation-worker"), 1)
        run_doc = AssistantRunRepository.find_by_continuation_key(call_id)
        self.assertIsNotNone(run_doc)
        run_id = run_doc["run_id"]

        events = [
            {"type": "status", "stage": "generation", "message": "正在生成回答..."},
            {"type": "answer_delta", "delta": "基于运行结果：分数 0.92。"},
            {
                "type": "final",
                "data": {
                    "content": "基于运行结果：分数 0.92。",
                    "answer_mode": "fallback",
                    "answer_scope": "unknown",
                    "retrieval_status": "not_needed",
                },
            },
        ]
        with patch(
            "app.services.assistant_run_service.stream_chat_assistant",
            return_value=iter(events),
        ):
            self.assertEqual(assistant_run_service.execute_next("continuation-exec-worker"), run_id)

        chat = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        self.assertEqual([item["role"] for item in chat["messages"]], ["user", "assistant"])
        self.assertEqual(chat["messages"][1]["tool_call_ids"], [call_id])
        self.assertEqual(
            chat["messages"][1]["metadata"]["continuation_tool_call_ids"],
            [call_id],
        )
        persisted = AssistantToolCallRepository.find_one({"call_id": call_id})
        self.assertEqual(persisted["continuation_state"], "completed")
        self.assertEqual(persisted["continuation_run_id"], run_id)

    def test_stream_falls_back_to_qa_when_model_does_not_support_tools(self) -> None:
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            side_effect=AssertionError("tool proposal should not start"),
        ), patch("app.core.llm_client.chat_stream", return_value=iter(["普通回答"])), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ), patch.object(
            AssistantService,
            "_resolve_llm_route",
            return_value={
                "purpose": "qa",
                "provider_id": "tool_calling_primary",
                "provider_type": "openai_compatible",
                "model_id": "plain-model",
                "capabilities": ["chat"],
            },
        ):
            events = self._stream_events(
                {
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                }
            )

        statuses = [event["message"] for event in events if event.get("type") == "status"]
        self.assertTrue(any("不支持算法工具调用" in message for message in statuses))
        self.assertEqual(events[-1]["type"], "final")
        self.assertEqual(events[-1]["data"]["content"], "普通回答")
        self.assertEqual(events[-1]["data"]["tool_calls"], [])

    def test_chat_proposes_tool_call_without_stream(self) -> None:
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[self._tool_call(self._function_name("algorithm:vertical-tool"), '{"smiles": "CCO"}')],
            ),
        ), patch(
            "app.services.assistant_service.AssistantWebSearchService.search",
            side_effect=self._no_web_search,
        ):
            resp = self.client.post(
                "/api/v1/assistant/chat",
                json={
                    "messages": [{"role": "user", "content": "预测 CCO 的属性"}],
                    "context": {
                        "mode": "qa",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "selected_tool_ids": ["algorithm:vertical-tool"],
                    },
                },
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual(len(data["tool_calls"]), 1)
        self.assertEqual(data["tool_calls"][0]["algorithm_id"], "vertical-tool")
        self.assertIn("确认", data["content"])

    def test_parallel_tool_call_budget_is_configurable(self) -> None:
        service = AssistantService()
        route = {"supports_parallel_tool_calls": True}
        with patch.object(settings, "assistant_max_parallel_tool_calls", 3):
            self.assertEqual(service._max_parallel_tool_calls(route, [object()]), 3)
        with patch.object(settings, "assistant_max_parallel_tool_calls", 1):
            self.assertEqual(service._max_parallel_tool_calls(route, [object()]), 1)
        self.assertEqual(service._max_parallel_tool_calls({"supports_parallel_tool_calls": False}, [object()]), 1)
