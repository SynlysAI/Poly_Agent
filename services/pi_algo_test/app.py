"""PI 合成难度评分 Mock 接口服务（真实 HTTP 接口 + 轻量确定性算法）。

启动（使用项目 poly_agent conda 环境）：
    cd services/pi_algo_test
    conda run -n poly_agent uvicorn app:app --host 127.0.0.1 --port 8300

接口：
    GET  /healthz   健康检查
    POST /predict   评分预测，请求体见 sample_input.json
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from mock_scoring import score

SERVICE_NAME = "pi_synthesis_mock"
SERVICE_VERSION = "1.0.0"


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    diamine: str = Field(min_length=1)
    dianhydride: str = Field(min_length=1)
    solvent: str = Field(min_length=1)
    diamine_structure: str | None = None
    dianhydride_structure: str | None = None
    diamine_solubility: int | float | None = Field(default=None, ge=0, le=5)
    dianhydride_solubility: int | float | None = Field(default=None, ge=0, le=5)
    water_content_status: str | None = None
    inert_atmosphere_status: bool | None = None
    historical_similar_experiment: str | None = None


app = FastAPI(title="PI 合成难度评分 Mock 接口", version=SERVICE_VERSION)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "rules": "PI_synthesis_difficulty_scoring_rules_v1.0.json",
    }


@app.post("/predict")
def predict(payload: PredictRequest) -> dict[str, Any]:
    try:
        return score(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
