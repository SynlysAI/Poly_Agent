"""Assistant Slash Command API 与会话状态测试。"""

from __future__ import annotations

from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantRunRepository,
)
from app.main import app
from app.services.assistant_command_parser import CommandParseError, parse_command
from app.schemas.llm_models import LLMModelCatalogData, LLMModelInfo, LLMProviderInfo


class AssistantCommandsApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-1", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def _catalog(self) -> LLMModelCatalogData:
        """构建不依赖外部配置的模型目录。"""
        return LLMModelCatalogData(
            providers=[
                LLMProviderInfo(
                    provider_id="provider-a",
                    display_name="Provider A",
                    provider_type="openai_compatible",
                    status="available",
                    models=[
                        LLMModelInfo(model_id="model-a", display_name="Model A"),
                        LLMModelInfo(model_id="model-b", display_name="Model B"),
                    ],
                )
            ]
        )

    def _chat_id(self) -> str:
        """创建一个空会话并返回 ID。"""
        response = self.client.post("/api/v1/assistant/chats", json={"title": "命令会话"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]["chat_id"]

    def _execute(self, chat_id: str, line: str):
        """执行一条命令并断言 API 成功返回。"""
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": line},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_catalog_plan_goal_permission_model_and_state_persistence(self) -> None:
        chat_id = self._chat_id()
        with patch(
            "app.services.llm_model_service.LLMModelService.get_catalog",
            return_value=self._catalog(),
        ):
            catalog = self.client.get(
                "/api/v1/assistant/commands",
                params={"chat_id": chat_id},
            )
            self.assertEqual(catalog.status_code, 200, catalog.text)
            data = catalog.json()["data"]
            self.assertEqual(data["total"], 5)
            self.assertEqual(
                {item["name"] for item in data["items"]},
                {"plan", "goal", "permission", "model", "status"},
            )
            self.assertEqual(data["session_state"]["permission_mode"], "workspace_write")

            enabled = self._execute(chat_id, "/PLAN")
            self.assertEqual(enabled["status"], "success")
            self.assertTrue(enabled["state_after"]["plan_mode"])

            goal = self._execute(chat_id, "/goal 构建材料实验智能体")
            self.assertEqual(goal["status"], "success")
            self.assertEqual(goal["state_after"]["goal"]["objective"], "构建材料实验智能体")

            permission = self._execute(chat_id, "/permission read-only")
            self.assertEqual(permission["status"], "success")
            self.assertEqual(permission["state_after"]["permission_mode"], "read_only")

            model = self._execute(chat_id, "/model provider-a::model-b")
            self.assertEqual(model["status"], "success")
            self.assertEqual(model["state_after"]["model"]["modelId"], "model-b")

            state = self.client.get(f"/api/v1/assistant/chats/{chat_id}/session-state")
            self.assertEqual(state.status_code, 200, state.text)
            persisted = state.json()["data"]
            self.assertTrue(persisted["plan_mode"])
            self.assertEqual(persisted["permission_mode"], "read_only")
            self.assertEqual(persisted["goal"]["objective"], "构建材料实验智能体")
            self.assertEqual(persisted["model"]["providerId"], "provider-a")

            cleared = self._execute(chat_id, "/goal clear")
            off_plan = self._execute(chat_id, "/plan off")
            full = self._execute(chat_id, "/permission full-access")
            self.assertIsNone(cleared["state_after"]["goal"])
            self.assertFalse(off_plan["state_after"]["plan_mode"])
            self.assertEqual(full["state_after"]["permission_mode"], "full_access")

            interaction = self._execute(chat_id, "/permission")
            self.assertEqual(interaction["status"], "interaction")
            self.assertEqual(
                [choice["value"] for choice in interaction["interaction"]["choices"]],
                ["read_only", "workspace_write", "full_access"],
            )

    def test_unknown_command_gets_closed_failed_result_without_model_run(self) -> None:
        chat_id = self._chat_id()
        result = self._execute(chat_id, "/not-a-command")

        self.assertEqual(result["status"], "failed")
        self.assertIn("未知命令", result["message"])
        runs, total = AssistantRunRepository.list_for_chat(chat_id, "user-1", page=1, page_size=10)
        self.assertEqual(total, 0)
        self.assertEqual(runs, [])

    def test_parser_normalizes_name_and_preserves_raw_args_and_non_command_slash(self) -> None:
        parsed = parse_command("  /PLAN   制定 计划  ")
        self.assertEqual(parsed.name, "plan")
        self.assertEqual(parsed.raw_args, "   制定 计划  ")
        with self.assertRaises(CommandParseError):
            parse_command("https://example.com/a")
        with self.assertRaises(CommandParseError):
            parse_command("路径 /tmp/file 不触发")

    def test_plan_message_enables_mode_and_creates_model_run(self) -> None:
        chat_id = self._chat_id()
        result = self._execute(chat_id, "/plan 制定聚合物实验方案")

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["state_after"]["plan_mode"])
        self.assertIsNotNone(result["run"])
        run = AssistantRunRepository.find_one({"run_id": result["run"]["run_id"]})
        self.assertIsNotNone(run)
        self.assertTrue(run["request_snapshot"]["context"]["plan_mode"])

    def test_legacy_chat_control_fields_receive_defaults_on_read(self) -> None:
        chat_id = self._chat_id()
        chat = AssistantChatRepository.find_one({"chat_id": chat_id}) or {}
        for field in ("plan_mode", "permission_mode", "goal", "todos", "compaction", "command_event_seq"):
            chat.pop(field, None)
        AssistantChatRepository.save("chat_id", chat)

        state = self.client.get(f"/api/v1/assistant/chats/{chat_id}/session-state")
        self.assertEqual(state.status_code, 200, state.text)
        data = state.json()["data"]
        self.assertFalse(data["plan_mode"])
        self.assertEqual(data["permission_mode"], "workspace_write")
        self.assertIsNone(data["goal"])
        self.assertEqual(data["todos"], [])
        self.assertIsNone(data["compaction"])
        self.assertEqual(data["command_event_seq"], 0)
