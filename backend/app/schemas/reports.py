"""Research report generation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ReportSubjectType = Literal["algorithm_run", "research_run", "workflow_run", "computation_run"]
ReportFormat = Literal["markdown", "latex", "pdf"]
ReportStatus = Literal["queued", "running", "converting", "completed", "failed", "cancelled"]
ReportStage = Literal[
    "context",
    "skill_plan",
    "draft",
    "polish",
    "quality_check",
    "latex",
    "pdf",
    "persist",
]
ReportProvider = Literal[
    "openai_responses",
    "openai_compatible",
    "local_ollama",
    "codex_exec",
    "custom_http",
    "mock",
]
ReportArtifactType = Literal["context_json", "markdown", "latex", "pdf", "log"]


class ReportScope(BaseModel):
    """Requested report content scope."""

    model_config = ConfigDict(extra="forbid")

    include_stages: bool = True
    include_algorithm_runs: bool = True
    include_computations: bool = True
    include_observations: bool = True
    include_audit_events: bool = True
    include_citations: bool = False
    include_figures: bool = False
    include_literature_background: bool = False
    include_failure_analysis: bool = False
    appendix_level: Literal["compact", "standard", "full"] = "standard"


class ReportCreateRequest(BaseModel):
    """Create a report generation job."""

    model_config = ConfigDict(extra="forbid")

    subject_type: ReportSubjectType
    subject_id: str = Field(min_length=1, max_length=120)
    template_id: str = Field(default="research_run_summary_zh", min_length=1, max_length=120)
    language: Literal["zh-CN", "en-US"] = "zh-CN"
    formats: list[ReportFormat] = Field(default_factory=lambda: ["markdown", "latex", "pdf"])
    provider: ReportProvider | Literal["auto"] = "auto"
    skill_pipeline_id: str = Field(default="nature_research_report_zh", min_length=1, max_length=160)
    scope: ReportScope = Field(default_factory=ReportScope)
    user_instructions: str | None = Field(default=None, max_length=4000)

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, value: list[ReportFormat]) -> list[ReportFormat]:
        """Require at least one unique output format."""
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise ValueError("formats 至少选择一种输出格式")
        return deduped


class ReportRetryRequest(BaseModel):
    """Retry an existing report as a new job."""

    model_config = ConfigDict(extra="forbid")

    retry_of: str = Field(min_length=1, max_length=120)


class ReportArtifactRef(BaseModel):
    """Report artifact reference safe for API responses."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: ReportArtifactType
    filename: str
    size_bytes: int | None = None
    sha256: str | None = None


class ReportJob(BaseModel):
    """Persisted report generation job."""

    model_config = ConfigDict(extra="forbid")

    report_id: str
    subject_type: ReportSubjectType
    subject_id: str
    problem_spec_id: str | None = None
    campaign_id: str | None = None
    template_id: str
    language: str = "zh-CN"
    formats: list[ReportFormat] = Field(default_factory=list)
    status: ReportStatus = "queued"
    stage: ReportStage = "context"
    progress: int = Field(default=0, ge=0, le=100)
    input_snapshot: dict = Field(default_factory=dict)
    context_ref: dict | None = None
    provider: ReportProvider
    model: str | None = None
    skill_pipeline_id: str
    skill_runs: list[dict] = Field(default_factory=list)
    artifact_refs: list[dict] = Field(default_factory=list)
    error: dict | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReportArtifact(BaseModel):
    """Persisted report output artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    report_id: str
    artifact_type: ReportArtifactType
    filename: str
    storage_uri: str
    size_bytes: int = Field(ge=0)
    sha256: str
    created_at: datetime


class ReportListData(BaseModel):
    """Paginated report list response payload."""

    items: list[ReportJob]
    page: int
    page_size: int
    total: int


class ReportReadinessData(BaseModel):
    """Report generation readiness summary."""

    reports_enabled: bool
    output_root_ready: bool
    provider: str
    provider_ready: bool
    skill_pipeline: str
    skill_pipeline_ready: bool
    latex_ready: bool
    codex_ready: bool | None = None
    ollama_ready: bool | None = None
    warnings: list[str] = Field(default_factory=list)
