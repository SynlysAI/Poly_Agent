"""能力中心只读聚合契约测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.api.v1.endpoints import capabilities as capabilities_endpoint
from app.core.auth import build_access_token
from app.core.config import settings
from app.schemas.agent_exec import (
    AgentExecPolicyUpdateRequest,
    AgentExecProviderReadiness,
    AgentExecProviderResult,
)
from app.schemas.capabilities import (
    CapabilityCatalogGroup,
    CapabilityCatalogItem,
    CapabilityInvocation,
    CapabilityPolicySummary,
)
from app.schemas.identity_runtime import UserRecord
from app.schemas.llm_models import LLMModelCatalogData, LLMModelInfo, LLMProviderInfo
from app.services.agent_exec_providers.registry import AgentExecProviderRegistry
from app.services.agent_exec_service import AgentExecService
from app.services.capability_catalog_service import CapabilityCatalogService


class CatalogProvider:
    """能力目录测试用外部 provider。"""

    supported_task_types = ("structured_file_task",)
    description = "测试连接器"
    attribution = "执行能力来自测试 CLI"

    def __init__(self, provider_id: str, *, available: bool = True) -> None:
        self.provider_id = provider_id
        self.display_name = "测试连接器"
        self._available = available

    def sandbox_summary(self) -> str:
        """返回安全 sandbox 摘要。"""
        return "read-only sandbox"

    def config_source(self) -> str:
        """返回脱敏配置来源。"""
        return "测试配置（已脱敏）"

    def readiness(self) -> AgentExecProviderReadiness:
        """返回 provider readiness。"""
        return AgentExecProviderReadiness(
            provider_id=self.provider_id,
            available=self._available,
            reason_code="" if self._available else "not_ready",
            message="" if self._available else "测试 provider 未就绪",
            checked_at=datetime.now(timezone.utc),
        )

    def execute(self, *, task, workdir, timeout_seconds, should_cancel=None):
        """返回固定成功结果。"""
        return AgentExecProviderResult(provider_id=self.provider_id, success=True)


def make_item(item_id: str, *, status: str = "available", can_invoke: bool = True) -> CapabilityCatalogItem:
    """构建测试能力卡片。

    Args:
        item_id: 能力 ID。
        status: 能力状态。
        can_invoke: 当前用户是否可调用。

    Returns:
        测试能力卡片。
    """
    return CapabilityCatalogItem(
        id=item_id,
        name=item_id,
        description="测试能力",
        module_id="test",
        status=status,  # type: ignore[arg-type]
        policy=CapabilityPolicySummary(
            allowed_roles=["admin", "user"],
            requires_confirmation=False,
            viewer_can_invoke=can_invoke,
            scope_note="测试",
        ),
        invocation=CapabilityInvocation(
            kind="dialogue_tool",
            method="navigate",
            target="/dialogue",
        ),
    )


class CapabilityCatalogApiTest(ComputationTestCase):
    """覆盖能力目录的角色视角、数据映射和失败隔离。"""

    def setUp(self) -> None:
        super().setUp()
        self.provider_id = f"catalog-{uuid4().hex[:8]}"
        registry = AgentExecProviderRegistry()
        registry.register(CatalogProvider(self.provider_id))
        self.original_catalog_service = capabilities_endpoint.catalog_service
        self.catalog_service = CapabilityCatalogService(
            agent_exec_service=AgentExecService(registry=registry, run_reader=lambda _: None),
            llm_model_service=self._fake_llm_service(),
        )
        capabilities_endpoint.catalog_service = self.catalog_service

    def tearDown(self) -> None:
        capabilities_endpoint.catalog_service = self.original_catalog_service
        super().tearDown()

    @staticmethod
    def _fake_llm_service():
        """构建只返回脱敏目录的 LLM 服务替身。

        Returns:
            带 get_catalog 方法的轻量对象。
        """

        class FakeLLMService:
            """不访问配置文件的 LLM 服务替身。"""

            @staticmethod
            def get_catalog(*, probe: bool = False) -> LLMModelCatalogData:
                """返回固定脱敏目录。

                Args:
                    probe: 兼容调用参数。

                Returns:
                固定 LLM catalog。
                """
                return LLMModelCatalogData(
                    providers=[
                        LLMProviderInfo(
                            provider_id="test-openai",
                            display_name="Test OpenAI",
                            provider_type="openai_compatible",
                            base_url_configured=True,
                            base_url_label="internal host",
                            api_key_configured=True,
                            status="available",
                            models=[LLMModelInfo(model_id="greet", display_name="Greeting")],
                        )
                    ]
                )

        return FakeLLMService()

    def test_local_demo_mode_returns_admin_catalog_without_sensitive_fields(self) -> None:
        response = self.client.get("/api/v1/capabilities/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["viewer_role"], "admin")
        self.assertTrue(data["is_admin"])
        self.assertEqual(
            list(
                [
                    data["dialogue_tools"]["group_id"],
                    data["agent_connectors"]["group_id"],
                    data["report_skills"]["group_id"],
                    data["llm_capabilities"]["group_id"],
                ]
            ),
            ["dialogue_tools", "agent_connectors", "report_skills", "llm_capabilities"],
        )
        connector = next(
            item for item in data["agent_connectors"]["items"] if item["id"] == self.provider_id
        )
        self.assertEqual(connector["status"], "disabled")
        self.assertFalse(connector["policy"]["viewer_can_invoke"])
        llm = data["llm_capabilities"]["items"][0]
        self.assertEqual(llm["id"], "test-openai:greet")
        self.assertEqual(llm["invocation"]["target"], "/dialogue?providerId=test-openai&modelId=greet")
        raw = response.text.lower()
        for forbidden in ("api_key", "base_url", "http://", "workdir", "prompt"):
            self.assertNotIn(forbidden, raw)

    def test_catalog_requires_authentication_when_auth_enabled(self) -> None:
        settings.auth_enabled = True
        token, _ = build_access_token("catalog_user", "Catalog User", "user")

        def fake_find_user(user_id: str) -> UserRecord | None:
            """返回测试普通用户。

            Args:
                user_id: 用户 ID。

            Returns:
                测试用户记录。
            """
            if user_id != "catalog_user":
                return None
            now = datetime.now(timezone.utc)
            return UserRecord(
                user_id=user_id,
                username="Catalog User",
                password_hash="unused",
                role="user",
                status="active",
                created_at=now,
                updated_at=now,
            )

        with patch(
            "app.infra.repositories.UserRepository.find_by_user_id",
            side_effect=fake_find_user,
        ):
            anonymous = self.client.get("/api/v1/capabilities/catalog")
            self.assertEqual(anonymous.status_code, 401)

            response = self.client.get(
                "/api/v1/capabilities/catalog",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["viewer_role"], "user")
        self.assertFalse(data["is_admin"])

    def test_user_connector_visibility_requires_enabled_and_role(self) -> None:
        provider = CatalogProvider(self.provider_id)
        service = self.catalog_service.agent_exec_service
        provider_id = self.provider_id
        service.policy_service.update_policy(
            provider,
            AgentExecPolicyUpdateRequest(
                enabled=True,
                allowed_roles=["admin", "user"],
                requires_confirmation=False,
            ),
            updated_by="test",
        )
        admin_catalog = self.catalog_service.get_catalog({"user_id": "admin", "role": "admin"})
        user_catalog = self.catalog_service.get_catalog({"user_id": "user", "role": "user"})
        self.assertEqual(admin_catalog.viewer_role, "admin")
        self.assertIn(provider_id, [item.id for item in admin_catalog.agent_connectors.items])
        self.assertEqual(
            [item.id for item in user_catalog.agent_connectors.items], [provider_id]
        )
        user_item = user_catalog.agent_connectors.items[0]
        self.assertTrue(user_item.policy.viewer_can_invoke)
        self.assertTrue(user_item.policy.requires_confirmation)

    def test_single_source_failure_only_marks_its_group_unavailable(self) -> None:
        original = self.catalog_service._llm_group
        self.catalog_service._llm_group = lambda **_: (_ for _ in ()).throw(RuntimeError("secret path"))
        try:
            data = self.catalog_service.get_catalog({"user_id": "user", "role": "user"})
        finally:
            self.catalog_service._llm_group = original
        self.assertEqual(data.llm_capabilities.status, "unavailable")
        self.assertEqual(data.llm_capabilities.unavailable_reason, "能力源读取失败：RuntimeError")
        self.assertEqual(data.report_skills.group_id, "report_skills")
        self.assertNotEqual(
            data.report_skills.unavailable_reason,
            "能力源读取失败：RuntimeError",
        )

    def test_group_aggregation_counts_available_and_invocable_items(self) -> None:
        group = CapabilityCatalogService._group(
            "llm_capabilities",
            "测试",
            "测试",
            [make_item("a"), make_item("b", status="unavailable"), make_item("c", can_invoke=False)],
        )
        self.assertEqual(group.status, "partial")
        self.assertEqual(group.total_count, 3)
        self.assertEqual(group.invocable_count, 1)
