"""Knowledge base RAG/KG API contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


KnowledgeQueryMode = Literal["hybrid", "local", "global", "naive", "mix"]


class KnowledgeSystem(BaseModel):
    """Knowledge base system available for querying and graph browsing."""

    model_config = ConfigDict(extra="forbid")

    system_id: str
    name: str
    domain: str
    material_family: str
    description: str
    is_demo: bool = False
    tags: list[str] = Field(default_factory=list)
    document_count: int = 0
    entity_count: int = 0
    relation_count: int = 0


class KnowledgeSystemListData(BaseModel):
    """Knowledge system list response."""

    items: list[KnowledgeSystem]
    total: int


class KnowledgeHit(BaseModel):
    """Retrieved text/card hit."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    snippet: str
    source: str | None = None
    doi: str | None = None
    url: str | None = None
    journal: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    score: float = 0.0
    metadata: dict = Field(default_factory=dict)


class KnowledgeCitation(BaseModel):
    """Citation metadata safe to expose to the frontend."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    doi: str | None = None
    url: str | None = None
    journal: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    chunk_id: str | None = None


class KnowledgeGraphNode(BaseModel):
    """Frontend-friendly graph node."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    type: str
    score: float = 1.0
    properties: dict = Field(default_factory=dict)


class KnowledgeGraphEdge(BaseModel):
    """Frontend-friendly graph edge."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    type: str
    weight: float = 1.0
    properties: dict = Field(default_factory=dict)


class KnowledgeGraphStats(BaseModel):
    """Knowledge graph aggregate counts."""

    model_config = ConfigDict(extra="forbid")

    entity_count: int
    relation_count: int
    document_count: int


class KnowledgeGraphData(BaseModel):
    """Knowledge graph response."""

    model_config = ConfigDict(extra="forbid")

    system_id: str
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    stats: KnowledgeGraphStats
    configured: bool = True
    message: str = "ok"
    provenance: dict = Field(default_factory=dict)


class KnowledgeQueryRequest(BaseModel):
    """RAG query request."""

    model_config = ConfigDict(extra="forbid")

    system_id: str = "ai4s_fluoropolymer"
    question: str = Field(min_length=1, max_length=2000)
    mode: KnowledgeQueryMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)
    include_graph_context: bool = True

    @field_validator("system_id", "question")
    @classmethod
    def normalize_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class KnowledgeQueryResponse(BaseModel):
    """RAG query response."""

    model_config = ConfigDict(extra="forbid")

    system_id: str
    question: str
    mode: KnowledgeQueryMode
    answer: str
    hits: list[KnowledgeHit] = Field(default_factory=list)
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    graph_context: KnowledgeGraphData | None = None
    configured: bool = False
    message: str = ""


class KnowledgeSuggestedQuestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: str
    questions: list[str] = Field(min_length=1, max_length=6)
    provider: str
    model: str
    generated_at: str


class KnowledgeHealthData(BaseModel):
    """Knowledge service readiness summary."""

    model_config = ConfigDict(extra="forbid")

    service: str = "knowledge-base"
    status: Literal["ready", "warning", "unavailable"]
    configured: bool
    demo_available: bool
    message: str
    systems: list[str] = Field(default_factory=list)
