# Raman Structure Analyzer Algorithm Package Guide

This document describes the Raman demo package used to verify PolyAgent's generic uploaded-algorithm file I/O flow.

## Purpose

The package is a business demo, not a platform-specific code path. PolyAgent sees only generic assets:

- JSON parameters through `input_schema`
- A file input declared as `data_kind: series`
- Managed model resources declared through `resource_assets`
- JSON and file outputs declared through `output_assets`

Raman-specific inference stays inside `examples/algorithm_upload/raman_structure_analyzer/src/`.

## Package

Source directory:

```text
examples/algorithm_upload/raman_structure_analyzer/
```

ZIP file:

```text
examples/algorithm_upload/raman_structure_analyzer-0.1.0.zip
```

Expected ZIP contents:

```text
polyagent.algorithm.yaml
requirements.txt
README.md
src/handler.py
src/raman_core/
tests/sample_input.json
tests/sample_assets/sample_spectrum.dat
```

## Inputs

JSON input fields:

- `spectype`: `raman` or `ir`
- `mode`: `beam_search`, `retrieval`, `function_groups`, or `greedy_decode`
- `x0`, `x1`: optional spectral range
- `k`: candidate count
- `transmittance`: IR transmittance flag
- `device`: `cpu` or `cuda`

File input:

- `spectrum_file`
- Generic declaration: `data_kind: series`, `parser: series_xy.v1`
- Supported files: `.txt`, `.dat`, `.csv`, `.xlsx`

## Managed Resources

Large files are not included in the ZIP. Register the server or mounted paths in PolyAgent resource management first. The backend process must be able to access the path locally; for example a remote server path on `10.25.15.93` must be mounted or otherwise visible to the PolyAgent backend host before registration.

Recommended allowed root:

```bash
export POLYAGENT_ALGORITHM_RESOURCE_ROOTS=/home/fangyikai/github_project/Spec_Agent/backend/resources
```

Example registration payloads:

```json
{
  "algorithm_id": "raman_structure_analyzer",
  "asset_key": "raman_checkpoints",
  "name": "Raman checkpoints",
  "path": "/home/fangyikai/github_project/Spec_Agent/backend/resources/raman/checkpoints",
  "resource_type": "checkpoints",
  "required_files": ["baseline_removal.pth", "raman_generation.pth"]
}
```

```json
{
  "algorithm_id": "raman_structure_analyzer",
  "asset_key": "raman_database",
  "name": "Raman database",
  "path": "/home/fangyikai/github_project/Spec_Agent/backend/resources/raman/database",
  "resource_type": "database",
  "required_files": ["raman_db.pkl"]
}
```

`RAMAN_CHECKPOINTS_ROOT`, `RAMAN_DATABASE_ROOT`, and `RAMAN_TOKENIZER_ROOT` remain supported as fallback bindings for older packages.

The runtime must already provide `torch`, `rdkit`, `transformers`, `numpy`, `pandas`, and `scipy`.

Validation fails if a required resource binding is missing, the path does not exist, the path is outside allowed roots, or a declared required file is missing.

## Outputs

The handler returns `polyagent_run_result.v1`:

- `output_summary.candidates`
- `normalized_series.json` as `series_json`
- `structure_candidates.json` as `structure_json`
- `candidates.csv` as `csv`
- `report.json` as `report_json`

## Flow Test

1. Upload `raman_structure_analyzer-0.1.0.zip`.
2. Validate the package.
3. Build, deploy, and activate the version.
4. Open the vertical prediction test panel.
5. Fill JSON parameters.
6. Upload `sample_spectrum.dat` or another supported x-y file.
7. Run multipart prediction.
8. Check the output summary and artifact list.

The product UI should not contain Raman-specific branches. It should render this demo from the generic asset declarations.
