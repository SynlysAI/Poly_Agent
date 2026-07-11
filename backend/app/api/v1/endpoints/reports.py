"""Report generation API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.reports import ReportCreateRequest, ReportJob, ReportListData, ReportReadinessData
from app.services.report_service import ReportService


router = APIRouter(prefix="/reports", tags=["Report Generation"])


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    return current_user["user_id"] if current_user else "demo_user"


def _access_user_id(current_user: dict[str, str] | None) -> str | None:
    return current_user["user_id"] if current_user else None


def _is_admin(current_user: dict[str, str] | None) -> bool:
    return bool(current_user and current_user.get("role") == "admin")


@router.get("/readiness", response_model=ApiResponse[ReportReadinessData])
def get_report_readiness() -> ApiResponse[ReportReadinessData]:
    """Return sanitized report-generation readiness."""
    return ApiResponse(data=ReportService().get_readiness())


@router.post("", response_model=ApiResponse[ReportJob])
def create_report(
    request: ReportCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ReportJob]:
    """Create a report generation job and schedule background execution."""
    service = ReportService()
    job = service.create_report_job(
        request,
        created_by=_actor_user_id(current_user),
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    background_tasks.add_task(
        ReportService().execute_report_job,
        job["report_id"],
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(data=job)


@router.post("/sync", response_model=ApiResponse[ReportJob], include_in_schema=False)
def create_report_sync(
    request: ReportCreateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ReportJob]:
    """Create and execute a report synchronously for tests and local diagnostics."""
    service = ReportService()
    job = service.create_report_job(
        request,
        created_by=_actor_user_id(current_user),
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    service.execute_report_job(
        job["report_id"],
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(
        data=service.get_report_job(
            job["report_id"],
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        )
    )


@router.get("", response_model=ApiResponse[ReportListData])
def list_reports(
    subject_type: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ReportListData]:
    """List report jobs."""
    items, total = ReportService().list_report_jobs(
        subject_type=subject_type,
        subject_id=subject_id,
        status=status,
        page=page,
        page_size=page_size,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(data=ReportListData(items=items, page=page, page_size=page_size, total=total))


@router.get("/{report_id}", response_model=ApiResponse[ReportJob])
def get_report(
    report_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ReportJob]:
    """Get a report job."""
    return ApiResponse(
        data=ReportService().get_report_job(
            report_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        )
    )


@router.get("/{report_id}/preview", response_model=ApiResponse[dict])
def preview_report(
    report_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[dict]:
    """Return the generated Markdown report for in-app preview."""
    return ApiResponse(
        data=ReportService().get_markdown_preview(
            report_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        )
    )


@router.post("/{report_id}/cancel", response_model=ApiResponse[ReportJob])
def cancel_report(
    report_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ReportJob]:
    """Cancel a queued/running report job."""
    return ApiResponse(
        data=ReportService().cancel_report_job(
            report_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        )
    )


@router.post("/{report_id}/retry", response_model=ApiResponse[ReportJob])
def retry_report(
    report_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ReportJob]:
    """Retry a failed report as a new report job."""
    service = ReportService()
    job = service.retry_report_job(
        report_id,
        created_by=_actor_user_id(current_user),
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    background_tasks.add_task(
        ReportService().execute_report_job,
        job["report_id"],
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(data=job)


@router.get("/{report_id}/artifacts/{artifact_id}/download")
def download_report_artifact(
    report_id: str,
    artifact_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> FileResponse:
    """Download a report artifact after report/artifact ownership validation."""
    artifact, path = ReportService().resolve_artifact_path(
        report_id=report_id,
        artifact_id=artifact_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_is_admin(current_user),
        audit_actor_user_id=_actor_user_id(current_user),
    )
    return FileResponse(
        path,
        filename=str(artifact.get("filename") or "report-artifact"),
        media_type="application/octet-stream",
    )
