"""健康检查接口。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from app.infra.mongo import get_mongo_client
from app.schemas.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict])
def health_check() -> ApiResponse[dict]:
    """服务健康检查接口。"""
    mongodb_status = "down"
    try:
        get_mongo_client().admin.command("ping")
        mongodb_status = "up"
    except Exception:
        mongodb_status = "down"

    payload = {
        "api": "up",
        "mongodb": mongodb_status,
        "time": datetime.now().isoformat(),
    }
    return ApiResponse(code=0, message="ok", data=payload)
