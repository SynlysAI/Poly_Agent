"""Deterministic mock computation adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.base import build_steps
from app.infra.computation_repositories import utc_now
from app.schemas.computation import ComputationRun


class MockComputationAdapter:
    """Adapter preserving the existing mock workflow behavior."""

    workflow_type = "MOCK"
    engine = "MOCK"
    step_labels = {
        "MOCK_VALIDATE_INPUT": "输入校验",
        "MOCK_GENERATE_STRUCTURE": "生成结构摘要",
        "MOCK_RESULT": "生成模拟结果",
    }

    def validate_input(self, context: AdapterContext) -> AdapterRunResult | None:
        """Mock inputs are already validated by Pydantic."""
        return None

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Generate deterministic mock files."""
        finished_at = utc_now()
        context.workdir.mkdir(parents=True, exist_ok=True)
        if context.run.mock_should_fail or context.run.parameters.method.upper() == "MOCK_FAIL":
            return self._fail(context, finished_at)
        return self._complete(context, finished_at)

    def collect_artifacts(self, context: AdapterContext, result: AdapterRunResult) -> list[ArtifactSpec]:
        """Return artifacts already produced during run."""
        return result.artifact_specs

    def parse_result(self, context: AdapterContext, result: AdapterRunResult) -> dict:
        """Return parsed mock summary for completed runs."""
        if result.status != "completed":
            return {}
        return result.result_summary

    def _complete(self, context: AdapterContext, finished_at: datetime) -> AdapterRunResult:
        summary = self._build_result_summary(context.run)
        files = [
            (
                "MOCK_GENERATE_STRUCTURE",
                "structure_json",
                "structure.json",
                self._build_structure(context.run),
                "application/json",
            ),
            ("MOCK_RESULT", "result_json", "result.json", summary, "application/json"),
            ("MOCK_RESULT", "log_text", "worker.log", self._build_log(context.run), "text/plain"),
        ]
        specs: list[ArtifactSpec] = []
        for step_key, artifact_type, filename, content, mime_type in files:
            path = context.workdir / filename
            if isinstance(content, str):
                path.write_text(content, encoding="utf-8")
            else:
                path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            specs.append(
                ArtifactSpec(
                    step_key=step_key,
                    artifact_type=artifact_type,
                    name=filename,
                    path=path,
                    mime_type=mime_type,
                    parser_name="mock_parser",
                    parser_version="0.1.0",
                    metadata={"source": "mock", "source_step": step_key},
                )
            )
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

    def _fail(self, context: AdapterContext, finished_at: datetime) -> AdapterRunResult:
        error_code = "MOCK_FAILURE_TRIGGERED"
        message = "Mock failure trigger requested"
        path = context.workdir / "worker-error.log"
        path.write_text(
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
        return AdapterRunResult(
            status="failed",
            steps=build_steps(
                self.step_labels,
                status="failed",
                started_at=context.started_at,
                finished_at=finished_at,
                failed_step_key="MOCK_RESULT",
                error_message=message,
            ),
            artifact_specs=[
                ArtifactSpec(
                    step_key="MOCK_RESULT",
                    artifact_type="log_text",
                    name="worker-error.log",
                    path=path,
                    mime_type="text/plain",
                    parser_name="mock_error_parser",
                    parser_version="0.1.0",
                    metadata={"source": "mock", "source_step": "MOCK_RESULT", "error_code": error_code},
                )
            ],
            error={"error_code": error_code, "message": message, "retryable": True},
        )

    def _build_result_summary(self, run: ComputationRun) -> dict:
        """Build deterministic mock result summary."""
        digest = int(hashlib.sha256(run.molecule.smiles.encode("utf-8")).hexdigest()[:10], 16)
        energy = -float(20 + digest % 9000) / 100
        homo = -float(300 + digest % 420) / 100
        lumo = homo + float(150 + digest % 220) / 100
        summary = {
            "engine": run.engine,
            "workflow_type": run.workflow_type,
            "total_energy_ev": round(energy, 4),
            "homo_ev": round(homo, 4),
            "lumo_ev": round(lumo, 4),
            "gap_ev": round(lumo - homo, 4),
            "dipole_debye": round(float(10 + digest % 250) / 10, 3),
        }
        if run.workflow_type == "MOCK_LASER":
            summary["laser_metrics"] = {
                "gain_factor": float((digest % 900) + 100) * 1e-18,
                "s1_energy_ev": round(1.5 + (digest % 180) / 100, 3),
            }
        return summary

    def _build_structure(self, run: ComputationRun) -> dict:
        """Build mock structure preview JSON."""
        atoms = [
            {"element": "C", "x": 0.0, "y": 0.0, "z": 0.0},
            {"element": "C", "x": 1.42, "y": 0.0, "z": 0.0},
            {"element": "H", "x": -0.52, "y": 0.93, "z": 0.0},
            {"element": "H", "x": 1.94, "y": 0.93, "z": 0.0},
        ]
        return {"name": run.molecule.name or run.run_id, "smiles": run.molecule.smiles, "atoms": atoms}

    def _build_log(self, run: ComputationRun) -> str:
        """Build mock worker log."""
        return "\n".join(
            [
                f"run_id={run.run_id}",
                f"workflow_type={run.workflow_type}",
                "adapter=mock",
                "validated input",
                "generated structure preview",
                "generated deterministic result summary",
            ]
        )

