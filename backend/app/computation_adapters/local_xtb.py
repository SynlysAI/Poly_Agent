"""Local xTB computation adapter."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.base import build_steps
from app.computation_adapters.local_structure import build_local_structure
from app.infra.computation_repositories import utc_now


XTB_STEP_LABELS = {
    "XTB_VALIDATE_INPUT": "输入校验",
    "XTB_PREPARE_STRUCTURE": "准备 xTB 输入结构",
    "XTB_RUN": "运行本地 xTB",
    "XTB_PARSE_RESULT": "解析 xTB 结果",
}

XTB_METHOD_TO_GFN = {
    "GFN2-XTB": "2",
    "GFN1-XTB": "1",
    "GFN0-XTB": "0",
}

MAX_LOCAL_TEXT_ARTIFACT_BYTES = 512 * 1024


class LocalXtbAdapter:
    """Run xTB locally in an isolated per-run workdir."""

    workflow_type = "LOCAL_XTB"
    engine = "XTB"
    step_labels = XTB_STEP_LABELS

    def validate_input(self, context: AdapterContext) -> AdapterRunResult | None:
        """Validate xTB method and dependency availability."""
        method = context.run.parameters.method.upper()
        if method not in XTB_METHOD_TO_GFN:
            return self._failed_result(
                context,
                step_key="XTB_VALIDATE_INPUT",
                error_code="XTB_METHOD_NOT_SUPPORTED",
                message=f"不支持的 xTB method：{context.run.parameters.method}",
                retryable=False,
                specs=[],
            )
        if not shutil.which("xtb"):
            return self._failed_result(
                context,
                step_key="XTB_VALIDATE_INPUT",
                error_code="XTB_NOT_AVAILABLE",
                message="未检测到 xtb 可执行文件",
                retryable=True,
                specs=[],
            )
        return None

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Prepare input structure and execute xTB subprocess."""
        context.workdir.mkdir(parents=True, exist_ok=True)
        config_path = context.workdir / "run_config.json"
        config = {
            "run_id": context.run.run_id,
            "workflow_type": context.run.workflow_type,
            "engine": context.run.engine,
            "method": context.run.parameters.method,
            "charge": context.run.parameters.charge,
            "multiplicity": context.run.parameters.multiplicity,
            "solvent": context.run.parameters.solvent,
            "num_cores": context.run.resources.num_cores,
            "timeout_seconds": context.timeout_seconds,
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        specs = [
            ArtifactSpec(
                step_key="XTB_PREPARE_STRUCTURE",
                artifact_type="input_json",
                name="run_config.json",
                path=config_path,
                mime_type="application/json",
                parser_name="local_xtb_adapter",
                parser_version="0.1.0",
                metadata={"source": "local_xtb", "source_step": "XTB_PREPARE_STRUCTURE"},
            )
        ]
        structure_output = build_local_structure(
            context.run,
            workdir=context.workdir,
            timeout_seconds=context.timeout_seconds,
            engine="LOCAL",
            step_key="XTB_PREPARE_STRUCTURE",
        )
        specs.extend(structure_output.artifact_specs)
        if structure_output.status == "failed" or not structure_output.xyz_path:
            error_code = "XTB_STRUCTURE_PREP_FAILED"
            if structure_output.error:
                error_code = structure_output.error.get("error_code", error_code)
            return self._failed_result(
                context,
                step_key="XTB_PREPARE_STRUCTURE",
                error_code=error_code,
                message=structure_output.error_message or "xTB 输入结构准备失败",
                retryable=True,
                specs=specs,
            )

        input_xyz = context.workdir / "input.xyz"
        shutil.copyfile(structure_output.xyz_path, input_xyz)
        specs.append(
            ArtifactSpec(
                step_key="XTB_PREPARE_STRUCTURE",
                artifact_type="xyz",
                name="input.xyz",
                path=input_xyz,
                mime_type="chemical/x-xyz",
                parser_name="local_xtb_adapter",
                parser_version="0.1.0",
                metadata={"source": "local_xtb", "source_step": "XTB_PREPARE_STRUCTURE"},
            )
        )

        xtb_path = shutil.which("xtb")
        if not xtb_path:
            return self._failed_result(
                context,
                step_key="XTB_VALIDATE_INPUT",
                error_code="XTB_NOT_AVAILABLE",
                message="未检测到 xtb 可执行文件",
                retryable=True,
                specs=specs,
            )
        command = self._build_command(context, xtb_path, input_xyz)
        stdout_path = context.workdir / "xtb.stdout.log"
        stderr_path = context.workdir / "xtb.stderr.log"
        try:
            returncode, cancelled = self._run_subprocess_with_heartbeat(context, command, stdout_path, stderr_path)
        except subprocess.TimeoutExpired:
            stdout_path.touch(exist_ok=True)
            stderr_path.touch(exist_ok=True)
            specs.extend(_xtb_log_specs(stdout_path, stderr_path))
            return self._failed_result(
                context,
                step_key="XTB_RUN",
                error_code="XTB_TIMEOUT",
                message="xTB 执行超时",
                retryable=True,
                specs=specs,
            )
        except OSError as exc:
            stderr_path.write_text(str(exc), encoding="utf-8")
            stdout_path.write_text("", encoding="utf-8")
            specs.extend(_xtb_log_specs(stdout_path, stderr_path))
            return self._failed_result(
                context,
                step_key="XTB_RUN",
                error_code="XTB_FAILED",
                message=str(exc),
                retryable=True,
                specs=specs,
            )

        specs.extend(_xtb_log_specs(stdout_path, stderr_path))
        specs.extend(_xtb_output_specs(context.workdir))
        if cancelled:
            return self._failed_result(
                context,
                step_key="XTB_RUN",
                error_code="XTB_CANCELLED",
                message="xTB 执行已取消",
                retryable=True,
                specs=specs,
            )
        if returncode != 0:
            return self._failed_result(
                context,
                step_key="XTB_RUN",
                error_code="XTB_FAILED",
                message=f"xTB 执行失败，returncode={returncode}",
                retryable=True,
                specs=specs,
            )

        try:
            summary = self._parse_summary(context, stdout_path)
        except ValueError as exc:
            _truncate_text_artifacts(specs)
            return self._failed_result(
                context,
                step_key="XTB_PARSE_RESULT",
                error_code="XTB_RESULT_PARSE_FAILED",
                message=str(exc),
                retryable=False,
                specs=specs,
            )
        result_path = context.workdir / "result.json"
        result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        specs.append(
            ArtifactSpec(
                step_key="XTB_PARSE_RESULT",
                artifact_type="result_json",
                name="result.json",
                path=result_path,
                mime_type="application/json",
                parser_name="local_xtb_parser",
                parser_version="0.1.0",
                metadata={"source": "local_xtb", "source_step": "XTB_PARSE_RESULT"},
            )
        )
        _truncate_text_artifacts(specs)
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
        """Return parsed xTB summary."""
        if result.status != "completed":
            return {}
        return result.result_summary

    def _run_subprocess_with_heartbeat(
        self,
        context: AdapterContext,
        command: list[str],
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[int, bool]:
        """Run xTB while refreshing heartbeat and honoring user cancellation."""
        from app.services.computation_service import ComputationService

        service = ComputationService()
        started = time.monotonic()
        with stdout_path.open("w", encoding="utf-8") as stdout_fp, stderr_path.open("w", encoding="utf-8") as stderr_fp:
            process = subprocess.Popen(
                command,
                cwd=str(context.workdir),
                text=True,
                stdout=stdout_fp,
                stderr=stderr_fp,
            )
            last_heartbeat = 0.0
            while True:
                returncode = process.poll()
                if returncode is not None:
                    return returncode, False
                now = time.monotonic()
                if now - started > context.timeout_seconds:
                    process.kill()
                    process.wait(timeout=5)
                    raise subprocess.TimeoutExpired(command, context.timeout_seconds)
                if now - last_heartbeat >= 5:
                    run = service.heartbeat_run(context.run.run_id, worker_id=context.worker_id)
                    last_heartbeat = now
                    if run.status == "cancelled":
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        return process.returncode or -15, True
                time.sleep(1)

    def _build_command(self, context: AdapterContext, xtb_path: str, input_xyz: Path) -> list[str]:
        method_key = context.run.parameters.method.upper()
        command = [
            xtb_path,
            str(input_xyz.name),
            "--gfn",
            XTB_METHOD_TO_GFN[method_key],
            "--chrg",
            str(context.run.parameters.charge),
            "--uhf",
            str(max(context.run.parameters.multiplicity - 1, 0)),
            "--parallel",
            str(context.run.resources.num_cores),
        ]
        if context.run.parameters.solvent:
            command.extend(["--alpb", context.run.parameters.solvent])
        return command

    def _parse_summary(self, context: AdapterContext, stdout_path: Path) -> dict:
        text = stdout_path.read_text(encoding="utf-8")
        summary_text = text
        energy = _parse_energy_hartree(text)
        xtb_out = context.workdir / "xtb.out"
        if xtb_out.exists():
            xtb_out_text = xtb_out.read_text(encoding="utf-8", errors="replace")
            summary_text = f"{text}\n{xtb_out_text}"
            if energy is None:
                energy = _parse_energy_hartree(xtb_out_text)
        if energy is None:
            raise ValueError("无法从 xTB 输出解析 total energy")
        runtime_seconds = _parse_runtime_seconds(summary_text)
        xtb_version = _parse_xtb_version(summary_text)
        normal_termination = _parse_normal_termination(summary_text)
        return {
            "engine": context.run.engine,
            "workflow_type": context.run.workflow_type,
            "method": context.run.parameters.method,
            "energy_hartree": energy,
            "normal_termination": normal_termination,
            "runtime_seconds": runtime_seconds,
            "xtb_version": xtb_version,
        }

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
        _truncate_text_artifacts(specs)
        error = {"error_code": error_code, "message": message, "retryable": retryable}
        error_path = context.workdir / "xtb-error.json"
        worker_log_path = context.workdir / "worker.log"
        error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        worker_log_path.write_text(
            "\n".join(
                [
                    f"run_id={context.run.run_id}",
                    f"workflow_type={context.run.workflow_type}",
                    f"error_code={error_code}",
                    f"message={message}",
                ]
            ),
            encoding="utf-8",
        )
        specs.extend(
            [
                ArtifactSpec(
                    step_key=step_key,
                    artifact_type="error_json",
                    name="xtb-error.json",
                    path=error_path,
                    mime_type="application/json",
                    parser_name="local_xtb_adapter",
                    parser_version="0.1.0",
                    metadata={"source": "local_xtb", "source_step": step_key, "error_code": error_code},
                ),
                ArtifactSpec(
                    step_key=step_key,
                    artifact_type="log_text",
                    name="worker.log",
                    path=worker_log_path,
                    mime_type="text/plain",
                    parser_name="local_xtb_adapter",
                    parser_version="0.1.0",
                    metadata={"source": "local_xtb", "source_step": step_key, "error_code": error_code},
                ),
            ]
        )
        finished_at = utc_now()
        return AdapterRunResult(
            status="failed",
            steps=build_steps(
                self.step_labels,
                status="failed",
                started_at=context.started_at,
                finished_at=finished_at,
                failed_step_key=step_key,
                error_message=message,
            ),
            artifact_specs=specs,
            error=error,
        )


def _parse_energy_hartree(text: str) -> float | None:
    patterns = [
        r"TOTAL\s+ENERGY\s+(-?\d+(?:\.\d+)?)",
        r"total\s+E\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
        r"energy_hartree\s*[:=]\s*(-?\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _parse_xtb_version(text: str) -> str:
    patterns = [
        r"\bxtb\s+version\s+([0-9A-Za-z_.+\-]+)",
        r"\bxTB\s+version\s+([0-9A-Za-z_.+\-]+)",
        r"\bversion\s*[:=]\s*([0-9A-Za-z_.+\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return "unknown"


def _parse_runtime_seconds(text: str) -> float | None:
    direct = re.search(r"\bruntime_seconds\s*[:=]\s*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if direct:
        return round(float(direct.group(1)), 3)
    wall_time = re.search(
        r"wall[-\s]?time\s*[:=]\s*(?:(\d+)\s*d[, ]*)?(?:(\d+)\s*h[, ]*)?(?:(\d+)\s*min[, ]*)?(\d+(?:\.\d+)?)\s*s",
        text,
        flags=re.IGNORECASE,
    )
    if wall_time:
        days = int(wall_time.group(1) or 0)
        hours = int(wall_time.group(2) or 0)
        minutes = int(wall_time.group(3) or 0)
        seconds = float(wall_time.group(4))
        return round(days * 86400 + hours * 3600 + minutes * 60 + seconds, 3)
    return None


def _parse_normal_termination(text: str) -> bool:
    lowered = text.lower()
    if "abnormal termination" in lowered:
        return False
    if "normal termination" in lowered:
        return True
    return True


def _truncate_text_artifacts(specs: list[ArtifactSpec]) -> None:
    for spec in specs:
        if spec.artifact_type not in {"log_text", "xyz", "sdf"}:
            continue
        truncated = _truncate_text_file(spec.path, MAX_LOCAL_TEXT_ARTIFACT_BYTES)
        if truncated:
            spec.metadata["truncated"] = True
            spec.metadata["max_bytes"] = MAX_LOCAL_TEXT_ARTIFACT_BYTES


def _truncate_text_file(path: Path, max_bytes: int) -> bool:
    if not path.exists() or path.stat().st_size <= max_bytes:
        return False
    marker = f"\n\n[artifact truncated at {max_bytes} bytes]\n".encode("utf-8")
    keep_bytes = max(max_bytes - len(marker), 0)
    with path.open("rb") as fp:
        head = fp.read(keep_bytes)
    path.write_bytes(head + marker)
    return True


def _xtb_log_specs(stdout_path: Path, stderr_path: Path) -> list[ArtifactSpec]:
    return [
        ArtifactSpec(
            step_key="XTB_RUN",
            artifact_type="log_text",
            name="xtb.stdout.log",
            path=stdout_path,
            mime_type="text/plain",
            parser_name="local_xtb_adapter",
            parser_version="0.1.0",
            metadata={"source": "local_xtb", "source_step": "XTB_RUN", "stream": "stdout"},
        ),
        ArtifactSpec(
            step_key="XTB_RUN",
            artifact_type="log_text",
            name="xtb.stderr.log",
            path=stderr_path,
            mime_type="text/plain",
            parser_name="local_xtb_adapter",
            parser_version="0.1.0",
            metadata={"source": "local_xtb", "source_step": "XTB_RUN", "stream": "stderr"},
        ),
    ]


def _xtb_output_specs(workdir: Path) -> list[ArtifactSpec]:
    specs: list[ArtifactSpec] = []
    known_outputs = {
        "xtbopt.xyz": ("xyz", "chemical/x-xyz"),
        "xtb.out": ("log_text", "text/plain"),
        "charges": ("log_text", "text/plain"),
        "wbo": ("log_text", "text/plain"),
    }
    for filename, (artifact_type, mime_type) in known_outputs.items():
        path = workdir / filename
        if not path.exists() or not path.is_file():
            continue
        specs.append(
            ArtifactSpec(
                step_key="XTB_RUN",
                artifact_type=artifact_type,
                name=filename,
                path=path,
                mime_type=mime_type,
                parser_name="local_xtb_adapter",
                parser_version="0.1.0",
                metadata={"source": "local_xtb", "source_step": "XTB_RUN"},
            )
        )
    return specs
