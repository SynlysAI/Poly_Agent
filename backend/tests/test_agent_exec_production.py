"""agent_exec 生产化收口测试。"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.config import Settings, settings
from app.infra.agent_exec_repositories import AgentExecRunRepository
from app.schemas.agent_exec import AgentExecProviderPolicy, AgentExecRunData
from app.services.agent_exec_alert_service import AgentExecAlertService
from app.services.agent_exec_providers.codex import CodexAgentExecProvider
from app.services.agent_exec_service import AgentExecService


def make_run(run_id: str, *, status: str = "running", finished_days_ago: int = 0) -> AgentExecRunData:
    """构建生产化测试用的持久化 run。

    Args:
        run_id: run ID。
        status: run 状态。
        finished_days_ago: 终态距今天数。

    Returns:
        可直接持久化的 run 对象。
    """
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=finished_days_ago + 1)
    finished = now - timedelta(days=finished_days_ago)
    return AgentExecRunData(
        run_id=run_id,
        provider_id="fake",
        task_type="structured_file_task",
        status=status,  # type: ignore[arg-type]
        created_by="admin",
        created_at=created,
        started_at=created,
        finished_at=finished if status in {"completed", "failed", "cancelled"} else None,
        duration_ms=1000 if status in {"completed", "failed", "cancelled"} else None,
        policy_snapshot=AgentExecProviderPolicy(provider_id="fake"),
    )


class AgentExecProductionTest(ComputationTestCase):
    """覆盖启动恢复、清理、配置诊断和资源隔离。"""

    def setUp(self) -> None:
        super().setUp()
        self.original_workdir = settings.agent_exec_workdir_root
        self.original_retention = settings.agent_exec_workdir_retention_hours
        self.original_max_workdirs = settings.agent_exec_max_retained_workdirs
        self.original_config_errors = list(settings.agent_exec_config_errors)
        settings.agent_exec_workdir_root = self.runtime_root / "agent_exec"
        settings.agent_exec_workdir_retention_hours = 24
        settings.agent_exec_max_retained_workdirs = 1
        settings.agent_exec_config_errors = []
        self.events: list[dict] = []

    def tearDown(self) -> None:
        settings.agent_exec_workdir_root = self.original_workdir
        settings.agent_exec_workdir_retention_hours = self.original_retention
        settings.agent_exec_max_retained_workdirs = self.original_max_workdirs
        settings.agent_exec_config_errors = self.original_config_errors
        super().tearDown()

    def test_invalid_agent_exec_config_falls_back_to_safe_defaults(self) -> None:
        env = {
            "AGENT_EXEC_ENABLED": "yes-please",
            "AGENT_EXEC_TIMEOUT_SECONDS": "not-a-number",
            "AGENT_EXEC_MAX_CONCURRENCY": "0",
            "AGENT_EXEC_DEPLOYMENT_MODE": "multi_process",
            "WEB_CONCURRENCY": "2",
            "AGENT_EXEC_CODEX_MIN_VERSION": "0.149",
        }
        with patch.dict(os.environ, env):
            parsed = Settings()
        self.assertFalse(parsed.agent_exec_enabled)
        self.assertEqual(parsed.agent_exec_timeout_seconds, 600)
        self.assertEqual(parsed.agent_exec_max_concurrency, 2)
        self.assertTrue(any("AGENT_EXEC_ENABLED" in item for item in parsed.agent_exec_config_errors))
        self.assertTrue(any("AGENT_EXEC_TIMEOUT_SECONDS" in item for item in parsed.agent_exec_config_errors))
        self.assertTrue(any("仅支持 single_process" in item for item in parsed.agent_exec_config_errors))
        self.assertTrue(any("单进程终态约束冲突" in item for item in parsed.agent_exec_config_errors))
        self.assertEqual(parsed.agent_exec_codex_min_version, "0.149.1")
        self.assertTrue(any("AGENT_EXEC_CODEX_MIN_VERSION" in item for item in parsed.agent_exec_config_errors))

    def test_invalid_config_makes_provider_unavailable_without_startup_failure(self) -> None:
        settings.agent_exec_config_errors = ["AGENT_EXEC_MAX_FILES 必须是整数"]
        settings.agent_exec_enabled = True
        readiness = CodexAgentExecProvider().readiness()
        self.assertFalse(readiness.available)
        self.assertEqual(readiness.reason_code, "agent_exec_config_invalid")
        self.assertIn("config_errors", readiness.details)

    def test_startup_recovery_marks_nonterminal_runs_failed(self) -> None:
        run = make_run("aer_restart_recovery")
        AgentExecRunRepository.save_run(run)
        service = AgentExecService(event_sink=self.events.append)

        recovered = service.recover_interrupted_runs()

        self.assertEqual([item.run_id for item in recovered], [run.run_id])
        persisted = AgentExecRunRepository.get_run(run.run_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, "failed")  # type: ignore[union-attr]
        self.assertEqual(persisted.error_code, "restart_recovered")  # type: ignore[union-attr]
        self.assertTrue(any(item["event_type"] == "agent_exec.restart.recovered" for item in self.events))

    def test_workdir_cleanup_honors_retention_limit_and_writes_audit(self) -> None:
        old_run = make_run("aer_cleanup_old", status="completed", finished_days_ago=3)
        new_run = make_run("aer_cleanup_new", status="completed", finished_days_ago=0)
        AgentExecRunRepository.save_run(old_run)
        AgentExecRunRepository.save_run(new_run)
        old_dir = settings.agent_exec_workdir_root / old_run.run_id
        new_dir = settings.agent_exec_workdir_root / new_run.run_id
        old_dir.mkdir(parents=True, mode=0o700)
        new_dir.mkdir(parents=True, mode=0o700)
        service = AgentExecService(event_sink=self.events.append)

        cleaned = service.cleanup_terminal_workdirs()

        self.assertEqual(cleaned, [old_run.run_id])
        self.assertFalse(old_dir.exists())
        self.assertTrue(new_dir.exists())
        self.assertTrue(any(item["event_type"] == "agent_exec.workdir.cleaned" for item in self.events))

    def test_audit_recovery_rewrites_missing_lifecycle_events(self) -> None:
        run = make_run(
            "aer_audit_retry",
            status="failed",
            finished_days_ago=0,
        ).model_copy(
            update={
                "error_code": "provider_unavailable",
                "error_message": "provider 未就绪",
                "audit_error": True,
            }
        )
        AgentExecRunRepository.save_run(run)
        service = AgentExecService(event_sink=self.events.append)

        recovered_run, recovered_events = service.recover_audit_events(run.run_id)

        self.assertEqual(
            recovered_events,
            ["agent_exec.requested", "agent_exec.started", "agent_exec.failed"],
        )
        self.assertFalse(recovered_run.audit_error)
        self.assertFalse(AgentExecRunRepository.get_run(run.run_id).audit_error)  # type: ignore[union-attr]
        self.assertIn("agent_exec.audit.recovered", {item["event_type"] for item in self.events})

    def test_repository_time_window_filters_work_in_sqlite_mode(self) -> None:
        old_run = make_run("aer_window_old", finished_days_ago=3)
        new_run = make_run("aer_window_new", finished_days_ago=0)
        AgentExecRunRepository.save_run(old_run)
        AgentExecRunRepository.save_run(new_run)
        boundary = datetime.now(timezone.utc) - timedelta(days=2)

        rows, total = AgentExecRunRepository.list_runs(
            created_after=boundary,
            page=1,
            page_size=10,
        )

        self.assertEqual(total, 1)
        self.assertEqual([item.run_id for item in rows], [new_run.run_id])


class CodexProbeAndResourceTest(unittest.TestCase):
    """覆盖显式版本探测与操作系统资源限制。"""

    def setUp(self) -> None:
        self.originals = {
            "enabled": settings.agent_exec_enabled,
            "errors": list(settings.agent_exec_config_errors),
            "api_key": settings.agent_exec_codex_api_key,
            "model": settings.agent_exec_codex_model,
        }
        settings.agent_exec_enabled = True
        settings.agent_exec_config_errors = []
        settings.agent_exec_codex_api_key = "test-key"
        settings.agent_exec_codex_model = ""

    def tearDown(self) -> None:
        settings.agent_exec_enabled = self.originals["enabled"]
        settings.agent_exec_config_errors = self.originals["errors"]
        settings.agent_exec_codex_api_key = self.originals["api_key"]
        settings.agent_exec_codex_model = self.originals["model"]

    def test_readiness_and_probe_record_binary_digest_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            binary = Path(raw_root) / "codex"
            binary.write_text("#!/bin/sh\necho 'codex 1.2.3'\n", encoding="utf-8")
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

            class FakeVersionProcess:
                """返回固定版本的探测进程。"""

                returncode = 0

                @staticmethod
                def communicate(timeout=None):
                    """返回版本输出。"""
                    return "codex 1.2.3\n", ""

            provider = CodexAgentExecProvider(process_factory=lambda *args, **kwargs: FakeVersionProcess())
            with patch(
                "app.services.agent_exec_providers.codex.shutil.which",
                return_value=str(binary),
            ):
                readiness = provider.readiness()
                probe = provider.probe()

            self.assertTrue(readiness.available)
            self.assertEqual(readiness.details["binary"], "codex")
            self.assertEqual(len(readiness.details["binary_sha256"]), 64)
            self.assertEqual(probe.version, "codex 1.2.3")
            self.assertEqual(probe.minimum_version, settings.agent_exec_codex_min_version)
            self.assertTrue(probe.version_supported)
            self.assertEqual(probe.binary_path, str(binary.resolve()))
            self.assertEqual(probe.binary_sha256, readiness.details["binary_sha256"])

    def test_probe_reports_unsupported_codex_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            binary = Path(raw_root) / "codex"
            binary.write_text("#!/bin/sh\necho 'codex-cli 0.148.0'\n", encoding="utf-8")
            binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

            class FakeVersionProcess:
                """返回过低版本的探测进程。"""

                returncode = 0

                @staticmethod
                def communicate(timeout=None):
                    """返回固定版本输出。"""
                    return "codex-cli 0.148.0\n", ""

            provider = CodexAgentExecProvider(
                process_factory=lambda *args, **kwargs: FakeVersionProcess()
            )
            with (
                patch(
                    "app.services.agent_exec_providers.codex.shutil.which",
                    return_value=str(binary),
                ),
                patch.object(settings, "agent_exec_codex_min_version", "0.149.1"),
            ):
                probe = provider.probe()

            self.assertEqual(probe.version, "codex-cli 0.148.0")
            self.assertFalse(probe.version_supported)
            self.assertTrue(any("最低要求" in warning for warning in probe.warnings))

    def test_process_limits_apply_cpu_memory_and_file_limits(self) -> None:
        provider = CodexAgentExecProvider()
        limits: list[tuple[int, tuple[int, int]]] = []

        def fake_setrlimit(resource_id, limits_tuple):
            """记录资源限制调用。"""
            limits.append((resource_id, limits_tuple))

        apply_limits = provider._make_process_limits(10)
        with patch("app.services.agent_exec_providers.codex.resource.setrlimit", side_effect=fake_setrlimit):
            apply_limits()

        self.assertEqual(len(limits), 3)
        self.assertTrue(all(entry[1][0] == entry[1][1] for entry in limits))


class AgentExecAlertServiceTest(unittest.TestCase):
    """覆盖外部告警出口。"""

    def test_webhook_failure_does_not_raise(self) -> None:
        calls: list[dict] = []

        def failed_post(url, json=None, timeout=None):
            """记录并模拟 webhook 故障。"""
            calls.append({"url": url, "json": json, "timeout": timeout})
            raise RuntimeError("network unavailable")

        with patch.object(settings, "agent_exec_alert_webhook_url", "https://alerts.example.test/hook"), patch(
            "app.services.agent_exec_alert_service.httpx.post",
            side_effect=failed_post,
        ):
            AgentExecAlertService.emit(
                level="critical",
                title="audit failed",
                reasons=["audit_event_write_failed"],
                context={"run_id": "aer_alert"},
            )

        self.assertEqual(len(calls), 1)
