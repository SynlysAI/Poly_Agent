"""Knowledge base RAG/KG service.

The platform consumes already-prepared text cards and graph data. It does not
download papers, parse PDFs, or perform data cleaning.
"""

from __future__ import annotations

import json
import os
import time
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
    KnowledgeSystem,
    KnowledgeSystemListData,
    KnowledgeSuggestedQuestions,
)


KNOWLEDGE_SYSTEM_ID = "ai4s_fluoropolymer"

class KnowledgeService:
    """Facade for LightRAG-backed querying and demo graph browsing."""

    def list_systems(self) -> KnowledgeSystemListData:
        items = [
            KnowledgeSystem(
                system_id=KNOWLEDGE_SYSTEM_ID,
                name="AI4S 氟聚合物材料体系",
                domain="AI4S",
                material_family="fluoropolymer",
                description="面向氟聚合物介电、热稳定与结构-性能关系的 LightRAG 知识库。",
                is_demo=False,
                tags=["AI4S", "fluoropolymer", "RAG", "knowledge_graph"],
                document_count=0,
                entity_count=0,
                relation_count=0,
            )
        ]
        return KnowledgeSystemListData(items=items, total=len(items))

    def health(self) -> KnowledgeHealthData:
        base_url = self._base_url()
        systems = [KNOWLEDGE_SYSTEM_ID]
        if not base_url:
            return KnowledgeHealthData(
                status="warning",
                configured=False,
                demo_available=False,
                message="LightRAG 未配置。",
                systems=systems,
            )
        try:
            with self._client(base_url) as client:
                client.get("/health").raise_for_status()
        except Exception as exc:
            return KnowledgeHealthData(
                status="warning",
                configured=False,
                demo_available=False,
                message=f"LightRAG 不可用：{type(exc).__name__}",
                systems=systems,
            )
        return KnowledgeHealthData(
            status="ready",
            configured=True,
            demo_available=False,
            message="LightRAG 服务可用。",
            systems=systems,
        )

    def query(self, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        self._ensure_known_system(payload.system_id)
        base_url = self._base_url()
        if not base_url:
            raise HTTPException(status_code=503, detail="LightRAG 未配置")
        try:
            return self._query_lightrag(base_url, payload)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LightRAG 查询失败：{type(exc).__name__}") from exc

    def get_graph(self, system_id: str) -> KnowledgeGraphData:
        self._ensure_known_system(system_id)
        raise HTTPException(status_code=400, detail="知识图谱必须提供实体或关键词后加载子图")

    def get_subgraph(self, system_id: str, *, query: str | None = None, limit: int = 30) -> KnowledgeGraphData:
        self._ensure_known_system(system_id)
        normalized_query = (query or "").strip()
        if not normalized_query:
            raise HTTPException(status_code=400, detail="请输入实体或关键词")
        base_url = self._base_url()
        if not base_url:
            raise HTTPException(status_code=503, detail="LightRAG 未配置")
        limit = max(1, min(limit, 100))
        try:
            with self._client(base_url) as client:
                labels_response = client.get("/graph/label/search", params={"q": normalized_query, "limit": 5})
                labels_response.raise_for_status()
                labels_raw = labels_response.json()
                labels = labels_raw if isinstance(labels_raw, list) else labels_raw.get("data") or labels_raw.get("labels") or []
                if not labels:
                    raise HTTPException(status_code=404, detail="未找到匹配的真实图谱实体")
                label = str(labels[0])
                graph_response = client.get(
                    "/graphs",
                    params={"label": label, "max_depth": 3, "max_nodes": limit},
                )
                graph_response.raise_for_status()
                raw = graph_response.json()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"LightRAG 图谱查询失败：{type(exc).__name__}") from exc
        return self._normalize_remote_graph(system_id, raw, query=normalized_query, label=label)

    def suggested_questions(self, system_id: str) -> KnowledgeSuggestedQuestions:
        self._ensure_known_system(system_id)
        if not settings.llm_model or not settings.llm_base_url:
            raise HTTPException(status_code=503, detail="建议问题 LLM 未配置")
        try:
            client = OpenAI(api_key=settings.llm_api_key or "EMPTY", base_url=settings.llm_base_url)
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，格式为 {\"questions\":[...]}。问题必须适合材料知识库检索，不得声称已有答案。"},
                    {"role": "user", "content": "为氟聚合物结构、介电性能、热稳定性和 AI4S 筛选生成 4 个简洁中文检索问题。"},
                ],
                response_format={"type": "json_object"},
                temperature=0.4,
                timeout=30,
            )
            payload = json.loads(response.choices[0].message.content or "{}")
            questions = [str(item).strip() for item in payload.get("questions") or [] if str(item).strip()][:6]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"建议问题生成失败：{type(exc).__name__}") from exc
        if not questions:
            raise HTTPException(status_code=502, detail="建议问题生成结果为空")
        return KnowledgeSuggestedQuestions(
            system_id=system_id,
            questions=questions,
            provider="openai_compatible",
            model=settings.llm_model,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def stream_query(self, payload: KnowledgeQueryRequest) -> Iterator[str]:
        """Proxy LightRAG NDJSON while adding observable, non-CoT stage events."""
        self._ensure_known_system(payload.system_id)
        base_url = self._base_url()
        if not base_url:
            raise HTTPException(status_code=503, detail="LightRAG 未配置")
        started = time.monotonic()

        def event(kind: str, **data: Any) -> str:
            return json.dumps({"event": kind, "elapsed_ms": round((time.monotonic() - started) * 1000), **data}, ensure_ascii=False) + "\n"

        yield event("query_prepared", label="问题解析完成")
        yield event("retrieval_started", label="正在检索真实知识源")
        request_body = {
            "query": payload.question,
            "mode": payload.mode,
            "top_k": payload.top_k,
            "stream": True,
            "include_references": True,
            "include_chunk_content": True,
        }
        references_sent = False
        answer_started = False
        try:
            with self._client(base_url) as client:
                with client.stream("POST", "/query/stream", json=request_body) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        raw = json.loads(line)
                        references = raw.get("references") or raw.get("sources")
                        if references is not None and not references_sent:
                            hits, citations = self._normalize_lightrag_references({"references": references})
                            hits = [item for item in hits if item.source_id and (item.doi or item.url or item.source)]
                            citations = [item for item in citations if item.source_id and (item.doi or item.url)]
                            yield event("retrieval_completed", label="检索完成", hit_count=len(hits))
                            yield event("evidence_validated", label="证据来源校验完成", citation_count=len(citations))
                            yield event(
                                "evidence",
                                hits=[item.model_dump(mode="json") for item in hits[: payload.top_k]],
                                citations=[item.model_dump(mode="json") for item in citations[: payload.top_k]],
                            )
                            references_sent = True
                        chunk = raw.get("response") or raw.get("content") or raw.get("text")
                        if chunk:
                            if not answer_started:
                                yield event("answer_started", label="正在生成回答")
                                answer_started = True
                            yield event("answer_delta", content=str(chunk))
            yield event("completed", label="检索问答完成")
        except Exception as exc:
            yield event("failed", label="检索问答失败", message=f"{type(exc).__name__}: {exc}")

    def _normalize_remote_graph(self, system_id: str, raw: dict[str, Any], *, query: str, label: str) -> KnowledgeGraphData:
        payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        raw_nodes = payload.get("nodes") or []
        raw_edges = payload.get("edges") or payload.get("links") or []
        nodes = []
        for index, item in enumerate(raw_nodes):
            properties = self._safe_metadata(item.get("properties") or item)
            source_id = item.get("source_id") or properties.get("source_id")
            if not source_id:
                continue
            nodes.append(KnowledgeGraphNode(
                id=str(item.get("id") or item.get("label") or f"node_{index}"),
                label=str(item.get("label") or item.get("entity_name") or item.get("id")),
                type=str(item.get("type") or item.get("entity_type") or properties.get("entity_type") or "Entity"),
                score=float(item.get("score") or 1.0),
                properties={**properties, "source_id": source_id, "provider": "lightrag"},
            ))
        node_ids = {node.id for node in nodes}
        edges = []
        for index, item in enumerate(raw_edges):
            source = str(item.get("source") or item.get("source_id") or "")
            target = str(item.get("target") or item.get("target_id") or "")
            properties = self._safe_metadata(item.get("properties") or item)
            provenance_id = item.get("chunk_id") or properties.get("source_id") or properties.get("chunk_id")
            if source not in node_ids or target not in node_ids or not provenance_id:
                continue
            edges.append(KnowledgeGraphEdge(
                id=str(item.get("id") or f"edge_{index}"),
                source=source,
                target=target,
                type=str(item.get("type") or item.get("relation") or "RELATED_TO"),
                weight=float(item.get("weight") or 1.0),
                properties={**properties, "source_id": provenance_id, "provider": "lightrag"},
            ))
        return KnowledgeGraphData(
            system_id=system_id,
            nodes=nodes,
            edges=edges,
            stats=KnowledgeGraphStats(entity_count=len(nodes), relation_count=len(edges), document_count=0),
            configured=True,
            message="LightRAG knowledge subgraph.",
            provenance={
                "provider": "lightrag",
                "query": query,
                "matched_label": label,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _query_lightrag(self, base_url: str, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        request_body = {
            "query": payload.question,
            "mode": payload.mode,
            "top_k": payload.top_k,
            "only_need_context": False,
            "include_references": True,
        }
        with self._client(base_url) as client:
            response = client.post("/query", json=request_body)
            response.raise_for_status()
            raw = response.json()
        answer = str(raw.get("response") or raw.get("answer") or raw.get("result") or "")
        hits, citations = self._normalize_lightrag_references(raw)
        graph_context = self.get_subgraph(payload.system_id, query=payload.question, limit=12) if payload.include_graph_context else None
        return KnowledgeQueryResponse(
            system_id=payload.system_id,
            question=payload.question,
            mode=payload.mode,
            answer=answer,
            hits=hits[: payload.top_k],
            citations=citations[: payload.top_k],
            graph_context=graph_context,
            configured=True,
            message="LightRAG query completed.",
        )

    def _normalize_lightrag_references(self, raw: dict[str, Any]) -> tuple[list[KnowledgeHit], list[KnowledgeCitation]]:
        references = raw.get("references") or raw.get("sources") or raw.get("context") or []
        if isinstance(references, dict):
            references = references.get("chunks") or references.get("items") or []
        if not isinstance(references, list):
            references = []
        hits: list[KnowledgeHit] = []
        citations: list[KnowledgeCitation] = []
        for idx, item in enumerate(references):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("reference_id") or item.get("source_id") or item.get("id") or f"lightrag_ref_{idx + 1}")
            title = str(item.get("title") or item.get("file_path") or item.get("source") or source_id)
            snippet = str(item.get("content") or item.get("snippet") or item.get("text") or "")[:500]
            source = str(item.get("file_path") or item.get("source") or item.get("url") or "") or None
            metadata = self._safe_metadata(item.get("metadata", {}))
            hits.append(KnowledgeHit(
                source_id=source_id,
                title=title,
                snippet=snippet,
                source=source,
                doi=item.get("doi") or metadata.get("doi"),
                url=item.get("url") or metadata.get("url"),
                journal=item.get("journal") or metadata.get("journal"),
                year=item.get("year") or metadata.get("year"),
                authors=list(item.get("authors") or metadata.get("authors") or []),
                score=float(item.get("score") or item.get("similarity") or 0.0),
                metadata=metadata,
            ))
            citations.append(KnowledgeCitation(
                source_id=source_id,
                title=title,
                doi=item.get("doi") or metadata.get("doi"),
                url=item.get("url") or metadata.get("url"),
                journal=item.get("journal") or metadata.get("journal"),
                year=item.get("year") or metadata.get("year"),
                authors=list(item.get("authors") or metadata.get("authors") or []),
                chunk_id=item.get("chunk_id") or source_id,
            ))
        return hits, citations

    @staticmethod
    def _base_url() -> str:
        return os.getenv("KNOWLEDGE_RAG_BASE_URL", "").strip().rstrip("/")

    @staticmethod
    def _client(base_url: str) -> httpx.Client:
        headers = {}
        api_key = os.getenv("KNOWLEDGE_RAG_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)

    @staticmethod
    def _ensure_known_system(system_id: str) -> None:
        if system_id != KNOWLEDGE_SYSTEM_ID:
            raise HTTPException(status_code=404, detail=f"知识库体系 '{system_id}' 不存在")

    @staticmethod
    def _safe_metadata(value: Any) -> dict:
        if not isinstance(value, dict):
            return {}
        blocked = {"storage_uri", "api_key", "token", "secret", "password", "index_path"}
        return {str(key): val for key, val in value.items() if str(key).lower() not in blocked}

    def _safe_node(self, value: dict[str, Any]) -> dict[str, Any]:
        item = dict(value)
        item["properties"] = self._safe_metadata(item.get("properties", {}))
        return item

    def _safe_edge(self, value: dict[str, Any]) -> dict[str, Any]:
        item = dict(value)
        item["properties"] = self._safe_metadata(item.get("properties", {}))
        return item
