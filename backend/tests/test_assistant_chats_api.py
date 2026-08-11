"""Assistant chat/message CRUD and tool-call restoration tests."""

from __future__ import annotations

from unittest.mock import patch

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import AlgorithmRegistryRepository, AlgorithmVersionRepository
from app.main import app


class AssistantChatsApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-1", "username": "user", "role": "user", "status": "active"}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def test_chat_and_message_crud_persists_options_and_supports_search_archive(self) -> None:
        created = self.client.post(
            "/api/v1/assistant/chats",
            json={
                "model": {"providerId": "default_openai", "modelId": "gpt-test"},
                "mode": "deep",
                "knowledge_base_ids": ["kb-1"],
                "knowledge_base_names": ["Materials"],
                "use_web_search": True,
                "selected_tool_ids": [],
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        chat = created.json()["data"]
        self.assertEqual(chat["title"], "新对话")
        self.assertEqual(chat["mode"], "deep")
        self.assertTrue(chat["use_web_search"])

        user_message = self.client.post(
            f"/api/v1/assistant/chats/{chat['chat_id']}/messages",
            json={"role": "user", "content": "  查找聚酰亚胺透过性  "},
        )
        self.assertEqual(user_message.status_code, 200, user_message.text)
        message = user_message.json()["data"]
        self.assertEqual(message["role"], "user")

        assistant_message = self.client.post(
            f"/api/v1/assistant/chats/{chat['chat_id']}/messages",
            json={
                "role": "assistant",
                "content": "结果见引用",
                "references": [{"label": "研究计划", "target": "doc/plan.md"}],
                "reasoning_summary": ["已检索项目事实"],
            },
        )
        self.assertEqual(assistant_message.status_code, 200, assistant_message.text)

        restored = self.client.get(f"/api/v1/assistant/chats/{chat['chat_id']}")
        self.assertEqual(restored.status_code, 200, restored.text)
        restored_chat = restored.json()["data"]
        self.assertEqual(restored_chat["title"], "查找聚酰亚胺透过性")
        self.assertEqual(len(restored_chat["messages"]), 2)
        self.assertEqual(restored_chat["messages"][1]["references"][0]["label"], "研究计划")

        renamed = self.client.patch(
            f"/api/v1/assistant/chats/{chat['chat_id']}",
            json={"title": "透过性研究", "archived": True},
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["data"]["title"], "透过性研究")
        self.assertTrue(renamed.json()["data"]["archived"])
        self.assertEqual(self.client.get("/api/v1/assistant/chats").json()["data"]["total"], 0)
        archived = self.client.get("/api/v1/assistant/chats?archived=true&query=透过性")
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["data"]["items"][0]["chat_id"], chat["chat_id"])

        deleted = self.client.delete(f"/api/v1/assistant/chats/{chat['chat_id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/v1/assistant/chats/{chat['chat_id']}").status_code, 404)

    def test_chat_and_messages_are_isolated_by_owner(self) -> None:
        created = self.client.post("/api/v1/assistant/chats", json={"title": "私有会话"})
        chat_id = created.json()["data"]["chat_id"]
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "user-2", "username": "other", "role": "user", "status": "active"
        }
        self.assertEqual(self.client.get(f"/api/v1/assistant/chats/{chat_id}").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/v1/assistant/chats/{chat_id}", json={"title": "越权"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/v1/assistant/chats/{chat_id}").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/assistant/chats").json()["data"]["total"], 0)

    def test_chat_restore_includes_linked_tool_call_events_and_run_result(self) -> None:
        now = utc_now()
        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": "vertical-tool",
                "name": "Vertical Tool",
                "description": "Test tool",
                "type": "predictor",
                "algorithm_family": "vertical_prediction",
                "capability_group": "vertical_algorithm",
                "visibility": "public",
                "owner": "owner-1",
                "status": "active",
                "deployment_status": "active",
                "active_version_id": "vertical-tool-v1",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
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
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"score": "number"}, "required": ["score"]},
                "input_assets": [],
                "output_assets": [],
                "created_by": "owner-1",
                "created_at": now,
                "updated_at": now,
            },
        )
        created = self.client.post(
            "/api/v1/assistant/chats",
            json={"title": "工具恢复", "selected_tool_ids": ["algorithm:vertical-tool"]},
        )
        chat_id = created.json()["data"]["chat_id"]
        message = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/messages",
            json={"role": "user", "content": "预测 CCO"},
        ).json()["data"]
        call = self.client.post(
            "/api/v1/assistant/tool-calls",
            json={
                "tool_id": "algorithm:vertical-tool",
                "chat_id": chat_id,
                "message_id": message["message_id"],
                "arguments": {"smiles": "CCO"},
            },
        )
        self.assertEqual(call.status_code, 200, call.text)
        call_id = call.json()["data"]["call_id"]

        def fake_run(_service, payload, *, actor_user_id, is_admin=False, request_id=None, input_asset_uploads=None):
            return type(
                "FakeRun",
                (),
                {
                    "run_id": "arun-restore-1",
                    "algorithm_id": payload.algorithm_id,
                    "algorithm_version_id": payload.algorithm_version_id,
                    "status": "completed",
                    "output_summary": {"score": 0.91},
                    "artifact_refs": [{"artifact_id": "artifact-1", "name": "result.json"}],
                    "error": None,
                },
            )()

        with patch("app.services.assistant_tool_service.ResearchEngineService.create_algorithm_run", new=fake_run):
            confirmed = self.client.post(f"/api/v1/assistant/tool-calls/{call_id}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

        restored = self.client.get(f"/api/v1/assistant/chats/{chat_id}").json()["data"]
        self.assertEqual(restored["selected_tool_ids"], ["algorithm:vertical-tool"])
        self.assertEqual(restored["tool_calls"][0]["run_id"], "arun-restore-1")
        self.assertEqual(restored["tool_calls"][0]["algorithm_version_id"], "vertical-tool-v1")
        self.assertEqual(restored["tool_calls"][0]["result_summary"]["score"], 0.91)
        self.assertEqual(restored["messages"][0]["tool_calls"][0]["call_id"], call_id)
        self.assertEqual(restored["messages"][0]["tool_calls"][0]["phase"], "completed")
        self.assertEqual(
            [event["phase"] for event in restored["tool_calls"][0]["events"] if event.get("phase")],
            ["requested", "awaiting_confirmation", "running", "completed"],
        )
