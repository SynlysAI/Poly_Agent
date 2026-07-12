from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiResponse(StrictModel):
    code: int = 0
    message: str = "ok"
    data: Any = None


class CorpusCreate(StrictModel):
    corpus_id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    domain: str = Field(default="literature", max_length=120)
    material_family: str = Field(default="", max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=20)


class CandidateImport(StrictModel):
    doi: str
    title: str = ""
    journal: str | None = None
    year: int | None = None
    relevance: float = Field(default=0.0, ge=0, le=1)
    journal_quality: float = Field(default=0.0, ge=0, le=1)
    citation_impact: float = Field(default=0.0, ge=0, le=1)
    recency_representativeness: float = Field(default=0.0, ge=0, le=1)
    fulltext_availability: float = Field(default=0.0, ge=0, le=1)
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    source_kind: str | None = None
    source_url: str | None = None


class CandidateImportRequest(StrictModel):
    items: list[CandidateImport] = Field(min_length=1, max_length=1000)


class IngestionJobCreate(StrictModel):
    document_id: str
    force: bool = False


class QueryRequest(StrictModel):
    corpus_id: str = "krf_photoresist"
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["naive", "local", "global", "hybrid", "mix"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)
    include_graph_context: bool = True

    @field_validator("corpus_id", "question")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized
