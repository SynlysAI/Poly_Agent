"""Shared contracts for uploaded algorithm runtime backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeExecutionLogs:
    """Captured stdout/stderr for one runtime call."""

    stdout: str = ""
    stderr: str = ""
    truncated: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {"stdout": self.stdout, "stderr": self.stderr, "truncated": self.truncated}


@dataclass(frozen=True)
class RuntimeExecutionResult:
    """Successful runtime call result."""

    output: dict[str, Any]
    runtime: dict[str, Any] = field(default_factory=dict)
    logs: RuntimeExecutionLogs = field(default_factory=RuntimeExecutionLogs)


class AlgorithmRuntimeError(RuntimeError):
    """Structured runtime failure that can be persisted on AlgorithmRun."""

    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        runtime: dict[str, Any] | None = None,
        logs: RuntimeExecutionLogs | None = None,
        traceback_tail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.runtime = runtime or {}
        self.logs = logs or RuntimeExecutionLogs()
        self.traceback_tail = traceback_tail

    def to_error_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "error_type": self.error_type,
            "message": self.message,
            "retryable": self.error_type not in {"ValueError", "ValidationError"},
        }
        if self.traceback_tail:
            data["traceback_tail"] = self.traceback_tail
        return data


class AlgorithmRuntimeBackend(Protocol):
    """Execution boundary for uploaded algorithm packages."""

    backend_name: str

    def validate_runtime(self, *, package_path: Path, runtime: dict[str, Any]) -> dict[str, Any]:
        """Return runtime health metadata or raise AlgorithmRuntimeError."""

    def build(
        self,
        *,
        version_id: str,
        package_sha256: str,
        package_path: Path,
        runtime: dict[str, Any],
        requirements: str = "",
    ) -> dict[str, Any]:
        """Prepare a runtime environment and return digest metadata."""

    def deploy(
        self,
        *,
        version_id: str,
        package_path: Path,
        runtime: dict[str, Any],
        digests: dict[str, Any],
    ) -> dict[str, Any]:
        """Return deployment metadata."""

    def health(self, *, deployment: dict[str, Any]) -> dict[str, Any]:
        """Return runtime health metadata."""

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
        """Run one prediction."""

    def stop(self, *, deployment: dict[str, Any]) -> dict[str, Any]:
        """Stop or mark unavailable for backends with lifecycle state."""

    def logs(self, *, deployment: dict[str, Any]) -> RuntimeExecutionLogs:
        """Return deployment logs where supported."""
