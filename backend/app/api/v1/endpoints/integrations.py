"""外部集成状态 API。"""

from __future__ import annotations

import shutil
from datetime import datetime

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.common import ApiResponse


router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/status", response_model=ApiResponse[dict])
def get_integration_status() -> ApiResponse[dict]:
    """查询 MVP 集成状态。"""
    checked_at = datetime.utcnow().isoformat()
    services = [
        {
            "service": "computation-worker",
            "status": "up",
            "checked_at": checked_at,
            "details": {
                "worker_id": "worker-local-mock",
                "capabilities": ["MOCK_XTB_ONLY", "MOCK_LASER"],
            },
        },
        {
            "service": "artifact-store",
            "status": "up" if settings.outputs_root.exists() else "down",
            "checked_at": checked_at,
            "details": {"root": str(settings.outputs_root)},
        },
        {
            "service": "chemos-demo",
            "status": "available" if (settings.project_root / "scripts" / "run_chemos.sh").exists() else "not_configured",
            "checked_at": checked_at,
            "details": {"command": "scripts/run_chemos.sh check"},
        },
        {
            "service": "aiida",
            "status": "not_configured",
            "checked_at": checked_at,
            "details": {"reason": "MVP 使用 mock/local adapter，AiiDA 为后续阶段接入"},
        },
        {
            "service": "speclabos",
            "status": "not_configured",
            "checked_at": checked_at,
            "details": {"reason": "MVP 仅保留 workflow run 集成边界"},
        },
        {
            "service": "docker",
            "status": "available" if shutil.which("docker") else "not_available",
            "checked_at": checked_at,
            "details": {},
        },
    ]
    return ApiResponse(code=0, message="ok", data={"items": services})
