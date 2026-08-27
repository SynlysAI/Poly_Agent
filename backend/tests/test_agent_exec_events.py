"""agent_exec 存储、Audit 与 Trace 投影测试。"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.infra.agent_exec_repositories import (
    AgentExecArtifactRepository,
    AgentExecAuditWriter,
    AgentExecProviderPolicyRepository,
    AgentExecRunRepository,
)
from app.infra.computation_repositories import AuditEventRepository
from app.infra.research_engine_repositories import AssistantEventRepository
from app.schemas.agent_exec import (
    AgentExecExecutionRequest,
    AgentExecInputFileData,
    AgentExecPolicyUpdateRequest,
    AgentExecProviderReadiness,
    AgentExecProviderResult,
    AgentExecTaskRequest,
)
from app.services.agent_exec_providers.base import AgentExecProviderError
from app.services.agent_exec_providers.registry import AgentExecProviderRegistry
from app.services.agent_exec_service import AgentExecService
from app.services.assistant_trace_service import AssistantTraceProjectionService


SCHEMA = {"type": "object", "required": ["summary"]}


class RecordingProvider:
    """测试用可控 provider，使用唯一 provider_id 隔离存储。"""

    supported_task_types = ("structured_file_task",)

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.display_name = "Recording Provider"
        self.available = True
        self.execute_handler = self._success

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
            message="未就绪",
        )

    def execute(self, *, task, workdir, timeout_seconds, should_cancel=None):
        """执行可控任务。"""
        return self.execute_handler(
            task=task, workdir=workdir, timeout_seconds=timeout_seconds,
            should_cancel=should_cancel,
        )

    def _success(self, *, task, workdir, timeout_seconds, should_cancel=None):
        """默认成功行为。"""
        return AgentExecProviderResult(
            provider_id=self.provider_id, success=True, output={"summary": "ok"}
        )


class AgentExecEventsTest(unittest.TestCase):
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
        }
        settings.agent_exec_workdir_root = root / "runs"
        settings.upload_root = root / "uploads"
        settings.outputs_root = root / "outputs"
        settings.upload_root.mkdir(parents=True)
        settings.outputs_root.mkdir(parents=True)
        settings.agent_exec_max_files = 5
        settings.agent_exec_max_input_bytes = 4096
        settings.agent_exec_max_output_bytes = 4096

        self.provider_id = f"rec-{uuid4().hex[:8]}"
        self.provider = RecordingProvider(self.provider_id)
        self.registry = AgentExecProviderRegistry()
        self.registry.register(self.provider)

    def tearDown(self) -> None:
        settings.agent_exec_workdir_root = self.originals["workdir"]
        settings.upload_root = self.originals["upload"]
        settings.outputs_root = self.originals["outputs"]
        settings.agent_exec_max_files = self.originals["max_files"]
        settings.agent_exec_max_input_bytes = self.originals["max_input"]
        settings.agent_exec_max_output_bytes = self.originals["max_output"]
        self.tmp.cleanup()

    def _service(self) -> AgentExecService:
        """构建使用真实仓储写入的服务。"""
        service = AgentExecService(registry=self.registry)
        service.policy_service.update_policy(
            self.provider,
            AgentExecPolicyUpdateRequest(enabled=True),
            updated_by="admin-1",
        )
        return service

    def _request(self, **overrides) -> AgentExecExecutionRequest:
        """构建执行请求。"""
        input_files = overrides.pop("input_files", [])
        payload = {
            "provider_id": self.provider_id,
            "task": AgentExecTaskRequest(
                task_type="structured_file_task",
                prompt="task",
                input_files=input_files,
                output_schema=SCHEMA,
                timeout_seconds=5,
            ),
            "actor_user_id": "admin-1",
            "actor_role": "admin",
            "confirmed": True,
        }
        payload.update(overrides)
        return AgentExecExecutionRequest(**payload)

    def test_run_and_artifacts_persisted(self) -> None:
        source = settings.upload_root / "input.txt"
        source.write_bytes(b"hello")

        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """写出 artifact。"""
            artifacts = workdir / "artifacts"
            artifacts.mkdir()
            (artifacts / "out.md").write_bytes(b"# ok")
            return AgentExecProviderResult(
                provider_id=self.provider_id, success=True, output={"summary": "ok"}
            )

        self.provider.execute_handler = handler
        service = self._service()
        item = AgentExecInputFileData(
            name="input.txt",
            size_bytes=5,
            sha256=hashlib.sha256(b"hello").hexdigest(),
            source_object_id="input.txt",
        )
        run = service.execute(self._request(input_files=[item]))

        stored = AgentExecRunRepository.get_run(run.run_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.policy_snapshot.enabled, True)
        self.assertEqual(stored.input_files[0].source_object_id, "input.txt")

        artifacts = AgentExecArtifactRepository.list_artifacts(run.run_id)
        self.assertEqual(artifacts[0]["path"], "out.md")

        runs, total = AgentExecRunRepository.list_runs(created_by="admin-1")
        self.assertGreaterEqual(total, 1)
        self.assertIn(run.run_id, {item.run_id for item in runs})

    def test_policy_repository_defaults_and_update_audit(self) -> None:
        self.assertIsNone(
            AgentExecProviderPolicyRepository.get_policy(self.provider_id)
        )

        service = self._service()
        policy = service.policy_service.get_policy(self.provider_id)
        self.assertTrue(policy.enabled)

        stored = AgentExecProviderPolicyRepository.get_policy(self.provider_id)
        self.assertIsNotNone(stored)
        self.assertTrue(stored.enabled)
        self.assertEqual(stored.updated_by, "admin-1")

        events, _ = AuditEventRepository.list_events(
            entity_type="agent_exec_provider",
            entity_id=self.provider_id,
            event_type="agent_exec.policy.updated",
            page=1,
            page_size=10,
        )
        self.assertGreaterEqual(len(events), 1)
        self.assertIn("enabled", events[0]["before"])
        self.assertIn("allowed_roles", events[0]["after"])

    def test_execute_with_chat_writes_audit_and_assistant_events(self) -> None:
        chat_id = f"chat-{uuid4().hex[:10]}"
        call_id = f"call-{uuid4().hex[:10]}"
        service = self._service()
        run = service.execute(
            self._request(chat_id=chat_id, assistant_tool_call_id=call_id)
        )

        audit_events, _ = AuditEventRepository.list_events(
            entity_type="agent_exec_run",
            entity_id=run.run_id,
            event_type=None,
            page=1,
            page_size=20,
        )
        audit_types = [item["event_type"] for item in audit_events]
        for expected in (
            "agent_exec.requested",
            "agent_exec.provider_ready",
            "agent_exec.started",
            "agent_exec.completed",
        ):
            self.assertIn(expected, audit_types)

        assistant_events, _ = AssistantEventRepository.list_all(
            {"chat_id": chat_id, "created_by": "admin-1"}, page=1, page_size=50
        )
        agent_events = [
            item for item in assistant_events
            if str(item.get("type") or "").startswith("agent_exec.")
        ]
        self.assertGreaterEqual(len(agent_events), 4)
        completed = next(
            item for item in agent_events
            if item.get("type") == "agent_exec.completed"
        )
        data = completed.get("data") or {}
        self.assertEqual(data.get("run_id"), run.run_id)
        self.assertEqual(data.get("provider_id"), self.provider_id)
        self.assertEqual(data.get("task_type"), "structured_file_task")
        self.assertEqual(data.get("source"), "agent_exec")

    def test_failed_run_terminal_state_persisted(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """模拟失败。"""
            raise AgentExecProviderError("codex_nonzero_exit", "boom")

        self.provider.execute_handler = handler
        service = self._service()
        run = service.execute(self._request())

        stored = AgentExecRunRepository.get_run(run.run_id)
        self.assertEqual(stored.status, "failed")
        self.assertEqual(stored.error_code, "codex_nonzero_exit")
        self.assertIsNotNone(stored.finished_at)

    def test_cancelled_run_terminal_state_persisted(self) -> None:
        def handler(*, task, workdir, timeout_seconds, should_cancel=None):
            """等待取消。"""
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if should_cancel is not None and should_cancel():
                    raise AgentExecProviderError("cancelled", "cancelled")
                time.sleep(0.01)
            raise AgentExecProviderError("timeout", "timeout")

        self.provider.execute_handler = handler
        service = self._service()
        result: dict = {}
        thread = threading.Thread(
            target=lambda: result.setdefault("run", service.execute(self._request()))
        )
        thread.start()
        run_id = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and run_id is None:
            for candidate in service.list_runs():
                if candidate.status == "running":
                    run_id = candidate.run_id
            time.sleep(0.01)
        self.assertIsNotNone(run_id)
        service.cancel(run_id)
        thread.join(timeout=5)

        stored = AgentExecRunRepository.get_run(run_id)
        self.assertEqual(stored.status, "cancelled")

    def test_audit_writer_sanitizes_sensitive_metadata(self) -> None:
        cleaned = AgentExecAuditWriter.sanitize_metadata(
            {
                "api_key": "secret",
                "prompt": "full prompt",
                "reason_code": "ok",
                "artifact_count": 2,
            }
        )

        self.assertNotIn("api_key", cleaned)
        self.assertNotIn("prompt", cleaned)
        self.assertEqual(cleaned["reason_code"], "ok")

    def test_trace_projection_recognizes_agent_exec_events(self) -> None:
        service = AssistantTraceProjectionService()
        agent_run_id = f"aer-{uuid4().hex[:8]}"
        events = [
            {
                "event_id": f"evt-{index}",
                "type": event_type,
                "run_id": "",
                "at": datetime.now(),
                "data": {
                    "run_id": agent_run_id,
                    "provider_id": self.provider_id,
                    "message": message,
                },
            }
            for index, (event_type, message) in enumerate(
                [
                    ("agent_exec.requested", ""),
                    ("agent_exec.started", ""),
                    ("agent_exec.completed", ""),
                ]
            )
        ]

        steps, _ = service._project_steps("trace-1", events, [])
        agent_steps = [step for step in steps if step.type == "agent_exec"]
        self.assertEqual(len(agent_steps), 1)
        self.assertEqual(agent_steps[0].status, "success")

        failed_events = [
            {
                "event_id": "evt-failed",
                "type": "agent_exec.failed",
                "run_id": "",
                "at": datetime.now(),
                "data": {
                    "run_id": agent_run_id,
                    "provider_id": self.provider_id,
                    "message": "执行失败",
                },
            }
        ]
        steps, _ = service._project_steps("trace-1", failed_events, [])
        failed_steps = [step for step in steps if step.type == "agent_exec"]
        self.assertEqual(failed_steps[0].status, "failed")
        self.assertIn("执行失败", failed_steps[0].summary)


if __name__ == "__main__":
    unittest.main()
