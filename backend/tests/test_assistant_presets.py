"""LUI 科研 Preset 兼容性测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
from app.schemas.assistant import AssistantChatRequest
from app.services.assistant_service import AssistantService


class AssistantPresetCompatibilityTest(ComputationTestCase):
    """验证两个科研 Preset 与旧版会话模式保持兼容。"""

    def setUp(self) -> None:
        super().setUp()
        self.user = {
            "user_id": "preset-user",
            "username": "preset-user",
            "role": "user",
            "status": "active",
        }
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    def test_chat_mode_maps_to_research_preset_and_syncs_on_update(self) -> None:
        created = self.client.post(
            "/api/v1/assistant/chats",
            json={"mode": "deep", "selected_tool_ids": []},
        )
        self.assertEqual(created.status_code, 200, created.text)
        chat = created.json()["data"]
        self.assertEqual(chat["preset_id"], "research_deep")
        self.assertEqual(chat["mode"], "deep")

        updated = self.client.patch(
            f"/api/v1/assistant/chats/{chat['chat_id']}",
            json={"preset_id": "research_qa"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["data"]["preset_id"], "research_qa")
        self.assertEqual(updated.json()["data"]["mode"], "qa")

    def test_legacy_deep_chat_restores_research_deep_preset(self) -> None:
        created = self.client.post("/api/v1/assistant/chats", json={"title": "旧模式会话"})
        self.assertEqual(created.status_code, 200, created.text)
        chat_id = created.json()["data"]["chat_id"]
        self.assertTrue(
            AssistantChatRepository.update_owned(
                chat_id,
                self.user["user_id"],
                {"mode": "deep"},
            )
        )
        document = AssistantChatRepository.find_one({"chat_id": chat_id})
        document.pop("preset_id", None)
        AssistantChatRepository.save("chat_id", document)

        restored = self.client.get(f"/api/v1/assistant/chats/{chat_id}")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["data"]["preset_id"], "research_deep")
        self.assertEqual(restored.json()["data"]["mode"], "deep")

    def test_run_snapshot_records_preset_for_trace_replay(self) -> None:
        created = self.client.post(
            "/api/v1/assistant/chats",
            json={"preset_id": "research_deep", "mode": "qa"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        chat = created.json()["data"]
        self.assertEqual(chat["preset_id"], "research_deep")
        self.assertEqual(chat["mode"], "deep")

        run = self.client.post(
            f"/api/v1/assistant/chats/{chat['chat_id']}/runs",
            json={"content": "深度问题", "messages": [], "context": {}},
        )
        self.assertEqual(run.status_code, 200, run.text)
        run_id = run.json()["data"]["run_id"]
        document = AssistantRunRepository.find_one({"run_id": run_id})
        self.assertEqual(document["request_snapshot"]["context"]["preset_id"], "research_deep")
        self.assertEqual(document["request_snapshot"]["context"]["mode"], "deep")
        self.assertEqual(document["route"]["preset_id"], "research_deep")

    def test_preset_route_keeps_explicit_model_and_does_not_enable_tools(self) -> None:
        request = AssistantChatRequest.model_validate(
            {
                "messages": [{"role": "user", "content": "比较两种算法"}],
                "context": {
                    "preset_id": "research_qa",
                    "mode": "deep",
                    "model": {"providerId": "explicit-provider", "modelId": "explicit-model"},
                },
            }
        )
        service = AssistantService()
        resolved_route = {
            "purpose": "qa",
            "route_reason": "user_selected",
            "requested_provider_id": "explicit-provider",
            "requested_model_id": "explicit-model",
            "provider_id": "explicit-provider",
            "model_id": "explicit-model",
            "capabilities": ["chat"],
        }
        with patch.object(
            service.llm_model_service,
            "resolve_route",
            return_value=resolved_route,
        ) as resolve_route:
            route = service._resolve_llm_route(mode="deep", request=request)

        self.assertEqual(route["preset_id"], "research_qa")
        self.assertEqual(route["purpose"], "qa")
        self.assertEqual(route["route_reason"], "user_selected")
        self.assertEqual(route["model_id"], "explicit-model")
        resolve_route.assert_called_once_with(
            purpose="qa",
            requested_model={"providerId": "explicit-provider", "modelId": "explicit-model"},
        )
