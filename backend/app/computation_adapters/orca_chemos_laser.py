"""Controlled ORCA/ChemOS laser workflow adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.base import build_steps
from app.computation_adapters.chemos_laser_parser import (
    GAIN_SCHEMA_VERSION,
    PARSER_NAME,
    PARSER_VERSION,
    RESULT_SCHEMA_VERSION,
    SPECTRUM_SCHEMA_VERSION,
    build_fixture_raw_outputs,
    parse_chemos_laser_outputs,
    write_json,
)
from app.core.config import settings
from app.infra.computation_repositories import utc_now


CHEMOS_LASER_STEP_LABELS = {
    "CHEMOS_PREPARE_STRUCTURE": "结构准备",
    "CHEMOS_XTB_CREST": "xTB/CREST 构象搜索",
    "CHEMOS_ORCA": "ORCA 激发态计算",
    "CHEMOS_SPECTRA_PARSE": "spectra parser",
    "CHEMOS_GAIN_PARSE": "gain parser",
}


@dataclass(frozen=True)
class ExternalJobStatus:
    """Status returned by a controlled ORCA/ChemOS executor."""

    status: str
    message: str | None = None
    raw_output_dir: Path | None = None


class FakeOrcaChemosExternalExecutor:
    """Deterministic external executor used to validate submit/poll boundaries."""

    def __init__(self, *, outcome: str) -> None:
        self.outcome = outcome

    def submit(self, context: AdapterContext, job_spec: dict, output_dir: Path) -> dict:
        """Submit a fake job and return backend-owned job references."""
        output_dir.mkdir(parents=True, exist_ok=True)
        return {
            "job_id": f"fake-orca-{context.run.run_id}",
            "queue": job_spec["queue"],
            "submitted_at": utc_now(),
            "executor": "fake",
        }

    def poll(self, job_id: str) -> ExternalJobStatus:
        """Return the configured terminal fake outcome."""
        if self.outcome == "failed":
            return ExternalJobStatus(status="failed", message=f"fake ORCA job failed: {job_id}")
        if self.outcome == "timeout":
            return ExternalJobStatus(status="timeout", message=f"fake ORCA job timed out: {job_id}")
        return ExternalJobStatus(status="completed")

    def collect(self, context: AdapterContext, output_dir: Path) -> tuple[Path, Path]:
        """Write deterministic raw outputs as if they were collected from HPC."""
        return build_fixture_raw_outputs(context.run, output_dir)

    def cancel(self, job_id: str) -> None:
        """Cancel fake external job."""
        return None


class OrcaChemosLaserAdapter:
    """Run the controlled ORCA/ChemOS laser workflow.

    The API exposes only workflow presets. Shell commands, queue scripts and local
    paths stay in backend deployment configuration and are not accepted from users.
    """

    workflow_type = "ORCA_CHEMOS_LASER"
    engine = "ORCA"
    step_labels = CHEMOS_LASER_STEP_LABELS

    def validate_input(self, context: AdapterContext) -> AdapterRunResult | None:
        """Validate backend ORCA/HPC readiness before execution."""
        mode = settings.orca_chemos_execution_mode
        if mode not in {"disabled", "fixture", "external"}:
            return self._failed_result(
                context,
                step_key="CHEMOS_PREPARE_STRUCTURE",
                error_code="ORCA_WORKFLOW_CONFIG_INVALID",
                message=f"ORCA/ChemOS workflow 配置无效：execution_mode={mode}",
                retryable=False,
                specs=[],
            )
        if mode == "disabled":
            return self._failed_result(
                context,
                step_key="CHEMOS_PREPARE_STRUCTURE",
                error_code="ORCA_WORKFLOW_NOT_CONFIGURED",
                message="ORCA/ChemOS workflow 未配置：请在后端启用 ORCA_CHEMOS_EXECUTION_MODE",
                retryable=False,
                specs=[],
            )
        if mode == "external" and not settings.orca_license_available:
            return self._failed_result(
                context,
                step_key="CHEMOS_ORCA",
                error_code="ORCA_LICENSE_UNAVAILABLE",
                message="ORCA license 不可用或未在后端配置",
                retryable=True,
                specs=[],
            )
        if mode == "external" and not settings.hpc_queue_available:
            return self._failed_result(
                context,
                step_key="CHEMOS_ORCA",
                error_code="HPC_QUEUE_UNAVAILABLE",
                message=f"HPC 队列不可用：queue={settings.hpc_queue_name}",
                retryable=True,
                specs=[],
            )
        if mode == "external" and settings.orca_chemos_external_executor != "fake":
            return self._failed_result(
                context,
                step_key="CHEMOS_ORCA",
                error_code="ORCA_EXTERNAL_EXECUTOR_UNSUPPORTED",
                message=f"不支持的 ORCA external executor：{settings.orca_chemos_external_executor}",
                retryable=False,
                specs=[],
            )
        return None

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Execute fixture mode and parse ChemOS laser outputs."""
        if settings.orca_chemos_execution_mode == "external":
            return self._run_external(context)
        context.workdir.mkdir(parents=True, exist_ok=True)
        specs: list[ArtifactSpec] = []
        config_path = context.workdir / "workflow_config.json"
        config = {
            "schema_version": "orca_chemos_workflow_config.v1",
            "run_id": context.run.run_id,
            "workflow_type": context.run.workflow_type,
            "engine": context.run.engine,
            "execution_mode": settings.orca_chemos_execution_mode,
            "allowed_method": context.run.parameters.method,
            "charge": context.run.parameters.charge,
            "multiplicity": context.run.parameters.multiplicity,
            "solvent": context.run.parameters.solvent,
            "resources": context.run.resources.model_dump(mode="python"),
            "hpc_queue": settings.hpc_queue_name,
        }
        write_json(config_path, config)
        specs.append(
            self._artifact(
                "CHEMOS_PREPARE_STRUCTURE",
                "input_json",
                "workflow_config.json",
                config_path,
                "application/json",
                metadata={"output_schema": "orca_chemos_workflow_config.v1"},
            )
        )

        structure_path = context.workdir / "structure.json"
        xyz_path = context.workdir / "structure.xyz"
        structure = self._fixture_structure(context)
        write_json(structure_path, structure)
        xyz_path.write_text(self._fixture_xyz(context), encoding="utf-8")
        specs.extend(
            [
                self._artifact("CHEMOS_PREPARE_STRUCTURE", "structure_json", "structure.json", structure_path, "application/json"),
                self._artifact("CHEMOS_PREPARE_STRUCTURE", "xyz", "structure.xyz", xyz_path, "chemical/x-xyz"),
            ]
        )

        xtb_log = context.workdir / "xtb_crest.log"
        orca_log = context.workdir / "orca.log"
        xtb_log.write_text("fixture xTB/CREST conformer search completed\n", encoding="utf-8")
        orca_log.write_text("fixture ORCA excited-state calculation completed\n", encoding="utf-8")
        specs.extend(
            [
                self._artifact("CHEMOS_XTB_CREST", "log_text", "xtb_crest.log", xtb_log, "text/plain"),
                self._artifact("CHEMOS_ORCA", "log_text", "orca.log", orca_log, "text/plain"),
            ]
        )

        spectra_raw_path, gain_raw_path = build_fixture_raw_outputs(context.run, context.workdir)
        specs.extend(
            [
                self._artifact("CHEMOS_SPECTRA_PARSE", "log_text", "spectra.raw.csv", spectra_raw_path, "text/csv"),
                self._artifact("CHEMOS_GAIN_PARSE", "log_text", "gain.raw.json", gain_raw_path, "application/json"),
            ]
        )
        try:
            parsed = parse_chemos_laser_outputs(
                context.run,
                spectra_raw_path=spectra_raw_path,
                gain_raw_path=gain_raw_path,
            )
        except ValueError as exc:
            return self._failed_result(
                context,
                step_key="CHEMOS_SPECTRA_PARSE",
                error_code="CHEMOS_LASER_PARSE_FAILED",
                message=str(exc),
                retryable=False,
                specs=specs,
            )

        spectrum_path = context.workdir / "spectrum.json"
        gain_path = context.workdir / "gain.json"
        result_path = context.workdir / "result.json"
        write_json(spectrum_path, parsed.spectrum)
        write_json(gain_path, parsed.gain)
        write_json(result_path, parsed.result_summary)
        specs.extend(
            [
                self._artifact(
                    "CHEMOS_SPECTRA_PARSE",
                    "spectrum_json",
                    "spectrum.json",
                    spectrum_path,
                    "application/json",
                    metadata={
                        "output_schema": SPECTRUM_SCHEMA_VERSION,
                        "input_checksums": parsed.input_checksums,
                    },
                ),
                self._artifact(
                    "CHEMOS_GAIN_PARSE",
                    "metrics_json",
                    "gain.json",
                    gain_path,
                    "application/json",
                    metadata={
                        "output_schema": GAIN_SCHEMA_VERSION,
                        "input_checksums": parsed.input_checksums,
                    },
                ),
                self._artifact(
                    "CHEMOS_GAIN_PARSE",
                    "result_json",
                    "result.json",
                    result_path,
                    "application/json",
                    metadata={
                        "output_schema": RESULT_SCHEMA_VERSION,
                        "input_checksums": parsed.input_checksums,
                    },
                ),
            ]
        )
        finished_at = utc_now()
        return AdapterRunResult(
            status="completed",
            steps=build_steps(
                self.step_labels,
                status="completed",
                started_at=context.started_at,
                finished_at=finished_at,
            ),
            artifact_specs=specs,
            result_summary=parsed.result_summary,
        )

    def _run_external(self, context: AdapterContext) -> AdapterRunResult:
        """Submit, poll, collect and parse an external ORCA/ChemOS job."""
        from app.services.computation_service import ComputationService

        service = ComputationService()
        context.workdir.mkdir(parents=True, exist_ok=True)
        specs: list[ArtifactSpec] = []
        config_path = context.workdir / "workflow_config.json"
        job_spec_path = context.workdir / "job_spec.json"
        raw_output_dir = context.workdir / "external_raw"
        config = self._workflow_config(context)
        write_json(config_path, config)
        specs.append(
            self._artifact(
                "CHEMOS_PREPARE_STRUCTURE",
                "input_json",
                "workflow_config.json",
                config_path,
                "application/json",
                metadata={"output_schema": "orca_chemos_workflow_config.v1"},
            )
        )
        job_spec = {
            "schema_version": "orca_chemos_external_job.v1",
            "run_id": context.run.run_id,
            "workflow_type": context.run.workflow_type,
            "engine": context.run.engine,
            "method": context.run.parameters.method,
            "queue": settings.hpc_queue_name,
            "resources": context.run.resources.model_dump(mode="python"),
            "molecule": context.run.molecule.model_dump(mode="python"),
            "output_dir": "external_raw",
        }
        write_json(job_spec_path, job_spec)
        specs.append(
            self._artifact(
                "CHEMOS_PREPARE_STRUCTURE",
                "input_json",
                "job_spec.json",
                job_spec_path,
                "application/json",
                metadata={"output_schema": "orca_chemos_external_job.v1"},
            )
        )

        executor = FakeOrcaChemosExternalExecutor(outcome=settings.orca_chemos_fake_external_outcome)
        submitted = executor.submit(context, job_spec, raw_output_dir)
        job_id = submitted["job_id"]
        service.update_external_refs(
            context.run.run_id,
            {
                "orca_chemos_job_id": job_id,
                "queue": submitted["queue"],
                "submitted_at": submitted["submitted_at"],
                "executor": submitted["executor"],
            },
            worker_id=context.worker_id,
        )
        polled = executor.poll(job_id)
        service.update_external_refs(
            context.run.run_id,
            {"polled_at": utc_now(), "external_status": polled.status},
            worker_id=context.worker_id,
        )
        current = service.get_run(context.run.run_id)
        if current.status == "cancelled":
            executor.cancel(job_id)
            service.update_external_refs(
                context.run.run_id,
                {"external_cancelled": True, "external_status": "cancelled"},
                worker_id=context.worker_id,
            )
            return self._failed_result(
                context,
                step_key="CHEMOS_ORCA",
                error_code="ORCA_EXTERNAL_JOB_CANCELLED",
                message="ORCA/ChemOS external job 已取消",
                retryable=True,
                specs=specs,
            )
        if polled.status == "failed":
            return self._failed_result(
                context,
                step_key="CHEMOS_ORCA",
                error_code="ORCA_EXTERNAL_JOB_FAILED",
                message=polled.message or "ORCA/ChemOS external job failed",
                retryable=True,
                specs=specs,
            )
        if polled.status == "timeout":
            return self._failed_result(
                context,
                step_key="CHEMOS_ORCA",
                error_code="ORCA_EXTERNAL_JOB_TIMEOUT",
                message=polled.message or "ORCA/ChemOS external job timed out",
                retryable=True,
                specs=specs,
            )

        spectra_raw_path, gain_raw_path = executor.collect(context, raw_output_dir)
        specs.extend(
            [
                self._artifact("CHEMOS_SPECTRA_PARSE", "log_text", "spectra.raw.csv", spectra_raw_path, "text/csv"),
                self._artifact("CHEMOS_GAIN_PARSE", "log_text", "gain.raw.json", gain_raw_path, "application/json"),
            ]
        )
        try:
            parsed = parse_chemos_laser_outputs(
                context.run,
                spectra_raw_path=spectra_raw_path,
                gain_raw_path=gain_raw_path,
            )
        except ValueError as exc:
            return self._failed_result(
                context,
                step_key="CHEMOS_SPECTRA_PARSE",
                error_code="CHEMOS_LASER_PARSE_FAILED",
                message=str(exc),
                retryable=False,
                specs=specs,
            )

        spectrum_path = context.workdir / "spectrum.json"
        gain_path = context.workdir / "gain.json"
        result_path = context.workdir / "result.json"
        write_json(spectrum_path, parsed.spectrum)
        write_json(gain_path, parsed.gain)
        write_json(result_path, parsed.result_summary)
        specs.extend(
            [
                self._artifact(
                    "CHEMOS_SPECTRA_PARSE",
                    "spectrum_json",
                    "spectrum.json",
                    spectrum_path,
                    "application/json",
                    metadata={
                        "output_schema": SPECTRUM_SCHEMA_VERSION,
                        "input_checksums": parsed.input_checksums,
                    },
                ),
                self._artifact(
                    "CHEMOS_GAIN_PARSE",
                    "metrics_json",
                    "gain.json",
                    gain_path,
                    "application/json",
                    metadata={
                        "output_schema": GAIN_SCHEMA_VERSION,
                        "input_checksums": parsed.input_checksums,
                    },
                ),
                self._artifact(
                    "CHEMOS_GAIN_PARSE",
                    "result_json",
                    "result.json",
                    result_path,
                    "application/json",
                    metadata={
                        "output_schema": RESULT_SCHEMA_VERSION,
                        "input_checksums": parsed.input_checksums,
                    },
                ),
            ]
        )
        finished_at = utc_now()
        return AdapterRunResult(
            status="completed",
            steps=build_steps(
                self.step_labels,
                status="completed",
                started_at=context.started_at,
                finished_at=finished_at,
            ),
            artifact_specs=specs,
            result_summary=parsed.result_summary,
        )

    def collect_artifacts(self, context: AdapterContext, result: AdapterRunResult) -> list[ArtifactSpec]:
        """Return artifacts produced during run."""
        return result.artifact_specs

    def parse_result(self, context: AdapterContext, result: AdapterRunResult) -> dict:
        """Return parsed result summary."""
        if result.status != "completed":
            return {}
        return result.result_summary

    def _failed_result(
        self,
        context: AdapterContext,
        *,
        step_key: str,
        error_code: str,
        message: str,
        retryable: bool,
        specs: list[ArtifactSpec],
    ) -> AdapterRunResult:
        context.workdir.mkdir(parents=True, exist_ok=True)
        error = {"error_code": error_code, "message": message, "retryable": retryable}
        error_path = context.workdir / "orca-chemos-error.json"
        log_path = context.workdir / "orca-chemos.log"
        write_json(error_path, error)
        log_path.write_text(
            "\n".join(
                [
                    f"run_id={context.run.run_id}",
                    f"workflow_type={context.run.workflow_type}",
                    f"engine={context.run.engine}",
                    f"error_code={error_code}",
                    f"message={message}",
                ]
            ),
            encoding="utf-8",
        )
        specs.extend(
            [
                self._artifact(step_key, "error_json", "orca-chemos-error.json", error_path, "application/json", {"error_code": error_code}),
                self._artifact(step_key, "log_text", "orca-chemos.log", log_path, "text/plain", {"error_code": error_code}),
            ]
        )
        now = utc_now()
        return AdapterRunResult(
            status="failed",
            steps=build_steps(
                self.step_labels,
                status="failed",
                started_at=context.started_at,
                finished_at=now,
                failed_step_key=step_key,
                error_message=message,
            ),
            artifact_specs=specs,
            error=error,
        )

    def _artifact(
        self,
        step_key: str,
        artifact_type: str,
        name: str,
        path,
        mime_type: str,
        metadata: dict | None = None,
    ) -> ArtifactSpec:
        return ArtifactSpec(
            step_key=step_key,
            artifact_type=artifact_type,
            name=name,
            path=path,
            mime_type=mime_type,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            metadata={"source": "orca_chemos_laser", "source_step": step_key, **(metadata or {})},
        )

    def _workflow_config(self, context: AdapterContext) -> dict:
        return {
            "schema_version": "orca_chemos_workflow_config.v1",
            "run_id": context.run.run_id,
            "workflow_type": context.run.workflow_type,
            "engine": context.run.engine,
            "execution_mode": settings.orca_chemos_execution_mode,
            "allowed_method": context.run.parameters.method,
            "charge": context.run.parameters.charge,
            "multiplicity": context.run.parameters.multiplicity,
            "solvent": context.run.parameters.solvent,
            "resources": context.run.resources.model_dump(mode="python"),
            "hpc_queue": settings.hpc_queue_name,
        }

    def _fixture_structure(self, context: AdapterContext) -> dict:
        return {
            "schema_version": "structure.v1",
            "name": context.run.molecule.name or context.run.run_id,
            "smiles": context.run.molecule.smiles,
            "source": "orca_chemos_fixture",
            "atoms": [
                {"index": 0, "element": "C", "x": 0.0, "y": 0.0, "z": 0.0},
                {"index": 1, "element": "C", "x": 1.42, "y": 0.0, "z": 0.0},
                {"index": 2, "element": "H", "x": -0.52, "y": 0.93, "z": 0.0},
                {"index": 3, "element": "H", "x": 1.94, "y": 0.93, "z": 0.0},
            ],
            "bonds": [{"begin": 0, "end": 1, "order": 1.0}],
        }

    def _fixture_xyz(self, context: AdapterContext) -> str:
        return "\n".join(
            [
                "4",
                f"fixture structure for {context.run.molecule.smiles}",
                "C 0.00000000 0.00000000 0.00000000",
                "C 1.42000000 0.00000000 0.00000000",
                "H -0.52000000 0.93000000 0.00000000",
                "H 1.94000000 0.93000000 0.00000000",
                "",
            ]
        )
