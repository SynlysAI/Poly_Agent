from __future__ import annotations

import csv
import json
from pathlib import Path


def load(context: dict):
    from .raman_core.resource_config import configure_from_context

    configure_from_context(context or {})
    return {"resources_ready": True}


def predict(inputs: dict, context: dict, model=None) -> dict:
    context = context or {}
    if model is None:
        model = load(context)
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("Raman demo requires torch in the runtime environment") from exc

    from .raman_core.main import main as run_raman

    points = _series_points(context, "spectrum_file")
    if not points:
        raise ValueError("spectrum_file did not contain x-y series data")
    x0 = float(inputs.get("x0") or points[0]["x"])
    x1 = float(inputs.get("x1") or points[-1]["x"])
    spectrum = [float(point["y"]) for point in points]
    spectype = str(inputs.get("spectype") or "raman")
    requested_mode = str(inputs.get("mode") or "function_groups")
    mode = "function_groups"
    if spectype != "raman":
        raise ValueError("This package only supports Raman functional group analysis.")
    k = int(inputs.get("k") or 3)
    transmittance = bool(inputs.get("transmittance") or False)
    device_name = str(inputs.get("device") or ("cuda" if torch.cuda.is_available() else "cpu"))
    device = torch.device(device_name)

    raw_output = run_raman(
        spectrum=spectrum,
        x0=x0,
        x1=x1,
        device=device,
        spectype=spectype,
        mode=mode,
        k=k,
        transmittance=transmittance,
    )
    candidates = _candidate_rows(raw_output)
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_series = {
        "schema_version": "polyagent_series.v1",
        "kind": "xy",
        "x_label": "Raman shift",
        "y_label": "Intensity",
        "points": points,
        "metadata": {"spectype": spectype, "mode": mode, "requested_mode": requested_mode, "x0": x0, "x1": x1},
    }
    (output_dir / "normalized_series.json").write_text(
        json.dumps(normalized_series, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    functional_group_result = {
        "schema_version": "polyagent_functional_groups.v1",
        "functional_groups": candidates,
        "metadata": {"spectype": spectype, "mode": mode, "requested_mode": requested_mode, "k": k},
    }
    (output_dir / "functional_groups.json").write_text(
        json.dumps(functional_group_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "functional_groups.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["rank", "functional_group"])
        writer.writeheader()
        writer.writerows(candidates)
    report = {
        "schema_version": "polyagent_algorithm_report.v1",
        "preprocessing": {"normalization": "platform parser + model preprocess_spectrum"},
        "model": {"spectype": spectype, "mode": mode, "requested_mode": requested_mode, "device": str(device)},
        "resource_status": model,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_summary": {
            "candidates": candidates,
            "point_count": len(points),
            "metadata": report["model"],
            "preprocessing": report["preprocessing"],
        },
        "artifacts": [
            {
                "key": "normalized_series",
                "path": "normalized_series.json",
                "artifact_type": "series_json",
                "mime_type": "application/json",
            },
            {
                "key": "functional_groups",
                "path": "functional_groups.json",
                "artifact_type": "result_json",
                "mime_type": "application/json",
            },
            {
                "key": "functional_group_table",
                "path": "functional_groups.csv",
                "artifact_type": "csv",
                "mime_type": "text/csv",
            },
            {
                "key": "run_report",
                "path": "report.json",
                "artifact_type": "report_json",
                "mime_type": "application/json",
            },
        ],
    }


def _series_points(context: dict, key: str) -> list[dict[str, float]]:
    parsed = (context.get("parsed_inputs") or {}).get(key) or {}
    data = parsed.get("data") or {}
    points = data.get("points") or []
    if points:
        return [{"x": float(point["x"]), "y": float(point["y"])} for point in points]
    path = Path((context.get("input_files") or {}).get(key, ""))
    if not path.is_file():
        return []
    parsed_points = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.replace(",", " ").replace(";", " ").split()
        if len(parts) < 2:
            continue
        try:
            parsed_points.append({"x": float(parts[0]), "y": float(parts[1])})
        except ValueError:
            continue
    return parsed_points


def _candidate_rows(raw_output) -> list[dict]:
    if isinstance(raw_output, list):
        return [
            {"rank": index + 1, "functional_group": str(function_group)}
            for index, function_group in enumerate(raw_output)
        ]
    structures = raw_output.get("structure") if isinstance(raw_output, dict) else []
    rows = []
    for index, structure in enumerate(structures or []):
        rows.append({"rank": index + 1, "functional_group": str(structure)})
    return rows
