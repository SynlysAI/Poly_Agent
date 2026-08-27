"""Codex agent_exec 适配器 mock subprocess 测试。"""

from __future__ import annotations


import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.schemas.agent_exec import AgentExecTaskRequest
from app.services.agent_exec_providers.base import AgentExecProviderError
from app.services.agent_exec_providers.codex import CodexAgentExecProvider


OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}


def _task() -> AgentExecTaskRequest:
    """构建测试用文件任务。"""
    return AgentExecTaskRequest(
        task_type="structured_file_task",
        prompt="summarize input",
        output_schema=OUTPUT_SCHEMA,
        timeout_seconds=5,
    )


class CodexProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.originals = {
            "enabled": settings.agent_exec_enabled,
            "bin": settings.agent_exec_codex_bin,
            "sandbox": settings.agent_exec_codex_sandbox_mode,
            "api_key": settings.agent_exec_codex_api_key,
            "model": settings.agent_exec_codex_model,
        }
        settings.agent_exec_enabled = True
        settings.agent_exec_codex_bin = "codex"
        settings.agent_exec_codex_sandbox_mode = "read-only"
        settings.agent_exec_codex_api_key = "test-key"
        settings.agent_exec_codex_model = ""

    def tearDown(self) -> None:
        settings.agent_exec_enabled = self.originals["enabled"]
        settings.agent_exec_codex_bin = self.originals["bin"]
        settings.agent_exec_codex_sandbox_mode = self.originals["sandbox"]
        settings.agent_exec_codex_api_key = self.originals["api_key"]
        settings.agent_exec_codex_model = self.originals["model"]

    def test_readiness_disabled_by_default(self) -> None:
        settings.agent_exec_enabled = False
        provider = CodexAgentExecProvider()

        readiness = provider.readiness()

        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason_code, "agent_exec_disabled")

    def test_readiness_sandbox_mode_unsupported(self) -> None:
        settings.agent_exec_codex_sandbox_mode = "danger-full-access"
        provider = CodexAgentExecProvider()

        readiness = provider.readiness()

        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason_code, "sandbox_mode_unsupported")

    def test_readiness_binary_missing(self) -> None:
        provider = CodexAgentExecProvider()

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which", return_value=None
        ):
            readiness = provider.readiness()

        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason_code, "codex_binary_missing")

    def test_readiness_credentials_missing(self) -> None:
        settings.agent_exec_codex_api_key = ""
        settings.agent_exec_codex_model = ""
        provider = CodexAgentExecProvider()

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ), patch(
            "app.services.agent_exec_providers.codex.os.access", return_value=True
        ):
            readiness = provider.readiness()

        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason_code, "credentials_missing")

    def test_readiness_ready_without_executing_binary(self) -> None:
        provider = CodexAgentExecProvider()

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ) as which_mock, patch(
            "app.services.agent_exec_providers.codex.os.access", return_value=True
        ):
            readiness = provider.readiness()

        self.assertTrue(readiness.available)
        self.assertEqual(readiness.reason_code, "ready")
        which_mock.assert_called_once_with("codex")

    def test_execute_success_uses_read_only_sandbox(self) -> None:
        provider = CodexAgentExecProvider()
        calls: list[dict] = []

        def runner(command, **kwargs):
            """记录命令并把结构化结果写入 workdir。"""
            calls.append({"command": command, **kwargs})
            output = Path(kwargs["cwd"]) / "result.json"
            output.write_text(
                json.dumps({"summary": "ok"}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            result = self._execute(provider, runner)

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"summary": "ok"})
        command = calls[0]["command"]
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")

    def test_execute_nonzero_exit(self) -> None:
        provider = CodexAgentExecProvider()

        def runner(command, **kwargs):
            """模拟非零退出。"""
            return subprocess.CompletedProcess(command, 2, stdout="", stderr="boom")

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider, runner)
        self.assertEqual(ctx.exception.code, "codex_nonzero_exit")
        self.assertIn("boom", ctx.exception.message)

    def test_execute_timeout(self) -> None:
        provider = CodexAgentExecProvider()

        def runner(command, **kwargs):
            """模拟超时。"""
            raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider, runner)
        self.assertEqual(ctx.exception.code, "timeout")

    def test_execute_output_missing(self) -> None:
        provider = CodexAgentExecProvider()

        def runner(command, **kwargs):
            """模拟成功退出但没有输出文件。"""
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider, runner)
        self.assertEqual(ctx.exception.code, "output_missing")

    def test_execute_schema_mismatch(self) -> None:
        provider = CodexAgentExecProvider()

        def runner(command, **kwargs):
            """模拟输出缺少必填字段。"""
            output = Path(kwargs["cwd"]) / "result.json"
            output.write_text(json.dumps({"other": 1}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider, runner)
        self.assertEqual(ctx.exception.code, "schema_mismatch")

    def _execute(self, provider, runner):
        """在临时 workdir 内执行 provider 并返回结果。"""
        import tempfile

        provider._command_runner = runner
        with tempfile.TemporaryDirectory() as tmp:
            return provider.execute(
                task=_task(), workdir=Path(tmp), timeout_seconds=5
            )


if __name__ == "__main__":
    unittest.main()
