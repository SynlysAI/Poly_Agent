"""Research report generation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcDatetimeJsonModel


ReportSubjectType = Literal["algorithm_run", "research_run", "workflow_run", "computation_run"]
ReportFormat = Literal["markdown", "latex", "pdf"]
ReportCreateFormat = Literal["markdown", "pdf"]
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
    formats: list[ReportCreateFormat] = Field(default_factory=lambda: ["markdown", "pdf"])
    provider: ReportProvider | Literal["auto"] = "auto"
    skill_pipeline_id: str = Field(default="nature_research_report_zh", min_length=1, max_length=160)
    scope: ReportScope = Field(default_factory=ReportScope)
    user_instructions: str | None = Field(default=None, max_length=4000)

    @field_validator("formats")
    @classmethod
    def validate_formats(cls, value: list[ReportCreateFormat]) -> list[ReportCreateFormat]:
        """Require at least one unique output format."""
        deduped = list(dict.fromkeys(value))
        if not deduped:
            raise ValueError("formats 至少选择一种输出格式")
        return deduped


class StructuredFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    confidence: str | None = None


class StructuredResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)


class StructuredReport(BaseModel):
    """Validated LLM output used by all report renderers."""

    model_config = ConfigDict(extra="allow")

    title: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    key_findings: list[StructuredFinding] = Field(min_length=1)
    methods: list[str] = Field(min_length=1)
    results: list[StructuredResult] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    next_steps: list[str] = Field(min_length=1)
    traceability: dict = Field(default_factory=dict)
    tables: list[dict] = Field(default_factory=list)
    figure_placeholders: list[dict] = Field(default_factory=list)
    appendices: list[dict] = Field(default_factory=list)

    @field_validator("methods", "limitations", "next_steps")
    @classmethod
    def validate_non_empty_items(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not normalized:
            raise ValueError("报告章节不能是空内容")
        return normalized

    @model_validator(mode="after")
    def validate_grounding(self):
        if not any(item.evidence for item in self.key_findings):
            raise ValueError("关键发现必须包含追溯证据")
        return self


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


class ReportJob(UtcDatetimeJsonModel):
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


class ReportArtifact(UtcDatetimeJsonModel):
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
    pdf_ready: bool
    codex_ready: bool | None = None
    ollama_ready: bool | None = None
    warnings: list[str] = Field(default_factory=list)
