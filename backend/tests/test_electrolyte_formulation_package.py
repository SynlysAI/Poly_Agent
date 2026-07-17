from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = PROJECT_ROOT / "examples" / "algorithm_upload" / "electrolyte_formulation_predictor"
PACKAGE_ZIP = PROJECT_ROOT / "examples" / "algorithm_upload" / "electrolyte_formulation_predictor-0.1.0.zip"


def _load_handler_module():
    script_path = PACKAGE_DIR / "src" / "handler.py"
    package_root = str(PACKAGE_DIR)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    spec = importlib.util.spec_from_file_location("electrolyte_formulation_handler", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_electrolyte_formulation_package_has_standard_upload_files():
    expected = {
        "polyagent.algorithm.yaml",
        "requirements.txt",
        "src/handler.py",
        "src/predictor_service.py",
        "src/predict.py",
        "model/model.pkl",
        "tests/sample_input.json",
        "README.md",
    }

    missing = [path for path in sorted(expected) if not (PACKAGE_DIR / path).is_file()]

    assert missing == []


def test_electrolyte_formulation_package_zip_matches_source_package():
    assert PACKAGE_ZIP.is_file()

    with zipfile.ZipFile(PACKAGE_ZIP) as zf:
        names = set(zf.namelist())
        expected = {
            "polyagent.algorithm.yaml",
            "requirements.txt",
            "README.md",
            "src/handler.py",
            "src/predictor_service.py",
            "src/predict.py",
            "model/model.pkl",
            "tests/sample_input.json",
        }
        assert expected.issubset(names)

        contract = yaml.safe_load(zf.read("polyagent.algorithm.yaml").decode("utf-8"))
        assert contract["algorithm_id"] == "electrolyte_formulation_predictor"
        assert contract["entrypoint"] == "src.handler:predict"
        assert contract["loader"] == "src.handler:load"
        assert contract["description"] == (
            "根据锂盐、溶剂/单体/填料组成及配比，预测第 1、4、20 周期放电比容量和库仑效率。"
        )

        zip_sample_input = json.loads(zf.read("tests/sample_input.json").decode("utf-8"))
        dir_sample_input = json.loads((PACKAGE_DIR / "tests" / "sample_input.json").read_text(encoding="utf-8"))
        assert zip_sample_input == dir_sample_input


def test_electrolyte_formulation_handler_returns_six_prediction_targets():
    handler = _load_handler_module()
    sample_input = json.loads((PACKAGE_DIR / "tests" / "sample_input.json").read_text(encoding="utf-8"))
    model = handler.load({"package_path": str(PACKAGE_DIR)})

    result = handler.predict(sample_input, {"package_path": str(PACKAGE_DIR)}, model)

    assert set(result) == {"results"}
    assert len(result["results"]) == 1
    first = result["results"][0]
    assert first["formula_id"] == "TEST-001"
    assert first["task_type"] == "electrolyte"
    assert first["model_name"] == "extra_trees"
    assert set(first["predictions"]) == {
        "DSC_1",
        "DSC_4",
        "DSC_20",
        "coulombic_efficiency_1",
        "coulombic_efficiency_4",
        "coulombic_efficiency_20",
    }
    assert all(isinstance(value, float) for value in first["predictions"].values())


def test_electrolyte_formulation_handler_rejects_missing_formulations():
    handler = _load_handler_module()

    try:
        handler.predict({}, {"package_path": str(PACKAGE_DIR)}, handler.load({"package_path": str(PACKAGE_DIR)}))
    except ValueError as exc:
        assert str(exc) == "formulations is required"
    else:
        raise AssertionError("missing formulations should raise ValueError")


def test_electrolyte_formulation_handler_rejects_incomplete_records():
    handler = _load_handler_module()

    try:
        handler.predict(
            {"formulations": [{"formula_id": "BAD-001", "task_type": "electrolyte"}]},
            {"package_path": str(PACKAGE_DIR)},
            handler.load({"package_path": str(PACKAGE_DIR)}),
        )
    except ValueError as exc:
        assert "lithium_salt" in str(exc)
    else:
        raise AssertionError("incomplete formulation should raise ValueError")
