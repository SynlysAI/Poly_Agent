"""ChemOS laser spectra and gain parser."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.schemas.computation import ComputationRun


PARSER_NAME = "chemos_laser_parser"
PARSER_VERSION = "1.0.0"
SPECTRUM_SCHEMA_VERSION = "chemos_spectrum.v1"
GAIN_SCHEMA_VERSION = "chemos_gain.v1"
RESULT_SCHEMA_VERSION = "chemos_laser_result.v1"


@dataclass(frozen=True)
class ChemosLaserParsedOutputs:
    """Parsed ChemOS laser output bundle."""

    spectrum: dict
    gain: dict
    result_summary: dict
    input_checksums: dict[str, str]


def parse_chemos_laser_outputs(
    run: ComputationRun,
    *,
    spectra_raw_path: Path,
    gain_raw_path: Path,
) -> ChemosLaserParsedOutputs:
    """Parse raw spectra/gain outputs into stable schemas."""
    input_checksums = {
        spectra_raw_path.name: sha256_file(spectra_raw_path),
        gain_raw_path.name: sha256_file(gain_raw_path),
    }
    points = _read_spectrum_points(spectra_raw_path)
    gain_factor, gain_payload = _read_gain_factor(gain_raw_path)
    absorption_peak_nm = _peak_x(points)
    spectrum = {
        "schema_version": SPECTRUM_SCHEMA_VERSION,
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
        "input_checksums": input_checksums,
        "spectrum": {
            "kind": "absorption",
            "x_label": "wavelength_nm",
            "y_label": "oscillator_strength",
            "points": points,
        },
        "summary": {"absorption_peak_nm": absorption_peak_nm},
    }
    gain = {
        "schema_version": GAIN_SCHEMA_VERSION,
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
        "input_checksums": input_checksums,
        "laser_metrics": {
            "gain_factor": gain_factor,
            "gain_unit": str(gain_payload.get("gain_unit") or "cm2_s"),
        },
    }
    result_summary = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "parser": {"name": PARSER_NAME, "version": PARSER_VERSION},
        "molecule": {
            "smiles": run.molecule.smiles,
            "name": run.molecule.name,
            "formula": run.molecule.formula,
        },
        "method": run.parameters.method,
        "spectra": {
            "absorption_peak_nm": absorption_peak_nm,
            "point_count": len(points),
        },
        "laser_metrics": gain["laser_metrics"],
        "input_checksums": input_checksums,
        "output_schemas": [SPECTRUM_SCHEMA_VERSION, GAIN_SCHEMA_VERSION],
    }
    return ChemosLaserParsedOutputs(
        spectrum=spectrum,
        gain=gain,
        result_summary=result_summary,
        input_checksums=input_checksums,
    )


def build_fixture_raw_outputs(run: ComputationRun, workdir: Path) -> tuple[Path, Path]:
    """Create deterministic fixture raw outputs for offline parser validation."""
    digest = int(hashlib.sha256(run.molecule.smiles.encode("utf-8")).hexdigest()[:10], 16)
    center_nm = 380 + digest % 180
    width = 42 + digest % 18
    amplitude = 0.45 + (digest % 35) / 100
    spectra_path = workdir / "spectra.raw.csv"
    with spectra_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["wavelength_nm", "oscillator_strength"])
        writer.writeheader()
        for wavelength in range(300, 701, 20):
            y = amplitude * math.exp(-((wavelength - center_nm) ** 2) / (2 * width**2))
            writer.writerow({"wavelength_nm": wavelength, "oscillator_strength": f"{y:.8f}"})

    gain_path = workdir / "gain.raw.json"
    gain_factor = float((digest % 900) + 100) * 1e-18
    gain_path.write_text(
        json.dumps(
            {
                "gain_factor": gain_factor,
                "gain_unit": "cm2_s",
                "source": "deterministic_fixture",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return spectra_path, gain_path


def write_json(path: Path, payload: dict) -> None:
    """Write stable JSON."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def sha256_file(path: Path) -> str:
    """Compute file SHA256."""
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_spectrum_points(path: Path) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            x_raw = row.get("wavelength_nm") or row.get("x") or row.get("wavelength")
            y_raw = row.get("oscillator_strength") or row.get("y") or row.get("intensity")
            if x_raw is None or y_raw is None:
                continue
            try:
                points.append({"x": float(x_raw), "y": float(y_raw)})
            except ValueError:
                continue
    if not points:
        raise ValueError("spectra raw output 不包含可解析光谱点")
    return points


def _read_gain_factor(path: Path) -> tuple[float, dict]:
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {}
    raw_value = payload.get("gain_factor") if isinstance(payload, dict) else None
    if not isinstance(raw_value, (int, float)):
        match = re.search(r"gain_factor\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?)", text, re.IGNORECASE)
        raw_value = float(match.group(1)) if match else None
    if not isinstance(raw_value, (int, float)):
        raise ValueError("gain raw output 不包含 gain_factor")
    return float(raw_value), payload if isinstance(payload, dict) else {}


def _peak_x(points: list[dict[str, float]]) -> float:
    peak = max(points, key=lambda item: item["y"])
    return float(peak["x"])
