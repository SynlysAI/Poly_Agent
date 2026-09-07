"""LUI 评测手动运行的子进程编排服务。"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from app.infra.lui_evaluation_repositories import (
    TERMINAL_JOB_STATUSES,
    LuiEvaluationJobRepository,
)
from app.schemas.lui_evaluation import LuiEvaluationRunRequest


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
LUI_EVALUATION_ROOT = BACKEND_ROOT / "evaluation" / "lui"
BASELINE_ROOT = LUI_EVALUATION_ROOT / "baselines"
REPORT_ROOT = LUI_EVALUATION_ROOT / "reports"
JOB_LOG_ROOT = REPORT_ROOT / "jobs"
DEFAULT_BACKEND_URL = "http://127.0.0.1:5201"
MAX_LOG_TAIL_LINES = 200
_creation_lock = threading.Lock()
_process_lock = threading.Lock()
_active_processes: dict[str, subprocess.Popen[str]] = {}
_progress_pattern = re.compile(r"^\[(\d+)/(\d+)\]\s+(\S+)\s+(PASS|FAIL)(?::|$)")
_capturing_pattern = re.compile(r"^\[(\d+)/(\d+)\]\s+capturing\s+(\S+)")
_facts_pattern = re.compile(r"^facts_written:\s*(\d+)$")


class CommandResult:
    """单个子进程的结构化输出结果。"""

    def __init__(self) -> None:
        """初始化空结果。"""
        self.returncode = 0
        self.facts_written = 0
        self.report_file: str | None = None
        self.baseline_file: str | None = None


class LuiEvaluationRunService:
    """创建、监控和取消 LUI 评测子进程任务。"""

    def __init__(
        self,
        *,
        process_factory: Callable[..., subprocess.Popen[str]] | None = None,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ) -> None:
        """初始化评测运行服务。

        Args:
            process_factory: 子进程工厂；测试可注入 fake Popen。
            thread_factory: 线程工厂；测试可注入同步执行器。
        """
        self._process_factory = process_factory or subprocess.Popen
        self._thread_factory = thread_factory or threading.Thread

    def create_job(
        self,
        request: LuiEvaluationRunRequest,
        *,
        created_by: str,
    ) -> dict[str, Any]:
        """创建评测任务并启动后台监控线程。

        Args:
            request: 已通过接口契约校验的创建请求。
            created_by: 触发评测的管理员标识。

        Returns:
            创建后的任务文档。

        Raises:
            HTTPException: 已有非终态任务、full 凭证缺失或模型未配置时抛出。
        """
        if request.mode == "full":
            self._validate_full_request(request)
        with _creation_lock:
            active = LuiEvaluationJobRepository.find_active_job()
            if active:
                raise HTTPException(
                    status_code=409,
                    detail=f"已有评测任务运行中：{active.get('job_id')}",
                )

            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y%m%d-%H%M")
            job_id = f"lui-job-{uuid.uuid4().hex}"
            document: dict[str, Any] = {
                "job_id": job_id,
                "mode": request.mode,
                "evaluation_id": f"lui-eval-{request.mode}-{timestamp}",
                "provider_id": request.provider_id,
                "model_id": request.model_id,
                "status": "queued",
                "progress": {"done": 0, "total": None, "current_task": None},
                "log_tail": [],
                "error": None,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "baseline_file": None,
                "report_file": None,
            }
            LuiEvaluationJobRepository.save_job(document)
            thread = self._thread_factory(
                target=self._execute_job,
                args=(job_id,),
                name=f"lui-evaluation-{job_id}",
                daemon=True,
            )
            thread.start()
            return document

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """取消运行中任务并向进程组发送 SIGTERM。

        Args:
            job_id: 任务唯一 ID。

        Returns:
            更新后的任务文档。

        Raises:
            HTTPException: 任务不存在时抛出 404。
        """
        document = LuiEvaluationJobRepository.find_by_job_id(job_id)
        if not document:
            raise HTTPException(status_code=404, detail="评测任务不存在")
        if document.get("status") in TERMINAL_JOB_STATUSES:
            return document

        self._transition_to_cancelled(job_id)
        with _process_lock:
            process = _active_processes.get(job_id)
        if process and process.poll() is None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        return LuiEvaluationJobRepository.find_by_job_id(job_id) or document

    def fail_stale_jobs(self) -> list[str]:
        """将服务重启遗留的非终态任务标记为失败。

        Returns:
            被标记为失败的任务 ID。
        """
        items, _ = LuiEvaluationJobRepository.list_jobs(page=1, page_size=100)
        stale_ids = [
            str(item.get("job_id"))
            for item in items
            if item.get("status") not in TERMINAL_JOB_STATUSES
        ]
        for job_id in stale_ids:
            LuiEvaluationJobRepository.update_fields(
                job_id,
                {
                    "status": "failed",
                    "error": "interrupted by restart",
                    "finished_at": datetime.now(timezone.utc),
                },
            )
        return stale_ids

    @staticmethod
    def _validate_full_request(request: LuiEvaluationRunRequest) -> None:
        """校验 full 模式凭证与固定模型配置。

        Args:
            request: 创建请求。

        Raises:
            HTTPException: 凭证或模型配置缺失时抛出 400。
        """
        from app.services.llm_model_service import LLMModelService

        if not os.getenv("LUI_EVAL_USERNAME") or not os.getenv("LUI_EVAL_PASSWORD"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "full 评测需要先在后端环境配置 LUI_EVAL_USERNAME 和 "
                    "LUI_EVAL_PASSWORD（需具备会话、run 与工具确认权限）"
                ),
            )
        catalog = LLMModelService().get_catalog(probe=False)
        provider = next(
            (
                item
                for item in catalog.providers
                if item.provider_id == request.provider_id
            ),
            None,
        )
        if provider is None or not any(
            model.model_id == request.model_id for model in provider.models
        ):
            raise HTTPException(
                status_code=400,
                detail=f"模型未在模型管理中配置：{request.provider_id}/{request.model_id}",
            )

    def _execute_job(self, job_id: str) -> None:
        """执行评测任务的主流程。

        Args:
            job_id: 任务唯一 ID。
        """
        document = LuiEvaluationJobRepository.find_by_job_id(job_id)
        if not document or document.get("status") in TERMINAL_JOB_STATUSES:
            return
        try:
            self._update_status(job_id, "evaluating" if document.get("mode") == "smoke" else "capturing")
            if document.get("mode") == "full":
                capture_ok = self._run_capture(job_id, document)
                if not capture_ok:
                    return
            self._update_status(job_id, "evaluating")
            self._run_evaluation(job_id, document)
        except Exception as exc:  # noqa: BLE001
            self._append_log(job_id, f"任务异常：{exc}")
            self._finish_failed(job_id, str(exc))

    def _run_capture(self, job_id: str, document: dict[str, Any]) -> bool:
        """执行 full 模式事实录制。

        Args:
            job_id: 任务唯一 ID。
            document: 任务文档快照。

        Returns:
            是否可以继续评测。
        """
        facts_dir = LUI_EVALUATION_ROOT / "fixtures" / str(document.get("evaluation_id"))
        command = [
            sys.executable,
            str(SCRIPTS_ROOT / "run_lui_capture.py"),
            "--evaluation-id",
            str(document.get("evaluation_id")),
            "--dataset",
            "backend/evaluation/lui/dataset",
            "--facts-dir",
            str(facts_dir),
            "--base-url",
            os.getenv("POLY_AGENT_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/"),
            "--provider-id",
            str(document.get("provider_id")),
            "--model-id",
            str(document.get("model_id")),
        ]
        result = self._run_command(job_id, command)
        latest = LuiEvaluationJobRepository.find_by_job_id(job_id) or {}
        if latest.get("status") == "cancelled":
            return False
        facts_written = result.facts_written
        if facts_written == 0:
            message = "录制完成但没有写入任何任务事实（facts_written=0），评测已停止"
            self._append_log(job_id, message)
            self._finish_failed(job_id, message)
            return False
        if result.returncode != 0:
            self._append_log(job_id, "部分任务录制失败，将继续评测已写入的事实")
        return True

    def _run_evaluation(self, job_id: str, document: dict[str, Any]) -> None:
        """执行离线评测并保存自动基线。

        Args:
            job_id: 任务唯一 ID。
            document: 任务文档快照。
        """
        latest = LuiEvaluationJobRepository.find_by_job_id(job_id) or {}
        if latest.get("status") in TERMINAL_JOB_STATUSES:
            return
        mode = str(document.get("mode"))
        started_at = datetime.now(timezone.utc)
        timestamp = started_at.strftime("%Y.%m.%d-%H%M")
        baseline_path = BASELINE_ROOT / f"{mode}-{timestamp}.json"
        report_dir = REPORT_ROOT / job_id
        command = [
            sys.executable,
            str(SCRIPTS_ROOT / "run_lui_eval.py"),
            "--dataset",
            "backend/evaluation/lui/dataset",
            "--mode",
            mode,
            "--evaluation-id",
            str(document.get("evaluation_id")),
            "--report-dir",
            str(report_dir),
            "--baseline",
            str(baseline_path),
        ]
        if mode == "full":
            metadata = {
                "model": f"{document.get('provider_id')}/{document.get('model_id')}",
                "trigger": "web",
                "created_by": document.get("created_by"),
            }
            command.extend(["--metadata", json.dumps(metadata, ensure_ascii=False)])
        result = self._run_command(job_id, command)
        latest = LuiEvaluationJobRepository.find_by_job_id(job_id) or {}
        if latest.get("status") == "cancelled":
            return
        if result.returncode not in {0, 1} or not result.report_file:
            self._finish_failed(job_id, f"评测命令退出码异常：{result.returncode}")
            return
        finished_at = datetime.now(timezone.utc)
        LuiEvaluationJobRepository.update_fields(
            job_id,
            {
                "status": "completed",
                "report_file": result.report_file,
                "baseline_file": result.baseline_file,
                "finished_at": finished_at,
            },
        )

    def _run_command(self, job_id: str, command: list[str]) -> CommandResult:
        """执行单个子进程并解析输出。

        Args:
            job_id: 任务唯一 ID。
            command: 子进程命令。

        Returns:
            子进程结构化结果。
        """
        document = LuiEvaluationJobRepository.find_by_job_id(job_id)
        if not document or document.get("status") in TERMINAL_JOB_STATUSES:
            result = CommandResult()
            result.returncode = -1
            return result

        JOB_LOG_ROOT.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(BACKEND_ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        command[0] = sys.executable
        log_path = JOB_LOG_ROOT / f"{job_id}.log"
        with log_path.open("a", encoding="utf-8") as log_file:
            process = self._process_factory(
                command,
                cwd=str(REPO_ROOT),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            with _process_lock:
                _active_processes[job_id] = process
            result = CommandResult()
            try:
                assert process.stdout is not None
                for raw_line in process.stdout:
                    line = raw_line.rstrip("\n")
                    log_file.write(line + "\n")
                    self._append_log(job_id, line)
                    self._parse_line(job_id, line, result=result)
                result.returncode = process.wait()
            finally:
                with _process_lock:
                    _active_processes.pop(job_id, None)

        latest = LuiEvaluationJobRepository.find_by_job_id(job_id) or {}
        if latest.get("status") == "cancelled":
            result.facts_written = 0
            result.report_file = None
            result.baseline_file = None
        return result

    @staticmethod
    def _parse_line(job_id: str, line: str, *, result: CommandResult) -> None:
        """解析子进程进度与输出文件行。

        Args:
            job_id: 任务唯一 ID。
            line: 子进程输出行。
            result: 当前命令结果收集器。
        """
        matching = _progress_pattern.match(line)
        if matching:
            done, total, task_id, _ = matching.groups()
            LuiEvaluationJobRepository.update_fields(
                job_id,
                {
                    "progress": {
                        "done": int(done),
                        "total": int(total),
                        "current_task": task_id,
                    }
                },
            )
            return
        capturing = _capturing_pattern.match(line)
        if capturing:
            done, total, task_id = capturing.groups()
            LuiEvaluationJobRepository.update_fields(
                job_id,
                {
                    "progress": {
                        "done": max(0, int(done) - 1),
                        "total": int(total),
                        "current_task": task_id,
                    }
                },
            )
            return
        facts = _facts_pattern.match(line)
        if facts:
            result.facts_written = int(facts.group(1))
        elif line.startswith("report: "):
            result.report_file = line.removeprefix("report: ")
        elif line.startswith("baseline: "):
            result.baseline_file = line.removeprefix("baseline: ")

    @staticmethod
    def _append_log(job_id: str, line: str) -> None:
        """追加任务日志并只保留尾部固定行数。

        Args:
            job_id: 任务唯一 ID。
            line: 日志内容。
        """
        document = LuiEvaluationJobRepository.find_by_job_id(job_id)
        if not document:
            return
        logs = list(document.get("log_tail") or [])
        logs.append(line)
        LuiEvaluationJobRepository.update_fields(job_id, {"log_tail": logs[-MAX_LOG_TAIL_LINES:]})

    @staticmethod
    def _update_status(job_id: str, status: str) -> None:
        """更新任务状态和开始时间。

        Args:
            job_id: 任务唯一 ID。
            status: 目标状态。
        """
        fields: dict[str, Any] = {"status": status}
        if status in {"capturing", "evaluating"}:
            fields["started_at"] = datetime.now(timezone.utc)
        LuiEvaluationJobRepository.update_fields(job_id, fields)

    @staticmethod
    def _finish_failed(job_id: str, error: str) -> None:
        """将任务标记为失败。

        Args:
            job_id: 任务唯一 ID。
            error: 失败原因。
        """
        LuiEvaluationJobRepository.update_fields(
            job_id,
            {
                "status": "failed",
                "error": error,
                "finished_at": datetime.now(timezone.utc),
            },
        )

    @staticmethod
    def _transition_to_cancelled(job_id: str) -> None:
        """将运行中任务切换为已取消。

        Args:
            job_id: 任务唯一 ID。
        """
        LuiEvaluationJobRepository.update_fields(
            job_id,
            {
                "status": "cancelled",
                "finished_at": datetime.now(timezone.utc),
            },
        )


lui_evaluation_run_service = LuiEvaluationRunService()
