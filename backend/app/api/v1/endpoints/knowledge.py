"""Knowledge base RAG/KG API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas.common import ApiResponse
from app.schemas.knowledge import (
    KnowledgeGraphData,
    KnowledgeHealthData,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeSystemListData,
    KnowledgeSuggestedQuestions,
)
from app.services.knowledge_service import KnowledgeService


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])
service = KnowledgeService()


@router.get("/systems", response_model=ApiResponse[KnowledgeSystemListData])
def list_knowledge_systems() -> ApiResponse[KnowledgeSystemListData]:
    """List available knowledge-base systems."""
    return ApiResponse(code=0, message="ok", data=service.list_systems())


@router.get("/health", response_model=ApiResponse[KnowledgeHealthData])
def get_knowledge_health() -> ApiResponse[KnowledgeHealthData]:
    """Return standalone literature RAG readiness."""
    return ApiResponse(code=0, message="ok", data=service.health())


@router.post("/query", response_model=ApiResponse[KnowledgeQueryResponse])
def query_knowledge_base(payload: KnowledgeQueryRequest) -> ApiResponse[KnowledgeQueryResponse]:
    """Run a query through the standalone literature RAG service."""
    return ApiResponse(code=0, message="ok", data=service.query(payload))


@router.post("/query/stream")
def stream_knowledge_query(payload: KnowledgeQueryRequest) -> StreamingResponse:
    """Stream observable retrieval stages and answer chunks as NDJSON."""
    if not service._base_url():
        raise HTTPException(status_code=503, detail="Literature RAG 服务未配置")
    return StreamingResponse(service.stream_query(payload), media_type="application/x-ndjson")


@router.post("/{system_id}/suggested-questions", response_model=ApiResponse[KnowledgeSuggestedQuestions])
def generate_suggested_questions(system_id: str) -> ApiResponse[KnowledgeSuggestedQuestions]:
    return ApiResponse(data=service.suggested_questions(system_id))


@router.get("/{system_id}/graph", response_model=ApiResponse[KnowledgeGraphData])
def get_knowledge_graph(system_id: str) -> ApiResponse[KnowledgeGraphData]:
    """Return the graph for a knowledge-base system."""
    return ApiResponse(code=0, message="ok", data=service.get_graph(system_id))


@router.get("/{system_id}/graph/subgraph", response_model=ApiResponse[KnowledgeGraphData])
def get_knowledge_subgraph(
    system_id: str,
    query: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=30, ge=1, le=100),
) -> ApiResponse[KnowledgeGraphData]:
    """Return a query-focused graph slice."""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_subgraph(system_id, query=query, limit=limit),
    )
