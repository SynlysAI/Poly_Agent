"""Shared ResearchEngine ownership access policy."""

from __future__ import annotations

from fastapi import HTTPException


def ensure_research_engine_doc_access(
    doc: dict,
    *,
    actor_user_id: str | None,
    is_admin: bool,
    resource_label: str,
) -> None:
    """Allow admins/demo mode or the owner/creator of a ResearchEngine document."""
    if not actor_user_id or is_admin:
        return
    owner_id = doc.get("owner_id") or doc.get("created_by")
    if owner_id != actor_user_id:
        raise HTTPException(status_code=403, detail=f"无权限访问该{resource_label}")
