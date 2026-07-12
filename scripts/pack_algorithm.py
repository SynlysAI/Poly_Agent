#!/usr/bin/env python3
"""Pack a Python algorithm directory into a Poly Agent algorithm ZIP."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Poly Agent algorithm package ZIP.")
    parser.add_argument("--algorithm-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--entrypoint", required=True, help="Python callable in module:function format")
    parser.add_argument("--loader", default=None, help="Optional loader callable in module:function format")
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--requirements", type=Path, default=None)
    parser.add_argument("--sample-input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--algorithm-family", default="vertical_prediction")
    parser.add_argument("--type", default="predictor")
    parser.add_argument("--material-scope", default='["universal"]')
    parser.add_argument("--task-scope", default='["COMPUTE_PREDICT"]')
    parser.add_argument("--trigger-modes", default='["human_workflow","autoresearch"]')
    parser.add_argument("--input-schema", default='{"fields":{"smiles":"string"},"required":["smiles"]}')
    parser.add_argument("--output-schema", default='{"fields":{"prediction":"object"},"required":["prediction"]}')
    return parser.parse_args()


def load_json_arg(value: str, label: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} must be valid JSON: {exc}") from exc


def assert_callable_ref(value: str | None, label: str) -> None:
    if value and ":" not in value:
        raise SystemExit(f"{label} must use module:function format")


def iter_source_files(source_dir: Path):
    forbidden_parts = {".git", "__pycache__", ".venv", "venv", "node_modules"}
    reserved = {"polyagent.algorithm.yaml", "requirements.txt", "tests/sample_input.json"}
    for path in source_dir.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(source_dir)
        if set(rel.parts) & forbidden_parts:
            continue
        archive_name = str(rel).replace("\\", "/")
        if archive_name in reserved:
            continue
        yield path, rel


def main() -> int:
    args = parse_args()
    if not args.source_dir.is_dir():
        raise SystemExit(f"source dir does not exist: {args.source_dir}")
    if not args.sample_input.is_file():
        raise SystemExit(f"sample input does not exist: {args.sample_input}")
    if args.requirements and not args.requirements.is_file():
        raise SystemExit(f"requirements file does not exist: {args.requirements}")
    assert_callable_ref(args.entrypoint, "--entrypoint")
    assert_callable_ref(args.loader, "--loader")

    sample_input = json.loads(args.sample_input.read_text(encoding="utf-8"))
    contract = {
        "contract_version": "0.1",
        "algorithm_id": args.algorithm_id,
        "name": args.name,
        "version": args.version,
        "algorithm_family": args.algorithm_family,
        "type": args.type,
        "material_scope": load_json_arg(args.material_scope, "--material-scope"),
        "task_scope": load_json_arg(args.task_scope, "--task-scope"),
        "trigger_modes": load_json_arg(args.trigger_modes, "--trigger-modes"),
        "entrypoint": args.entrypoint,
        "loader": args.loader,
        "runtime": {
            "python": "3.11",
            "resources": {"cpu": 1, "memory": "1Gi", "gpu": False},
            "timeout_seconds": 30,
        },
        "input_schema": load_json_arg(args.input_schema, "--input-schema"),
        "output_schema": load_json_arg(args.output_schema, "--output-schema"),
        "sample_input_path": "tests/sample_input.json",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("polyagent.algorithm.yaml", yaml.safe_dump(contract, allow_unicode=True, sort_keys=False))
        zf.writestr("tests/sample_input.json", json.dumps(sample_input, ensure_ascii=False, indent=2))
        if args.requirements:
            zf.writestr("requirements.txt", args.requirements.read_bytes())
        else:
            zf.writestr("requirements.txt", "")
        for path, rel in iter_source_files(args.source_dir):
            archive_name = str(rel).replace("\\", "/")
            zf.write(path, archive_name)

    print(f"Created {args.output}")
    print("Upload it in Poly Agent: ResearchEngine -> Algorithm Registry -> Upload Algorithm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
