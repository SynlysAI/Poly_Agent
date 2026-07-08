"""AutoResearch startup readiness checks."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.research_engine import ResearchEngineReadinessData, ResearchEngineReadinessItem
from app.services.integration_status_service import IntegrationStatusService


class ResearchEngineReadinessService:
    """Build a product-facing readiness summary for AutoResearch."""

    def get_readiness(self) -> ResearchEngineReadinessData:
        checked_at = datetime.now(timezone.utc)
        integration_items = IntegrationStatusService().get_status().get("items", [])
        by_service = {str(item.get("service")): item for item in integration_items}

        items = [
            self._rag_readiness(),
            self._integration_readiness(
                by_service.get("computation-worker"),
                service="computation-engine",
                label="计算引擎",
                required=True,
                up_statuses={"up", "available"},
                unavailable_message="计算 Worker 不可用，AutoResearch 无法提交计算任务。",
            ),
            self._integration_readiness(
                by_service.get("alchemist-backend"),
                service="alchemist-backend",
                label="BO/Alchemist",
                required=False,
                demo_fallback=True,
                up_statuses={"up", "available"},
                unavailable_message="Alchemist 未连接，候选推荐将使用 demo fallback。",
            ),
            self._integration_readiness(
                by_service.get("artifact-store"),
                service="artifact-store",
                label="Artifact Store",
                required=True,
                up_statuses={"up", "available"},
                unavailable_message="Artifact Store 不可用，运行产物无法保存。",
            ),
        ]
        can_start = all(not item.blocking for item in items)
        return ResearchEngineReadinessData(
            ready=all(item.status == "ready" for item in items),
            can_start=can_start,
            checked_at=checked_at,
            items=items,
        )

    def _integration_readiness(
        self,
        raw: dict[str, Any] | None,
        *,
        service: str,
        label: str,
        required: bool,
        up_statuses: set[str],
        unavailable_message: str,
        demo_fallback: bool = False,
    ) -> ResearchEngineReadinessItem:
        raw_status = str((raw or {}).get("status") or "unknown")
        is_ready = raw_status in up_statuses
        status = "ready" if is_ready else ("warning" if demo_fallback else "unavailable")
        return ResearchEngineReadinessItem(
            service=service,
            label=label,
            status=status,
            required=required,
            blocking=required and not is_ready,
            demo_fallback=demo_fallback and not is_ready,
            message="可用" if is_ready else unavailable_message,
            details={
                "integration_status": raw_status,
                **dict((raw or {}).get("details") or {}),
            },
        )

    def _rag_readiness(self) -> ResearchEngineReadinessItem:
        index_path = Path(
            os.getenv(
                "RESEARCH_ENGINE_RAG_INDEX",
                str(settings.runtime_root / "rag" / "literature_index.json"),
            )
        )
        details: dict[str, Any] = {"index_path": str(index_path)}
        if not index_path.exists():
            return ResearchEngineReadinessItem(
                service="literature-rag",
                label="文献 RAG",
                status="warning",
                required=False,
                blocking=False,
                demo_fallback=True,
                message="本地文献索引未配置，文献检索将使用 demo fallback。",
                details=details,
            )

        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return ResearchEngineReadinessItem(
                service="literature-rag",
                label="文献 RAG",
                status="warning",
                required=False,
                blocking=False,
                demo_fallback=True,
                message="本地文献索引无法读取，文献检索将使用 demo fallback。",
                details={**details, "error": str(exc)},
            )

        documents = raw.get("documents", raw) if isinstance(raw, dict) else raw
        count = len(documents) if isinstance(documents, list) else 0
        details["document_count"] = count
        if count <= 0:
            return ResearchEngineReadinessItem(
                service="literature-rag",
                label="文献 RAG",
                status="warning",
                required=False,
                blocking=False,
                demo_fallback=True,
                message="本地文献索引为空，文献检索将使用 demo fallback。",
                details=details,
            )
        return ResearchEngineReadinessItem(
            service="literature-rag",
            label="文献 RAG",
            status="ready",
            required=False,
            blocking=False,
            demo_fallback=False,
            message=f"已加载 {count} 条文献索引。",
            details=details,
        )
