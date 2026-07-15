from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from src.predictor_service import load_model, predict_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict fluorinated electrolyte formulation properties.")
    parser.add_argument("--input", required=True, type=Path, help="Input CSV containing formulation records")
    parser.add_argument("--output", required=True, type=Path, help="Output CSV for predictions")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = _read_csv(args.input)
    model = load_model({"package_path": str(Path(__file__).resolve().parents[1])})
    results = predict_records(records, model=model)
    _write_csv(args.output, results)
    return 0


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "formula_id",
        "task_type",
        "model_name",
        "DSC_1",
        "DSC_4",
        "DSC_20",
        "coulombic_efficiency_1",
        "coulombic_efficiency_4",
        "coulombic_efficiency_20",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            row = {
                "formula_id": result["formula_id"],
                "task_type": result["task_type"],
                "model_name": result["model_name"],
                **result["predictions"],
            }
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
