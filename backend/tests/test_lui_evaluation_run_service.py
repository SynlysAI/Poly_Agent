"""LUI 评测手动运行服务与接口测试。"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.infra.lui_evaluation_repositories import LuiEvaluationJobRepository
from app.schemas.lui_evaluation import LuiEvaluationRunRequest
from app.services.lui_evaluation_run_service import LuiEvaluationRunService

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class NoStartThread:
    """模拟后台线程但不执行任务。"""

    def __init__(self, **kwargs: object) -> None:
        """保存线程参数。

        Args:
            **kwargs: threading.Thread 参数。
        """
        self.kwargs = kwargs

    def start(self) -> None:
        """保持任务为 queued 状态。"""


class SyncThread:
    """在当前线程同步执行任务的测试线程。"""

    def __init__(self, **kwargs: object) -> None:
        """保存线程参数。

        Args:
            **kwargs: threading.Thread 参数。
        """
        self.kwargs = kwargs

    def start(self) -> None:
        """同步调用目标函数。"""
        self.kwargs["target"](*self.kwargs.get("args", ()))


class FakeProcess:
    """按预设输出返回的假子进程。"""

    def __init__(self, output: str, returncode: int = 0) -> None:
        """初始化假进程。

        Args:
            output: 进程 stdout 输出。
            returncode: 进程退出码。
        """
        self.pid = 43210
        self.stdout = io.StringIO(output)
        self._returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        """返回进程是否退出。"""
        return None

    def wait(self) -> int:
        """返回预设退出码。"""
        return self._returncode

    def terminate(self) -> None:
        """记录终止调用。"""
        self.terminated = True


class LuiEvaluationRunServiceTest(ComputationTestCase):
    """运行服务单元测试。"""

    def _service(self, processes: list[FakeProcess] | None = None, *, sync: bool = True):
        """构造可注入假进程的服务。

        Args:
            processes: 按调用顺序返回的假进程。
            sync: 是否同步执行监控线程。

        Returns:
            测试专用服务实例。
        """
        outputs = processes or []

        def process_factory(*args: object, **kwargs: object) -> FakeProcess:
            """弹出下一个假进程。"""
            if not outputs:
                raise AssertionError(f"unexpected subprocess: {args}, {kwargs}")
            return outputs.pop(0)

        thread_factory = SyncThread if sync else NoStartThread
        return LuiEvaluationRunService(
            process_factory=process_factory,
            thread_factory=thread_factory,
        )

    def test_full_mode_requires_credentials_and_model(self) -> None:
        """full 模式缺凭证时返回 400。"""
        service = self._service()
        with patch.dict("os.environ", {}, clear=False):
            with self.assertRaises(HTTPException) as caught:
                service.create_job(
                    LuiEvaluationRunRequest(
                        mode="full",
                        provider_id="deepseek",
                        model_id="deepseek-chat",
                    ),
                    created_by="admin",
                )
        self.assertEqual(caught.exception.status_code, 400)

    def test_full_mode_requires_configured_model(self) -> None:
        """full 模式提交未配置模型时返回 400。"""
        service = self._service()
        catalog = type("Catalog", (), {"providers": []})()
        with patch.dict(
            "os.environ",
            {"LUI_EVAL_USERNAME": "eval", "LUI_EVAL_PASSWORD": "secret"},
        ), patch(
            "app.services.llm_model_service.LLMModelService.get_catalog",
            return_value=catalog,
        ):
            with self.assertRaises(HTTPException) as caught:
                service.create_job(
                    LuiEvaluationRunRequest(
                        mode="full",
                        provider_id="deepseek",
                        model_id="missing",
                    ),
                    created_by="admin",
                )
        self.assertEqual(caught.exception.status_code, 400)

    def test_active_job_blocks_second_creation(self) -> None:
        """存在非终态任务时禁止再次创建。"""
        service = self._service(sync=False)
        created = service.create_job(LuiEvaluationRunRequest(mode="smoke"), created_by="admin")
        with self.assertRaises(HTTPException) as caught:
            service.create_job(LuiEvaluationRunRequest(mode="smoke"), created_by="admin")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(created["status"], "queued")

    def test_progress_is_parsed_and_job_completes(self) -> None:
        """评测输出进度后任务置为完成。"""
        output = "\n".join(
            [
                "evaluation_id: test-id",
                "evaluated: 8",
                "skipped: 0",
                "missing_facts: 0",
                "task_success_rate: 1.0",
                "report: /tmp/report.json",
                "baseline: /tmp/baseline.json",
            ]
        )
        # 先占用一条假进程，但 smoke 只会启动评测进程。
        service = self._service([FakeProcess(output)])
        service.create_job(LuiEvaluationRunRequest(mode="smoke"), created_by="admin")
        document = LuiEvaluationJobRepository.find_latest()
        self.assertIsNotNone(document)
        self.assertEqual(document["status"], "completed")
        self.assertEqual(document["report_file"], "/tmp/report.json")
        self.assertEqual(document["baseline_file"], "/tmp/baseline.json")

    def test_capture_failure_with_facts_continues_evaluation(self) -> None:
        """full 录制部分失败但已有事实时继续评测。"""
        capture = FakeProcess(
            "\n".join(
                [
                    "[1/2] capturing LUI-TS-0001",
                    "[1/2] LUI-TS-0001 PASS",
                    "[2/2] LUI-TS-0002 FAIL: timeout",
                    "facts_written: 1",
                ]
            ),
            returncode=1,
        )
        evaluation = FakeProcess(
            "\n".join(
                [
                    "report: /tmp/report.json",
                    "baseline: /tmp/baseline.json",
                ]
            ),
            returncode=1,
        )
        service = self._service([capture, evaluation])
        with patch.dict(
            "os.environ",
            {"LUI_EVAL_USERNAME": "eval", "LUI_EVAL_PASSWORD": "secret"},
        ), patch(
            "app.services.llm_model_service.LLMModelService.get_catalog",
            return_value=type(
                "Catalog",
                (),
                {
                    "providers": [
                        type(
                            "Provider",
                            (),
                            {
                                "provider_id": "deepseek",
                                "models": [type("Model", (), {"model_id": "deepseek-chat"})()],
                            },
                        )(),
                    ]
                },
            )(),
        ):
            service.create_job(
                LuiEvaluationRunRequest(
                    mode="full",
                    provider_id="deepseek",
                    model_id="deepseek-chat",
                ),
                created_by="admin",
            )
        document = LuiEvaluationJobRepository.find_latest()
        self.assertEqual(document["status"], "completed")
        self.assertEqual(document["progress"]["done"], 2)
        self.assertEqual(document["progress"]["total"], 2)

    def test_capture_zero_facts_marks_failed(self) -> None:
        """full 录制零事实时任务失败且不进入评测。"""
        capture = FakeProcess("facts_written: 0", returncode=1)
        service = self._service([capture])
        with patch.dict(
            "os.environ",
            {"LUI_EVAL_USERNAME": "eval", "LUI_EVAL_PASSWORD": "secret"},
        ), patch(
            "app.services.llm_model_service.LLMModelService.get_catalog",
            return_value=type("Catalog", (), {"providers": []})(),
        ):
            # 模型校验已在其他用例覆盖，这里绕过模型目录限制。
            with patch.object(
                LuiEvaluationRunService,
                "_validate_full_request",
                lambda _service, _request: None,
            ):
                service.create_job(
                    LuiEvaluationRunRequest(
                        mode="full",
                        provider_id="deepseek",
                        model_id="deepseek-chat",
                    ),
                    created_by="admin",
                )
        document = LuiEvaluationJobRepository.find_latest()
        self.assertEqual(document["status"], "failed")
        self.assertIn("facts_written=0", document["error"])

    def test_cancel_uses_process_group_signal(self) -> None:
        """取消任务时优先向子进程进程组发送 SIGTERM。"""
        service = self._service(sync=False)
        created = service.create_job(LuiEvaluationRunRequest(mode="smoke"), created_by="admin")
        process = FakeProcess("")
        from app.services.lui_evaluation_run_service import _active_processes

        _active_processes[created["job_id"]] = process
        with patch(
            "app.services.lui_evaluation_run_service.os.getpgid",
            return_value=process.pid,
        ), patch(
            "app.services.lui_evaluation_run_service.os.killpg",
            side_effect=lambda pid, sig: self.assertEqual(sig.name, "SIGTERM"),
        ):
            cancelled = service.cancel_job(created["job_id"])
        self.assertEqual(cancelled["status"], "cancelled")

    def test_stale_jobs_are_failed_on_recovery(self) -> None:
        """启动恢复会把遗留任务标记为失败。"""
        service = self._service(sync=False)
        created = service.create_job(LuiEvaluationRunRequest(mode="smoke"), created_by="admin")
        failed = service.fail_stale_jobs()
        document = LuiEvaluationJobRepository.find_by_job_id(created["job_id"])
        self.assertEqual(failed, [created["job_id"]])
        self.assertEqual(document["status"], "failed")
        self.assertEqual(document["error"], "interrupted by restart")


class LuiEvaluationRunApiTest(ComputationTestCase):
    """评测任务 API 契约测试。"""

    def _patched_service(self):
        """构造不启动子进程线程的服务。"""
        return LuiEvaluationRunService(
            process_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("API contract test should not spawn a process")
            ),
            thread_factory=NoStartThread,
        )

    def test_create_latest_cancel_run_contract(self) -> None:
        """验证创建、最新任务与取消接口契约。"""
        from app.api.v1.endpoints import assistant

        with patch.object(assistant, "lui_evaluation_run_service", self._patched_service()):
            created_resp = self.client.post(
                "/api/v1/assistant/lui-evaluation/runs",
                json={"mode": "smoke"},
            )
            self.assertEqual(created_resp.status_code, 200)
            created = created_resp.json()["data"]
            self.assertEqual(created["status"], "queued")
            self.assertEqual(created["created_by"], "system")

            latest_resp = self.client.get("/api/v1/assistant/lui-evaluation/runs/latest")
            self.assertEqual(latest_resp.status_code, 200)
            self.assertEqual(latest_resp.json()["data"]["job_id"], created["job_id"])

            duplicate_resp = self.client.post(
                "/api/v1/assistant/lui-evaluation/runs",
                json={"mode": "smoke"},
            )
            self.assertEqual(duplicate_resp.status_code, 409)

            cancel_resp = self.client.post(
                f"/api/v1/assistant/lui-evaluation/runs/{created['job_id']}/cancel"
            )
            self.assertEqual(cancel_resp.status_code, 200)
            self.assertEqual(cancel_resp.json()["data"]["status"], "cancelled")
