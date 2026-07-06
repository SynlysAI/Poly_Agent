"""Controlled local ORCA refinement workflow adapter."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.base import build_steps
from app.computation_adapters.local_structure import build_local_structure
from app.core.config import settings
from app.infra.computation_repositories import utc_now


PARSER_NAME = "local_orca_adapter"
PARSER_VERSION = "0.1.0"

ORCA_STEP_LABELS = {
    "ORCA_PREPARE_STRUCTURE": "结构准备",
    "ORCA_XTB_CREST": "xTB/CREST 构象搜索",
    "ORCA_RUN": "运行本机 ORCA",
    "ORCA_PARSE_RESULT": "解析 ORCA 结果",
}

ORCA_METHOD_LINES = {
    "ORCA_B3LYP_DEF2_SVP": "B3LYP def2-SVP TightSCF",
    "ORCA_PBE0_DEF2_SVP": "PBE0 def2-SVP TightSCF",
}


class OrcaComputeEngineLaserAdapter:
    """Run a real local ORCA refinement workflow.

    The API exposes only backend-owned presets. Users cannot provide shell
    commands, queue scripts, executable paths, or arbitrary ORCA input text.
    """

    workflow_type = "ORCA_COMPUTE_ENGINE_LASER"
    engine = "ORCA"
    step_labels = ORCA_STEP_LABELS

    def validate_input(self, context: AdapterContext) -> AdapterRunResult | None:
        """Validate local ORCA, xTB, CREST and license readiness before execution."""
        if settings.orca_execution_mode != "local":
            return self._failed_result(
                context,
                step_key="ORCA_PREPARE_STRUCTURE",
                error_code="ORCA_WORKFLOW_NOT_CONFIGURED",
                message="ORCA workflow 未配置：请设置 ORCA_EXECUTION_MODE=local",
                retryable=False,
                specs=[],
            )
        if context.run.parameters.method not in ORCA_METHOD_LINES:
            return self._failed_result(
                context,
                step_key="ORCA_PREPARE_STRUCTURE",
                error_code="ORCA_METHOD_NOT_SUPPORTED",
                message="ORCA method 必须来自后端白名单",
                retryable=False,
                specs=[],
            )
        if not settings.orca_license_available:
            return self._failed_result(
                context,
                step_key="ORCA_RUN",
                error_code="ORCA_LICENSE_UNAVAILABLE",
                message="ORCA license 不可用或未在后端配置",
                retryable=True,
                specs=[],
            )
        for service, executable, step_key in (
            ("ORCA", settings.orca_executable, "ORCA_RUN"),
            ("xTB", settings.xtb_executable, "ORCA_XTB_CREST"),
            ("CREST", settings.crest_executable, "ORCA_XTB_CREST"),
        ):
            if not shutil.which(executable):
                return self._failed_result(
                    context,
                    step_key=step_key,
                    error_code=f"{service.upper()}_NOT_AVAILABLE",
                    message=f"未检测到 {service} 可执行文件",
                    retryable=True,
                    specs=[],
                )
        return None

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Prepare structure with CREST/xTB, run local ORCA, and parse scalar outputs."""
        context.workdir.mkdir(parents=True, exist_ok=True)
        specs: list[ArtifactSpec] = []
        config_path = context.workdir / "workflow_config.json"
        _write_json(config_path, self._workflow_config(context))
        specs.append(self._artifact("ORCA_PREPARE_STRUCTURE", "input_json", "workflow_config.json", config_path, "application/json"))

        structure_output = build_local_structure(
            context.run,
            workdir=context.workdir,
            timeout_seconds=context.timeout_seconds,
            engine="LOCAL",
            step_key="ORCA_PREPARE_STRUCTURE",
        )
        specs.extend(structure_output.artifact_specs)
        if structure_output.status == "failed" or not structure_output.xyz_path:
            return self._failed_result(
                context,
                step_key="ORCA_PREPARE_STRUCTURE",
                error_code=(structure_output.error or {}).get("error_code", "ORCA_STRUCTURE_PREP_FAILED"),
                message=structure_output.error_message or "ORCA 输入结构准备失败",
                retryable=True,
                specs=specs,
            )

        input_xyz = context.workdir / "input.xyz"
        shutil.copyfile(structure_output.xyz_path, input_xyz)
        specs.append(self._artifact("ORCA_PREPARE_STRUCTURE", "xyz", "input.xyz", input_xyz, "chemical/x-xyz"))

        crest_result = self._run_crest(context, input_xyz)
        specs.extend(crest_result["specs"])
        if crest_result["returncode"] != 0:
            return self._failed_result(
                context,
                step_key="ORCA_XTB_CREST",
                error_code="CREST_FAILED",
                message=f"CREST 构象搜索失败，returncode={crest_result['returncode']}",
                retryable=True,
                specs=specs,
            )
        crest_best = context.workdir / "crest_best.xyz"
        if not crest_best.exists():
            return self._failed_result(
                context,
                step_key="ORCA_XTB_CREST",
                error_code="CREST_OUTPUT_MISSING",
                message="CREST 未生成 crest_best.xyz",
                retryable=True,
                specs=specs,
            )
        specs.append(self._artifact("ORCA_XTB_CREST", "xyz", "crest_best.xyz", crest_best, "chemical/x-xyz"))

        orca_input = context.workdir / "orca.inp"
        orca_input.write_text(self._build_orca_input(context, crest_best), encoding="utf-8")
        stdout_path = context.workdir / "orca.stdout.log"
        stderr_path = context.workdir / "orca.stderr.log"
        specs.extend(
            [
                self._artifact("ORCA_RUN", "log_text", "orca.inp", orca_input, "text/plain"),
                self._artifact("ORCA_RUN", "log_text", "orca.stdout.log", stdout_path, "text/plain"),
                self._artifact("ORCA_RUN", "log_text", "orca.stderr.log", stderr_path, "text/plain"),
            ]
        )
        try:
            orca_result = self._run_command(
                context,
                [shutil.which(settings.orca_executable), orca_input.name],
                stdout_path,
                stderr_path,
            )
        except subprocess.TimeoutExpired:
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)
            return self._failed_result(
                context,
                step_key="ORCA_RUN",
                error_code="ORCA_TIMEOUT",
                message="ORCA 执行超时",
                retryable=True,
                specs=specs,
            )
        if orca_result.returncode != 0:
            return self._failed_result(
                context,
                step_key="ORCA_RUN",
                error_code="ORCA_FAILED",
                message=f"ORCA 执行失败，returncode={orca_result.returncode}",
                retryable=True,
                specs=specs,
            )

        try:
            summary = self._parse_orca_summary(context, stdout_path)
        except ValueError as exc:
            return self._failed_result(
                context,
                step_key="ORCA_PARSE_RESULT",
                error_code="ORCA_RESULT_PARSE_FAILED",
                message=str(exc),
                retryable=False,
                specs=specs,
            )
        result_path = context.workdir / "result.json"
        _write_json(result_path, summary)
        specs.append(self._artifact("ORCA_PARSE_RESULT", "result_json", "result.json", result_path, "application/json"))

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
            result_summary=summary,
        )

    def collect_artifacts(self, context: AdapterContext, result: AdapterRunResult) -> list[ArtifactSpec]:
        """Return artifacts produced during run."""
        return result.artifact_specs

    def parse_result(self, context: AdapterContext, result: AdapterRunResult) -> dict:
        """Return parsed ORCA summary."""
        if result.status != "completed":
            return {}
        return result.result_summary

    def _run_crest(self, context: AdapterContext, input_xyz: Path) -> dict:
        stdout_path = context.workdir / "crest.stdout.log"
        stderr_path = context.workdir / "crest.stderr.log"
        command = [
            shutil.which(settings.crest_executable),
            input_xyz.name,
            "--gfn",
            "2",
            "--chrg",
            str(context.run.parameters.charge),
            "--uhf",
            str(max(context.run.parameters.multiplicity - 1, 0)),
        ]
        try:
            completed = self._run_command(context, command, stdout_path, stderr_path)
            returncode = completed.returncode
        except subprocess.TimeoutExpired:
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)
            returncode = 124
        return {
            "returncode": returncode,
            "specs": [
                self._artifact("ORCA_XTB_CREST", "log_text", "crest.stdout.log", stdout_path, "text/plain"),
                self._artifact("ORCA_XTB_CREST", "log_text", "crest.stderr.log", stderr_path, "text/plain"),
            ],
        }

    def _run_command(
        self,
        context: AdapterContext,
        command: list[str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> subprocess.CompletedProcess:
        with stdout_path.open("w", encoding="utf-8") as stdout_fp, stderr_path.open("w", encoding="utf-8") as stderr_fp:
            return subprocess.run(
                command,
                cwd=str(context.workdir),
                text=True,
                stdout=stdout_fp,
                stderr=stderr_fp,
                timeout=context.timeout_seconds,
                check=False,
            )

    def _build_orca_input(self, context: AdapterContext, xyz_path: Path) -> str:
        maxcore = max(int(context.run.resources.memory_mb / max(context.run.resources.num_cores, 1)), 512)
        coordinates = _read_xyz_coordinates(xyz_path)
        return "\n".join(
            [
                f"! {ORCA_METHOD_LINES[context.run.parameters.method]}",
                f"%pal nprocs {context.run.resources.num_cores} end",
                f"%maxcore {maxcore}",
                f"* xyz {context.run.parameters.charge} {context.run.parameters.multiplicity}",
                *coordinates,
                "*",
                "",
            ]
        )

    def _parse_orca_summary(self, context: AdapterContext, stdout_path: Path) -> dict:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        energy = _parse_orca_energy_hartree(text)
        if energy is None:
            raise ValueError("无法从 ORCA 输出解析 FINAL SINGLE POINT ENERGY")
        return {
            "engine": context.run.engine,
            "workflow_type": context.run.workflow_type,
            "method": context.run.parameters.method,
            "energy_hartree": energy,
            "normal_termination": "ORCA TERMINATED NORMALLY" in text,
            "crest_used": True,
            "orca_executable": settings.orca_executable,
        }

    def _workflow_config(self, context: AdapterContext) -> dict:
        return {
            "schema_version": "local_orca_workflow_config.v1",
            "run_id": context.run.run_id,
            "workflow_type": context.run.workflow_type,
            "engine": context.run.engine,
            "execution_mode": settings.orca_execution_mode,
            "allowed_method": context.run.parameters.method,
            "charge": context.run.parameters.charge,
            "multiplicity": context.run.parameters.multiplicity,
            "solvent": context.run.parameters.solvent,
            "resources": context.run.resources.model_dump(mode="python"),
            "executables": {
                "orca": settings.orca_executable,
                "xtb": settings.xtb_executable,
                "crest": settings.crest_executable,
            },
        }

    def _artifact(
        self,
        step_key: str,
        artifact_type: str,
        name: str,
        path: Path,
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
            metadata={"source": "local_orca", "source_step": step_key, **(metadata or {})},
        )

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
        error_path = context.workdir / "orca-error.json"
        log_path = context.workdir / "orca-worker.log"
        _write_json(error_path, error)
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
                self._artifact(step_key, "error_json", "orca-error.json", error_path, "application/json", {"error_code": error_code}),
                self._artifact(step_key, "log_text", "orca-worker.log", log_path, "text/plain", {"error_code": error_code}),
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


def _read_xyz_coordinates(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        raise ValueError("XYZ 文件缺少坐标")
    coordinates = [line.strip() for line in lines[2:] if line.strip()]
    if not coordinates:
        raise ValueError("XYZ 文件缺少坐标")
    return coordinates


def _parse_orca_energy_hartree(text: str) -> float | None:
    match = re.search(r"FINAL\s+SINGLE\s+POINT\s+ENERGY\s+(-?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
