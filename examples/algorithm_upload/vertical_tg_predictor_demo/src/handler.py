from __future__ import annotations

from sklearn.ensemble import RandomForestRegressor


def _features(smiles: str) -> list[float]:
    length = len(smiles)
    carbon_count = smiles.count("C")
    fluorine_count = smiles.count("F")
    oxygen_count = smiles.count("O")
    nitrogen_count = smiles.count("N")
    double_bonds = smiles.count("=")
    ring_marks = sum(ch.isdigit() for ch in smiles)
    fluorine_ratio = fluorine_count / max(length, 1)
    return [
        length,
        carbon_count,
        fluorine_count,
        oxygen_count,
        nitrogen_count,
        double_bonds,
        ring_marks,
        fluorine_ratio,
    ]


def load(context: dict):
    samples = ["CCO", "C=C(F)F", "FC(F)=C(F)F", "CC(C)(F)F", "C1=CC=CC=C1"]
    targets = [68.0, 102.0, 118.0, 96.0, 82.0]
    model = RandomForestRegressor(n_estimators=24, random_state=7)
    model.fit([_features(smiles) for smiles in samples], targets)
    return model


def predict(inputs: dict, context: dict, model=None) -> dict:
    smiles = str(inputs.get("smiles", "")).strip()
    if not smiles:
        raise ValueError("smiles is required")
    if model is None:
        model = load(context)
    features = _features(smiles)
    tg_c = float(model.predict([features])[0])
    return {
        "prediction": {
            "property": "glass_transition_temperature",
            "tg_c": round(tg_c, 2),
            "uncertainty": 8.5,
            "model_version": "demo-rf-0.1.0",
        },
        "feature_summary": {
            "length": features[0],
            "carbon_count": features[1],
            "fluorine_count": features[2],
            "fluorine_ratio": round(features[7], 4),
        },
    }
