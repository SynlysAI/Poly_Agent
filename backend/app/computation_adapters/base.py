"""Shared computation adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.schemas.computation import ComputationRun
from app.schemas.computation import ComputationStep
from app.schemas.execution_security import ExecutionAccessMode, validate_execution_access


AdapterTerminalStatus = Literal["completed", "failed"]


@dataclass(frozen=True)
class ArtifactSpec:
    """File produced by an adapter and ready to be registered."""

    step_key: str
    artifact_type: str
    name: str
    path: Path
    mime_type: str
    parser_name: str | None = None
    parser_version: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterContext:
    """Runtime context for a single computation run."""

    run: ComputationRun
    worker_id: str
    workdir: Path
    started_at: datetime
    timeout_seconds: int
    access_mode: ExecutionAccessMode = "writable"
    sandbox_profile: str | None = None


@dataclass
class AdapterRunResult:
    """Terminal result returned by an adapter."""

    status: AdapterTerminalStatus
    steps: list[ComputationStep]
    artifact_specs: list[ArtifactSpec] = field(default_factory=list)
    result_summary: dict = field(default_factory=dict)
    error: dict | None = None


class ComputationAdapter(Protocol):
    """Protocol implemented by concrete computation adapters."""

    workflow_type: str
    engine: str
    step_labels: dict[str, str]

    def validate_input(self, context: AdapterContext) -> AdapterRunResult | None:
        """Validate run input before execution.

        Return a failed AdapterRunResult when validation should finish the run.
        Return None when execution can continue.
        """

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Execute the workflow in the adapter workdir."""

    def collect_artifacts(self, context: AdapterContext, result: AdapterRunResult) -> list[ArtifactSpec]:
        """Collect files produced by run into artifact specs."""

    def parse_result(self, context: AdapterContext, result: AdapterRunResult) -> dict:
        """Parse adapter outputs into run.result_summary."""


def build_steps(
    step_labels: dict[str, str],
    *,
    status: AdapterTerminalStatus,
    started_at: datetime,
    finished_at: datetime,
    failed_step_key: str | None = None,
    error_message: str | None = None,
) -> list[ComputationStep]:
    """Build a simple completed/failed timeline for adapter execution."""
    steps: list[ComputationStep] = []
    for key, label in step_labels.items():
        step_status = "completed"
        step_error = None
        if status == "failed" and failed_step_key == key:
            step_status = "failed"
            step_error = error_message
        elif status == "failed" and failed_step_key and steps and steps[-1].status == "failed":
            break
        steps.append(
            ComputationStep(
                step_key=key,
                label=label,
                status=step_status,
                started_at=started_at,
                finished_at=finished_at,
                error=step_error,
            )
        )
        if step_status == "failed":
            break
    return steps


def validate_adapter_access(
    context: AdapterContext,
    *,
    artifact_write_count: int = 0,
    external_dispatch_count: int = 0,
    persist_count: int = 0,
) -> None:
    """校验 adapter 运行结果是否违反当前访问模式。

    Args:
        context: adapter 运行上下文。
        artifact_write_count: adapter 声明或产出的可写制品数量。
        external_dispatch_count: adapter 声明的外部下发次数。
        persist_count: adapter 声明的持久化记录数量。

    Raises:
        ValueError: read_only 模式尝试写入制品、持久化或外部下发。
    """
    validate_execution_access(
        context.access_mode,
        artifact_write_count=artifact_write_count,
        external_dispatch_count=external_dispatch_count,
        persist_count=persist_count,
    )
