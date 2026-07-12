"""Application facade for the standalone literature RAG service."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterator

import httpx
from fastapi import HTTPException
from openai import OpenAI

from app.core.config import settings
from app.schemas.knowledge import (
    KnowledgeCitation,
    KnowledgeGraphData,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphStats,
    KnowledgeHealthData,
    KnowledgeHit,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeSuggestedQuestions,
    KnowledgeSystem,
    KnowledgeSystemListData,
)


LOCAL_APP_ENVS = {"dev", "development", "local", "test", "testing", "ci"}
LOCAL_RAG_BASE_URL_CANDIDATES = ("http://127.0.0.1:8200", "http://localhost:8200")
PLACEHOLDER_API_KEYS = {
    "replace-with-query-key",
    "replace-with-admin-key",
    "your-api-key",
    "your-query-api-key",
    "<query-service-key>",
}


class KnowledgeService:
    """Keep Poly_Agent contracts stable while the literature service evolves independently."""

    def list_systems(self) -> KnowledgeSystemListData:
        base_url = self._base_url()
        default_system_id = self._default_system_id()
        if not base_url:
            return KnowledgeSystemListData(items=[], total=0, default_system_id=default_system_id)
        try:
            raw = self._fetch_corpora(base_url)
        except Exception:
            return KnowledgeSystemListData(items=[], total=0, default_system_id=default_system_id)
        items = [self._normalize_corpus(item) for item in raw.get("items") or [] if item.get("corpus_id") or item.get("system_id")]
        return KnowledgeSystemListData(items=items, total=len(items), default_system_id=default_system_id)

    def health(self) -> KnowledgeHealthData:
        base_url = self._base_url()
        if not base_url:
            return KnowledgeHealthData(status="unavailable", configured=False, demo_available=False,
                                       message="Literature RAG 服务未配置或本地未发现。", systems=[])
        try:
            with self._client(base_url) as client:
                response = client.get("/health")
                response.raise_for_status()
                raw = self._unwrap(response.json())
        except Exception as exc:
            return KnowledgeHealthData(status="unavailable", configured=False, demo_available=False,
                                       message=f"Literature RAG 服务不可用：{type(exc).__name__}", systems=[])
        ready = raw.get("status") == "ready"
        try:
            corpora = self._fetch_corpora(base_url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return KnowledgeHealthData(
                    status="warning",
                    configured=False,
                    demo_available=False,
                    message="Literature RAG 服务已发现，但查询 API Key 未配置或无效。",
                    systems=[],
                )
            return KnowledgeHealthData(status="warning", configured=False, demo_available=False,
                                       message=f"Literature RAG corpus registry 不可用：HTTP {exc.response.status_code}",
                                       systems=[])
        except Exception as exc:
            return KnowledgeHealthData(status="warning", configured=False, demo_available=False,
                                       message=f"Literature RAG corpus registry 不可用：{type(exc).__name__}",
                                       systems=[])
        items = [self._normalize_corpus(item) for item in corpora.get("items") or [] if item.get("corpus_id") or item.get("system_id")]
        systems = [item.system_id for item in items]
        configured = ready and bool(systems)
        if not ready:
            message = "Literature RAG 服务尚未就绪。"
        elif configured:
            message = "Literature RAG 服务可用，已加载知识库体系。"
        else:
            message = "Literature RAG 服务可用，但未发现可用知识库体系。"
        return KnowledgeHealthData(status="ready" if configured else "warning", configured=configured,
                                   demo_available=False, message=message, systems=systems)

    def query(self, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        base_url = self._require_base_url()
        self._ensure_known_system(payload.system_id)
        request_body = {
            "corpus_id": payload.system_id,
            "question": payload.question,
            "mode": payload.mode,
            "top_k": payload.top_k,
            "include_graph_context": payload.include_graph_context,
        }
        try:
            with self._client(base_url) as client:
                response = client.post("/api/v1/query", json=request_body)
                response.raise_for_status()
                raw = self._unwrap(response.json())
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Literature RAG 查询失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Literature RAG 查询失败：{type(exc).__name__}") from exc
        return self._normalize_query(payload, raw)

    def get_graph(self, system_id: str) -> KnowledgeGraphData:
        self._require_base_url()
        self._ensure_known_system(system_id)
        raise HTTPException(status_code=400, detail="知识图谱必须提供实体或关键词后加载子图")

    def get_subgraph(self, system_id: str, *, query: str | None = None, limit: int = 30) -> KnowledgeGraphData:
        base_url = self._require_base_url()
        self._ensure_known_system(system_id)
        normalized_query = (query or "").strip()
        if not normalized_query:
            raise HTTPException(status_code=400, detail="请输入实体或关键词")
        try:
            with self._client(base_url) as client:
                response = client.get(
                    f"/api/v1/corpora/{system_id}/graph/subgraph",
                    params={"query": normalized_query, "limit": max(1, min(limit, 100))},
                )
                response.raise_for_status()
                raw = self._unwrap(response.json())
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="Literature RAG 图谱查询失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Literature RAG 图谱查询失败：{type(exc).__name__}") from exc
        return self._normalize_graph(system_id, raw)

    def suggested_questions(self, system_id: str) -> KnowledgeSuggestedQuestions:
        self._require_base_url()
        self._ensure_known_system(system_id)
        if not settings.llm_model or not settings.llm_base_url:
            raise HTTPException(status_code=503, detail="建议问题 LLM 未配置")
        system = self._get_system(system_id)
        try:
            client = OpenAI(api_key=settings.llm_api_key or "EMPTY", base_url=settings.llm_base_url)
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，格式为 {\"questions\":[...]}。不得声称知识库已有答案。"},
                    {"role": "user", "content": self._suggestion_prompt(system)},
                ],
                response_format={"type": "json_object"}, temperature=0.4, timeout=30,
            )
            raw = json.loads(response.choices[0].message.content or "{}")
            questions = [str(item).strip() for item in raw.get("questions") or [] if str(item).strip()][:6]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"建议问题生成失败：{type(exc).__name__}") from exc
        if not questions:
            raise HTTPException(status_code=502, detail="建议问题生成结果为空")
        return KnowledgeSuggestedQuestions(system_id=system_id, questions=questions, provider="openai_compatible",
                                           model=settings.llm_model, generated_at=datetime.now(timezone.utc).isoformat())

    def stream_query(self, payload: KnowledgeQueryRequest) -> Iterator[str]:
        base_url = self._require_base_url()
        self._ensure_known_system(payload.system_id)
        request_body = {
            "corpus_id": payload.system_id, "question": payload.question, "mode": payload.mode,
            "top_k": payload.top_k, "include_graph_context": payload.include_graph_context,
        }
        try:
            with self._client(base_url) as client:
                with client.stream("POST", "/api/v1/query/stream", json=request_body) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        if event.get("event") == "evidence":
                            event["hits"] = [self._safe_hit(item) for item in event.get("hits") or []]
                            event["citations"] = [self._safe_citation(item) for item in event.get("citations") or []]
                            if event.get("graph_context"):
                                event["graph_context"] = self._normalize_graph(
                                    payload.system_id, event["graph_context"],
                                ).model_dump()
                        yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"event": "failed", "label": "检索问答失败",
                              "message": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n"

    def _normalize_query(self, request: KnowledgeQueryRequest, raw: dict[str, Any]) -> KnowledgeQueryResponse:
        hits = [KnowledgeHit(**self._safe_hit(item)) for item in raw.get("hits") or []]
        citations = [KnowledgeCitation(**self._safe_citation(item)) for item in raw.get("citations") or []]
        graph = self._normalize_graph(request.system_id, raw["graph_context"]) if raw.get("graph_context") else None
        return KnowledgeQueryResponse(
            system_id=request.system_id, question=request.question, mode=request.mode,
            answer=str(raw.get("answer") or ""), hits=hits[: request.top_k], citations=citations[: request.top_k],
            graph_context=graph, configured=bool(raw.get("configured", True)), message=str(raw.get("message") or "ok"),
        )

    def _normalize_graph(self, system_id: str, raw: dict[str, Any]) -> KnowledgeGraphData:
        nodes = [KnowledgeGraphNode(
            id=str(item.get("id")), label=str(item.get("label") or item.get("id")),
            type=str(item.get("type") or "Entity"), score=float(item.get("score") or 1.0),
            properties=self._safe_metadata(item.get("properties") or {}),
        ) for item in raw.get("nodes") or []]
        node_ids = {node.id for node in nodes}
        edges = [KnowledgeGraphEdge(
            id=str(item.get("id")), source=str(item.get("source")), target=str(item.get("target")),
            type=str(item.get("type") or "RELATED_TO"), weight=float(item.get("weight") or 1.0),
            properties=self._safe_metadata(item.get("properties") or {}),
        ) for item in raw.get("edges") or [] if str(item.get("source")) in node_ids and str(item.get("target")) in node_ids]
        stats = raw.get("stats") or {}
        return KnowledgeGraphData(
            system_id=system_id, nodes=nodes, edges=edges,
            stats=KnowledgeGraphStats(entity_count=int(stats.get("entity_count", len(nodes))),
                                      relation_count=int(stats.get("relation_count", len(edges))),
                                      document_count=int(stats.get("document_count", 0))),
            configured=bool(raw.get("configured", True)), message=str(raw.get("message") or "ok"),
            provenance=self._safe_metadata(raw.get("provenance") or {"provider": "literature-rag"}),
        )

    @staticmethod
    def _normalize_corpus(item: dict[str, Any]) -> KnowledgeSystem:
        document_count = int(item.get("document_count") or item.get("indexed_document_count") or 0)
        indexed_document_count = int(item.get("indexed_document_count") or document_count)
        status = str(item.get("status") or ("ready" if indexed_document_count > 0 else "empty"))
        allowed_statuses = {"ready", "indexing", "empty", "warning", "unavailable"}
        if status not in allowed_statuses:
            status = "warning"
        corpus_id = str(item.get("corpus_id") or item.get("system_id") or "")
        provider = str(item.get("provider") or "literature-rag")
        return KnowledgeSystem(
            system_id=corpus_id, name=str(item.get("name") or corpus_id),
            domain=str(item.get("domain") or "literature"),
            material_family=str(item.get("material_family") or corpus_id),
            description=str(item.get("description") or ""), is_demo=False,
            tags=list(item.get("tags") or []), document_count=document_count,
            entity_count=int(item.get("entity_count") or 0), relation_count=int(item.get("relation_count") or 0),
            data_source_id=str(item.get("data_source_id") or f"{provider}:{corpus_id}"),
            provider=provider,
            corpus_id=corpus_id,
            status=status,
            capabilities=list(item.get("capabilities") or ["query", "streaming", "graph", "suggestions"]),
            health_message=str(item.get("health_message") or item.get("message") or ""),
            last_indexed_at=item.get("last_indexed_at"),
            indexed_document_count=indexed_document_count,
        )

    @classmethod
    def _safe_hit(cls, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": str(item.get("source_id") or item.get("document_id") or ""),
            "title": str(item.get("title") or item.get("source_id") or "Untitled source"),
            "snippet": str(item.get("snippet") or item.get("text") or "")[:500],
            "source": item.get("source") or item.get("url"), "doi": item.get("doi"), "url": item.get("url"),
            "journal": item.get("journal"), "year": item.get("year"), "authors": list(item.get("authors") or []),
            "score": float(item.get("score") or 0.0), "metadata": cls._safe_metadata(item.get("metadata") or {}),
        }

    @staticmethod
    def _safe_citation(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": str(item.get("source_id") or item.get("document_id") or ""),
            "title": str(item.get("title") or item.get("source_id") or "Untitled source"),
            "doi": item.get("doi"), "url": item.get("url"), "journal": item.get("journal"),
            "year": item.get("year"), "authors": list(item.get("authors") or []),
            "chunk_id": item.get("chunk_id"),
        }

    @staticmethod
    def _unwrap(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            return raw["data"]
        return raw if isinstance(raw, dict) else {}

    def _fetch_corpora(self, base_url: str) -> dict[str, Any]:
        with self._client(base_url) as client:
            response = client.get("/api/v1/corpora")
            response.raise_for_status()
            return self._unwrap(response.json())

    @classmethod
    def _base_url(cls) -> str:
        explicit = cls._explicit_base_url()
        if explicit:
            return explicit
        if not cls._local_discovery_enabled():
            return ""
        for candidate in LOCAL_RAG_BASE_URL_CANDIDATES:
            if cls._probe_base_url(candidate):
                return candidate
        return ""

    @staticmethod
    def _explicit_base_url() -> str:
        return (os.getenv("LITERATURE_RAG_BASE_URL") or os.getenv("KNOWLEDGE_RAG_BASE_URL") or "").strip().rstrip("/")

    @staticmethod
    def _local_discovery_enabled() -> bool:
        return os.getenv("APP_ENV", settings.app_env).strip().lower() in LOCAL_APP_ENVS

    @staticmethod
    def _probe_base_url(base_url: str) -> bool:
        try:
            with httpx.Client(base_url=base_url, timeout=2.0) as client:
                response = client.get("/health")
                response.raise_for_status()
                raw = KnowledgeService._unwrap(response.json())
        except Exception:
            return False
        return raw.get("service") == "literature-rag" and raw.get("status") in {"ready", "warning"}

    @staticmethod
    def _client(base_url: str) -> httpx.Client:
        api_key = KnowledgeService._api_key()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)

    @staticmethod
    def _api_key() -> str:
        for key in ("LITERATURE_RAG_API_KEY", "KNOWLEDGE_RAG_API_KEY", "LITERATURE_RAG_QUERY_API_KEY"):
            value = os.getenv(key, "").strip()
            if value and value.lower() not in PLACEHOLDER_API_KEYS:
                return value
        return ""

    def _require_base_url(self) -> str:
        base_url = self._base_url()
        if not base_url:
            raise HTTPException(status_code=503, detail="Literature RAG 服务未配置或本地未发现")
        return base_url

    def _get_system(self, system_id: str) -> KnowledgeSystem:
        for item in self.list_systems().items:
            if item.system_id == system_id:
                return item
        raise HTTPException(status_code=404, detail=f"知识库体系 '{system_id}' 不存在")

    def _ensure_known_system(self, system_id: str) -> None:
        self._get_system(system_id)

    @staticmethod
    def _default_system_id() -> str | None:
        return (
            os.getenv("KNOWLEDGE_DEFAULT_SYSTEM_ID", "").strip()
            or os.getenv("LITERATURE_RAG_DEFAULT_CORPUS_ID", "").strip()
            or None
        )

    @staticmethod
    def _suggestion_prompt(system: KnowledgeSystem) -> str:
        tags = "、".join(system.tags[:6]) if system.tags else "未提供标签"
        return (
            "基于以下知识库体系生成 4 个简洁中文检索问题。"
            f"体系名称：{system.name}；领域：{system.domain}；材料族：{system.material_family}；"
            f"标签：{tags}；描述：{system.description or '无'}。"
        )

    @staticmethod
    def _safe_metadata(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        blocked = {"storage_uri", "object_key", "api_key", "token", "secret", "password", "index_path", "embedding"}
        return {str(key): val for key, val in value.items() if str(key).lower() not in blocked}
