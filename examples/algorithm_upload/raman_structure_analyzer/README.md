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

The model resources are not stored in the ZIP. The package first uses an optional managed resource binding, then `RAMAN_RESOURCES_ROOT`, then the service default path `/home/fangyikai/github_project/Spec_Agent/backend/resources/raman`. If you register a mounted resource in PolyAgent resource management, the registered path must be the Raman resource parent directory, not the `checkpoints` subdirectory:

- `algorithm_id`: `raman_structure_analyzer`
- `asset_key`: `raman_runtime_resources`
- `path`: `/home/fangyikai/github_project/Spec_Agent/backend/resources/raman`
- `resource_type`: `raman_runtime`
- `required_files`: `checkpoints/baseline_removal.pth`, `checkpoints/raman_generation.pth`, `moltokenizer/vocab.json`

`path` is local to the machine running the PolyAgent backend service. In the test environment, register the path on `10.26.15.93`; in production, when the backend runs on `localhost`, register the same Raman resource parent directory on the production host.

When the resources live outside the default `.runtime/algorithm-resources` root, include their parent directory in `POLYAGENT_ALGORITHM_RESOURCE_ROOTS`, for example:

```bash
export POLYAGENT_ALGORITHM_RESOURCE_ROOTS=/home/fangyikai/github_project/Spec_Agent/backend/resources
```

`RAMAN_RESOURCES_ROOT` can be used as an environment-variable fallback. Managed resource binding is optional for this service-mounted package. The package prefers `moltokenizer/vocab.json` and also accepts legacy `tokenizer/vocab.json`. `retrieval` mode also needs `database/raman_db.pkl`. Validation fails if any required service file is missing.

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
