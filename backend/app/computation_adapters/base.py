"""Shared computation adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.schemas.computation import ComputationRun
from app.schemas.computation import ComputationStep


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

