from __future__ import annotations

from math import sqrt
from typing import Any


def _features(smiles: str, temperature_c: float) -> list[float]:
    length = len(smiles)
    if length == 0:
        raise ValueError("smiles is required")

    carbon_count = smiles.count("C")
    fluorine_count = smiles.count("F")
    oxygen_count = smiles.count("O")
    nitrogen_count = smiles.count("N")
    double_bonds = smiles.count("=")
    ring_marks = sum(ch.isdigit() for ch in smiles)
    branches = smiles.count("(") + smiles.count(")")
    halogen_count = fluorine_count + smiles.count("Cl") + smiles.count("Br")

    return [
        float(length),
        float(carbon_count),
        float(fluorine_count),
        float(oxygen_count),
        float(nitrogen_count),
        float(double_bonds),
        float(ring_marks),
        float(branches),
        float(halogen_count) / max(length, 1),
        float(temperature_c),
    ]


def _distance(left: list[float], right: list[float]) -> float:
    return sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def load(context: dict[str, Any]) -> dict[str, Any]:
    samples = [
        {"smiles": "CCO", "temperature_c": 25.0, "tg_c": 68.0},
        {"smiles": "C=C(F)F", "temperature_c": 25.0, "tg_c": 102.0},
        {"smiles": "FC(F)=C(F)F", "temperature_c": 25.0, "tg_c": 118.0},
        {"smiles": "CC(C)(F)F", "temperature_c": 25.0, "tg_c": 96.0},
        {"smiles": "C1=CC=CC=C1", "temperature_c": 25.0, "tg_c": 82.0},
        {"smiles": "CCN", "temperature_c": 25.0, "tg_c": 63.0},
    ]
    training_rows = [
        {
            "smiles": row["smiles"],
            "features": _features(str(row["smiles"]), float(row["temperature_c"])),
            "tg_c": float(row["tg_c"]),
        }
        for row in samples
    ]
    return {"algorithm": "pure_python_knn_tg_demo", "k": 3, "training_rows": training_rows}


def predict(inputs: dict[str, Any], context: dict[str, Any], model: dict[str, Any] | None = None) -> dict[str, Any]:
    smiles = str(inputs.get("smiles", "")).strip()
    if not smiles:
        raise ValueError("smiles is required")

    temperature_c = float(inputs.get("temperature_c", 25.0))
    if model is None:
        model = load(context)

    features = _features(smiles, temperature_c)
    distances = [
        (_distance(features, row["features"]), row["tg_c"], row["smiles"])
        for row in model["training_rows"]
    ]
    neighbors = sorted(distances, key=lambda item: item[0])[: int(model["k"])]

    weighted_total = 0.0
    weight_sum = 0.0
    for distance, target, _neighbor_smiles in neighbors:
        weight = 1.0 / (distance + 1.0)
        weighted_total += target * weight
        weight_sum += weight

    tg_c = weighted_total / weight_sum
    return {
        "prediction": {
            "property": "glass_transition_temperature",
            "tg_c": round(tg_c, 2),
            "unit": "C",
            "model_version": "pure-python-knn-0.1.0",
            "neighbor_count": len(neighbors),
            "nearest_training_smiles": [item[2] for item in neighbors],
        },
        "feature_summary": {
            "length": int(features[0]),
            "carbon_count": int(features[1]),
            "fluorine_count": int(features[2]),
            "double_bonds": int(features[5]),
            "halogen_ratio": round(features[8], 4),
            "temperature_c": temperature_c,
        },
    }
