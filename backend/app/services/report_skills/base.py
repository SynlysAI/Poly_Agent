"""Report skill adapter helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_skill_run(
    *,
    skill_id: str,
    status: str,
    input_artifact_id: str,
    output_artifact_id: str,
    provider: str,
    model: str | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    now = utc_iso()
    return {
        "skill_id": skill_id,
        "status": status,
        "input_artifact_id": input_artifact_id,
        "output_artifact_id": output_artifact_id,
        "provider": provider,
        "model": model,
        "warnings": warnings or [],
        "started_at": now,
        "finished_at": now,
        "duration_ms": 0,
    }
