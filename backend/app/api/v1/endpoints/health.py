"""健康检查接口。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from app.core.config import settings
from app.infra.mongo import get_mongo_client
from app.infra.sqlite_store import demo_store
from app.schemas.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict])
def health_check() -> ApiResponse[dict]:
    """服务健康检查接口。"""
    if settings.uses_mongodb:
        mongodb_status = "down"
        try:
            get_mongo_client().admin.command("ping")
            mongodb_status = "up"
        except Exception:
            mongodb_status = "down"
        sqlite_status = "not_configured"
    else:
        mongodb_status = "not_configured"
        sqlite_status = "up" if demo_store.ping() else "down"

    payload = {
        "api": "up",
        "storage_backend": settings.storage_backend,
        "mongodb": mongodb_status,
        "sqlite": sqlite_status,
        "time": datetime.now().isoformat(),
    }
    return ApiResponse(code=0, message="ok", data=payload)
