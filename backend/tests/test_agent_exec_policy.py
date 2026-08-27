"""agent_exec 连接器策略治理测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.agent_exec import (
    AgentExecExecutionRequest,
    AgentExecPolicyUpdateRequest,
    AgentExecProviderReadiness,
    AgentExecTaskRequest,
)
from app.services.agent_exec_policy_service import (
    AgentExecPolicyRejected,
    AgentExecPolicyService,
)


class StaticProvider:
    """测试用静态 provider。"""

    provider_id = "static"
    display_name = "Static"
    supported_task_types = ("structured_file_task",)

    def readiness(self) -> AgentExecProviderReadiness:
        """返回静态 ready。"""
        raise AssertionError("策略测试不应触发 readiness")


class OtherTaskProvider(StaticProvider):
    """仅支持其他任务类型的 provider。"""

    provider_id = "other"
    supported_task_types = ("report_task",)


SCHEMA = {"type": "object"}


def _request(**overrides) -> AgentExecExecutionRequest:
    """构建执行请求。"""
    payload = {
        "provider_id": "static",
        "task": AgentExecTaskRequest(
            task_type="structured_file_task",
            prompt="task",
            output_schema=SCHEMA,
            timeout_seconds=10,
        ),
        "actor_user_id": "admin-1",
        "actor_role": "admin",
        "confirmed": True,
    }
    payload.update(overrides)
    return AgentExecExecutionRequest(**payload)


class AgentExecPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = StaticProvider()
        self.service = AgentExecPolicyService()

    def test_default_policy_is_safe(self) -> None:
        policy = self.service.get_policy("static")

        self.assertFalse(policy.enabled)
        self.assertEqual(policy.allowed_roles, ["admin"])
        self.assertEqual(policy.allowed_task_types, ["structured_file_task"])
        self.assertTrue(policy.requires_confirmation)

    def test_update_policy_records_updated_by_and_at(self) -> None:
        before, after = self.service.update_policy(
            self.provider,
            AgentExecPolicyUpdateRequest(enabled=True, allowed_roles=["admin", "user"]),
            updated_by="admin-1",
        )

        self.assertFalse(before.enabled)
        self.assertTrue(after.enabled)
        self.assertEqual(after.allowed_roles, ["admin", "user"])
        self.assertEqual(after.updated_by, "admin-1")
        self.assertIsNotNone(after.updated_at)
        self.assertEqual(self.service.get_policy("static"), after)

    def test_update_policy_rejects_task_type_out_of_provider_scope(self) -> None:
        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            self.service.update_policy(
                self.provider,
                AgentExecPolicyUpdateRequest(
                    allowed_task_types=["structured_file_task", "shell_task"]
                ),
                updated_by="admin-1",
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.reason_code, "task_type_not_supported")

    def test_update_policy_rejects_empty_roles_or_task_types(self) -> None:
        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            self.service.update_policy(
                self.provider,
                AgentExecPolicyUpdateRequest(allowed_roles=[]),
                updated_by="admin-1",
            )
        self.assertEqual(ctx.exception.reason_code, "roles_empty")

        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            self.service.update_policy(
                self.provider,
                AgentExecPolicyUpdateRequest(allowed_task_types=[]),
                updated_by="admin-1",
            )
        self.assertEqual(ctx.exception.reason_code, "task_types_empty")

    def test_validation_order_role_enabled_task_type(self) -> None:
        # 默认策略下角色优先被拒绝
        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            self.service.check_request_policy(self.provider, _request(actor_role="user"))
        self.assertEqual(ctx.exception.reason_code, "role_not_allowed")

        # 管理员越过角色检查后命中 disabled
        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            self.service.check_request_policy(self.provider, _request())
        self.assertEqual(ctx.exception.reason_code, "provider_disabled")

        # enabled 后命中 provider 支持范围校验
        other = OtherTaskProvider()
        self.service.update_policy(
            other,
            AgentExecPolicyUpdateRequest(enabled=True, allowed_task_types=["report_task"]),
            updated_by="admin-1",
        )
        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            self.service.check_request_policy(other, _request())
        self.assertEqual(ctx.exception.reason_code, "task_type_not_supported")

        # 全部通过时返回策略快照
        self.service.update_policy(
            self.provider,
            AgentExecPolicyUpdateRequest(enabled=True),
            updated_by="admin-1",
        )
        policy = self.service.check_request_policy(self.provider, _request())
        self.assertTrue(policy.enabled)

    def test_confirmation_rules(self) -> None:
        policy = self.service.get_policy("static")

        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            AgentExecPolicyService.check_confirmation(policy, _request(confirmed=False))
        self.assertEqual(ctx.exception.reason_code, "confirmation_required")

        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            AgentExecPolicyService.check_confirmation(policy, _request(plan_mode=True))
        self.assertEqual(ctx.exception.reason_code, "plan_mode_blocked")

        with self.assertRaises(AgentExecPolicyRejected) as ctx:
            AgentExecPolicyService.check_confirmation(
                policy, _request(permission_mode="read_only")
            )
        self.assertEqual(ctx.exception.reason_code, "read_only_blocked")

        AgentExecPolicyService.check_confirmation(policy, _request(confirmed=True))


if __name__ == "__main__":
    unittest.main()
