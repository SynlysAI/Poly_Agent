"""PolyAgent 远程接口配置 Demo 服务（教学用玩具 Tg 预测）。

用于配合“垂类模型（接口配置）”向导完成端到端联调：
打开接口配置页 → 一键填入示例场景 → 确认 endpoint → 保存 → 样例测试。

启动方式（使用项目 poly_agent conda 环境或任意含 fastapi/uvicorn 的环境）：
    cd examples/interface_config/demo_service
    pip install -r requirements.txt
    uvicorn app:app --host 127.0.0.1 --port 8301

可选鉴权（配合“带鉴权的接口接入”示例场景）：
    DEMO_API_TOKEN=demo-secret uvicorn app:app --host 127.0.0.1 --port 8301

注意：生产环境要求 HTTPS；本地 127.0.0.1 联调需要后端开发环境允许访问私网地址
（配置项 REMOTE_INTERFACE_ALLOW_PRIVATE_NETWORK=true）。
"""

from __future__ import annotations

import os
import re

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

SERVICE_NAME = "polyagent_interface_demo"
SERVICE_VERSION = "1.0.0"

app = FastAPI(title="PolyAgent 远程接口配置 Demo 服务", version=SERVICE_VERSION)


def _token_required(authorization: str | None) -> None:
    """设置了 DEMO_API_TOKEN 时校验 Bearer 鉴权，演示“密钥引用”场景。"""
    expected = os.environ.get("DEMO_API_TOKEN", "").strip()
    if not expected:
        return
    if not authorization or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


def _predict_tg(smiles: str) -> float:
    """玩具规则：重原子数越多 Tg 越高，双键/三键越多 Tg 越低。仅用于教学演示。"""
    heavy_atoms = len(re.findall(r"[A-Z][a-z]?", smiles))
    unsaturated_bonds = len(re.findall(r"[=\#]", smiles))
    return round(100.0 + 8.0 * heavy_atoms - 5.0 * unsaturated_bonds, 2)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "service": SERVICE_NAME, "version": SERVICE_VERSION}


class PredictRequest(BaseModel):
    smiles: str = Field(min_length=1)


@app.post("/predict")
def predict_post(
    payload: PredictRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _token_required(authorization)
    return {"data": {"prediction": _predict_tg(payload.smiles), "smiles": payload.smiles}}


@app.get("/predict")
def predict_get(
    smiles: str = Query(min_length=1),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    _token_required(authorization)
    return {"data": {"prediction": _predict_tg(smiles), "smiles": smiles}}
