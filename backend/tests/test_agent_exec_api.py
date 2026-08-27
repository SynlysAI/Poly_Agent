"""Agent 连接器管理 API 测试。"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import build_access_token
from app.core.config import settings
from app.api.v1.endpoints import agent_exec as agent_exec_endpoint
from app.schemas.identity_runtime import UserRecord
from app.schemas.agent_exec import AgentExecProviderReadiness, AgentExecProviderResult
from app.services.agent_exec_providers.registry import AgentExecProviderRegistry
from app.services.agent_exec_service import AgentExecService
from unittest.mock import patch


SCHEMA = {"type": "object", "required": ["summary"]}


class ApiProvider:
    """API 测试用受控 provider。"""

    supported_task_types = ("structured_file_task",)
    description = "测试连接器"
    attribution = "执行能力来自测试 CLI"

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.display_name = "测试连接器"

    def sandbox_summary(self) -> str:
        """返回 sandbox 摘要。"""
        return "read-only sandbox"

    def config_source(self) -> str:
        """返回脱敏配置来源。"""
        return "环境变量（已脱敏）"

    def readiness(self) -> AgentExecProviderReadiness:
        """返回可用状态。"""
        return AgentExecProviderReadiness(
            provider_id=self.provider_id,
            available=True,
            reason_code="ready",
            checked_at=datetime.now(timezone.utc),
        )

    def execute(self, *, task, workdir, timeout_seconds, should_cancel=None):
        """返回成功结果。"""
        return AgentExecProviderResult(
            provider_id=self.provider_id,
            success=True,
            output={"summary": "ok"},
        )


class AgentExecApiTest(ComputationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.provider_id = f"api-{uuid4().hex[:8]}"
        self.provider = ApiProvider(self.provider_id)
        registry = AgentExecProviderRegistry()
        registry.register(self.provider)
        self.original_service = agent_exec_endpoint.service
        agent_exec_endpoint.service = AgentExecService(
            registry=registry,
            run_reader=lambda run_id: self._read_run(run_id),
        )
        self.original_upload_root = settings.upload_root
        settings.upload_root = self.runtime_root / "uploads"
        settings.upload_root.mkdir(parents=True, exist_ok=True)
        self.original_workdir_root = settings.agent_exec_workdir_root
        settings.agent_exec_workdir_root = self.runtime_root / "agent_exec"
        self.runs: dict = {}

        self.admin_token, _ = build_access_token("admin_api", "Admin", "admin")
        self.user_token, _ = build_access_token("user_api", "User", "user")

    def tearDown(self) -> None:
        settings.upload_root = self.original_upload_root
        settings.agent_exec_workdir_root = self.original_workdir_root
        agent_exec_endpoint.service = self.original_service
        super().tearDown()

    def _read_run(self, run_id: str):
        """读取测试内 run。"""
        return self.runs.get(run_id)

    def _enable_policy(self) -> None:
        """启用测试连接器策略。"""
        response = self.client.patch(
            f"/api/v1/agent-exec/providers/{self.provider_id}/policy",
            json={"enabled": True},
            headers=self._admin_headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _admin_headers(self) -> dict:
        """管理员请求头。"""
        return {"Authorization": f"Bearer {self.admin_token}"}

    def _user_headers(self) -> dict:
        """普通用户请求头。"""
        return {"Authorization": f"Bearer {self.user_token}"}

    def _patch_user(self, enabled: bool = True):
        """返回用户仓储 patch 上下文。"""
        now = datetime.now(timezone.utc)

        def fake_find(user_id: str) -> UserRecord | None:
            """返回测试用户。"""
            if user_id not in {"admin_api", "user_api"}:
                return None
            return UserRecord(
                user_id=user_id,
                username="Admin" if user_id == "admin_api" else "User",
                password_hash="unused",
                role="admin" if user_id == "admin_api" else "user",
                status="active",
                created_at=now,
                updated_at=now,
            )

        return patch(
            "app.infra.repositories.UserRepository.find_by_user_id",
            side_effect=fake_find,
        )

    def _run_payload(self, **overrides) -> dict:
        """构建 run 请求。"""
        payload = {
            "provider_id": self.provider_id,
            "task_type": "structured_file_task",
            "prompt": "summarize",
            "output_schema": SCHEMA,
            "timeout_seconds": 5,
            "confirmed": True,
        }
        payload.update(overrides)
        return payload

    def test_providers_require_authentication_and_admin(self) -> None:
        settings.auth_enabled = True
        with self._patch_user():
            response = self.client.get("/api/v1/agent-exec/providers")
            self.assertEqual(response.status_code, 401)

            response = self.client.get(
                "/api/v1/agent-exec/providers", headers=self._user_headers()
            )
            self.assertEqual(response.status_code, 403)

            response = self.client.get(
                "/api/v1/agent-exec/providers", headers=self._admin_headers()
            )
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            card = next(item for item in data if item["provider_id"] == self.provider_id)
            self.assertTrue(card["readiness"]["available"])
            self.assertEqual(card["policy"]["enabled"], False)
            self.assertIn("sandbox", card["sandbox_summary"])
            self.assertNotIn("workdir", response.text)
            self.assertNotIn("api_key", response.text.lower())

    def test_policy_update_admin_only_and_scope_validation(self) -> None:
        settings.auth_enabled = True
        with self._patch_user():
            response = self.client.patch(
                f"/api/v1/agent-exec/providers/{self.provider_id}/policy",
                json={"enabled": True},
                headers=self._user_headers(),
            )
            self.assertEqual(response.status_code, 403)

            response = self.client.patch(
                f"/api/v1/agent-exec/providers/{self.provider_id}/policy",
                json={"allowed_task_types": ["shell_task"]},
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["data"]["detail"]["reason_code"], "task_type_not_supported"
            )

            response = self.client.patch(
                f"/api/v1/agent-exec/providers/{self.provider_id}/policy",
                json={"enabled": True, "requires_confirmation": True},
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["data"]["enabled"])

    def test_create_run_policy_checked_and_sanitized(self) -> None:
        settings.auth_enabled = True
        with self._patch_user():
            self._enable_policy()
            # 未确认被拒绝
            response = self.client.post(
                "/api/v1/agent-exec/runs",
                json=self._run_payload(confirmed=False),
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(
                response.json()["data"]["detail"]["reason_code"], "confirmation_required"
            )

            response = self.client.post(
                "/api/v1/agent-exec/runs",
                json=self._run_payload(),
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 200, response.text)
            run = response.json()["data"]
            self.assertEqual(run["status"], "completed")
            self.runs[run["run_id"]] = run
            self.assertNotIn(str(settings.agent_exec_workdir_root), response.text)

    def test_get_and_cancel_run_with_stable_terminal_state(self) -> None:
        settings.auth_enabled = True
        with self._patch_user():
            self._enable_policy()
            create_response = self.client.post(
                "/api/v1/agent-exec/runs",
                json=self._run_payload(),
                headers=self._admin_headers(),
            )
            run = create_response.json()["data"]
            self.runs[run["run_id"]] = run

            response = self.client.get(
                f"/api/v1/agent-exec/runs/{run['run_id']}",
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()["data"]
            self.assertEqual(detail["run"]["status"], "completed")
            self.assertGreaterEqual(len(detail["events"]), 3)
            self.assertTrue(detail["policy_summary"]["enabled"])

            cancel_response = self.client.post(
                f"/api/v1/agent-exec/runs/{run['run_id']}/cancel",
                headers=self._admin_headers(),
            )
            self.assertEqual(cancel_response.status_code, 200)
            self.assertEqual(cancel_response.json()["data"]["status"], "completed")

            missing = self.client.get(
                "/api/v1/agent-exec/runs/aer_missing",
                headers=self._admin_headers(),
            )
            self.assertEqual(missing.status_code, 404)

    def test_unknown_provider_and_user_role_rejected(self) -> None:
        settings.auth_enabled = True
        with self._patch_user():
            response = self.client.post(
                "/api/v1/agent-exec/runs",
                json=self._run_payload(provider_id="missing"),
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["data"]["detail"]["reason_code"], "provider_not_registered"
            )

            response = self.client.post(
                "/api/v1/agent-exec/runs",
                json=self._run_payload(),
                headers=self._user_headers(),
            )
            self.assertEqual(response.status_code, 403)

    def test_quality_summary(self) -> None:
        settings.auth_enabled = True
        with self._patch_user():
            self._enable_policy()
            create_response = self.client.post(
                "/api/v1/agent-exec/runs",
                json=self._run_payload(),
                headers=self._admin_headers(),
            )
            self.assertEqual(create_response.status_code, 200)

            response = self.client.get(
                "/api/v1/agent-exec/quality",
                headers=self._admin_headers(),
            )
            self.assertEqual(response.status_code, 200, response.text)
            summary = response.json()["data"]
            self.assertIn("success_rate", summary)
            self.assertIn("timeout_count", summary)


if __name__ == "__main__":
    unittest.main()
