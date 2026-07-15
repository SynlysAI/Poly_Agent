from __future__ import annotations

from typing import Any

from src.predictor_service import load_model, predict_records


def load(context: dict[str, Any]) -> dict[str, Any]:
    return load_model(context)


def predict(inputs: dict[str, Any], context: dict[str, Any], model: dict[str, Any] | None = None) -> dict[str, Any]:
    formulations = inputs.get("formulations")
    if formulations is None:
        raise ValueError("formulations is required")
    if model is None:
        model = load(context)
    return {"results": predict_records(formulations, model=model)}
