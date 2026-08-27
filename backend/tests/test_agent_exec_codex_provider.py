"""Codex agent_exec 适配器 mock subprocess 测试。"""

from __future__ import annotations


import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.schemas.agent_exec import AgentExecTaskRequest
from app.services.agent_exec_providers.base import AgentExecProviderError
from app.services.agent_exec_providers.codex import CodexAgentExecProvider


class FakeProcess:
    """模拟 codex 子进程的可控行为。"""

    def __init__(self, command, *, cwd, mode, payload=None):
        """初始化模拟进程。

        Args:
            command: 命令行。
            cwd: 工作目录。
            mode: ok / nonzero / timeout / missing / cancel。
            payload: ok 模式写出的 JSON 内容。
        """
        self.command = command
        self.cwd = cwd
        self.mode = mode
        self.payload = payload
        self.returncode = 0
        self.pid = 12345
        self.terminated = False

    def communicate(self, timeout=None):
        """模拟进程输出。"""
        if self.mode in {"timeout", "cancel"} and not self.terminated:
            raise subprocess.TimeoutExpired(self.command, timeout=timeout or 0)
        if self.mode == "timeout":
            return ("", "process timed out")
        if self.mode == "ok":
            output = Path(self.cwd) / "result.json"
            output.write_text(json.dumps(self.payload), encoding="utf-8")
            return ("done", "")
        if self.mode == "nonzero":
            self.returncode = 2
            return ("", "boom")
        return ("", "")

    def wait(self, timeout=None):
        """等待进程结束。"""
        return self.returncode

    def terminate(self):
        """模拟 SIGTERM。"""
        self.terminated = True
        self.returncode = -15

    def kill(self):
        """模拟 SIGKILL。"""
        self.terminated = True
        self.returncode = -9


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
        captured: dict = {}

        def factory(command, **kwargs):
            """记录命令并返回成功进程。"""
            captured["command"] = command
            captured.update(kwargs)
            return FakeProcess(
                command,
                cwd=kwargs["cwd"],
                mode="ok",
                payload={"summary": "ok"},
            )

        provider = CodexAgentExecProvider(process_factory=factory)
        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            result = self._execute(provider)

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"summary": "ok"})
        command = captured["command"]
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        env_keys = set(captured.get("env", {}))
        self.assertLessEqual(
            env_keys,
            {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "CODEX_API_KEY"},
        )

    def test_execute_nonzero_exit(self) -> None:
        provider = CodexAgentExecProvider(
            process_factory=lambda command, **kwargs: FakeProcess(
                command, cwd=kwargs["cwd"], mode="nonzero"
            )
        )
        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider)
        self.assertEqual(ctx.exception.code, "codex_nonzero_exit")
        self.assertIn("boom", ctx.exception.message)

    def test_execute_timeout(self) -> None:
        provider = CodexAgentExecProvider(
            process_factory=lambda command, **kwargs: FakeProcess(
                command, cwd=kwargs["cwd"], mode="timeout"
            )
        )
        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider, timeout_seconds=0.2)
        self.assertEqual(ctx.exception.code, "timeout")

    def test_execute_cancelled(self) -> None:
        provider = CodexAgentExecProvider(
            process_factory=lambda command, **kwargs: FakeProcess(
                command, cwd=kwargs["cwd"], mode="cancel"
            )
        )
        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                provider.execute(
                    task=_task(),
                    workdir=Path(tempfile.mkdtemp()),
                    timeout_seconds=5,
                    should_cancel=lambda: True,
                )
        self.assertEqual(ctx.exception.code, "cancelled")

    def test_execute_output_missing(self) -> None:
        provider = CodexAgentExecProvider(
            process_factory=lambda command, **kwargs: FakeProcess(
                command, cwd=kwargs["cwd"], mode="missing"
            )
        )
        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider)
        self.assertEqual(ctx.exception.code, "output_missing")

    def test_execute_schema_mismatch(self) -> None:
        provider = CodexAgentExecProvider(
            process_factory=lambda command, **kwargs: FakeProcess(
                command, cwd=kwargs["cwd"], mode="ok", payload={"other": 1}
            )
        )
        with patch(
            "app.services.agent_exec_providers.codex.shutil.which",
            return_value="/usr/local/bin/codex",
        ):
            with self.assertRaises(AgentExecProviderError) as ctx:
                self._execute(provider)
        self.assertEqual(ctx.exception.code, "schema_mismatch")

    def _execute(self, provider, timeout_seconds: float = 5):
        """在临时 workdir 内执行 provider 并返回结果。

        Args:
            provider: 被测适配器。
            timeout_seconds: 测试用超时秒数。
        """
        with tempfile.TemporaryDirectory() as tmp:
            return provider.execute(
                task=_task(), workdir=Path(tmp), timeout_seconds=timeout_seconds
            )


if __name__ == "__main__":
    unittest.main()
