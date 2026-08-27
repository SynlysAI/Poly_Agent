"""agent_exec 契约、配置与 registry 测试。"""

from __future__ import annotations


import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.schemas.agent_exec import (
    AgentExecInputFileData,
    AgentExecProviderPolicy,
    AgentExecProviderReadiness,
    AgentExecTaskRequest,
)
from app.services.agent_exec_providers.base import AgentExecProviderUnavailable
from app.services.agent_exec_providers.registry import AgentExecProviderRegistry


class StaticProvider:
    """测试用静态 provider，不访问任何外部资源。"""

    provider_id = "static"
    display_name = "Static Provider"
    supported_task_types = ("structured_file_task",)

    def readiness(self) -> AgentExecProviderReadiness:
        """返回静态 ready 状态。"""
        return AgentExecProviderReadiness(
            provider_id=self.provider_id,
            available=True,
            checked_at=datetime(2026, 1, 1),
        )


class AgentExecContractTest(unittest.TestCase):
    def test_settings_default_disabled_and_resource_limits(self) -> None:
        settings = Settings()

        self.assertFalse(settings.agent_exec_enabled)
        self.assertEqual(settings.agent_exec_workdir_root.name, "agent_exec")
        self.assertGreater(settings.agent_exec_timeout_seconds, 0)
        self.assertGreater(settings.agent_exec_max_input_bytes, 0)
        self.assertGreater(settings.agent_exec_max_output_bytes, 0)
        self.assertGreater(settings.agent_exec_max_files, 0)

    def test_policy_defaults_are_safe(self) -> None:
        policy = AgentExecProviderPolicy(provider_id="codex")

        self.assertFalse(policy.enabled)
        self.assertEqual(policy.allowed_roles, ["admin"])
        self.assertEqual(policy.allowed_task_types, ["structured_file_task"])
        self.assertTrue(policy.requires_confirmation)
        self.assertEqual(policy.updated_by, "")
        self.assertIsNone(policy.updated_at)

    def test_task_request_requires_explicit_task_type_and_timeout(self) -> None:
        task = AgentExecTaskRequest(
            task_type="structured_file_task",
            prompt="summarize input files",
            input_files=[
                AgentExecInputFileData(
                    name="input.csv",
                    size_bytes=12,
                    sha256="a" * 64,
                    source_object_id="artifact-1",
                )
            ],
            output_schema={"type": "object"},
            timeout_seconds=30,
        )

        self.assertEqual(task.task_type, "structured_file_task")
        self.assertEqual(len(task.input_files), 1)

        with self.assertRaises(ValueError):
            AgentExecTaskRequest(
                task_type="structured_file_task",
                prompt="x",
                output_schema={},
                timeout_seconds=0,
            )

    def test_registry_missing_provider_returns_structured_unavailable(self) -> None:
        registry = AgentExecProviderRegistry()

        readiness = registry.readiness("missing")

        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason_code, "provider_not_registered")
        with self.assertRaises(AgentExecProviderUnavailable) as ctx:
            registry.require("missing")
        self.assertEqual(ctx.exception.code, "provider_not_registered")

    def test_registry_resolves_supported_task_type_only(self) -> None:
        registry = AgentExecProviderRegistry()
        registry.register(StaticProvider())

        provider = registry.resolve("static", "structured_file_task")
        self.assertEqual(provider.provider_id, "static")

        with self.assertRaises(AgentExecProviderUnavailable) as ctx:
            registry.resolve("static", "shell_task")
        self.assertEqual(ctx.exception.code, "task_type_not_supported")

    def test_registry_init_does_not_probe_or_raise(self) -> None:
        registry = AgentExecProviderRegistry()

        self.assertEqual(registry.list_providers(), [])
        self.assertIsNone(registry.get("codex"))


if __name__ == "__main__":
    unittest.main()
