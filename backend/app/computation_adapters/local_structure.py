"""Local structure generation adapter using optional RDKit/OpenBabel."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.computation_adapters.base import AdapterContext
from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.base import build_steps
from app.infra.computation_repositories import utc_now
from app.schemas.computation import ComputationRun


LOCAL_STRUCTURE_STEP_LABELS = {
    "LOCAL_VALIDATE_INPUT": "输入校验",
    "LOCAL_GENERATE_STRUCTURE": "生成本地结构",
    "LOCAL_COLLECT_ARTIFACTS": "收集结构产物",
}
MAX_LOCAL_TEXT_ARTIFACT_BYTES = 512 * 1024


@dataclass
class StructureBuildOutput:
    """Result from local structure file generation."""

    status: str
    artifact_specs: list[ArtifactSpec]
    structure: dict | None = None
    xyz_path: Path | None = None
    sdf_path: Path | None = None
    error: dict | None = None
    failed_step_key: str = "LOCAL_GENERATE_STRUCTURE"
    error_message: str | None = None
    result_summary: dict | None = None


class LocalStructureAdapter:
    """Generate local SDF/XYZ/structure JSON artifacts."""

    workflow_type = "LOCAL_STRUCTURE"
    engine = "LOCAL"
    step_labels = LOCAL_STRUCTURE_STEP_LABELS

    def validate_input(self, context: AdapterContext) -> AdapterRunResult | None:
        """Validate basic local structure inputs."""
        if not context.run.molecule.smiles.strip():
            return self._failed_result(
                context,
                error_code="LOCAL_STRUCTURE_INVALID_SMILES",
                message="SMILES 不能为空",
                failed_step_key="LOCAL_VALIDATE_INPUT",
            )
        return None

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Generate structure files using RDKit or OpenBabel."""
        output = build_local_structure(
            context.run,
            workdir=context.workdir,
            timeout_seconds=context.timeout_seconds,
            engine=context.run.engine,
            step_key="LOCAL_GENERATE_STRUCTURE",
        )
        finished_at = utc_now()
        if output.status == "failed":
            return AdapterRunResult(
                status="failed",
                steps=build_steps(
                    self.step_labels,
                    status="failed",
                    started_at=context.started_at,
                    finished_at=finished_at,
                    failed_step_key=output.failed_step_key,
                    error_message=output.error_message,
                ),
                artifact_specs=output.artifact_specs,
                error=output.error,
            )
        return AdapterRunResult(
            status="completed",
            steps=build_steps(
                self.step_labels,
                status="completed",
                started_at=context.started_at,
                finished_at=finished_at,
            ),
            artifact_specs=output.artifact_specs,
            result_summary=output.result_summary or {},
        )

    def collect_artifacts(self, context: AdapterContext, result: AdapterRunResult) -> list[ArtifactSpec]:
        """Return artifacts produced during run."""
        return result.artifact_specs

    def parse_result(self, context: AdapterContext, result: AdapterRunResult) -> dict:
        """Return local structure summary."""
        if result.status != "completed":
            return {}
        return result.result_summary

    def _failed_result(
        self,
        context: AdapterContext,
        *,
        error_code: str,
        message: str,
        failed_step_key: str,
    ) -> AdapterRunResult:
        context.workdir.mkdir(parents=True, exist_ok=True)
        error_path = context.workdir / "error.json"
        error = {"error_code": error_code, "message": message, "retryable": True}
        error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
        log_path = context.workdir / "structure.log"
        log_path.write_text(message, encoding="utf-8")
        finished_at = utc_now()
        return AdapterRunResult(
            status="failed",
            steps=build_steps(
                self.step_labels,
                status="failed",
                started_at=context.started_at,
                finished_at=finished_at,
                failed_step_key=failed_step_key,
                error_message=message,
            ),
            artifact_specs=[
                _artifact_spec(failed_step_key, "error_json", "error.json", error_path, "application/json"),
                _artifact_spec(failed_step_key, "log_text", "structure.log", log_path, "text/plain"),
            ],
            error=error,
        )


def build_local_structure(
    run: ComputationRun,
    *,
    workdir: Path,
    timeout_seconds: int,
    engine: str,
    step_key: str,
) -> StructureBuildOutput:
    """Build local structure files for a molecule."""
    workdir.mkdir(parents=True, exist_ok=True)
    input_path = workdir / "input.json"
    log_path = workdir / "structure.log"
    error_path = workdir / "error.json"
    input_payload = {
        "run_id": run.run_id,
        "workflow_type": run.workflow_type,
        "engine": engine,
        "molecule": run.molecule.model_dump(mode="python"),
        "parameters": run.parameters.model_dump(mode="python"),
        "dependencies": {
            "rdkit": _rdkit_available(),
            "openbabel": bool(shutil.which("obabel")),
        },
    }
    input_path.write_text(json.dumps(input_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log_lines = [
        f"run_id={run.run_id}",
        f"workflow_type={run.workflow_type}",
        f"engine={engine}",
    ]
    specs = [_artifact_spec(step_key, "input_json", "input.json", input_path, "application/json")]

    preferred = engine.upper()
    if preferred in {"LOCAL", "RDKIT"} and _rdkit_available():
        try:
            structure, xyz_path, sdf_path = _generate_with_rdkit(run, workdir)
            log_lines.append("structure_backend=rdkit")
            log_path.write_text("\n".join(log_lines), encoding="utf-8")
            specs.extend(_structure_success_specs(step_key, structure, workdir, xyz_path, sdf_path, log_path, "rdkit"))
            _truncate_text_artifacts(specs)
            return _success_output(specs, structure, xyz_path, sdf_path, "rdkit")
        except ValueError as exc:
            return _failed_output(
                specs,
                log_path,
                error_path,
                step_key,
                error_code="LOCAL_STRUCTURE_INVALID_SMILES",
                message=str(exc),
                retryable=False,
                log_lines=log_lines,
            )
        except Exception as exc:  # pragma: no cover - defensive around optional dependency internals
            log_lines.append(f"rdkit_error={exc}")
            if preferred == "RDKIT":
                return _failed_output(
                    specs,
                    log_path,
                    error_path,
                    step_key,
                    error_code="LOCAL_STRUCTURE_RDKIT_FAILED",
                    message="RDKit 结构生成失败",
                    retryable=True,
                    log_lines=log_lines,
                )

    obabel_path = shutil.which("obabel")
    if preferred in {"LOCAL", "OPENBABEL"} and obabel_path:
        output = _generate_with_openbabel(run, workdir, obabel_path, timeout_seconds, step_key, specs, log_lines)
        if output.status == "completed" or preferred == "OPENBABEL":
            return output

    return _failed_output(
        specs,
        log_path,
        error_path,
        step_key,
        error_code="LOCAL_STRUCTURE_DEPENDENCY_MISSING",
        message="未检测到可用的 RDKit 或 OpenBabel，无法生成本地结构",
        retryable=True,
        log_lines=log_lines,
    )


def _generate_with_rdkit(run: ComputationRun, workdir: Path) -> tuple[dict, Path, Path]:
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(run.molecule.smiles)
    if mol is None:
        raise ValueError("SMILES 无法被 RDKit 解析")
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 0xC0FFEE
    embed_code = AllChem.EmbedMolecule(mol, params)
    if embed_code != 0:
        raise ValueError("RDKit 无法生成 3D 构象")
    try:
        AllChem.MMFFOptimizeMolecule(mol, maxIters=200)
    except Exception:
        AllChem.UFFOptimizeMolecule(mol, maxIters=200)
    sdf_path = workdir / "structure.sdf"
    writer = Chem.SDWriter(str(sdf_path))
    writer.write(mol)
    writer.close()
    xyz_path = workdir / "structure.xyz"
    _write_rdkit_xyz(mol, xyz_path)
    structure = _structure_from_rdkit(run, mol)
    return structure, xyz_path, sdf_path


def _write_rdkit_xyz(mol: Any, path: Path) -> None:
    conf = mol.GetConformer()
    lines = [str(mol.GetNumAtoms()), "generated by RDKit"]
    for atom in mol.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol()} {pos.x:.8f} {pos.y:.8f} {pos.z:.8f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _structure_from_rdkit(run: ComputationRun, mol: Any) -> dict:
    conf = mol.GetConformer()
    atoms = []
    for atom in mol.GetAtoms():
        pos = conf.GetAtomPosition(atom.GetIdx())
        atoms.append(
            {
                "index": atom.GetIdx(),
                "element": atom.GetSymbol(),
                "x": round(pos.x, 8),
                "y": round(pos.y, 8),
                "z": round(pos.z, 8),
            }
        )
    bonds = [
        {
            "begin": bond.GetBeginAtomIdx(),
            "end": bond.GetEndAtomIdx(),
            "order": float(bond.GetBondTypeAsDouble()),
        }
        for bond in mol.GetBonds()
    ]
    return _structure_payload(run, atoms=atoms, bonds=bonds, source="rdkit")


def _generate_with_openbabel(
    run: ComputationRun,
    workdir: Path,
    obabel_path: str,
    timeout_seconds: int,
    step_key: str,
    specs: list[ArtifactSpec],
    log_lines: list[str],
) -> StructureBuildOutput:
    smi_path = workdir / "input.smi"
    xyz_path = workdir / "structure.xyz"
    sdf_path = workdir / "structure.sdf"
    log_path = workdir / "structure.log"
    error_path = workdir / "error.json"
    smi_path.write_text(f"{run.molecule.smiles}\t{run.molecule.name or run.run_id}\n", encoding="utf-8")
    commands = [
        [obabel_path, "-ismi", str(smi_path), "-oxyz", "-O", str(xyz_path), "--gen3d"],
        [obabel_path, "-ismi", str(smi_path), "-osdf", "-O", str(sdf_path), "--gen3d"],
    ]
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=str(workdir),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _failed_output(
                specs,
                log_path,
                error_path,
                step_key,
                error_code="LOCAL_STRUCTURE_TIMEOUT",
                message="OpenBabel 结构生成超时",
                retryable=True,
                log_lines=log_lines,
            )
        except OSError as exc:
            return _failed_output(
                specs,
                log_path,
                error_path,
                step_key,
                error_code="LOCAL_STRUCTURE_OPENBABEL_FAILED",
                message=str(exc),
                retryable=True,
                log_lines=log_lines,
            )
        stdout_chunks.append(completed.stdout)
        stderr_chunks.append(completed.stderr)
        if completed.returncode != 0:
            return _failed_output(
                specs,
                log_path,
                error_path,
                step_key,
                error_code="LOCAL_STRUCTURE_OPENBABEL_FAILED",
                message="OpenBabel 结构生成失败",
                retryable=True,
                log_lines=[*log_lines, completed.stderr[-1000:]],
            )
    if not xyz_path.exists():
        return _failed_output(
            specs,
            log_path,
            error_path,
            step_key,
            error_code="LOCAL_STRUCTURE_OPENBABEL_FAILED",
            message="OpenBabel 未生成 XYZ 文件",
            retryable=True,
            log_lines=log_lines,
        )
    try:
        structure = _structure_from_xyz(run, xyz_path, source="openbabel")
    except ValueError as exc:
        return _failed_output(
            specs,
            log_path,
            error_path,
            step_key,
            error_code="LOCAL_STRUCTURE_INVALID_XYZ",
            message=str(exc),
            retryable=False,
            log_lines=log_lines,
        )
    log_lines.extend(["structure_backend=openbabel", *stdout_chunks, *stderr_chunks])
    log_path.write_text("\n".join(line for line in log_lines if line), encoding="utf-8")
    specs.extend(_structure_success_specs(step_key, structure, workdir, xyz_path, sdf_path if sdf_path.exists() else None, log_path, "openbabel"))
    _truncate_text_artifacts(specs)
    return _success_output(specs, structure, xyz_path, sdf_path if sdf_path.exists() else None, "openbabel")


def _structure_from_xyz(run: ComputationRun, xyz_path: Path, *, source: str) -> dict:
    lines = [line.strip() for line in xyz_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    atom_lines = lines[2:] if lines and lines[0].isdigit() else lines
    atoms = []
    for index, line in enumerate(atom_lines):
        parts = line.split()
        if len(parts) < 4:
            continue
        atoms.append(
            {
                "index": index,
                "element": parts[0],
                "x": float(parts[1]),
                "y": float(parts[2]),
                "z": float(parts[3]),
            }
        )
    if not atoms:
        raise ValueError("XYZ 文件不包含可解析原子坐标")
    return _structure_payload(run, atoms=atoms, bonds=[], source=source)


def _structure_payload(run: ComputationRun, *, atoms: list[dict], bonds: list[dict], source: str) -> dict:
    return {
        "name": run.molecule.name or run.run_id,
        "smiles": run.molecule.smiles,
        "charge": run.parameters.charge,
        "multiplicity": run.parameters.multiplicity,
        "source": source,
        "atoms": atoms,
        "bonds": bonds,
    }


def _structure_success_specs(
    step_key: str,
    structure: dict,
    workdir: Path,
    xyz_path: Path,
    sdf_path: Path | None,
    log_path: Path,
    source: str,
) -> list[ArtifactSpec]:
    structure_path = workdir / "structure.json"
    structure_path.write_text(json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8")
    specs = [
        _artifact_spec(step_key, "structure_json", "structure.json", structure_path, "application/json", source),
        _artifact_spec(step_key, "xyz", "structure.xyz", xyz_path, "chemical/x-xyz", source),
        _artifact_spec(step_key, "log_text", "structure.log", log_path, "text/plain", source),
    ]
    if sdf_path and sdf_path.exists():
        specs.append(_artifact_spec(step_key, "sdf", "structure.sdf", sdf_path, "chemical/x-mdl-sdfile", source))
    return specs


def _success_output(
    specs: list[ArtifactSpec],
    structure: dict,
    xyz_path: Path,
    sdf_path: Path | None,
    source: str,
) -> StructureBuildOutput:
    return StructureBuildOutput(
        status="completed",
        artifact_specs=specs,
        structure=structure,
        xyz_path=xyz_path,
        sdf_path=sdf_path,
        result_summary={
            "workflow_type": "LOCAL_STRUCTURE",
            "structure_backend": source,
            "atom_count": len(structure.get("atoms", [])),
            "bond_count": len(structure.get("bonds", [])),
        },
    )


def _failed_output(
    specs: list[ArtifactSpec],
    log_path: Path,
    error_path: Path,
    step_key: str,
    *,
    error_code: str,
    message: str,
    retryable: bool,
    log_lines: list[str],
) -> StructureBuildOutput:
    error = {"error_code": error_code, "message": message, "retryable": retryable}
    error_path.write_text(json.dumps(error, ensure_ascii=False, indent=2), encoding="utf-8")
    log_path.write_text("\n".join([*log_lines, f"error_code={error_code}", f"message={message}"]), encoding="utf-8")
    specs.extend(
        [
            _artifact_spec(step_key, "error_json", "error.json", error_path, "application/json", "local_structure"),
            _artifact_spec(step_key, "log_text", "structure.log", log_path, "text/plain", "local_structure"),
        ]
    )
    _truncate_text_artifacts(specs)
    return StructureBuildOutput(
        status="failed",
        artifact_specs=specs,
        error=error,
        failed_step_key=step_key,
        error_message=message,
    )


def _artifact_spec(
    step_key: str,
    artifact_type: str,
    name: str,
    path: Path,
    mime_type: str,
    source: str = "local_structure",
) -> ArtifactSpec:
    return ArtifactSpec(
        step_key=step_key,
        artifact_type=artifact_type,
        name=name,
        path=path,
        mime_type=mime_type,
        parser_name="local_structure_adapter",
        parser_version="0.1.0",
        metadata={"source": source, "source_step": step_key},
    )


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


def _rdkit_available() -> bool:
    return importlib.util.find_spec("rdkit") is not None
