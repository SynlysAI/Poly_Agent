"""Report generation service."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import AuditEventRepository
from app.infra.report_repositories import ReportArtifactRepository, ReportJobRepository
from app.schemas.reports import ReportCreateRequest, ReportReadinessData
from app.services.report_context_service import ReportContextService
from app.services.report_providers.registry import ReportProviderRegistry
from app.services.report_renderers.html import HtmlReportRenderer
from app.services.report_renderers.markdown import MarkdownReportRenderer
from app.services.report_renderers.pdf import PdfCompiler
from app.services.report_skill_orchestrator import ReportSkillOrchestrator


SUPPORTED_PROVIDERS = {
    "openai_responses",
    "openai_compatible",
    "local_ollama",
    "codex_exec",
    "custom_http",
    "mock",
}
SUPPORTED_SUBJECT_TYPES = {"algorithm_run", "research_run", "workflow_run", "computation_run"}

SUPPORTED_PIPELINES = {
    "nature_research_report_zh",
    "nature_research_report_with_citations_zh",
    "nature_research_report_with_figures_zh",
    "research_run_failure_analysis_zh",
}
SUPPORTED_TEMPLATES = {
    "algorithm_run_summary_zh",
    "research_run_summary_zh",
    "research_summary_zh",
    "research_run_failure_analysis_zh",
    "nature_research_report_zh",
    "nature_research_report_with_citations_zh",
    "nature_research_report_with_figures_zh",
}


class ReportJobCancelled(RuntimeError):
    """Internal signal used to stop a report job that has been cancelled."""


class ReportService:
    """Coordinates report job lifecycle and readiness checks."""

    def create_report_job(
        self,
        request: ReportCreateRequest,
        *,
        created_by: str = "anonymous",
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Create a queued report job."""
        if not settings.reports_enabled:
            raise HTTPException(status_code=503, detail="报告生成功能未启用")
        if request.provider == "mock" and settings.require_mongodb:
            raise HTTPException(status_code=400, detail="正式环境不允许使用 mock 报告 provider")
        self._validate_subject_type(request.subject_type)
        self._validate_template_and_pipeline(request.template_id, request.skill_pipeline_id)
        self._ensure_subject_access(request.subject_type, request.subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
        now = self._now()
        provider, model, route_hint = self._resolve_provider_selection(request.provider)
        report_id = f"report_{uuid.uuid4().hex[:16]}"
        input_snapshot = request.model_dump(mode="python")
        if route_hint:
            input_snapshot["resolved_model_route"] = route_hint
        job = {
            "report_id": report_id,
            "subject_type": request.subject_type,
            "subject_id": request.subject_id,
            "problem_spec_id": None,
            "campaign_id": None,
            "template_id": request.template_id,
            "language": request.language,
            "formats": request.formats,
            "status": "queued",
            "stage": "context",
            "progress": 0,
            "input_snapshot": input_snapshot,
            "context_ref": None,
            "provider": provider,
            "model": model,
            "skill_pipeline_id": request.skill_pipeline_id,
            "skill_runs": [],
            "artifact_refs": [],
            "error": None,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        ReportJobRepository.save_job(job)
        self._audit(
            "report.created",
            report_id=report_id,
            after={"status": "queued", "subject_type": request.subject_type, "subject_id": request.subject_id},
            related_ids={request.subject_type: request.subject_id},
            actor_user_id=created_by,
        )
        return job

    def get_report_job(
        self,
        report_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        job = ReportJobRepository.find_by_report_id(report_id)
        if not job:
            raise HTTPException(status_code=404, detail="报告任务不存在")
        self._ensure_report_access(job, actor_user_id=actor_user_id, is_admin=is_admin)
        return job

    def list_report_jobs(
        self,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        return ReportJobRepository.list_jobs(
            subject_type=subject_type,
            subject_id=subject_id,
            status=status,
            created_by=None if is_admin or not actor_user_id else actor_user_id,
            page=page,
            page_size=page_size,
        )

    def execute_report_job(
        self,
        report_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Execute a report job and persist artifacts."""
        job = self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if job.get("status") == "cancelled":
            return job
        try:
            ReportJobRepository.update_status(
                report_id,
                status="running",
                stage="context",
                progress=10,
                started_at=self._now(),
            )
            context = ReportContextService().collect_context(
                subject_type=job["subject_type"],
                subject_id=job["subject_id"],
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            context_artifact = self.create_artifact(
                report_id=report_id,
                artifact_type="context_json",
                filename="context.json",
                content=json.dumps(context, ensure_ascii=False, indent=2, default=str),
            )
            self._audit(
                "report.context_collected",
                report_id=report_id,
                after={
                    "artifact_id": context_artifact["artifact_id"],
                    "subject_type": job["subject_type"],
                    "subject_id": job["subject_id"],
                },
                related_ids={job["subject_type"]: job["subject_id"]},
                actor_user_id=job.get("created_by") or "anonymous",
            )
            ReportJobRepository.update_fields(
                report_id,
                {
                    "context_ref": {
                        "artifact_id": context_artifact["artifact_id"],
                        "filename": context_artifact["filename"],
                    },
                    "status": "running",
                    "stage": "context",
                    "progress": 20,
                },
            )
            self._raise_if_cancelled(report_id)

            ReportJobRepository.update_status(report_id, status="running", stage="skill_plan", progress=25)
            plan = ReportSkillOrchestrator().build_plan(
                report_request=job["input_snapshot"],
                context=context,
            )
            self._raise_if_cancelled(report_id)
            ReportJobRepository.update_status(report_id, status="running", stage="draft", progress=35)
            provider, result = self._run_plan_with_provider_fallback(
                primary_provider=job["provider"],
                primary_route_hint=(job.get("input_snapshot") or {}).get("resolved_model_route"),
                plan=plan,
                context=context,
            )
            structured_report = result["structured_report"]
            ReportJobRepository.update_status(report_id, status="running", stage="quality_check", progress=65)
            self._raise_if_cancelled(report_id)
            ReportJobRepository.update_fields(
                report_id,
                {
                    "provider": getattr(provider, "name", job["provider"]),
                    "model": getattr(provider, "model", None),
                    "skill_runs": result["skill_runs"],
                    "status": "converting",
                    "stage": "quality_check",
                    "progress": 70,
                },
            )
            self._render_artifacts(report_id=report_id, formats=job["formats"], structured_report=structured_report)
            ReportJobRepository.update_status(
                report_id,
                status="completed",
                stage="persist",
                progress=100,
                finished_at=self._now(),
            )
            self._audit(
                "report.generated",
                report_id=report_id,
                after={"status": "completed", "artifact_count": len(self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin).get("artifact_refs") or [])},
                related_ids={job["subject_type"]: job["subject_id"]},
                actor_user_id=job.get("created_by") or "anonymous",
            )
        except ReportJobCancelled:
            return self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)
        except Exception as exc:
            ReportJobRepository.update_status(
                report_id,
                status="failed",
                stage="persist",
                progress=100,
                error={"message": self._safe_error_message(exc), "error_type": type(exc).__name__},
                finished_at=self._now(),
            )
            try:
                self.create_artifact(
                    report_id=report_id,
                    artifact_type="log",
                    filename="report-error.log",
                    content=self._safe_error_message(exc),
                )
            except Exception:
                pass
            self._audit(
                "report.failed",
                report_id=report_id,
                after={"status": "failed", "error_type": type(exc).__name__},
                related_ids={job.get("subject_type", "subject"): job.get("subject_id")},
                actor_user_id=job.get("created_by") or "anonymous",
            )
        return self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)

    def _raise_if_cancelled(self, report_id: str) -> None:
        latest = ReportJobRepository.find_by_report_id(report_id) or {}
        if latest.get("status") == "cancelled":
            raise ReportJobCancelled("报告任务已取消")

    def _run_plan_with_provider_fallback(
        self,
        *,
        primary_provider: str,
        primary_route_hint: dict[str, Any] | None = None,
        plan: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[Any, dict[str, Any]]:
        provider_names = self._provider_sequence(primary_provider)
        last_error: Exception | None = None
        for provider_name in provider_names:
            try:
                route = None
                if provider_name == primary_provider and primary_route_hint:
                    route = ReportProviderRegistry().resolve_report_route(primary_route_hint)
                provider = ReportProviderRegistry().get_provider(provider_name, model_route=route)
                result = ReportSkillOrchestrator().run_plan(plan, provider=provider, context=context)
                return provider, result
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("No report provider configured")

    def cancel_report_job(
        self,
        report_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        job = self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if job.get("status") in {"queued", "running", "converting"}:
            ReportJobRepository.update_status(
                report_id,
                status="cancelled",
                stage=job.get("stage") or "context",
                progress=job.get("progress") or 0,
                finished_at=self._now(),
            )
            self._audit(
                "report.cancelled",
                report_id=report_id,
                before={"status": job.get("status")},
                after={"status": "cancelled"},
                related_ids={job.get("subject_type", "subject"): job.get("subject_id")},
                actor_user_id=job.get("created_by") or "anonymous",
            )
        return self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)

    def retry_report_job(
        self,
        report_id: str,
        *,
        created_by: str = "anonymous",
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        source_job = self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if source_job.get("status") != "failed":
            raise HTTPException(status_code=400, detail="仅失败的报告任务允许重试")
        new_report_id = f"report_{uuid.uuid4().hex[:16]}"
        retry_doc = ReportJobRepository.create_retry_job(report_id, new_report_id=new_report_id, created_by=created_by)
        requested_provider = str((retry_doc.get("input_snapshot") or {}).get("provider") or retry_doc.get("provider") or "auto")
        provider, model, route_hint = self._resolve_provider_selection(requested_provider)
        input_snapshot = dict(retry_doc.get("input_snapshot") or {})
        if route_hint:
            input_snapshot["resolved_model_route"] = route_hint
        else:
            input_snapshot.pop("resolved_model_route", None)
        retry_doc.update({"provider": provider, "model": model, "input_snapshot": input_snapshot})
        ReportJobRepository.update_fields(
            new_report_id,
            {
                "provider": provider,
                "model": model,
                "input_snapshot": input_snapshot,
            },
        )
        self._audit(
            "report.created",
            report_id=new_report_id,
            after={"status": "queued", "retry_of": report_id},
            related_ids={retry_doc.get("subject_type", "subject"): retry_doc.get("subject_id"), "retry_of": report_id},
            actor_user_id=created_by,
        )
        return retry_doc

    def create_artifact(
        self,
        *,
        report_id: str,
        artifact_type: str,
        filename: str,
        content: bytes | str,
    ) -> dict[str, Any]:
        """Persist a report artifact file and register metadata."""
        job = ReportJobRepository.find_by_report_id(report_id)
        if not job:
            raise HTTPException(status_code=404, detail="报告任务不存在")

        safe_filename = self._safe_filename(filename)
        artifact_id = f"rart_{uuid.uuid4().hex[:16]}"
        data = content.encode("utf-8") if isinstance(content, str) else content

        report_dir = settings.report_output_root / report_id
        report_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = report_dir / safe_filename
        artifact_path.write_bytes(data)

        digest = hashlib.sha256(data).hexdigest()
        artifact = {
            "artifact_id": artifact_id,
            "report_id": report_id,
            "artifact_type": artifact_type,
            "filename": safe_filename,
            "storage_uri": f"{report_id}/{safe_filename}",
            "size_bytes": len(data),
            "sha256": digest,
            "created_at": self._now(),
        }
        ReportArtifactRepository.save_artifact(artifact)
        ReportJobRepository.append_artifact_ref(
            report_id,
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "filename": safe_filename,
                "size_bytes": len(data),
                "sha256": digest,
            },
        )
        return artifact

    def resolve_artifact_path(
        self,
        *,
        report_id: str,
        artifact_id: str,
        actor_user_id: str | None = None,
        is_admin: bool = False,
        audit_actor_user_id: str = "anonymous",
    ) -> tuple[dict[str, Any], Path]:
        """Resolve a report artifact to a safe local path for download."""
        report = self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)
        artifact = ReportArtifactRepository.find_by_artifact_id(artifact_id)
        if not artifact or artifact.get("report_id") != report_id:
            raise HTTPException(status_code=404, detail="报告产物不存在")

        root = settings.report_output_root.resolve()
        candidate = (root / str(artifact.get("storage_uri", ""))).resolve()
        if not candidate.is_file() or not self._is_relative_to(candidate, root):
            raise HTTPException(status_code=404, detail="报告产物文件不存在")
        self._audit(
            "report.downloaded",
            report_id=report_id,
            after={"artifact_id": artifact_id, "artifact_type": artifact.get("artifact_type")},
            related_ids={report.get("subject_type", "subject"): report.get("subject_id")},
            actor_user_id=audit_actor_user_id,
        )
        return artifact, candidate

    def get_markdown_preview(
        self,
        report_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Return Markdown content for an authorized report without exposing storage paths."""
        job = self.get_report_job(report_id, actor_user_id=actor_user_id, is_admin=is_admin)
        markdown_ref = next(
            (item for item in job.get("artifact_refs") or [] if item.get("artifact_type") == "markdown"),
            None,
        )
        if not markdown_ref:
            raise HTTPException(status_code=404, detail="报告尚无 Markdown 内容")
        artifact = ReportArtifactRepository.find_by_artifact_id(markdown_ref["artifact_id"])
        if not artifact:
            raise HTTPException(status_code=404, detail="Markdown artifact 不存在")
        root = settings.report_output_root.resolve()
        path = (root / str(artifact.get("storage_uri", ""))).resolve()
        if not self._is_relative_to(path, root) or not path.is_file():
            raise HTTPException(status_code=404, detail="Markdown artifact 文件不存在")
        return {
            "report_id": report_id,
            "content": path.read_text(encoding="utf-8"),
            "provider": job.get("provider"),
            "model": job.get("model"),
        }

    def _render_artifacts(
        self,
        *,
        report_id: str,
        formats: list[str],
        structured_report: dict[str, Any],
    ) -> None:
        if "markdown" in formats:
            self.create_artifact(
                report_id=report_id,
                artifact_type="markdown",
                filename="report.md",
                content=MarkdownReportRenderer().render(structured_report),
            )

        if "pdf" in formats:
            ReportJobRepository.update_status(report_id, status="converting", stage="pdf", progress=85)
            result = PdfCompiler(timeout_seconds=settings.report_pdf_timeout_seconds).compile(
                HtmlReportRenderer().render(structured_report),
                output_dir=settings.report_output_root / report_id,
            )
            if result["status"] == "completed" and result["pdf_path"]:
                self.create_artifact(
                    report_id=report_id,
                    artifact_type="pdf",
                    filename="report.pdf",
                    content=Path(result["pdf_path"]).read_bytes(),
                )
            else:
                self.create_artifact(
                    report_id=report_id,
                    artifact_type="log",
                    filename="pdf-compile.log",
                    content=result.get("log") or "PDF compilation failed.",
                )
                raise RuntimeError(result.get("log") or "PDF generation failed")

    def get_readiness(self) -> ReportReadinessData:
        """Return sanitized report-generation readiness."""
        warnings: list[str] = []
        provider = str(settings.report_llm_provider or "openai_compatible")
        pipeline = str(settings.report_skill_pipeline_default or "nature_research_report_zh")

        output_root_ready = self._ensure_output_root(settings.report_output_root, warnings)
        provider_ready = self._provider_ready(provider, warnings)
        pipeline_ready = pipeline in SUPPORTED_PIPELINES
        if not pipeline_ready:
            warnings.append(f"未知报告 Skill pipeline: {pipeline}")
        elif not self._pipeline_allowlist_ready(pipeline, warnings):
            pipeline_ready = False
        default_template = "research_run_summary_zh"
        if default_template not in SUPPORTED_TEMPLATES:
            warnings.append(f"默认报告模板不可用: {default_template}")

        pdf_ready = self._playwright_pdf_ready()
        if not pdf_ready:
            warnings.append("Playwright Chromium 不可用，PDF 输出将失败。")

        codex_ready = None
        if provider == "codex_exec":
            codex_ready = bool(shutil.which(settings.report_codex_bin))
            if not codex_ready:
                warnings.append("Codex CLI 不可用。")

        ollama_ready = None
        if provider == "local_ollama":
            ollama_ready = bool(settings.report_ollama_model)
            if not ollama_ready:
                warnings.append("REPORT_OLLAMA_MODEL 未配置。")

        return ReportReadinessData(
            reports_enabled=bool(settings.reports_enabled),
            output_root_ready=output_root_ready,
            provider=provider,
            provider_ready=provider_ready,
            skill_pipeline=pipeline,
            skill_pipeline_ready=pipeline_ready,
            latex_ready=False,
            pdf_ready=pdf_ready,
            codex_ready=codex_ready,
            ollama_ready=ollama_ready,
            warnings=warnings,
        )

    @staticmethod
    def _playwright_pdf_ready() -> bool:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                return Path(playwright.chromium.executable_path).exists()
        except Exception:
            return False

    def _ensure_output_root(self, output_root: Path, warnings: list[str]) -> bool:
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            probe = output_root / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            warnings.append("报告输出目录不可写。")
            return False

    def _provider_ready(self, provider: str, warnings: list[str]) -> bool:
        if provider not in SUPPORTED_PROVIDERS:
            warnings.append(f"未知报告 LLM provider: {provider}")
            return False
        if provider == "mock":
            return True
        if provider in {"openai_responses", "openai_compatible"}:
            ready = bool(settings.report_llm_model) and (
                bool(settings.report_llm_api_key) or provider == "openai_compatible"
            )
            if not ready:
                warnings.append("报告 LLM provider 缺少模型或 API key 配置。")
            return ready
        if provider == "custom_http":
            ready = bool(settings.report_llm_base_url) and bool(settings.report_llm_model)
            if not ready:
                warnings.append("Custom HTTP provider 缺少 endpoint 或模型配置。")
            return ready
        if provider == "local_ollama":
            ready = bool(settings.report_ollama_model)
            if not ready:
                warnings.append("本地 Ollama provider 缺少模型配置。")
            return ready
        if provider == "codex_exec":
            ready = bool(settings.report_codex_api_key) and bool(shutil.which(settings.report_codex_bin))
            if not ready:
                warnings.append("Codex provider 缺少 API key 或 CLI。")
            return ready
        return False

    def _pipeline_allowlist_ready(self, pipeline: str, warnings: list[str]) -> bool:
        scope = {
            "include_citations": pipeline == "nature_research_report_with_citations_zh",
            "include_figures": pipeline == "nature_research_report_with_figures_zh",
            "include_literature_background": pipeline == "nature_research_report_with_citations_zh",
            "include_failure_analysis": pipeline == "research_run_failure_analysis_zh",
        }
        try:
            ReportSkillOrchestrator().build_plan(
                report_request={"skill_pipeline_id": pipeline, "scope": scope},
                context={"subject": {"subject_type": "readiness", "subject_id": "readiness"}},
            )
            return True
        except HTTPException as exc:
            warnings.append(str(exc.detail))
            return False

    def _provider_sequence(self, primary_provider: str) -> list[str]:
        providers = [primary_provider]
        providers.extend(settings.report_llm_fallback_providers or [])
        deduped: list[str] = []
        for provider in providers:
            provider = str(provider or "").strip()
            if provider and provider not in deduped:
                deduped.append(provider)
        return deduped

    def _resolve_provider_selection(self, requested_provider: str) -> tuple[str, str | None, dict[str, Any] | None]:
        if requested_provider != "auto":
            return requested_provider, self._configured_model(requested_provider), None
        if settings.report_llm_provider == "mock":
            return "mock", self._configured_model("mock"), None
        try:
            route = ReportProviderRegistry().resolve_report_route()
        except Exception:
            return settings.report_llm_provider, self._configured_model(settings.report_llm_provider), None
        provider = self._provider_name_from_route(route)
        route_hint = {
            "provider_id": route.get("provider_id"),
            "provider_type": route.get("provider_type"),
            "model_id": route.get("model_id"),
        }
        return provider, route.get("model_id") or self._configured_model(provider), route_hint

    def _provider_name_from_route(self, route: dict[str, Any]) -> str:
        provider_type = str(route.get("provider_type") or "")
        if provider_type == "ollama":
            return "local_ollama"
        if provider_type == "custom_http":
            return "custom_http"
        return "openai_compatible"

    def _safe_filename(self, filename: str) -> str:
        safe = Path(filename).name.strip()
        if not safe or safe in {".", ".."}:
            return "artifact.bin"
        return safe

    def _now(self):
        return datetime.now(timezone.utc)

    def _is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _configured_model(self, provider: str) -> str | None:
        if provider == "local_ollama":
            return settings.report_ollama_model
        if provider == "codex_exec":
            return settings.report_codex_model
        if provider == "mock":
            return settings.report_llm_model or "mock-report-model"
        return settings.report_llm_model

    def _safe_error_message(self, exc: Exception) -> str:
        text = str(exc) or type(exc).__name__
        for secret in (
            settings.report_llm_api_key,
            settings.report_codex_api_key,
        ):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return text

    def _ensure_report_access(
        self,
        job: dict[str, Any],
        *,
        actor_user_id: str | None,
        is_admin: bool,
    ) -> None:
        if not actor_user_id or is_admin:
            return
        if job.get("created_by") == actor_user_id:
            return
        self._ensure_subject_access(
            str(job.get("subject_type") or ""),
            str(job.get("subject_id") or ""),
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )

    def _validate_subject_type(self, subject_type: str) -> None:
        if subject_type not in SUPPORTED_SUBJECT_TYPES:
            raise HTTPException(status_code=400, detail=f"暂不支持为 {subject_type} 生成报告")

    def _validate_template_and_pipeline(self, template_id: str, pipeline_id: str) -> None:
        if template_id not in SUPPORTED_TEMPLATES:
            raise HTTPException(status_code=400, detail=f"未知报告模板: {template_id}")
        if pipeline_id not in SUPPORTED_PIPELINES:
            raise HTTPException(status_code=400, detail=f"未知报告 Skill pipeline: {pipeline_id}")

    def _ensure_subject_access(
        self,
        subject_type: str,
        subject_id: str,
        *,
        actor_user_id: str | None,
        is_admin: bool,
    ) -> None:
        if not actor_user_id or is_admin:
            return
        if subject_type == "algorithm_run":
            from app.services.research_engine_service import ResearchEngineService

            ResearchEngineService().get_algorithm_run(subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
            return
        if subject_type == "research_run":
            from app.services.research_engine_orchestrator import ResearchEngineOrchestrator

            ResearchEngineOrchestrator().get_research_run(subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
            return
        if subject_type == "workflow_run":
            from app.services.research_engine_service import ResearchEngineService

            ResearchEngineService().get_workflow_run(subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
            return
        if subject_type == "computation_run":
            from app.services.computation_service import ComputationService

            ComputationService().get_run(subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
            return
        raise HTTPException(status_code=400, detail=f"暂不支持为 {subject_type} 生成报告")

    def _audit(
        self,
        event_type: str,
        *,
        report_id: str,
        actor_user_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        related_ids: dict[str, Any] | None = None,
    ) -> None:
        AuditEventRepository.append(
            {
                "event_id": f"audit_{uuid.uuid4().hex[:16]}",
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "actor_role": "user" if actor_user_id != "system" else "system",
                "request_id": None,
                "entity_type": "report",
                "entity_id": report_id,
                "related_ids": related_ids or {},
                "before": before or {},
                "after": after or {},
                "metadata": {"source": "poly_agent"},
                "created_at": self._now(),
            }
        )
