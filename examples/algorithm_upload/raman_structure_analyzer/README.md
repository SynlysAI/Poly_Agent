# Raman Structure Analyzer

This is a PolyAgent uploaded-algorithm demo for generic file I/O.

The platform treats the uploaded spectrum as a generic `series` input parsed by `series_xy.v1`. Raman-specific behavior lives only in this package.

## Package Layout

```text
polyagent.algorithm.yaml
requirements.txt
src/handler.py
src/raman_core/
tests/sample_input.json
tests/sample_assets/sample_spectrum.dat
README.md
```

## Runtime Requirements

The runtime environment must already provide `torch`, `rdkit`, `transformers`, `numpy`, `pandas`, and `scipy`.

The model resources are not stored in the ZIP. Register the mounted server paths in PolyAgent resource management, or use these environment variables as a compatibility fallback:

- `RAMAN_CHECKPOINTS_ROOT`
- `RAMAN_DATABASE_ROOT`
- `RAMAN_TOKENIZER_ROOT`

When the resources live outside the default `.runtime/algorithm-resources` root, include their parent directory in `POLYAGENT_ALGORITHM_RESOURCE_ROOTS`, for example:

```bash
export POLYAGENT_ALGORITHM_RESOURCE_ROOTS=/home/fangyikai/github_project/Spec_Agent/backend/resources
```

Validation fails if any required binding, path, or declared resource file is missing.

## Inputs

JSON parameters:

- `spectype`: `raman` or `ir`
- `mode`: `beam_search`, `retrieval`, `function_groups`, or `greedy_decode`
- `x0`, `x1`: optional spectral x-axis bounds
- `k`: candidate count
- `transmittance`: IR transmittance flag
- `device`: `cpu` or `cuda`

File parameter:

- `spectrum_file`: `.txt`, `.dat`, `.csv`, or `.xlsx` x-y series data

## Outputs

The handler returns `polyagent_run_result.v1` with:

- `output_summary.candidates`
- `normalized_series.json`
- `structure_candidates.json`
- `candidates.csv`
- `report.json`
