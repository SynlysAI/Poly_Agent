"""V1 路由聚合模块。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.alchemist_proxy import router as alchemist_router
from app.api.v1.endpoints.llm import router as llm_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(alchemist_router, prefix="/alchemist")
api_router.include_router(llm_router, prefix="/llm")
