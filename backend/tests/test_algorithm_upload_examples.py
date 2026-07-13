from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_example_module():
    project_root = Path(__file__).resolve().parents[2]
    script_path = project_root / "examples" / "algorithm_upload" / "polymer_tg_knn_upload_test.py"
    spec = importlib.util.spec_from_file_location("polymer_tg_knn_upload_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_polymer_tg_knn_upload_test_predicts_required_output_fields():
    module = _load_example_module()
    model = module.load({})

    result = module.predict({"smiles": "C=C(F)F", "temperature_c": 25}, {}, model)

    assert set(result) == {"prediction", "feature_summary"}
    assert result["prediction"]["property"] == "glass_transition_temperature"
    assert isinstance(result["prediction"]["tg_c"], float)
    assert result["prediction"]["neighbor_count"] == 3
    assert result["feature_summary"]["fluorine_count"] == 2


def test_polymer_tg_knn_upload_test_rejects_empty_smiles():
    module = _load_example_module()

    try:
        module.predict({"smiles": "   "}, {}, module.load({}))
    except ValueError as exc:
        assert str(exc) == "smiles is required"
    else:
        raise AssertionError("empty smiles should raise ValueError")
