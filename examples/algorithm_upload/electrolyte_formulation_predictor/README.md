# Electrolyte Formulation Predictor

This is a Poly Agent standard algorithm package for `electrolyte_formulation_predictor`.

The platform entrypoint is `src.handler:predict`, with optional loader `src.handler:load`.
The handler accepts:

```json
{
  "formulations": [
    {
      "formula_id": "TEST-001",
      "task_type": "electrolyte",
      "lithium_salt": "LiTFSI",
      "lithium_salt_mol_L": 1.0,
      "electrolyte_component_1": "FEC",
      "electrolyte_component_1_mol_ratio": 1,
      "electrolyte_component_2": "DME",
      "electrolyte_component_2_mol_ratio": 1
    }
  ]
}
```

and returns:

```json
{
  "results": [
    {
      "formula_id": "TEST-001",
      "task_type": "electrolyte",
      "predictions": {
        "DSC_1": 78.3,
        "DSC_4": 71.78,
        "DSC_20": 70.66,
        "coulombic_efficiency_1": 0.558,
        "coulombic_efficiency_4": 0.472,
        "coulombic_efficiency_20": 0.503
      },
      "model_name": "extra_trees"
    }
  ]
}
```

The included `model/model.pkl` is a small calibration artifact so the package is runnable in this repository.
Replace it with the real ExtraTrees `model.pkl` and update `src/predictor_service.py` feature construction when deploying the production model.
