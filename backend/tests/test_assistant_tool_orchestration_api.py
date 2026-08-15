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
from app.infra.computation_repositories import utc_now
from app.infra.llm_repositories import LLMRoutingRepository
from app.infra.research_engine_repositories import (
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
    AssistantToolCallRepository,
)
from app.main import app
from app.services.assistant_service import AssistantService, SearchOutcome


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
                            }
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

    def test_stream_proposes_tool_call_and_persists_pending_call(self) -> None:
        chat_id, message_id = self._chat_and_message()
        captured: dict = {}

        def fake_chat_message(messages, **kwargs):
            captured["tools"] = kwargs.get("tools")
            captured["messages"] = messages
            return self._fake_message(
                tool_calls=[self._tool_call("algorithm_vertical-tool", '{"smiles": "CCO"}')],
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

        self.assertEqual(captured["tools"][0]["function"]["name"], "algorithm_vertical-tool")
        self.assertEqual(
            captured["tools"][0]["function"]["parameters"]["required"],
            ["smiles"],
        )
        self.assertEqual(
            captured["tools"][0]["function"]["parameters"]["properties"]["temperature"]["type"],
            "number",
        )
        tool_events = [event for event in events if event.get("type") == "tool_call"]
        self.assertEqual(
            [event["phase"] for event in tool_events],
            ["requested", "awaiting_confirmation"],
        )
        final = events[-1]
        self.assertEqual(final["type"], "final")
        self.assertEqual(final["data"]["tool_calls"][0]["tool_id"], "algorithm:vertical-tool")
        call_id = final["data"]["tool_calls"][0]["call_id"]
        persisted = AssistantToolCallRepository.find_one({"call_id": call_id})
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["chat_id"], chat_id)
        self.assertEqual(persisted["message_id"], message_id)

    def test_property_schema_maps_bare_list_and_dict(self) -> None:
        schema = type("FakeSchema", (), {"field_options": {}, "constraints": {}})()
        self.assertEqual(
            AssistantService._property_schema("formulations", "list", schema)["type"],
            "array",
        )
        self.assertNotIn(
            "items",
            AssistantService._property_schema("formulations", "list", schema),
        )
        self.assertEqual(
            AssistantService._property_schema("formulations", "array", schema)["type"],
            "array",
        )
        self.assertEqual(
            AssistantService._property_schema("meta", "dict", schema)["type"],
            "object",
        )
        self.assertEqual(
            AssistantService._property_schema("items", "list[string]", schema)["items"]["type"],
            "string",
        )

    def test_stream_wraps_single_object_into_bare_list_field(self) -> None:
        chat_id, message_id = self._chat_and_message()
        captured: dict = {}

        def fake_chat_message(messages, **kwargs):
            captured["tools"] = kwargs.get("tools")
            return self._fake_message(
                tool_calls=[
                    self._tool_call(
                        "algorithm_list-tool",
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

    def test_stream_surfaces_tool_proposal_validation_error(self) -> None:
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            return_value=self._fake_message(
                tool_calls=[
                    self._tool_call("algorithm_vertical-tool", '{"smiles": "CCO", "bogus": 1}'),
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
                        "algorithm_vertical-tool",
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

    def test_stream_falls_back_to_qa_when_model_does_not_support_tools(self) -> None:
        chat_id, message_id = self._chat_and_message()
        with patch(
            "app.core.llm_client.chat_message",
            side_effect=RuntimeError("tools not supported"),
        ), patch("app.core.llm_client.chat_stream", return_value=iter(["普通回答"])), patch(
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
                tool_calls=[self._tool_call("algorithm_vertical-tool", '{"smiles": "CCO"}')],
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
