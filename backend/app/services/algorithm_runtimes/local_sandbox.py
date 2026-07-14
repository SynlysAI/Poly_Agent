"""Subprocess sandbox runtime backend for uploaded algorithms."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.algorithm_runtimes.base import (
    AlgorithmRuntimeError,
    RuntimeExecutionLogs,
    RuntimeExecutionResult,
)


SAFE_ENV_KEYS = {"PATH", "LANG", "LC_ALL", "PYTHONPATH", "SYSTEMROOT", "WINDIR"}
SENSITIVE_ENV_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL")


class LocalSandboxRuntimeBackend:
    """Run uploaded code in a short-lived Python subprocess."""

    backend_name = "local_sandbox_runtime"

    def __init__(
        self,
        *,
        max_output_bytes: int | None = None,
        max_concurrency: int | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.max_output_bytes = max_output_bytes or getattr(settings, "algorithm_runtime_max_output_bytes", 65536)
        self.max_concurrency = max_concurrency or getattr(settings, "algorithm_runtime_max_concurrency", 2)
        self.python_executable = python_executable or sys.executable
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)

    def validate_runtime(self, *, package_path: Path, runtime: dict[str, Any]) -> dict[str, Any]:
        if not package_path.exists():
            raise AlgorithmRuntimeError(
                error_type="RuntimeNotFound",
                message=f"算法包目录不存在: {package_path}",
                runtime={"backend": self.backend_name},
            )
        return {"backend": self.backend_name, "health": "ready", "package_path": str(package_path)}

    def build(
        self,
        *,
        version_id: str,
        package_sha256: str,
        package_path: Path,
        runtime: dict[str, Any],
        requirements: str = "",
    ) -> dict[str, Any]:
        requirements_sha256 = hashlib.sha256(requirements.encode("utf-8")).hexdigest()
        package_digest = f"sha256:{package_sha256}"
        environment_digest = self._digest(
            {
                "backend": self.backend_name,
                "python": runtime.get("python"),
                "requirements_sha256": requirements_sha256,
                "install_policy": "preinstalled_environment",
            }
        )
        runtime_digest = self._digest(
            {
                "backend": self.backend_name,
                "version_id": version_id,
                "package_digest": package_digest,
                "environment_digest": environment_digest,
                "max_output_bytes": self.max_output_bytes,
                "max_concurrency": self.max_concurrency,
            }
        )
        return {
            "package_digest": package_digest,
            "requirements_sha256": requirements_sha256,
            "environment_digest": environment_digest,
            "runtime_digest": runtime_digest,
        }

    def deploy(
        self,
        *,
        version_id: str,
        package_path: Path,
        runtime: dict[str, Any],
        digests: dict[str, Any],
    ) -> dict[str, Any]:
        self.validate_runtime(package_path=package_path, runtime=runtime)
        return {
            "kind": self.backend_name,
            "backend": self.backend_name,
            "health": "ready",
            "endpoint": "internal://algorithm-sandbox-runtime",
            "endpoint_type": "subprocess",
            "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "resource_limits": {
                "timeout_seconds": runtime.get("timeout_seconds", 30),
                "max_output_bytes": self.max_output_bytes,
                "max_concurrency": self.max_concurrency,
                "env_policy": "allowlist",
            },
            **digests,
        }

    def health(self, *, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"backend": self.backend_name, "health": deployment.get("health", "unknown")}

    def predict(
        self,
        *,
        package_path: Path,
        entrypoint: str,
        loader: str | None,
        inputs: dict[str, Any],
        timeout_seconds: int,
        context: dict[str, Any] | None = None,
    ) -> RuntimeExecutionResult:
        request = {
            "package_path": str(package_path),
            "entrypoint": entrypoint,
            "loader": loader,
            "inputs": inputs,
            "context": context or {},
        }
        runtime_base = {
            "backend": self.backend_name,
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_concurrency": self.max_concurrency,
            "env_policy": "allowlist",
        }

        acquired = self._semaphore.acquire(timeout=max(timeout_seconds, 1))
        if not acquired:
            raise AlgorithmRuntimeError(
                error_type="ConcurrencyLimitExceeded",
                message="算法运行并发已达到上限",
                runtime=runtime_base,
            )
        try:
            return self._run_subprocess(request, timeout_seconds=timeout_seconds, runtime_base=runtime_base)
        finally:
            self._semaphore.release()

    def stop(self, *, deployment: dict[str, Any]) -> dict[str, Any]:
        return {"backend": self.backend_name, "stopped": True}

    def logs(self, *, deployment: dict[str, Any]) -> RuntimeExecutionLogs:
        return RuntimeExecutionLogs()

    def _run_subprocess(
        self,
        request: dict[str, Any],
        *,
        timeout_seconds: int,
        runtime_base: dict[str, Any],
    ) -> RuntimeExecutionResult:
        env = self._build_env()
        cmd = [self.python_executable, "-m", "app.services.algorithm_runtimes.sandbox_shim"]
        try:
            completed = subprocess.run(
                cmd,
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                cwd=str(Path(request["package_path"]).resolve()),
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, truncated = self._capture_logs(exc.stdout or "", exc.stderr or "")
            logs = RuntimeExecutionLogs(stdout=stdout, stderr=stderr, truncated=truncated)
            raise AlgorithmRuntimeError(
                error_type="TimeoutExpired",
                message=f"algorithm execution timed out after {timeout_seconds}s",
                runtime={**runtime_base, "duration_ms": int(timeout_seconds * 1000)},
                logs=logs,
            ) from exc

        stdout, stderr, truncated = self._capture_logs(completed.stdout, completed.stderr)
        logs = RuntimeExecutionLogs(stdout=stdout, stderr=stderr, truncated=truncated)
        response_text = stdout
        json_start = response_text.rfind('{"ok"')
        if json_start == -1:
            raise AlgorithmRuntimeError(
                error_type="InvalidRuntimeResponse",
                message="sandbox runtime did not return JSON",
                runtime={**runtime_base, "returncode": completed.returncode},
                logs=logs,
            )
        try:
            response = json.loads(response_text[json_start:])
        except json.JSONDecodeError as exc:
            raise AlgorithmRuntimeError(
                error_type="InvalidRuntimeResponse",
                message="sandbox runtime returned invalid JSON",
                runtime={**runtime_base, "returncode": completed.returncode},
                logs=logs,
            ) from exc

        runtime = {**runtime_base, **(response.get("runtime") or {}), "returncode": completed.returncode}
        user_stdout = response_text[:json_start]
        logs = RuntimeExecutionLogs(stdout=user_stdout[-self.max_output_bytes :], stderr=stderr, truncated=truncated)

        if completed.returncode != 0 and response.get("ok") is not False:
            raise AlgorithmRuntimeError(
                error_type="RuntimeProcessError",
                message=f"sandbox runtime exited with code {completed.returncode}",
                runtime=runtime,
                logs=logs,
            )
        if response.get("ok") is not True:
            error = response.get("error") or {}
            raise AlgorithmRuntimeError(
                error_type=str(error.get("error_type") or "AlgorithmRuntimeError"),
                message=str(error.get("message") or "uploaded algorithm failed"),
                runtime=runtime,
                logs=logs,
                traceback_tail=error.get("traceback_tail"),
            )
        output = response.get("output")
        if not isinstance(output, dict):
            raise AlgorithmRuntimeError(
                error_type="InvalidRuntimeResponse",
                message="sandbox runtime output must be an object",
                runtime=runtime,
                logs=logs,
            )
        return RuntimeExecutionResult(output=output, runtime=runtime, logs=logs)

    def _build_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in SAFE_ENV_KEYS:
            value = os.environ.get(key)
            if value and not any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS):
                env[key] = value
        backend_root = str(settings.backend_root)
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = backend_root if not existing_pythonpath else f"{backend_root}{os.pathsep}{existing_pythonpath}"
        env["POLY_AGENT_RUNTIME_BACKEND"] = self.backend_name
        return env

    def _capture_logs(self, stdout: str | bytes, stderr: str | bytes) -> tuple[str, str, bool]:
        stdout_text = self._to_text(stdout)
        stderr_text = self._to_text(stderr)
        combined = len(stdout_text.encode("utf-8")) + len(stderr_text.encode("utf-8"))
        truncated = combined > self.max_output_bytes
        return stdout_text[-self.max_output_bytes :], stderr_text[-self.max_output_bytes :], truncated

    @staticmethod
    def _to_text(value: str | bytes) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value or ""

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"
