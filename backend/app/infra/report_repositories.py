"""Report generation repositories."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo.errors import PyMongoError

from app.infra.computation_repositories import (
    BaseRepository,
    _apply_update_fields,
    clone_document,
    demo_store,
)
from app.infra.mongo import get_report_artifacts_collection, get_report_jobs_collection


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReportJobRepository(BaseRepository):
    """ReportJob repository with Mongo-first + demo-store fallback."""

    collection_name = "report_jobs"

    @classmethod
    def _collection(cls):
        return get_report_jobs_collection()

    @classmethod
    def save_job(cls, document: dict[str, Any]) -> None:
        """Create or replace a report job."""
        cls.save("report_id", document)

    @classmethod
    def find_by_report_id(cls, report_id: str) -> dict[str, Any] | None:
        """Find a report job by ID."""
        return cls.find_one({"report_id": report_id})

    @classmethod
    def list_jobs(
        cls,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """List report jobs with common filters."""
        filters: dict[str, Any] = {}
        if subject_type:
            filters["subject_type"] = subject_type
        if subject_id:
            filters["subject_id"] = subject_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, report_id: str, fields: dict[str, Any]) -> bool:
        """Update report job fields."""
        payload = clone_document(fields)
        payload["updated_at"] = payload.get("updated_at") or _utcnow()
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"report_id": report_id}, {"$set": payload})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("report_id") == report_id:
                    _apply_update_fields(item, payload)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def update_status(
        cls,
        report_id: str,
        *,
        status: str,
        stage: str | None = None,
        progress: int | None = None,
        error: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> bool:
        """Update status-related fields for a report job."""
        fields: dict[str, Any] = {"status": status}
        if stage is not None:
            fields["stage"] = stage
        if progress is not None:
            fields["progress"] = progress
        if error is not None:
            fields["error"] = clone_document(error)
        if started_at is not None:
            fields["started_at"] = started_at
        if finished_at is not None:
            fields["finished_at"] = finished_at
        return cls.update_fields(report_id, fields)

    @classmethod
    def append_artifact_ref(cls, report_id: str, artifact_ref: dict[str, Any]) -> bool:
        """Append an artifact reference to a report job."""
        payload = clone_document(artifact_ref)
        now = _utcnow()
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"report_id": report_id},
                    {
                        "$push": {"artifact_refs": payload},
                        "$set": {"updated_at": now},
                    },
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("report_id") == report_id:
                    refs = item.setdefault("artifact_refs", [])
                    refs.append(payload)
                    item["updated_at"] = now
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def create_retry_job(
        cls,
        retry_of_report_id: str,
        *,
        new_report_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        """Create a new queued report job copied from a failed source job."""
        source = cls.find_by_report_id(retry_of_report_id)
        if not source:
            raise ValueError(f"ReportJob not found: {retry_of_report_id}")

        now = _utcnow()
        retry_doc = clone_document(source)
        input_snapshot = clone_document(retry_doc.get("input_snapshot") or {})
        input_snapshot["retry_of"] = retry_of_report_id
        retry_doc.update(
            {
                "report_id": new_report_id,
                "status": "queued",
                "stage": "context",
                "progress": 0,
                "input_snapshot": input_snapshot,
                "context_ref": None,
                "skill_runs": [],
                "artifact_refs": [],
                "error": None,
                "created_by": created_by,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
            }
        )
        cls.save_job(retry_doc)
        return retry_doc


class ReportArtifactRepository(BaseRepository):
    """ReportArtifact repository."""

    collection_name = "report_artifacts"

    @classmethod
    def _collection(cls):
        return get_report_artifacts_collection()

    @classmethod
    def save_artifact(cls, document: dict[str, Any]) -> None:
        """Create or replace a report artifact."""
        cls.save("artifact_id", document)

    @classmethod
    def find_by_artifact_id(cls, artifact_id: str) -> dict[str, Any] | None:
        """Find a report artifact by ID."""
        return cls.find_one({"artifact_id": artifact_id})

    @classmethod
    def list_by_report_id(
        cls,
        report_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        """List artifacts for a report."""
        return cls.list_all(
            {"report_id": report_id},
            sort_field="created_at",
            reverse=False,
            page=page,
            page_size=page_size,
        )
