"""V1 路由聚合模块。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.assistant import router as assistant_router
from app.api.v1.endpoints.attributions import router as attributions_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.capabilities import router as capabilities_router
from app.api.v1.endpoints.computations import router as computations_router
from app.api.v1.endpoints.data_catalog import router as data_catalog_router
from app.api.v1.endpoints.experiment_dispatch import router as experiment_dispatch_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.integrations import router as integrations_router
from app.api.v1.endpoints.knowledge import router as knowledge_router
from app.api.v1.endpoints.optimization import router as optimization_router
from app.api.v1.endpoints.alchemist import router as alchemist_router
from app.api.v1.endpoints.llm import router as llm_router
from app.api.v1.endpoints.reports import router as reports_router
from app.api.v1.endpoints.research_engine import router as research_engine_router
from app.api.v1.endpoints.tasks import router as tasks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(capabilities_router)
api_router.include_router(attributions_router)
api_router.include_router(admin_router)
api_router.include_router(computations_router)
api_router.include_router(data_catalog_router)
api_router.include_router(experiment_dispatch_router)
api_router.include_router(optimization_router)
api_router.include_router(integrations_router)
api_router.include_router(knowledge_router)
api_router.include_router(alchemist_router, prefix="/alchemist")
api_router.include_router(llm_router, prefix="/llm")
api_router.include_router(assistant_router)
api_router.include_router(research_engine_router)
api_router.include_router(reports_router)
api_router.include_router(tasks_router)
