"""agent_exec 执行服务与安全边界测试。"""

from __future__ import annotations

import hashlib
from datetime import datetime
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.schemas.agent_exec import (
    AgentExecExecutionRequest,
    AgentExecInputFileData,
    AgentExecPolicyUpdateRequest,
    AgentExecProviderReadiness,
    AgentExecProviderResult,
    AgentExecTaskRequest,
)
from app.services.agent_exec_policy_service import AgentExecPolicyService
from app.services.agent_exec_providers.base import AgentExecProviderError
from app.services.agent_exec_providers.registry import AgentExecProviderRegistry
from app.services.agent_exec_service import AgentExecRequestError, AgentExecService


SCHEMA = {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}}


class FakeProvider:
    """测试用可控 provider。"""

    provider_id = "fake"
    display_name = "Fake Provider"
    supported_task_types = ("structured_file_task",)

    def __init__(self) -> None:
        self.available = True
        self.execute_handler = self._success_execute

    def readiness(self) -> AgentExecProviderReadiness:
        """返回可控 readiness。"""
        if self.available:
            return AgentExecProviderReadiness(
                provider_id=self.provider_id,
                available=True,
                reason_code="ready",
                checked_at=datetime.now(),
            )
        return AgentExecProviderReadiness.unavailable(
            provider_id=self.provider_id,
            reason_code="not_ready",
            message="provider 未就绪",
        )

    def execute(self, *, task, workdir, timeout_seconds, should_cancel=None):
        """执行可控任务。"""
        return self.execute_handler(
            task=task,
            workdir=workdir,
            timeout_seconds=timeout_seconds,
            should_cancel=should_cancel,
        )

    @staticmethod
    def _success_execute(*, task, workdir, timeout_seconds, should_cancel=None):
        """默认成功行为。"""
        return AgentExecProviderResult(
            provider_id="fake",
            success=True,
            output={"summary": "ok"},
        )


class AgentExecServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.originals = {
            "workdir": settings.agent_exec_workdir_root,
            "upload": settings.upload_root,
            "outputs": settings.outputs_root,
            "max_files": settings.agent_exec_max_files,
            "max_input": settings.agent_exec_max_input_bytes,
            "max_output": settings.agent_exec_max_output_bytes,
            "timeout": settings.agent_exec_timeout_seconds,
        }
        settings.agent_exec_workdir_root = root / "runs"
        settings.upload_root = root / "uploads"
        settings.outputs_root = root / "outputs"
        settings.upload_root.mkdir(parents=True)
        settings.outputs_root.mkdir(parents=True)
        settings.agent_exec_max_files = 5
        settings.agent_exec_max_input_bytes = 1024
        settings.agent_exec_max_output_bytes = 1024
        settings.agent_exec_timeout_seconds = 10

        self.provider = FakeProvider()
        self.registry = AgentExecProviderRegistry()
        self.registry.register(self.provider)
        self.events: list[dict] = []
        self.service = AgentExecService(
            registry=self.registry,
            policy_service=AgentExecPolicyService(),
            event_sink=self.events.append,
        )
        self.service.policy_service.update_policy(
            self.provider,
            AgentExecPolicyUpdateRequest(enabled=True),
            updated_by="admin-1",
        )

    def tearDown(self) -> None:
        settings.agent_exec_workdir_root = self.originals["workdir"]
        settings.upload_root = self.originals["upload"]
        settings.outputs_root = self.originals["outputs"]
        settings.agent_exec_max_files = self.originals["max_files"]
        settings.agent_exec_max_input_bytes = self.originals["max_input"]
        settings.agent_exec_max_output_bytes = self.originals["max_output"]
        settings.agent_exec_timeout_seconds = self.originals["timeout"]
        self.tmp.cleanup()

    def _input(self, content: bytes, name: str = "input.txt"):
        """创建受管输入文件并返回 manifest 项。"""
        source = settings.upload_root / name
        source.write_bytes(content)
        return AgentExecInputFileData(
            name=name,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            source_object_id=name,
        )

    def _request(self, input_files=None, **overrides):
        """构建执行请求。"""
        payload = {
            "provider_id": "fake",
            "task": AgentExecTaskRequest(
                task_type="structured_file_task",
                prompt="do work",
                input_files=input_files or [],
                output_schema=SCHEMA,
                timeout_seconds=5,
            ),
            "actor_user_id": "admin-1",
            "actor_role": "admin",
            "confirmed": True,
        }
        payload.update(overrides)
        return AgentExecExecutionRequest(**payload)

    def test_success_lifecycle_and_events(self) -> None:
        run = self.service.execute(self._request([self._input(b"hello")]))

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.output, {"summary": "ok"})
        self.assertEqual(run.input_files[0].name, "input.txt")
        self.assertEqual(
            [event["event_type"] for event in self.events],
            [
                "agent_exec.requested",
                "agent_exec.provider_ready",
                "agent_exec.started",
                "agent_exec.completed",
            ],
        )

    def test_role_policy_rejected(self) -> None:
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request(actor_role="user"))

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.reason_code, "role_not_allowed")
        self.assertEqual(self.events[-1]["event_type"], "agent_exec.policy.rejected")

    def test_disabled_policy_rejected(self) -> None:
        service = AgentExecService(
            registry=self.registry,
            policy_service=AgentExecPolicyService(),
        )
        with self.assertRaises(AgentExecRequestError) as ctx:
            service.execute(self._request())

        self.assertEqual(ctx.exception.reason_code, "provider_disabled")

    def test_confirmation_plan_mode_and_read_only_blocked(self) -> None:
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request(confirmed=False))
        self.assertEqual(ctx.exception.reason_code, "confirmation_required")

        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request(plan_mode=True))
        self.assertEqual(ctx.exception.reason_code, "plan_mode_blocked")

        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request(permission_mode="read_only"))
        self.assertEqual(ctx.exception.reason_code, "read_only_blocked")

    def test_task_type_not_allowed(self) -> None:
        self.provider.supported_task_types = ("shell_task",)
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request())

        self.assertEqual(ctx.exception.reason_code, "task_type_not_supported")

    def test_unknown_provider_rejected(self) -> None:
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request(provider_id="missing"))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.reason_code, "provider_not_registered")

    def test_provider_unavailable_returns_structured_error(self) -> None:
        self.provider.available = False

        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request())

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.reason_code, "provider_unavailable")
        event_types = [event["event_type"] for event in self.events]
        self.assertIn("agent_exec.provider_unavailable", event_types)
        self.assertIn("agent_exec.failed", event_types)

    def test_input_source_not_found(self) -> None:
        item = AgentExecInputFileData(
            name="missing.txt",
            size_bytes=1,
            sha256="0" * 64,
            source_object_id="missing.txt",
        )
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request([item]))

        self.assertEqual(ctx.exception.reason_code, "input_source_not_found")

    def test_input_symlink_rejected(self) -> None:
        target = settings.upload_root / "real.txt"
        target.write_bytes(b"real")
        link = settings.upload_root / "link.txt"
        link.symlink_to(target)
        item = AgentExecInputFileData(
            name="link.txt",
            size_bytes=4,
            sha256=hashlib.sha256(b"real").hexdigest(),
            source_object_id="link.txt",
        )
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request([item]))

        self.assertEqual(ctx.exception.reason_code, "input_symlink_rejected")

    def test_input_hash_mismatch(self) -> None:
        item = self._input(b"hello")
        item = item.model_copy(update={"sha256": "0" * 64})
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request([item]))

        self.assertEqual(ctx.exception.reason_code, "input_hash_mismatch")

    def test_input_too_large_and_too_many_files(self) -> None:
        big = self._input(b"x" * 2048, name="big.bin")
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request([big]))
        self.assertEqual(ctx.exception.reason_code, "input_too_large")

        files = [self._input(b"1", name=f"f{i}.txt") for i in range(6)]
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request(files))
        self.assertEqual(ctx.exception.reason_code, "too_many_input_files")

    def test_input_name_traversal_rejected(self) -> None:
        source = self._input(b"hello", name="safe.txt")
        item = source.model_copy(update={"name": "../escape.txt"})
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.execute(self._request([item]))

        self.assertEqual(ctx.exception.reason_code, "input_name_invalid")

    def test_output_symlink_rejected(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """写入逃逸 symlink。"""
            artifacts = workdir / "artifacts"
            artifacts.mkdir()
            (artifacts / "escape").symlink_to(settings.upload_root)
            return AgentExecProviderResult(
                provider_id="fake", success=True, output={"summary": "ok"}
            )

        self.provider.execute_handler = handler
        run = self.service.execute(self._request())

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "output_symlink_rejected")

    def test_output_executable_hidden_empty_rejected(self) -> None:
        cases = {
            "output_executable_rejected": ("script.sh", b"echo hi", 0o755),
            "output_hidden_rejected": (".hidden.txt", b"x", 0o644),
            "output_empty_rejected": ("empty.txt", b"", 0o644),
        }
        for expected_code, (name, content, mode) in cases.items():
            with self.subTest(expected_code):

                def handler(*, task, workdir, timeout_seconds, should_cancel=None,
                            name=name, content=content, mode=mode):
                    """写入违规输出。"""
                    artifacts = workdir / "artifacts"
                    artifacts.mkdir()
                    path = artifacts / name
                    path.write_bytes(content)
                    path.chmod(mode)
                    return AgentExecProviderResult(
                        provider_id="fake", success=True, output={"summary": "ok"}
                    )

                self.provider.execute_handler = handler
                run = self.service.execute(self._request())
                self.assertEqual(run.status, "failed")
                self.assertEqual(run.error_code, expected_code)

    def test_output_too_large_rejected(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """写入超限输出。"""
            artifacts = workdir / "artifacts"
            artifacts.mkdir()
            (artifacts / "big.bin").write_bytes(b"x" * 2048)
            return AgentExecProviderResult(
                provider_id="fake", success=True, output={"summary": "ok"}
            )

        self.provider.execute_handler = handler
        run = self.service.execute(self._request())

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "output_too_large")

    def test_valid_artifacts_recorded(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """写入合法 artifact。"""
            artifacts = workdir / "artifacts"
            artifacts.mkdir()
            (artifacts / "result.md").write_bytes(b"# result")
            return AgentExecProviderResult(
                provider_id="fake", success=True, output={"summary": "ok"}
            )

        self.provider.execute_handler = handler
        run = self.service.execute(self._request())

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.artifacts[0].path, "result.md")
        self.assertEqual(run.artifacts[0].content_type, "text/markdown")

    def test_provider_failure_marks_failed(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """模拟 provider 超时。"""
            raise AgentExecProviderError("timeout", "timed out")

        self.provider.execute_handler = handler
        run = self.service.execute(self._request())

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "timeout")
        self.assertEqual(self.events[-1]["event_type"], "agent_exec.failed")

    def test_cancel_running_run_and_stable_terminal_state(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """等待取消信号。"""
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if should_cancel is not None and should_cancel():
                    raise AgentExecProviderError("cancelled", "已取消")
                time.sleep(0.01)
            raise AgentExecProviderError("timeout", "timeout")

        self.provider.execute_handler = handler
        result: dict = {}

        def run_execute():
            """在线程中执行。"""
            result["run"] = self.service.execute(self._request())

        thread = threading.Thread(target=run_execute)
        thread.start()
        run_id = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and run_id is None:
            runs = self.service.list_runs()
            if runs and runs[0].status == "running":
                run_id = runs[0].run_id
            time.sleep(0.01)
        self.assertIsNotNone(run_id)

        cancelled = self.service.cancel(run_id)
        self.assertEqual(cancelled.status, "cancelled")
        thread.join(timeout=5)

        final_run = self.service.get_run(run_id)
        self.assertEqual(final_run.status, "cancelled")
        stable = self.service.cancel(run_id)
        self.assertEqual(stable.status, "cancelled")
        event_types = [event["event_type"] for event in self.events]
        self.assertEqual(event_types.count("agent_exec.cancelled"), 1)

    def test_cancel_missing_run(self) -> None:
        with self.assertRaises(AgentExecRequestError) as ctx:
            self.service.cancel("aer_missing")

        self.assertEqual(ctx.exception.status_code, 404)

    def test_lui_tool_default_hidden_and_gated_visibility(self) -> None:
        fresh = AgentExecService(
            registry=self.registry,
            policy_service=AgentExecPolicyService(),
            event_sink=lambda event: None,
        )
        self.assertIsNone(fresh.lui_tool(role="admin"))

        tool = self.service.lui_tool(role="admin")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.tool_id, "agent_exec:structured_file_task")
        self.assertTrue(tool.requires_confirmation)
        self.assertIn("input_files", tool.confirmation_fields)
        self.assertIn("timeout_seconds", tool.confirmation_fields)

        self.assertIsNone(self.service.lui_tool(role="user"))
        self.provider.available = False
        self.assertIsNone(self.service.lui_tool(role="admin"))


if __name__ == "__main__":
    unittest.main()
