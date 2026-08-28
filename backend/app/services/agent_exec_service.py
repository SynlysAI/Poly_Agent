"""受控外部 Agent 执行服务与安全边界。"""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil
import stat
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.time import utc_now
from app.infra.agent_exec_repositories import (
    AgentExecArtifactRepository,
    AgentExecAuditWriter,
    AgentExecProviderPolicyRepository,
    AgentExecRunRepository,
)
from app.schemas.agent_exec import (
    AgentExecArtifactData,
    AgentExecExecutionRequest,
    AgentExecInputFileData,
    AgentExecLuiToolData,
    AgentExecRunData,
)
from app.services.agent_exec_policy_service import (
    AgentExecPolicyRejected,
    AgentExecPolicyService,
)
from app.services.agent_exec_providers.base import (
    AgentExecProvider,
    AgentExecProviderError,
    AgentExecProviderUnavailable,
)
from app.services.agent_exec_providers.registry import AgentExecProviderRegistry
from app.services.agent_exec_providers.codex import CodexAgentExecProvider


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
CONTENT_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
}
LOGGER = logging.getLogger(__name__)


class AgentExecRequestError(Exception):
    """agent_exec 请求级结构化错误。"""

    def __init__(self, *, status_code: int, reason_code: str, message: str) -> None:
        """初始化请求错误。

        Args:
            status_code: API 应返回的 HTTP 状态码。
            reason_code: 稳定机器可读错误码。
            message: 面向管理员的安全描述。
        """
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code
        self.message = message


class AgentExecOutputInvalid(Exception):
    """provider 输出违反安全边界。"""

    def __init__(self, reason_code: str, message: str) -> None:
        """初始化输出违规错误。

        Args:
            reason_code: 稳定机器可读错误码。
            message: 违规描述。
        """
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


def build_default_agent_exec_registry() -> AgentExecProviderRegistry:
    """构建默认 provider 注册表。

    Returns:
        已注册服务端受控 provider 的注册表；不探测外部二进制。
    """
    registry = AgentExecProviderRegistry()
    registry.register(CodexAgentExecProvider())
    return registry


class AgentExecService:
    """统一创建 run、准备输入、调用 provider、校验输出。"""

    def __init__(
        self,
        *,
        registry: AgentExecProviderRegistry | None = None,
        policy_service: AgentExecPolicyService | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        run_persister: Callable[[AgentExecRunData], None] | None = None,
        run_reader: Callable[[str], AgentExecRunData | None] | None = None,
        artifact_resolver: Callable[[str], Path | None] | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        """初始化执行服务。

        Args:
            registry: provider 注册表；缺省注册 Codex。
            policy_service: 策略治理服务。
            event_sink: 生命周期事件写入回调。
            run_persister: run 状态持久化回调。
            run_reader: run 读取回调。
            artifact_resolver: 受管输入对象解析回调。
            max_concurrency: 最大并发 run 数；缺省读取全局配置。
        """
        self._registry = registry or build_default_agent_exec_registry()
        self._policy_service = policy_service or AgentExecPolicyService(
            policy_loader=AgentExecProviderPolicyRepository.get_policy,
            policy_saver=AgentExecProviderPolicyRepository.save_policy,
        )
        self._event_sink = event_sink or AgentExecAuditWriter.write_event
        self._run_persister = run_persister or self._persist_run
        self._run_reader = run_reader or AgentExecRunRepository.get_run
        self._artifact_resolver = artifact_resolver or self._default_artifact_resolver
        self._runs: dict[str, AgentExecRunData] = {}
        self._active_runs: dict[str, threading.Event] = {}
        self._active_run_counts: dict[str, int] = {}
        self._lock = threading.Lock()
        concurrency_limit = max_concurrency or settings.agent_exec_max_concurrency
        if concurrency_limit < 1:
            raise ValueError("agent_exec 最大并发数必须大于 0")
        self._execution_slots = threading.BoundedSemaphore(concurrency_limit)

    @property
    def registry(self) -> AgentExecProviderRegistry:
        """provider 注册表。"""
        return self._registry

    @property
    def policy_service(self) -> AgentExecPolicyService:
        """策略治理服务。"""
        return self._policy_service

    def execute(self, request: AgentExecExecutionRequest) -> AgentExecRunData:
        """执行一次受控外部 Agent 文件任务，并强制资源配额。

        Args:
            request: 显式执行请求。

        Returns:
            权威 run 状态；provider 执行失败时返回 failed 终态。

        Raises:
            AgentExecRequestError: policy、readiness、资源配额或输入校验失败。
        """
        if not self._execution_slots.acquire(blocking=False):
            self._reject_capacity_request(
                request,
                reason_code="concurrency_limit",
                message="外部 Agent 执行并发已达上限，请稍后重试",
            )
        if not self._reserve_user_slot(request.actor_user_id):
            self._execution_slots.release()
            self._reject_capacity_request(
                request,
                reason_code="user_active_run_limit",
                message="当前用户已有执行中的外部 Agent 任务",
            )
        try:
            return self._execute_with_reservation(request)
        finally:
            self._release_user_slot(request.actor_user_id)
            self._execution_slots.release()


    def cancel(self, run_id: str) -> AgentExecRunData:
        """服务端取消未结束 run，已结束 run 返回稳定终态。

        Args:
            run_id: 服务端生成的 run ID。

        Returns:
            取消后或原本已终态的 run。

        Raises:
            AgentExecRequestError: run 不存在。
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None and self._run_reader is not None:
                run = self._run_reader(run_id)
            if run is None:
                raise AgentExecRequestError(
                    status_code=404,
                    reason_code="run_not_found",
                    message=f"agent_exec run '{run_id}' 不存在",
                )
            if run.status in TERMINAL_STATUSES:
                return run
            event = self._active_runs.get(run_id)
        if event is not None:
            event.set()
        cancelled_run = self._finish(run, status="cancelled")
        if cancelled_run.status != "cancelled":
            return cancelled_run
        self._emit("agent_exec.cancelled", cancelled_run)
        return cancelled_run

    def get_run(self, run_id: str) -> AgentExecRunData:
        """读取 run 权威状态。

        Args:
            run_id: 服务端生成的 run ID。

        Returns:
            run 状态。

        Raises:
            AgentExecRequestError: run 不存在。
        """
        return self._get_run_or_raise(run_id)

    def list_runs(self) -> list[AgentExecRunData]:
        """列出内存中的 run 状态。

        Returns:
            run 列表；持久化读取由仓储层补充。
        """
        return list(self._runs.values())

    def lui_tool(self, *, role: str) -> AgentExecLuiToolData | None:
        """返回 LUI 专用工具描述符；任一条件不满足即不暴露。

        Args:
            role: 当前用户角色。

        Returns:
            满足 readiness、policy、角色、任务类型与确认要求的工具描述符；
            默认关闭时返回 None。
        """
        for provider in self._registry.list_providers():
            policy = self._policy_service.get_policy(provider.provider_id)
            if not policy.enabled:
                continue
            if role not in policy.allowed_roles:
                continue
            if "structured_file_task" not in policy.allowed_task_types:
                continue
            if "structured_file_task" not in provider.supported_task_types:
                continue
            readiness = provider.readiness()
            if not readiness.available:
                continue
            return AgentExecLuiToolData(
                provider_id=provider.provider_id,
                provider_display_name=provider.display_name,
                task_type="structured_file_task",
                requires_confirmation=policy.requires_confirmation,
                timeout_seconds=settings.agent_exec_timeout_seconds,
                max_input_bytes=settings.agent_exec_max_input_bytes,
                max_output_bytes=settings.agent_exec_max_output_bytes,
                max_files=settings.agent_exec_max_files,
            )
        return None

    def _reserve_user_slot(self, actor_user_id: str) -> bool:
        """为当前用户预留一个活跃 run 配额。

        Args:
            actor_user_id: 操作人用户 ID。

        Returns:
            预留成功返回 True；已达到配额返回 False。
        """
        with self._lock:
            count = self._active_run_counts.get(actor_user_id, 0)
            if count >= settings.agent_exec_max_active_runs_per_user:
                return False
            self._active_run_counts[actor_user_id] = count + 1
            return True

    def _release_user_slot(self, actor_user_id: str) -> None:
        """释放当前用户的活跃 run 配额。

        Args:
            actor_user_id: 操作人用户 ID。
        """
        with self._lock:
            count = self._active_run_counts.get(actor_user_id, 0) - 1
            if count > 0:
                self._active_run_counts[actor_user_id] = count
            else:
                self._active_run_counts.pop(actor_user_id, None)

    def _reject_capacity_request(
        self,
        request: AgentExecExecutionRequest,
        *,
        reason_code: str,
        message: str,
    ) -> None:
        """记录并抛出资源配额拒绝。

        Args:
            request: 显式执行请求。
            reason_code: 稳定机器可读原因码。
            message: 面向调用方的拒绝描述。

        Raises:
            AgentExecRequestError: 当前资源配额不足。
        """
        self._emit_policy_rejected(
            run_id=f"aer_{uuid.uuid4().hex}",
            provider_id=request.provider_id,
            task_type=request.task.task_type,
            actor=request.actor_user_id,
            actor_role=request.actor_role,
            reason_code=reason_code,
            message=message,
        )
        raise AgentExecRequestError(
            status_code=429,
            reason_code=reason_code,
            message=message,
        )

    def _execute_with_reservation(
        self,
        request: AgentExecExecutionRequest,
    ) -> AgentExecRunData:
        """在已占用全局与用户配额后执行任务。

        Args:
            request: 显式执行请求。

        Returns:
            权威 run 状态。

        Raises:
            AgentExecRequestError: policy、readiness 或输入校验失败。
        """
        run_id = f"aer_{uuid.uuid4().hex}"
        provider = self._resolve_provider(run_id, request)
        policy = self._check_request_policy(run_id, provider, request)

        run = AgentExecRunData(
            run_id=run_id,
            provider_id=request.provider_id,
            task_type=request.task.task_type,
            status="requested",
            created_by=request.actor_user_id,
            actor_role=request.actor_role,
            created_at=utc_now(),
            policy_snapshot=policy,
            chat_id=request.chat_id,
            assistant_tool_call_id=request.assistant_tool_call_id,
        )
        self._save_run(run)
        self._emit("agent_exec.requested", run)

        readiness = provider.readiness()
        if not readiness.available:
            run = self._finish(
                run,
                status="failed",
                error_code="provider_unavailable",
                error_message=readiness.message,
            )
            self._emit(
                "agent_exec.provider_unavailable",
                run,
                reason_code=readiness.reason_code,
            )
            self._emit("agent_exec.failed", run, error_code="provider_unavailable")
            raise AgentExecRequestError(
                status_code=503,
                reason_code="provider_unavailable",
                message=readiness.message,
            )
        self._emit(
            "agent_exec.provider_ready",
            run,
            reason_code=readiness.reason_code,
        )

        try:
            self._policy_service.check_confirmation(policy, request)
        except AgentExecPolicyRejected as exc:
            self._reject_run(run, exc)
            raise AgentExecRequestError(
                status_code=exc.status_code,
                reason_code=exc.reason_code,
                message=exc.message,
            ) from exc

        workdir = self._create_workdir(run_id)
        cancel_event = threading.Event()
        with self._lock:
            self._active_runs[run_id] = cancel_event
        try:
            try:
                manifest = self._prepare_inputs(workdir, request.task.input_files)
            except AgentExecRequestError as exc:
                self._reject_run(
                    run,
                    AgentExecPolicyRejected(
                        status_code=exc.status_code,
                        reason_code=exc.reason_code,
                        message=exc.message,
                    ),
                )
                raise

            run.input_files = manifest
            self._save_run(run)
            run = run.model_copy(update={"status": "running", "started_at": utc_now()})
            self._save_run(run)
            self._emit("agent_exec.started", run)

            timeout_seconds = min(
                request.task.timeout_seconds,
                settings.agent_exec_timeout_seconds,
            )
            try:
                result = provider.execute(
                    task=request.task,
                    workdir=workdir,
                    timeout_seconds=timeout_seconds,
                    should_cancel=cancel_event.is_set,
                )
            except AgentExecProviderError as exc:
                with self._lock:
                    current = self._runs.get(run_id)
                    already_cancelled = bool(
                        current and current.status == "cancelled"
                    )
                if exc.code == "cancelled" or already_cancelled:
                    if not already_cancelled:
                        run = self._finish(run, status="cancelled")
                        self._emit("agent_exec.cancelled", run)
                    return self._get_run_or_raise(run_id)
                run = self._finish(
                    run,
                    status="failed",
                    error_code=exc.code,
                    error_message=exc.message,
                )
                if run.status != "failed" or run.error_code != exc.code:
                    return run
                self._emit("agent_exec.failed", run, error_code=exc.code)
                return run

            try:
                artifacts = self._scan_outputs(workdir)
            except AgentExecOutputInvalid as exc:
                self._remove_path(workdir / "artifacts")
                run = self._finish(
                    run,
                    status="failed",
                    error_code=exc.reason_code,
                    error_message=exc.message,
                )
                if run.status != "failed" or run.error_code != exc.reason_code:
                    return run
                self._emit("agent_exec.failed", run, error_code=exc.reason_code)
                return run

            run = run.model_copy(
                update={"artifacts": artifacts, "output": result.output}
            )
            run = self._finish(run, status="completed")
            if run.status != "completed":
                return run
            self._emit(
                "agent_exec.completed",
                run,
                artifact_count=len(artifacts),
            )
            return run
        finally:
            with self._lock:
                self._active_runs.pop(run_id, None)
            self._strip_executable_bits(workdir)

    def _resolve_provider(
        self,
        run_id: str,
        request: AgentExecExecutionRequest,
    ) -> AgentExecProvider:
        """解析 provider 并处理未知 provider 拒绝。

        Args:
            run_id: 服务端生成的 run ID。
            request: 执行请求。

        Returns:
            provider 实例。

        Raises:
            AgentExecRequestError: provider 未注册。
        """
        try:
            return self._registry.require(request.provider_id)
        except AgentExecProviderUnavailable as exc:
            self._emit_policy_rejected(
                run_id=run_id,
                provider_id=request.provider_id,
                task_type=request.task.task_type,
                actor=request.actor_user_id,
                actor_role=request.actor_role,
                reason_code=exc.code,
                message=exc.message,
            )
            raise AgentExecRequestError(
                status_code=400,
                reason_code=exc.code,
                message=exc.message,
            ) from exc

    def _check_request_policy(
        self,
        run_id: str,
        provider: AgentExecProvider,
        request: AgentExecExecutionRequest,
    ):
        """执行角色 / enabled / task_type 固定顺序校验。

        Args:
            run_id: 服务端生成的 run ID。
            provider: provider 实例。
            request: 执行请求。

        Returns:
            生效中的策略快照。

        Raises:
            AgentExecRequestError: 任一步骤不通过。
        """
        try:
            return self._policy_service.check_request_policy(provider, request)
        except AgentExecPolicyRejected as exc:
            self._emit_policy_rejected(
                run_id=run_id,
                provider_id=request.provider_id,
                task_type=request.task.task_type,
                actor=request.actor_user_id,
                actor_role=request.actor_role,
                reason_code=exc.reason_code,
                message=exc.message,
            )
            raise AgentExecRequestError(
                status_code=exc.status_code,
                reason_code=exc.reason_code,
                message=exc.message,
            ) from exc

    def _prepare_inputs(
        self,
        workdir: Path,
        input_files: list[AgentExecInputFileData],
    ) -> list[AgentExecInputFileData]:
        """校验并复制 allowlist 输入到受限 workdir。

        Args:
            workdir: run 专属 workdir。
            input_files: 显式输入清单。

        Returns:
            记录 path、size、sha256 与来源对象的 manifest。

        Raises:
            AgentExecRequestError: 数量、大小、来源、symlink 或哈希校验失败。
        """
        if len(input_files) > settings.agent_exec_max_files:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="too_many_input_files",
                message=f"输入文件数超过上限 {settings.agent_exec_max_files}",
            )
        manifest: list[AgentExecInputFileData] = []
        seen_names: set[str] = set()
        total_bytes = 0
        for item in input_files:
            self._validate_input_name(item.name, seen_names)
            source = self._resolve_source(item.source_object_id)
            resolved = self._validate_source_file(source, item.source_object_id)
            if item.size_bytes > settings.agent_exec_max_input_bytes:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_too_large",
                    message=f"输入文件 '{item.name}' 超过大小上限",
                )
            total_bytes += item.size_bytes
            if total_bytes > settings.agent_exec_max_input_bytes:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_total_too_large",
                    message="输入文件总大小超过上限",
                )
            size, digest = self._copy_verified_input(
                source=resolved,
                destination=workdir / item.name,
                expected_size=item.size_bytes,
                expected_sha256=item.sha256,
            )
            manifest.append(
                AgentExecInputFileData(
                    name=item.name,
                    size_bytes=size,
                    sha256=digest,
                    source_object_id=item.source_object_id,
                )
            )
        return manifest

    def _copy_verified_input(
        self,
        *,
        source: Path,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
    ) -> tuple[int, str]:
        """基于稳定文件描述符校验并复制输入，压缩 TOCTOU 窗口。

        Args:
            source: 受管来源路径。
            destination: run workdir 内目标文件。
            expected_size: 调用方声明的来源大小。
            expected_sha256: 调用方声明的来源 sha256。

        Returns:
            (实际大小, 实际 sha256) 元组。

        Raises:
            AgentExecRequestError: 来源被替换、大小不符、超限或哈希校验失败。
        """
        if expected_size <= 0:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_empty",
                message=f"输入文件 '{destination.name}' 声明大小无效",
            )
        if expected_size > settings.agent_exec_max_input_bytes:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_too_large",
                message=f"输入文件 '{destination.name}' 超过大小上限",
            )
        temporary = destination.with_name(
            f".{destination.name}.tmp-{uuid.uuid4().hex}"
        )
        try:
            source_fd = self._open_managed_source(source)
        except OSError as exc:
            reason_code = (
                "input_symlink_rejected"
                if exc.errno == getattr(errno, "ELOOP", -1)
                else "input_source_not_found"
            )
            raise AgentExecRequestError(
                status_code=400,
                reason_code=reason_code,
                message=f"输入来源 '{source.name}' 打开失败或被替换",
            ) from exc

        digest = hashlib.sha256()
        try:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_not_a_file",
                    message=f"输入来源 '{source.name}' 不是普通文件",
                )
            if source_stat.st_nlink > 1:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_hardlink_rejected",
                    message=f"输入来源 '{source.name}' 存在硬链接语义",
                )
            size = source_stat.st_size
            if size <= 0:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_empty",
                    message=f"输入文件 '{source.name}' 为空",
                )
            if size != expected_size:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_size_mismatch",
                    message=f"输入文件 '{destination.name}' 大小与声明不符",
                )
            if size > settings.agent_exec_max_input_bytes:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_too_large",
                    message=f"输入文件 '{destination.name}' 超过大小上限",
                )

            destination_fd = os.open(
                temporary,
                (
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                ),
                0o600,
            )
            try:
                with (
                    os.fdopen(source_fd, "rb", closefd=False) as source_handle,
                    os.fdopen(
                        destination_fd, "wb", closefd=False
                    ) as destination_handle,
                ):
                    for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                        destination_handle.write(chunk)
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
                final_source_stat = os.fstat(source_fd)
                if (
                    final_source_stat.st_ino != source_stat.st_ino
                    or final_source_stat.st_size != source_stat.st_size
                    or final_source_stat.st_nlink != source_stat.st_nlink
                ):
                    raise AgentExecRequestError(
                        status_code=400,
                        reason_code="input_source_changed",
                        message=f"输入文件 '{destination.name}' 在复制期间发生变化",
                    )
            finally:
                os.close(source_fd)
                os.close(destination_fd)

            actual_digest = digest.hexdigest()
            if actual_digest != expected_sha256:
                raise AgentExecRequestError(
                    status_code=400,
                    reason_code="input_hash_mismatch",
                    message=f"输入文件 '{destination.name}' sha256 校验失败",
                )
            os.replace(temporary, destination)
            return size, actual_digest
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _open_managed_source(path: Path) -> int:
        """从受管根目录逐级安全打开来源文件。

        Args:
            path: 已通过 realpath 校验的受管来源路径。

        Returns:
            不跟随任意 symlink 组件的来源文件描述符。

        Raises:
            AgentExecRequestError: 来源不在受管根目录内。
            OSError: 任一路径组件缺失、被替换或违反 symlink 约束。
        """
        managed_roots = (
            settings.upload_root.resolve(),
            settings.outputs_root.resolve(),
        )
        selected_root = next(
            (root for root in managed_roots if path.is_relative_to(root)),
            None,
        )
        if selected_root is None:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_outside_managed_root",
                message=f"输入来源 '{path.name}' 逃逸受管根目录",
            )
        components = path.relative_to(selected_root).parts
        directory_flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_flags = (
            os.O_RDONLY
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        directory_fd = os.open(selected_root, directory_flags)
        try:
            for component in components[:-1]:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
                os.close(directory_fd)
                directory_fd = next_fd
            if not components:
                file_fd = os.open(".", file_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                return file_fd
            file_fd = os.open(components[-1], file_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            return file_fd
        except OSError:
            os.close(directory_fd)
            raise

    def _scan_outputs(self, workdir: Path) -> list[AgentExecArtifactData]:
        """扫描并校验 provider 输出 artifact。

        Args:
            workdir: run 专属 workdir。

        Returns:
            通过安全校验的 artifact 清单。

        Raises:
            AgentExecOutputInvalid: 路径穿越、symlink、隐藏文件、可执行位、
                空文件、数量或总大小超限。
        """
        artifacts_dir = workdir / "artifacts"
        for path in workdir.rglob("*"):
            if path.is_symlink():
                raise AgentExecOutputInvalid(
                    "output_symlink_rejected",
                    f"输出包含 symlink：{path.relative_to(workdir)}",
                )
        if not artifacts_dir.exists():
            return []
        if artifacts_dir.is_symlink() or not artifacts_dir.is_dir():
            raise AgentExecOutputInvalid(
                "output_path_invalid", "artifacts 必须是 run workdir 内的目录"
            )
        artifacts: list[AgentExecArtifactData] = []
        total_bytes = 0
        for path in sorted(artifacts_dir.rglob("*")):
            if path.is_symlink():
                raise AgentExecOutputInvalid(
                    "output_symlink_rejected",
                    f"输出包含 symlink：{path.relative_to(workdir)}",
                )
            if not path.is_file():
                if path.is_dir():
                    continue
                raise AgentExecOutputInvalid(
                    "output_path_invalid",
                    f"输出包含非普通文件：{path.relative_to(artifacts_dir)}",
                )
            relative = path.relative_to(artifacts_dir)
            if any(part.startswith(".") for part in relative.parts):
                raise AgentExecOutputInvalid(
                    "output_hidden_rejected",
                    f"输出包含隐藏文件：{relative}",
                )
            if not path.is_relative_to(artifacts_dir):
                raise AgentExecOutputInvalid(
                    "output_escape_rejected",
                    f"输出逃逸 workdir：{relative}",
                )
            size, sha256, file_stat = self._inspect_output_file(path)
            mode = file_stat.st_mode
            if file_stat.st_nlink > 1:
                raise AgentExecOutputInvalid(
                    "output_hardlink_rejected",
                    f"输出包含外部硬链接：{relative}",
                )
            if mode & 0o111:
                raise AgentExecOutputInvalid(
                    "output_executable_rejected",
                    f"输出包含可执行文件：{relative}",
                )
            if size == 0:
                raise AgentExecOutputInvalid(
                    "output_empty_rejected", f"输出包含空文件：{relative}"
                )
            if len(artifacts) >= settings.agent_exec_max_files:
                raise AgentExecOutputInvalid(
                    "output_too_many_files",
                    f"输出文件数超过上限 {settings.agent_exec_max_files}",
                )
            total_bytes += size
            if total_bytes > settings.agent_exec_max_output_bytes:
                raise AgentExecOutputInvalid(
                    "output_too_large", "输出总大小超过上限"
                )
            artifacts.append(
                AgentExecArtifactData(
                    path=str(relative),
                    size_bytes=size,
                    sha256=sha256,
                    content_type=CONTENT_TYPES.get(path.suffix.lower(), ""),
                )
            )
        return artifacts

    @staticmethod
    def _inspect_output_file(path: Path) -> tuple[int, str, os.stat_result]:
        """以不跟随 symlink 的文件描述符检查并哈希输出文件。

        Args:
            path: 待检查的输出文件路径。

        Returns:
            (大小, sha256, stat 结果) 元组。

        Raises:
            AgentExecOutputInvalid: 输出为 symlink、非普通文件或读取失败。
        """
        flags = (
            os.O_RDONLY
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            file_fd = os.open(path, flags)
        except OSError as exc:
            reason_code = (
                "output_symlink_rejected"
                if exc.errno == getattr(errno, "ELOOP", -1)
                else "output_path_invalid"
            )
            raise AgentExecOutputInvalid(
                reason_code, f"输出文件打开失败：{path.name}"
            ) from exc
        digest = hashlib.sha256()
        read_bytes = 0
        try:
            file_stat = os.fstat(file_fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise AgentExecOutputInvalid(
                    "output_path_invalid", f"输出不是普通文件：{path.name}"
                )
            with os.fdopen(file_fd, "rb", closefd=False) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    read_bytes += len(chunk)
            if read_bytes != file_stat.st_size:
                raise AgentExecOutputInvalid(
                    "output_path_invalid",
                    f"输出文件在扫描期间发生变化：{path.name}",
                )
            final_stat = os.fstat(file_fd)
            if (
                final_stat.st_size != file_stat.st_size
                or final_stat.st_nlink != file_stat.st_nlink
            ):
                raise AgentExecOutputInvalid(
                    "output_path_invalid",
                    f"输出文件在扫描期间发生变化：{path.name}",
                )
            return file_stat.st_size, digest.hexdigest(), file_stat
        finally:
            os.close(file_fd)

    def _create_workdir(self, run_id: str) -> Path:
        """创建 run 专属受限 workdir。

        Args:
            run_id: 服务端生成的 run ID。

        Returns:
            0o700 权限的独立 workdir。
        """
        workdir = settings.agent_exec_workdir_root / run_id
        workdir.mkdir(parents=True, mode=0o700, exist_ok=False)
        return workdir

    def _resolve_source(self, source_object_id: str) -> Path:
        """解析服务端受管输入来源。

        Args:
            source_object_id: 受管 artifact / 上传对象 ID。

        Returns:
            来源文件路径。

        Raises:
            AgentExecRequestError: 来源不存在。
        """
        source = self._artifact_resolver(source_object_id)
        if source is None:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_source_not_found",
                message=f"输入来源 '{source_object_id}' 不在受管目录中",
            )
        return source

    def _validate_source_file(self, source: Path, source_object_id: str) -> Path:
        """校验来源文件安全语义。

        Args:
            source: 解析出的来源路径。
            source_object_id: 受管对象 ID。

        Returns:
            realpath 后的来源文件。

        Raises:
            AgentExecRequestError: symlink、硬链接、非文件或逃逸受管根目录。
        """
        if source.is_symlink():
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_symlink_rejected",
                message=f"输入来源 '{source_object_id}' 是 symlink",
            )
        if not source.is_file():
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_not_a_file",
                message=f"输入来源 '{source_object_id}' 不是普通文件",
            )
        source_stat = source.stat()
        if source_stat.st_nlink > 1:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_hardlink_rejected",
                message=f"输入来源 '{source_object_id}' 存在硬链接语义",
            )
        resolved = source.resolve(strict=True)
        managed_roots = (
            settings.upload_root.resolve(),
            settings.outputs_root.resolve(),
        )
        if not any(resolved.is_relative_to(root) for root in managed_roots):
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_outside_managed_root",
                message=f"输入来源 '{source_object_id}' 逃逸受管根目录",
            )
        return resolved

    @staticmethod
    def _validate_input_name(name: str, seen_names: set[str]) -> None:
        """校验 workdir 内的安全文件名。

        Args:
            name: 客户端声明的输入文件名。
            seen_names: 已出现的文件名集合。

        Raises:
            AgentExecRequestError: 名称不安全或重复。
        """
        if (
            not name
            or os.path.basename(name) != name
            or name in {".", ".."}
            or name.startswith(".")
            or "/" in name
            or "\\" in name
        ):
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_name_invalid",
                message=f"输入文件名不安全：{name!r}",
            )
        if name in seen_names:
            raise AgentExecRequestError(
                status_code=400,
                reason_code="input_name_duplicate",
                message=f"输入文件名重复：{name}",
            )
        seen_names.add(name)

    @staticmethod
    def _default_artifact_resolver(source_object_id: str) -> Path | None:
        """在受管上传与输出目录中解析来源对象。

        Args:
            source_object_id: 相对受管根目录的对象 ID。

        Returns:
            来源路径；不存在时返回 None。
        """
        if not source_object_id or source_object_id.startswith("/"):
            return None
        for root in (settings.upload_root, settings.outputs_root):
            candidate = root / source_object_id
            try:
                if candidate.resolve().is_relative_to(root.resolve()) and candidate.exists():
                    return candidate
            except OSError:
                continue
        return None

    def _reject_run(
        self,
        run: AgentExecRunData,
        rejection: AgentExecPolicyRejected,
    ) -> None:
        """把策略拒绝落到 run 终态并写事件。

        Args:
            run: 当前 run。
            rejection: 策略拒绝错误。
        """
        self._emit_policy_rejected(
            run_id=run.run_id,
            provider_id=run.provider_id,
            task_type=run.task_type,
            actor=run.created_by,
            actor_role=run.actor_role,
            reason_code=rejection.reason_code,
            message=rejection.message,
        )
        run = self._finish(
            run,
            status="failed",
            error_code=rejection.reason_code,
            error_message=rejection.message,
        )
        if run.status == "failed" and run.error_code == rejection.reason_code:
            self._emit("agent_exec.failed", run, error_code=rejection.reason_code)

    def _finish(
        self,
        run: AgentExecRunData,
        *,
        status: str,
        error_code: str = "",
        error_message: str = "",
    ) -> AgentExecRunData:
        """写入稳定终态。

        Args:
            run: 当前 run。
            status: 终态状态。
            error_code: 失败错误码。
            error_message: 失败描述。

        Returns:
            更新后的 run。
        """
        with self._lock:
            current = self._runs.get(run.run_id, run)
            if current.status in TERMINAL_STATUSES:
                return current
            if current.audit_error and not run.audit_error:
                run = run.model_copy(update={"audit_error": True})
            now = utc_now()
            started = run.started_at or run.created_at
            updated = run.model_copy(
                update={
                    "status": status,
                    "error_code": error_code,
                    "error_message": error_message,
                    "finished_at": now,
                    "duration_ms": int((now - started).total_seconds() * 1000),
                }
            )
            self._runs[run.run_id] = updated
            if self._run_persister is not None:
                self._run_persister(updated)
            return updated

    def _save_run(self, run: AgentExecRunData) -> None:
        """保存 run 权威状态。

        Args:
            run: 当前 run。
        """
        with self._lock:
            current = self._runs.get(run.run_id)
            if current is not None and current.audit_error and not run.audit_error:
                run = run.model_copy(update={"audit_error": True})
            self._runs[run.run_id] = run
        if self._run_persister is not None:
            self._run_persister(run)

    def _get_run_or_raise(self, run_id: str) -> AgentExecRunData:
        """读取 run，不存在时抛出结构化错误。

        Args:
            run_id: run ID。

        Returns:
            run 状态。

        Raises:
            AgentExecRequestError: run 不存在。
        """
        run = None
        with self._lock:
            run = self._runs.get(run_id)
        if run is None and self._run_reader is not None:
            run = self._run_reader(run_id)
        if run is None:
            raise AgentExecRequestError(
                status_code=404,
                reason_code="run_not_found",
                message=f"agent_exec run '{run_id}' 不存在",
            )
        return run

    def _emit(
        self,
        event_type: str,
        run: AgentExecRunData,
        **metadata: Any,
    ) -> None:
        """写出脱敏生命周期事件。

        Args:
            event_type: agent_exec 事件类型。
            run: 关联 run。
            **metadata: 脱敏后的附加信息。
        """
        event = {
            "event_type": event_type,
            "run_id": run.run_id,
            "provider_id": run.provider_id,
            "task_type": run.task_type,
            "actor_user_id": run.created_by,
            "actor_role": run.actor_role,
            "chat_id": run.chat_id,
            "assistant_tool_call_id": run.assistant_tool_call_id,
            "metadata": metadata,
            "created_at": utc_now(),
        }
        try:
            self._event_sink(event)
        except Exception:
            LOGGER.exception(
                "agent_exec audit event failed (run_id=%s, event_type=%s)",
                run.run_id,
                event_type,
            )
            self._mark_audit_error(run)

    def _mark_audit_error(self, run: AgentExecRunData) -> None:
        """把审计写入失败标记到权威 run。

        Args:
            run: 发生审计写入失败的 run。
        """
        with self._lock:
            current = self._runs.get(run.run_id)
            updated = (current or run).model_copy(update={"audit_error": True})
            self._runs[run.run_id] = updated
            try:
                if self._run_persister is not None:
                    self._run_persister(updated)
            except Exception:
                LOGGER.exception(
                    "agent_exec audit_error state persist failed (run_id=%s)",
                    run.run_id,
                )

    def _emit_policy_rejected(
        self,
        *,
        run_id: str,
        provider_id: str,
        task_type: str,
        actor: str,
        actor_role: str,
        reason_code: str,
        message: str,
    ) -> None:
        """写出策略拒绝事件，不包含敏感输入。

        Args:
            run_id: run ID。
            provider_id: provider ID。
            task_type: 任务类型。
            actor: 操作人 ID。
            actor_role: 操作人真实角色。
            reason_code: 拒绝原因码。
            message: 拒绝描述。
        """
        self._event_sink(
            {
                "event_type": "agent_exec.policy.rejected",
                "run_id": run_id,
                "provider_id": provider_id,
                "task_type": task_type,
                "actor_user_id": actor,
                "actor_role": actor_role,
                "metadata": {"reason_code": reason_code, "message": message},
                "created_at": utc_now(),
            }
        )

    @staticmethod
    def _persist_run(run: AgentExecRunData) -> None:
        """把 run 与 artifact 清单写入双模存储。

        Args:
            run: 当前 run。
        """
        AgentExecRunRepository.save_run(run)
        if run.artifacts:
            AgentExecArtifactRepository.save_artifacts(run.run_id, run.artifacts)

    @staticmethod
    def _strip_executable_bits(workdir: Path) -> None:
        """清理 run workdir 内可执行产物权限。

        Args:
            workdir: run 专属 workdir。
        """
        if not workdir.exists():
            return
        for path in workdir.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o111)

    @staticmethod
    def _remove_path(path: Path) -> None:
        """删除违规输出路径。

        Args:
            path: 待删除路径。
        """
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink(missing_ok=True)
