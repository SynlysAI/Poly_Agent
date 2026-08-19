"""Dynamic Assistant tool Slash Command API tests."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmRunRepository,
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
    AssistantMessageRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.main import app
from app.schemas.assistant_commands import CommandDescriptor
from app.services.assistant_command_registry import AssistantCommandRegistry, dynamic_slug
from app.services.assistant_command_service import assistant_command_service
from app.services.assistant_run_service import AssistantRunService
from app.services.assistant_tool_service import assistant_tool_call_service
from app.services.assistant_tool_command_provider import _command_category


class AssistantDynamicToolCommandTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-1", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user
        self._save_vertical_tool()

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _save_vertical_tool() -> None:
        """Persist one public vertical algorithm with developer attribution."""
        now = utc_now()
        registry = {
            "algorithm_id": "Vertical Predictor.v2",
            "name": "Vertical Predictor",
            "description": "Predict a polymer property",
            "type": "predictor",
            "algorithm_family": "vertical_prediction",
            "material_scope": ["polymer"],
            "task_scope": ["COMPUTE_PREDICT"],
            "capability_group": "vertical_algorithm",
            "tool_type": "prediction",
            "visibility": "public",
            "owner": "owner-1",
            "status": "active",
            "deployment_status": "active",
            "active_version_id": "vertical-predictor-v1",
            "trigger_modes": ["human_workflow"],
            "source": "Example Lab",
            "source_kind": "uploaded_package",
            "input_schema": {
                "fields": {
                    "smiles": "string",
                    "temperature": "number",
                    "verbose": "boolean",
                    "tags": "list[string]",
                    "constraints": "dict[string, float]",
                },
                "required": ["smiles"],
                "field_options": {},
            },
            "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
            "input_assets": [],
            "output_assets": [],
            "developer_attribution": {
                "name": "Example Lab Model Team",
                "role": "developer",
                "organization": "Example Lab",
                "url": "https://example.com/vertical-predictor",
            },
            "framework_attributions": [
                {
                    "name": "Polymer Property Framework",
                    "role": "framework_reference",
                    "url": "https://example.com/framework",
                }
            ],
            "method_attributions": [],
            "created_at": now,
            "updated_at": now,
        }
        AlgorithmRegistryRepository.save("algorithm_id", registry)
        AlgorithmVersionRepository.save(
            "version_id",
            {
                "version_id": "vertical-predictor-v1",
                "algorithm_id": "Vertical Predictor.v2",
                "name": registry["name"],
                "version": "1.0.0",
                "status": "active",
                "input_schema": registry["input_schema"],
                "output_schema": registry["output_schema"],
                "input_assets": [],
                "output_assets": [],
                "resource_assets": [],
                "created_by": "user-1",
                "created_at": now,
                "updated_at": now,
            },
        )

    def _chat_id(self) -> str:
        """Create an owned chat and return its ID."""
        response = self.client.post("/api/v1/assistant/chats", json={"title": "动态命令"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["chat_id"]

    def test_catalog_derives_tool_command_with_schema_and_attribution(self) -> None:
        chat_id = self._chat_id()
        response = self.client.get("/api/v1/assistant/commands", params={"chat_id": chat_id})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["data"]["items"]
        command = next(item for item in items if item["tool_id"] == "algorithm:Vertical Predictor.v2")

        self.assertEqual(command["name"], "vertical-predictor-v2")
        self.assertEqual(command["category"], "tool")
        self.assertEqual(command["input_mode"], "tool_schema")
        self.assertEqual(command["algorithm_id"], "Vertical Predictor.v2")
        self.assertTrue(command["requires_confirmation"])
        self.assertEqual(set(command["tool_json_schema"]["properties"]), {
            "smiles", "temperature", "verbose", "tags", "constraints"
        })
        self.assertEqual(command["attributions"][0]["organization"], "Example Lab")

    def test_dynamic_slug_normalization_and_builtin_conflict_receive_hash(self) -> None:
        class Provider:
            @staticmethod
            def descriptors(_current_user=None):
                return [
                    CommandDescriptor(
                        name=dynamic_slug("Plan Predictor.v2!!"),
                        title="Plan Predictor",
                        description="External plan algorithm",
                        usage="/plan",
                        category="tool",
                        source="External Algorithm",
                        input_mode="tool_schema",
                        tool_id="algorithm:plan-predictor",
                    )
                ]

        self.assertEqual(dynamic_slug("Plan Predictor.v2!!"), "plan-predictor-v2")
        registry = AssistantCommandRegistry()
        registry.register_provider(Provider(), lambda *_args, **_kwargs: None)
        dynamic_names = [
            item.name
            for item in registry.descriptors(None)
            if item.tool_id == "algorithm:plan-predictor"
        ]
        self.assertEqual(len(dynamic_names), 1)
        self.assertNotEqual(dynamic_names[0], "plan")
        self.assertTrue(dynamic_names[0].startswith("plan-"))

    def test_tool_command_category_uses_capability_group(self) -> None:
        tool = SimpleNamespace(
            algorithm_family="vertical_prediction",
            tool_type="workflow",
            capability_group="agent_skill",
        )
        self.assertEqual(_command_category(tool), "skill")

    def test_dynamic_command_creates_existing_tool_call_and_owned_hidden_message(self) -> None:
        chat_id = self._chat_id()
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={
                "chat_id": chat_id,
                "line": '/vertical-predictor-v2 {"smiles":"CCO"}',
                "payload": {"task_content": "请解释预测结果"},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]

        self.assertEqual(result["status"], "interaction")
        self.assertEqual(result["message"], "已创建算法工具调用，请在参数表单中确认。")
        self.assertEqual(result["tool_call"]["phase"], "awaiting_confirmation")
        self.assertEqual(result["tool_call"]["arguments"]["smiles"], "CCO")
        self.assertEqual(result["tool_call"]["command_id"], result["command_id"])
        self.assertEqual(result["tool_call"]["attributions"][0]["organization"], "Example Lab")

        confirmed = self.client.post(
            f"/api/v1/assistant/tool-calls/{result['tool_call']['call_id']}/confirm",
            json={},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        confirmed_call = confirmed.json()["data"]
        self.assertEqual(confirmed_call["phase"], "queued", confirmed.text)
        run = AlgorithmRunRepository.find_one({
            "trigger_context_id": confirmed_call["call_id"]
        })
        self.assertIsNotNone(run)
        self.assertEqual(confirmed_call["run_id"], run["run_id"])
        self.assertEqual(confirmed_call["trace_id"], result["command_id"])

        call = AssistantToolCallRepository.find_one({"command_id": result["command_id"]})
        self.assertIsNotNone(call)
        message = AssistantMessageRepository.find_one({"message_id": call["message_id"]})
        self.assertEqual(message["metadata"]["origin"], "slash_command")
        self.assertFalse(message["metadata"]["model_visible"])
        self.assertEqual(message["metadata"]["command_id"], result["command_id"])
        self.assertEqual(message["metadata"]["task_content"], "请解释预测结果")

        visible = AssistantRunService.model_visible_messages([
            {"role": "user", "content": "visible"},
            {"role": "user", "content": "hidden", "metadata": {"model_visible": False}},
        ])
        self.assertEqual(visible, [{"role": "user", "content": "visible"}])

    def test_read_only_blocks_dynamic_command_creation_with_permission_event(self) -> None:
        chat_id = self._chat_id()
        enabled = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/permission read-only"},
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)

        catalog = self.client.get("/api/v1/assistant/commands", params={"chat_id": chat_id})
        self.assertEqual(catalog.status_code, 200, catalog.text)
        dynamic_command = next(
            item for item in catalog.json()["data"]["items"]
            if item["tool_id"] == "algorithm:Vertical Predictor.v2"
        )
        self.assertFalse(dynamic_command["available"])
        self.assertIn("只读", dynamic_command["unavailable_reason"])

        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/vertical-predictor-v2"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]
        self.assertEqual(result["status"], "failed")
        self.assertIn("只读模式", result["message"])
        self.assertIsNone(AssistantToolCallRepository.find_one({"command_id": result["command_id"]}))

        events, _ = assistant_command_service.command_events(chat_id, self.user)
        decisions = [
            event for event in events
            if event.get("type") == "permission.decision"
            and (event.get("data") or {}).get("command_id") == result["command_id"]
        ]
        self.assertTrue(decisions)
        self.assertEqual(decisions[0]["data"]["reason"], "read_only_blocked")

    def test_plan_mode_marks_dynamic_commands_unavailable_in_catalog(self) -> None:
        chat_id = self._chat_id()
        enabled = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/plan"},
        )
        self.assertEqual(enabled.status_code, 200, enabled.text)

        response = self.client.get("/api/v1/assistant/commands", params={"chat_id": chat_id})
        self.assertEqual(response.status_code, 200, response.text)
        dynamic_command = next(
            item for item in response.json()["data"]["items"]
            if item["tool_id"] == "algorithm:Vertical Predictor.v2"
        )
        self.assertFalse(dynamic_command["available"])
        self.assertIn("Plan Mode", dynamic_command["unavailable_reason"])

    def test_continuation_requires_task_content_and_prefers_it(self) -> None:
        chat_id = self._chat_id()
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/vertical-predictor-v2"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]
        self.assertEqual(result["tool_call"]["phase"], "awaiting_input")
        self.assertIn("smiles", result["tool_call"]["missing_fields"])
        call = AssistantToolCallRepository.find_one({"command_id": result["command_id"]})

        AssistantToolCallRepository.update_fields(call["call_id"], {"phase": "completed"})
        call = AssistantToolCallRepository.find_one({"call_id": call["call_id"]}) or call
        assistant_tool_call_service._schedule_continuation(call)
        call = AssistantToolCallRepository.find_one({"call_id": call["call_id"]})
        self.assertEqual(call["continuation_state"], "skipped")
        self.assertEqual(
            call["continuation_error"]["error_type"],
            "MISSING_TASK_CONTENT",
        )
        self.assertEqual(
            AssistantRunService.continuation_user_content(
                {"content": "/vertical-predictor-v2"},
                {"task_content": "请解释预测结果"},
            ),
            "请解释预测结果",
        )
        with self.assertRaises(HTTPException) as raised:
            AssistantRunService()._ensure_continuation_run(call)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            raised.exception.detail,
            {"code": "MISSING_TASK_CONTENT", "message": "未提供任务说明，不自动生成续答"},
        )

    def test_task_content_creates_command_owned_continuation(self) -> None:
        chat_id = self._chat_id()
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/vertical-predictor-v2 请解释预测结果"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]
        call_id = result["tool_call"]["call_id"]
        self.assertEqual(result["tool_call"]["phase"], "awaiting_input")

        updated = self.client.patch(
            f"/api/v1/assistant/tool-calls/{call_id}/input",
            json={"arguments": {"smiles": "CCO"}},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        confirmed = self.client.post(
            f"/api/v1/assistant/tool-calls/{call_id}/confirm",
            json={},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        AssistantToolCallRepository.update_fields(call_id, {"phase": "completed"})
        call = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        assistant_tool_call_service._schedule_continuation(call)
        call = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        self.assertEqual(call["continuation_state"], "pending")
        self.assertTrue(AssistantRunService()._ensure_continuation_run(call))

        run = AssistantRunRepository.find_by_continuation_key(call_id)
        self.assertIsNotNone(run)
        self.assertEqual(
            run["request_snapshot"]["messages"],
            [{"role": "user", "content": "请解释预测结果"}],
        )
        self.assertEqual(run["request_snapshot"]["context"]["command_id"], result["command_id"])
