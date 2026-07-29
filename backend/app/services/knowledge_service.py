"""WeKnora 知识库服务适配层。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import quote

import httpx
from fastapi import HTTPException

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


WEKNORA_PROVIDER = "weknora"
WEKNORA_SOURCE_MODE = "weknora-api"
WEKNORA_GRAPH_BACKEND = "search-synthesis"
WEKNORA_NEO4J_GRAPH_BACKEND = "weknora-neo4j"
WEKNORA_WIKI_GRAPH_BACKEND = "weknora-wiki-graph"
WEKNORA_DEFAULT_SUGGESTION_AGENT_ID = "builtin-quick-answer"
PLACEHOLDER_API_KEYS = {
    "replace-with-query-key",
    "replace-with-admin-key",
    "your-api-key",
    "your-query-api-key",
    "<query-service-key>",
}


class KnowledgeService:
    """将 PolyAgent 知识库契约映射到 WeKnora API。"""

    def list_systems(self) -> KnowledgeSystemListData:
        """列出 WeKnora 中可查询的知识库。"""
        base_url = self._base_url()
        default_system_id = self._default_system_id()
        if not base_url:
            return KnowledgeSystemListData(items=[], total=0, default_system_id=default_system_id)
        try:
            raw = self._list_weknora_knowledge_bases(base_url)
        except Exception:
            return KnowledgeSystemListData(items=[], total=0, default_system_id=default_system_id)
        items = [self._normalize_knowledge_base(item) for item in self._raw_items(raw)]
        return KnowledgeSystemListData(
            items=items,
            total=len(items),
            default_system_id=default_system_id,
        )

    def health(self) -> KnowledgeHealthData:
        """返回 WeKnora 知识库服务健康状态。"""
        base_url = self._base_url()
        if not base_url:
            return KnowledgeHealthData(
                status="unavailable",
                configured=False,
                demo_available=False,
                message="WeKnora 服务未配置。",
                systems=[],
                backend=WEKNORA_PROVIDER,
                graph_backend=WEKNORA_GRAPH_BACKEND,
                source_mode=WEKNORA_SOURCE_MODE,
                is_demo=False,
            )
        try:
            raw = self._list_weknora_knowledge_bases(base_url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return KnowledgeHealthData(
                    status="warning",
                    configured=False,
                    demo_available=False,
                    message="WeKnora 已连接，但 X-API-Key 未配置或无效。",
                    systems=[],
                    backend=WEKNORA_PROVIDER,
                    graph_backend=WEKNORA_GRAPH_BACKEND,
                    source_mode=WEKNORA_SOURCE_MODE,
                    is_demo=False,
                )
            return KnowledgeHealthData(
                status="warning",
                configured=False,
                demo_available=False,
                message=f"WeKnora 知识库列表不可用：HTTP {exc.response.status_code}",
                systems=[],
                backend=WEKNORA_PROVIDER,
                graph_backend=WEKNORA_GRAPH_BACKEND,
                source_mode=WEKNORA_SOURCE_MODE,
                is_demo=False,
            )
        except Exception as exc:
            return KnowledgeHealthData(
                status="unavailable",
                configured=False,
                demo_available=False,
                message=f"WeKnora 服务不可用：{type(exc).__name__}",
                systems=[],
                backend=WEKNORA_PROVIDER,
                graph_backend=WEKNORA_GRAPH_BACKEND,
                source_mode=WEKNORA_SOURCE_MODE,
                is_demo=False,
            )
        systems = [item.system_id for item in [self._normalize_knowledge_base(kb) for kb in self._raw_items(raw)]]
        configured = bool(systems)
        return KnowledgeHealthData(
            status="ready" if configured else "warning",
            configured=configured,
            demo_available=False,
            message="WeKnora 服务可用，已加载知识库。" if configured else "WeKnora 服务可用，但未发现知识库。",
            systems=systems,
            backend=WEKNORA_PROVIDER,
            graph_backend=str(raw.get("graph_backend") or WEKNORA_GRAPH_BACKEND),
            source_mode=WEKNORA_SOURCE_MODE,
            is_demo=False,
            graph_node_count=0,
            graph_relationship_count=0,
        )

    def query(self, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        """通过 WeKnora 知识问答接口执行非流式查询。"""
        base_url = self._require_base_url()
        self._ensure_known_system(payload.system_id)
        try:
            session_id = self._create_session(base_url, payload.question)
            answer, references = self._consume_chat_stream(base_url, session_id, payload)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="WeKnora 知识问答失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"WeKnora 知识问答失败：{type(exc).__name__}") from exc
        raw = {
            "answer": answer,
            "hits": references,
            "citations": references,
            "configured": True,
            "message": "weknora_chat",
        }
        if payload.include_graph_context and references:
            raw["graph_context"] = self._graph_from_search_results(
                payload.system_id,
                references,
                query=payload.question,
                limit=payload.top_k,
            ).model_dump()
        return self._normalize_query(payload, raw)

    def search_hits(self, system_id: str, query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        """调用 WeKnora 检索接口并返回归一化命中片段。

        Args:
            system_id: WeKnora 知识库 ID。
            query: 用户检索问题。
            limit: 最大返回命中数。

        Returns:
            归一化后的知识库命中片段列表。
        """
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []
        base_url = self._require_base_url()
        self._ensure_known_system(system_id)
        results = self._search_knowledge(
            base_url,
            system_id,
            normalized_query,
            limit=max(1, min(limit, 20)),
        )
        return [KnowledgeHit(**self._safe_hit(item)) for item in results[:limit]]

    def search_hits_many(self, system_ids: list[str], query: str, *, limit: int = 5) -> list[KnowledgeHit]:
        """调用 WeKnora 多知识库检索接口并返回归一化命中片段。

        Args:
            system_ids: WeKnora 知识库 ID 列表。
            query: 用户检索问题。
            limit: 最大返回命中数。

        Returns:
            归一化后的知识库命中片段列表。
        """
        normalized_query = str(query or "").strip()
        normalized_ids = self._normalize_system_ids(system_ids)
        if not normalized_query or not normalized_ids:
            return []
        base_url = self._require_base_url()
        for system_id in normalized_ids:
            self._ensure_known_system(system_id)
        results = self._search_knowledge_many(
            base_url,
            normalized_ids,
            normalized_query,
            limit=max(1, min(limit, 20)),
        )
        hits = [KnowledgeHit(**self._safe_hit(item)) for item in results[: max(1, min(limit, 20))]]
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]

    def get_graph(self, system_id: str) -> KnowledgeGraphData:
        """加载 WeKnora Wiki 页面链接图谱概览。"""
        base_url = self._require_base_url()
        self._ensure_known_system(system_id)
        try:
            raw = self._get_wiki_graph(base_url, system_id, mode="overview", limit=500)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="WeKnora Wiki 图谱查询失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"WeKnora Wiki 图谱查询失败：{type(exc).__name__}") from exc
        return self._graph_from_wiki_graph(base_url, system_id, raw, query="", limit=500)

    def get_subgraph(self, system_id: str, *, query: str | None = None, limit: int = 30) -> KnowledgeGraphData:
        """优先加载 WeKnora Wiki 图谱切片，失败时回退到检索实体子图。"""
        base_url = self._require_base_url()
        self._ensure_known_system(system_id)
        normalized_query = (query or "").strip()
        normalized_limit = max(1, min(limit, 100))
        try:
            return self._wiki_subgraph(base_url, system_id, query=normalized_query, limit=normalized_limit)
        except Exception:
            if not normalized_query:
                raise HTTPException(status_code=400, detail="请输入实体或关键词")
        try:
            results = self._search_knowledge(base_url, system_id, normalized_query, limit=normalized_limit)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=exc.response.status_code, detail="WeKnora 检索子图查询失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"WeKnora 检索子图查询失败：{type(exc).__name__}") from exc
        return self._graph_from_search_results(system_id, results, query=normalized_query, limit=normalized_limit)

    def fetch_file_resource(self, system_id: str, file_path: str) -> tuple[bytes, str]:
        """代理读取 WeKnora 知识库内的受保护文件资源。

        Args:
            system_id: WeKnora 知识库 ID。
            file_path: WeKnora 回答中的文件资源路径。

        Returns:
            文件内容字节与 Content-Type。
        """
        base_url = self._require_base_url()
        self._ensure_known_system(system_id)
        normalized_path = str(file_path or "").strip()
        if not self._is_allowed_file_resource(normalized_path):
            raise HTTPException(status_code=400, detail="不支持的知识库资源路径")
        try:
            with self._client(base_url) as client:
                response = client.get(
                    f"/knowledge-bases/{system_id}/files",
                    params={"file_path": normalized_path},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise HTTPException(
                    status_code=403,
                    detail="当前 WeKnora API Key 无文件资源读取权限，请使用租户级 full_access Key 或非知识库受限且具备 retrieve 能力的 Key。",
                ) from exc
            raise HTTPException(status_code=exc.response.status_code, detail="WeKnora 文件资源读取失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"WeKnora 文件资源读取失败：{type(exc).__name__}") from exc
        return response.content, response.headers.get("content-type") or "application/octet-stream"

    def suggested_questions(self, system_id: str) -> KnowledgeSuggestedQuestions:
        """优先从 WeKnora 获取知识库推荐问题。"""
        base_url = self._require_base_url()
        system = self._get_system(system_id)
        try:
            questions = self._get_weknora_suggested_questions(base_url, system_id, limit=6)
        except Exception:
            questions = []
        if questions:
            return KnowledgeSuggestedQuestions(
                system_id=system_id,
                questions=questions[:6],
                provider=WEKNORA_PROVIDER,
                model="weknora_agent_suggestions",
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
        return self._fallback_suggested_questions(system)

    def _fallback_suggested_questions(self, system: KnowledgeSystem) -> KnowledgeSuggestedQuestions:
        """在 WeKnora 推荐问题不可用时生成兜底问题。

        Args:
            system: 当前知识库体系。

        Returns:
            固定模板生成的推荐问题。
        """
        name = system.name or system.system_id
        topic = system.description or name
        questions = [
            f"{name} 知识库目前包含哪些核心资料？",
            f"请总结 {topic} 的关键结论和证据来源。",
            f"{name} 中有哪些高相关文档可以用于当前研究？",
            f"围绕 {topic}，哪些证据支持材料设计决策？",
        ]
        return KnowledgeSuggestedQuestions(
            system_id=system.system_id,
            questions=questions[:6],
            provider=WEKNORA_PROVIDER,
            model="metadata_templates",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def stream_query(self, payload: KnowledgeQueryRequest) -> Iterator[str]:
        """将 WeKnora SSE 事件转换为前端兼容的 NDJSON 事件。"""
        try:
            base_url = self._require_base_url()
            self._ensure_known_system(payload.system_id)
            session_id = self._create_session(base_url, payload.question)
            yield self._ndjson({
                "event": "progress",
                "label": "已创建 WeKnora 会话",
                "session_id": session_id,
            })
            references: list[dict[str, Any]] = []
            done_emitted = False
            try:
                references = self._search_knowledge(
                    base_url,
                    payload.system_id,
                    payload.question,
                    limit=payload.top_k,
                )
            except Exception:
                references = []
            if references:
                yield self._ndjson({
                    "event": "evidence",
                    "label": "WeKnora 已返回命中证据",
                    "hits": [self._safe_hit(item) for item in references][: payload.top_k],
                    "citations": [self._safe_citation(item) for item in references][: payload.top_k],
                    "graph_context": (
                        self._graph_from_search_results(
                            payload.system_id,
                            references,
                            query=payload.question,
                            limit=payload.top_k,
                        ).model_dump()
                        if payload.include_graph_context
                        else None
                    ),
                })
            for event in self._iter_chat_stream(base_url, session_id, payload):
                event_type = str(event.get("response_type") or "")
                if event_type == "references":
                    references = self._merge_reference_items(
                        references,
                        list(event.get("knowledge_references") or []),
                    )
                    graph_context = (
                        self._graph_from_search_results(
                            payload.system_id,
                            references,
                            query=payload.question,
                            limit=payload.top_k,
                        ).model_dump()
                        if payload.include_graph_context and references
                        else None
                    )
                    yield self._ndjson({
                        "event": "evidence",
                        "label": "WeKnora 已返回检索证据",
                        "hits": [self._safe_hit(item) for item in references][: payload.top_k],
                        "citations": [self._safe_citation(item) for item in references][: payload.top_k],
                        "graph_context": graph_context,
                    })
                elif event_type == "answer":
                    yield self._ndjson({
                        "event": "answer_delta",
                        "content": str(event.get("content") or ""),
                    })
                    if bool(event.get("done")) and not done_emitted:
                        done_emitted = True
                        yield self._ndjson({"event": "done", "label": "WeKnora 回答完成"})
                elif event_type == "complete" and not done_emitted:
                    done_emitted = True
                    yield self._ndjson({"event": "done", "label": "WeKnora 回答完成"})
                elif event_type == "error":
                    yield self._ndjson({
                        "event": "failed",
                        "label": "WeKnora 回答失败",
                        "message": str(event.get("content") or "WeKnora 流式回答失败"),
                    })
                elif event_type in {"thinking", "tool_call", "tool_result", "reflection"}:
                    yield self._ndjson({
                        "event": "progress",
                        "label": self._stream_label(event_type),
                    })
            if not references:
                results = self._search_knowledge(
                    base_url,
                    payload.system_id,
                    payload.question,
                    limit=payload.top_k,
                )
                yield self._ndjson({
                    "event": "evidence",
                    "label": "WeKnora 已返回检索证据",
                    "hits": [self._safe_hit(item) for item in results][: payload.top_k],
                    "citations": [self._safe_citation(item) for item in results][: payload.top_k],
                    "graph_context": (
                        self._graph_from_search_results(
                            payload.system_id,
                            results,
                            query=payload.question,
                            limit=payload.top_k,
                        ).model_dump()
                        if payload.include_graph_context and results
                        else None
                    ),
                })
        except Exception as exc:
            yield self._ndjson({
                "event": "failed",
                "label": "检索问答失败",
                "message": f"{type(exc).__name__}: {exc}",
            })

    def _normalize_query(self, request: KnowledgeQueryRequest, raw: dict[str, Any]) -> KnowledgeQueryResponse:
        """将 WeKnora 回答归一为 PolyAgent 查询响应。"""
        hits = [KnowledgeHit(**self._safe_hit(item)) for item in raw.get("hits") or []]
        citations = [KnowledgeCitation(**self._safe_citation(item)) for item in raw.get("citations") or []]
        graph = self._normalize_graph(request.system_id, raw["graph_context"]) if raw.get("graph_context") else None
        return KnowledgeQueryResponse(
            system_id=request.system_id,
            question=request.question,
            mode=request.mode,
            answer=str(raw.get("answer") or ""),
            hits=hits[: request.top_k],
            citations=citations[: request.top_k],
            graph_context=graph,
            configured=bool(raw.get("configured", True)),
            message=str(raw.get("message") or "weknora_chat"),
        )

    def _normalize_graph(self, system_id: str, raw: dict[str, Any]) -> KnowledgeGraphData:
        """归一化前端知识图谱数据。"""
        nodes = [
            KnowledgeGraphNode(
                id=str(item.get("id")),
                label=str(item.get("label") or item.get("id")),
                type=self._normalize_node_type(item),
                score=float(item.get("score") or 1.0),
                properties=self._safe_metadata(item.get("properties") or {}),
            )
            for item in raw.get("nodes") or []
        ]
        node_ids = {node.id for node in nodes}
        edges = [
            KnowledgeGraphEdge(
                id=str(item.get("id")),
                source=str(item.get("source")),
                target=str(item.get("target")),
                type=str(item.get("type") or "CONTAINS"),
                weight=float(item.get("weight") or 1.0),
                properties=self._safe_metadata(item.get("properties") or {}),
            )
            for item in raw.get("edges") or []
            if str(item.get("source")) in node_ids and str(item.get("target")) in node_ids
        ]
        stats = raw.get("stats") or {}
        return KnowledgeGraphData(
            system_id=system_id,
            nodes=nodes,
            edges=edges,
            stats=KnowledgeGraphStats(
                entity_count=int(stats.get("entity_count", len(nodes))),
                relation_count=int(stats.get("relation_count", len(edges))),
                document_count=int(stats.get("document_count", 0)),
                node_type_counts={str(k): int(v) for k, v in (stats.get("node_type_counts") or {}).items()},
                category_counts={str(k): int(v) for k, v in (stats.get("category_counts") or {}).items()},
            ),
            configured=bool(raw.get("configured", True)),
            message=str(raw.get("message") or "weknora_search_synthesis"),
            backend=WEKNORA_PROVIDER,
            graph_backend=str(raw.get("graph_backend") or WEKNORA_GRAPH_BACKEND),
            source_mode=WEKNORA_SOURCE_MODE,
            is_demo=False,
            provenance=self._safe_metadata(raw.get("provenance") or {"provider": WEKNORA_PROVIDER}),
        )

    def _wiki_subgraph(
        self,
        base_url: str,
        system_id: str,
        *,
        query: str,
        limit: int,
    ) -> KnowledgeGraphData:
        """根据关键词加载 WeKnora Wiki 图谱切片。

        Args:
            base_url: WeKnora API 基础地址。
            system_id: WeKnora 知识库 ID。
            query: 前端输入的图谱检索关键词。
            limit: 节点数量上限。

        Returns:
            前端可渲染的 Wiki 页面链接图谱数据。
        """
        center = self._wiki_search_first_slug(base_url, system_id, query, limit=1) if query else ""
        if center:
            raw = self._get_wiki_graph(
                base_url,
                system_id,
                mode="ego",
                center=center,
                depth=2,
                limit=limit,
            )
        else:
            raw = self._get_wiki_graph(base_url, system_id, mode="overview", limit=limit)
        return self._graph_from_wiki_graph(base_url, system_id, raw, query=query, limit=limit, center=center)

    def _get_wiki_graph(
        self,
        base_url: str,
        system_id: str,
        *,
        mode: str,
        limit: int,
        center: str = "",
        depth: int | None = None,
    ) -> dict[str, Any]:
        """调用 WeKnora Wiki 页面链接图谱接口。

        Args:
            base_url: WeKnora API 基础地址。
            system_id: WeKnora 知识库 ID。
            mode: 图谱模式，支持 overview 或 ego。
            limit: 节点数量上限。
            center: ego 模式中心页面 slug。
            depth: ego 模式扩展深度。

        Returns:
            WeKnora Wiki Graph 原始响应。
        """
        params: dict[str, Any] = {
            "mode": mode,
            "limit": max(1, min(limit, 500)),
        }
        if center:
            params["center"] = center
        if depth is not None:
            params["depth"] = depth
        with self._client(base_url) as client:
            response = client.get(f"/knowledgebase/{system_id}/wiki/graph", params=params)
            response.raise_for_status()
            return self._unwrap(response.json())

    def _wiki_search_first_slug(self, base_url: str, system_id: str, query: str, *, limit: int) -> str:
        """检索 Wiki 页面并返回最相关页面 slug。

        Args:
            base_url: WeKnora API 基础地址。
            system_id: WeKnora 知识库 ID。
            query: Wiki 页面检索关键词。
            limit: 检索数量上限。

        Returns:
            最相关 Wiki 页面的 slug；无结果时返回空字符串。
        """
        if not query:
            return ""
        try:
            with self._client(base_url) as client:
                response = client.get(
                    f"/knowledgebase/{system_id}/wiki/search",
                    params={"q": query, "limit": max(1, min(limit, 20))},
                )
                response.raise_for_status()
                raw = self._unwrap(response.json())
        except Exception:
            return ""
        items = self._raw_items(raw)
        if not items and isinstance(raw.get("pages"), list):
            items = [item for item in raw["pages"] if isinstance(item, dict)]
        first = items[0] if items else {}
        return str(first.get("slug") or "").strip()

    def _get_weknora_suggested_questions(self, base_url: str, system_id: str, *, limit: int) -> list[str]:
        """调用 WeKnora 智能体推荐问题接口。

        Args:
            base_url: WeKnora API 基础地址。
            system_id: WeKnora 知识库 ID。
            limit: 推荐问题数量上限。

        Returns:
            WeKnora 返回的推荐问题文本列表。
        """
        agent_id = (
            os.getenv("WEKNORA_SUGGESTION_AGENT_ID", "").strip()
            or WEKNORA_DEFAULT_SUGGESTION_AGENT_ID
        )
        with self._client(base_url) as client:
            response = client.get(
                f"/agents/{agent_id}/suggested-questions",
                params={
                    "knowledge_base_ids": system_id,
                    "limit": max(1, min(limit, 8)),
                },
            )
            response.raise_for_status()
            raw = self._unwrap(response.json())
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        raw_questions = (data or {}).get("questions") or []
        questions: list[str] = []
        for item in raw_questions:
            if isinstance(item, dict):
                question = str(item.get("question") or "").strip()
            else:
                question = str(item or "").strip()
            if question and question not in questions:
                questions.append(question)
        return questions

    def _graph_from_wiki_graph(
        self,
        base_url: str,
        system_id: str,
        raw: dict[str, Any],
        *,
        query: str,
        limit: int,
        center: str = "",
    ) -> KnowledgeGraphData:
        """将 WeKnora Wiki 页面链接图谱转换为 PolyAgent 图谱格式。

        Args:
            system_id: WeKnora 知识库 ID。
            raw: WeKnora Wiki Graph 原始响应。
            query: 当前图谱检索关键词。
            limit: 节点数量上限。
            center: ego 模式中心页面 slug。

        Returns:
            前端可渲染的知识图谱数据。
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        type_counts: dict[str, int] = {}
        page_cache: dict[str, dict[str, Any]] = {}
        for item in raw.get("nodes") or []:
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            page = self._get_wiki_page_safe(base_url, system_id, slug, page_cache)
            page_type = str(item.get("page_type") or "wiki").strip()
            node_type = self._normalize_wiki_node_type(page_type)
            type_counts[node_type] = type_counts.get(node_type, 0) + 1
            nodes.append({
                "id": f"wiki:{slug}",
                "label": str(item.get("title") or slug),
                "type": node_type,
                "score": float(item.get("link_count") or 1),
                "properties": {
                    "slug": slug,
                    "page_type": page_type,
                    "link_count": int(item.get("link_count") or 0),
                    **self._wiki_page_detail_properties(page),
                    "provider": WEKNORA_PROVIDER,
                    "graph_backend": WEKNORA_WIKI_GRAPH_BACKEND,
                },
            })
        node_ids = {node["id"] for node in nodes}
        for index, item in enumerate(raw.get("edges") or []):
            source = f"wiki:{item.get('source')}"
            target = f"wiki:{item.get('target')}"
            if source not in node_ids or target not in node_ids:
                continue
            edges.append({
                "id": f"{source}->WIKI_LINK->{target}:{index}",
                "source": source,
                "target": target,
                "type": "WIKI_LINK",
                "weight": 1.0,
                "properties": {
                    "provider": WEKNORA_PROVIDER,
                    "graph_backend": WEKNORA_WIKI_GRAPH_BACKEND,
                },
            })
        meta = raw.get("meta") or {}
        graph_raw = {
            "nodes": nodes[: max(1, min(limit, 500))],
            "edges": edges,
            "stats": {
                "entity_count": len(nodes),
                "relation_count": len(edges),
                "document_count": int(meta.get("total") or len(nodes)),
                "node_type_counts": type_counts,
                "category_counts": {
                    str(key): int(value)
                    for key, value in type_counts.items()
                },
            },
            "configured": True,
            "message": "weknora_wiki_graph",
            "provenance": {
                "provider": WEKNORA_PROVIDER,
                "query": query,
                "center": center,
                "wiki_mode": meta.get("mode"),
                "wiki_total": meta.get("total"),
                "wiki_returned": meta.get("returned"),
                "wiki_truncated": meta.get("truncated"),
            },
            "graph_backend": WEKNORA_WIKI_GRAPH_BACKEND,
        }
        return self._normalize_graph(system_id, graph_raw)

    def _get_wiki_page_safe(
        self,
        base_url: str,
        system_id: str,
        slug: str,
        cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """按 slug 获取 Wiki 页面详情，失败时返回空字典。"""
        if slug in cache:
            return cache[slug]
        try:
            with self._client(base_url) as client:
                response = client.get(f"/knowledgebase/{system_id}/wiki/pages/{quote(slug, safe='')}")
                response.raise_for_status()
                page = self._unwrap(response.json())
        except Exception:
            page = {}
        cache[slug] = page if isinstance(page, dict) else {}
        return cache[slug]

    @classmethod
    def _wiki_page_detail_properties(cls, page: dict[str, Any]) -> dict[str, Any]:
        """提取适合前端节点详情展示的 Wiki 页面字段。"""
        if not page:
            return {}
        summary = str(page.get("summary") or "").strip()
        content = str(page.get("content") or "").strip()
        return {
            "summary": summary,
            "content_preview": cls._compact_wiki_content(content),
            "source_refs": cls._safe_string_list(page.get("source_refs"))[:8],
            "chunk_refs": cls._safe_string_list(page.get("chunk_refs"))[:12],
            "aliases": cls._safe_string_list(page.get("aliases"))[:8],
            "category_path": cls._safe_string_list(page.get("category_path"))[:8],
            "wiki_path": str(page.get("wiki_path") or "").strip(),
            "status": str(page.get("status") or "").strip(),
            "updated_at": str(page.get("updated_at") or "").strip(),
        }

    def _graph_from_search_results(
        self,
        system_id: str,
        results: list[dict[str, Any]],
        *,
        query: str,
        limit: int,
    ) -> KnowledgeGraphData:
        """用 WeKnora 检索命中文档和片段构造轻量子图。

        Args:
            system_id: WeKnora 知识库 ID。
            results: WeKnora 检索或引用结果列表。
            query: 当前查询文本。
            limit: 子图节点数量上限。

        Returns:
            前端可渲染的图谱数据。
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        for index, item in enumerate(results[: max(1, min(limit, 100))]):
            hit = self._safe_hit(item)
            doc_id = f"doc:{hit['source_id'] or item.get('knowledge_id') or index}"
            chunk_id = f"chunk:{item.get('id') or item.get('parent_chunk_id') or item.get('chunk_id') or index}"
            if doc_id not in seen_nodes:
                nodes.append({
                    "id": doc_id,
                    "label": hit["title"],
                    "type": "Paper",
                    "score": max(float(hit.get("score") or 0.0), 0.1),
                    "properties": hit["metadata"] | {
                        "source_url": hit.get("url") or hit.get("source"),
                        "provider": WEKNORA_PROVIDER,
                    },
                })
                seen_nodes.add(doc_id)
            if chunk_id not in seen_nodes:
                nodes.append({
                    "id": chunk_id,
                    "label": self._compact_label(hit["snippet"]) or f"片段 {index + 1}",
                    "type": "Chunk",
                    "score": max(float(hit.get("score") or 0.0), 0.1),
                    "properties": hit["metadata"] | {
                        "snippet": hit["snippet"],
                        "source_url": hit.get("url") or hit.get("source"),
                        "provider": WEKNORA_PROVIDER,
                    },
                })
                seen_nodes.add(chunk_id)
            edges.append({
                "id": f"{doc_id}->{chunk_id}",
                "source": doc_id,
                "target": chunk_id,
                "type": "HAS_CHUNK",
                "weight": max(float(hit.get("score") or 0.0), 0.1),
                "properties": {"query": query, "provider": WEKNORA_PROVIDER},
            })
        graph_raw = {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "entity_count": len(nodes),
                "relation_count": len(edges),
                "document_count": len({edge["source"] for edge in edges}),
                "node_type_counts": {
                    "Paper": len([node for node in nodes if node["type"] == "Paper"]),
                    "Chunk": len([node for node in nodes if node["type"] == "Chunk"]),
                },
            },
            "configured": True,
            "message": "weknora_search_synthesis",
            "provenance": {"provider": WEKNORA_PROVIDER, "query": query},
            "graph_backend": WEKNORA_GRAPH_BACKEND,
        }
        enhanced_raw = self._enhance_graph_with_neo4j(
            graph_raw,
            system_id=system_id,
            results=results,
            query=query,
            limit=limit,
        )
        return self._normalize_graph(
            system_id,
            enhanced_raw,
        )

    def _enhance_graph_with_neo4j(
        self,
        graph_raw: dict[str, Any],
        *,
        system_id: str,
        results: list[dict[str, Any]],
        query: str,
        limit: int,
    ) -> dict[str, Any]:
        """用 WeKnora Neo4j 实体关系增强检索子图。

        Args:
            graph_raw: 已由检索结果合成的 Paper/Chunk 子图。
            system_id: WeKnora 知识库 ID。
            results: WeKnora 检索命中结果。
            query: 当前查询文本。
            limit: 图谱节点数量上限。

        Returns:
            合并 Neo4j 实体关系后的图谱原始数据；不可用时返回原始子图。
        """
        if not self._neo4j_configured():
            return graph_raw
        try:
            neo4j_graph = self._query_weknora_neo4j(results, system_id=system_id, limit=limit)
        except Exception as exc:
            provenance = dict(graph_raw.get("provenance") or {})
            provenance["neo4j_status"] = "unavailable"
            provenance["neo4j_error"] = type(exc).__name__
            return graph_raw | {"provenance": provenance}
        if not neo4j_graph["nodes"]:
            provenance = dict(graph_raw.get("provenance") or {})
            provenance["neo4j_status"] = "empty"
            return graph_raw | {"provenance": provenance}
        nodes = list(graph_raw.get("nodes") or [])
        edges = list(graph_raw.get("edges") or [])
        seen_nodes = {str(node.get("id")) for node in nodes}
        seen_edges = {str(edge.get("id")) for edge in edges}
        chunk_node_ids = {
            str(node.get("properties", {}).get("chunk_id") or "")
            for node in nodes
            if str(node.get("type") or "") == "Chunk"
        }
        for node in neo4j_graph["nodes"]:
            if node["id"] not in seen_nodes:
                nodes.append(node)
                seen_nodes.add(node["id"])
            for chunk_id in node.get("properties", {}).get("chunks", []) or []:
                chunk_graph_id = f"chunk:{chunk_id}"
                if chunk_id not in chunk_node_ids or chunk_graph_id not in seen_nodes:
                    continue
                edge_id = f"{chunk_graph_id}->mentions->{node['id']}"
                if edge_id in seen_edges:
                    continue
                edges.append({
                    "id": edge_id,
                    "source": chunk_graph_id,
                    "target": node["id"],
                    "type": "MENTIONS",
                    "weight": 1.0,
                    "properties": {
                        "provider": WEKNORA_PROVIDER,
                        "graph_backend": WEKNORA_NEO4J_GRAPH_BACKEND,
                    },
                })
                seen_edges.add(edge_id)
        for edge in neo4j_graph["edges"]:
            if edge["id"] not in seen_edges and edge["source"] in seen_nodes and edge["target"] in seen_nodes:
                edges.append(edge)
                seen_edges.add(edge["id"])
        node_type_counts: dict[str, int] = {}
        for node in nodes:
            node_type = str(node.get("type") or "Entity")
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1
        provenance = dict(graph_raw.get("provenance") or {})
        provenance.update({
            "provider": WEKNORA_PROVIDER,
            "query": query,
            "neo4j_status": "ready",
            "neo4j_uri": self._redact_neo4j_uri(settings.weknora_neo4j_uri),
        })
        return {
            **graph_raw,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "entity_count": len(nodes),
                "relation_count": len(edges),
                "document_count": len({edge["source"] for edge in edges if str(edge.get("source", "")).startswith("doc:")}),
                "node_type_counts": node_type_counts,
            },
            "message": "weknora_neo4j_enhanced",
            "graph_backend": WEKNORA_NEO4J_GRAPH_BACKEND,
            "provenance": provenance,
        }

    def _query_weknora_neo4j(
        self,
        results: list[dict[str, Any]],
        *,
        system_id: str,
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """按 WeKnora 检索命中的 chunk 从 Neo4j 反查实体关系。

        Args:
            results: WeKnora 检索命中结果。
            system_id: WeKnora 知识库 ID。
            limit: 返回节点数量上限。

        Returns:
            包含 nodes 和 edges 的图谱增强数据。
        """
        from neo4j import GraphDatabase

        groups = self._neo4j_lookup_groups(results, system_id=system_id)
        if not groups:
            return {"nodes": [], "edges": []}
        driver = GraphDatabase.driver(
            settings.weknora_neo4j_uri,
            auth=(settings.weknora_neo4j_username, settings.weknora_neo4j_password),
            connection_timeout=settings.weknora_neo4j_timeout_seconds,
        )
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        try:
            with driver.session(database=settings.weknora_neo4j_database) as session:
                for group in groups:
                    label_expr = self._weknora_neo4j_label_expr(system_id, group["knowledge_id"])
                    records = session.run(
                        self._neo4j_chunk_entity_query(label_expr),
                        {
                            "knowledge_id": group["knowledge_id"],
                            "chunk_ids": group["chunk_ids"],
                            "limit": max(1, min(limit, 100)),
                        },
                    )
                    for record in records:
                        for key in ("n", "m"):
                            node = record.get(key)
                            if node is None:
                                continue
                            mapped = self._neo4j_node_to_graph_node(node)
                            nodes[mapped["id"]] = mapped
                        rel = record.get("r")
                        source = record.get("n")
                        target = record.get("m")
                        if rel is None or source is None or target is None:
                            continue
                        mapped_edge = self._neo4j_relation_to_graph_edge(rel, source, target)
                        edges[mapped_edge["id"]] = mapped_edge
        finally:
            driver.close()
        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
        }

    @classmethod
    def _neo4j_lookup_groups(cls, results: list[dict[str, Any]], *, system_id: str) -> list[dict[str, Any]]:
        """按 knowledge_id 聚合 WeKnora 检索命中的 chunk id。"""
        groups: dict[str, set[str]] = {}
        for item in results:
            knowledge_id = str(item.get("knowledge_id") or item.get("source_id") or "").strip()
            knowledge_base_id = str(item.get("knowledge_base_id") or system_id).strip()
            if knowledge_base_id != system_id or not knowledge_id:
                continue
            for value in (item.get("id"), item.get("chunk_id"), item.get("parent_chunk_id")):
                chunk_id = str(value or "").strip()
                if chunk_id:
                    groups.setdefault(knowledge_id, set()).add(chunk_id)
        return [
            {"knowledge_id": knowledge_id, "chunk_ids": sorted(chunk_ids)}
            for knowledge_id, chunk_ids in groups.items()
            if chunk_ids
        ]

    @classmethod
    def _neo4j_chunk_entity_query(cls, label_expr: str) -> str:
        """构造按 chunk 反查实体邻域的 Cypher。"""
        return f"""
            MATCH (n:{label_expr})
            WHERE n.kg = $knowledge_id
              AND any(chunk IN coalesce(n.chunks, []) WHERE chunk IN $chunk_ids)
            OPTIONAL MATCH (n)-[r]-(m:{label_expr})
            WHERE m.kg = $knowledge_id
            RETURN n, r, m
            LIMIT $limit
        """

    @classmethod
    def _weknora_neo4j_label_expr(cls, knowledge_base_id: str, knowledge_id: str | None = None) -> str:
        """生成 WeKnora Neo4j 命名空间 label 表达式。"""
        labels = [cls._weknora_neo4j_label(knowledge_base_id)]
        if knowledge_id:
            labels.append(cls._weknora_neo4j_label(knowledge_id))
        return ":".join(labels)

    @classmethod
    def _weknora_neo4j_label(cls, value: str) -> str:
        """将 WeKnora ID 转换为 Neo4j 实体 label。"""
        normalized = re.sub(r"[^0-9A-Za-z_]", "_", str(value or "").replace("-", "_"))
        return f"ENTITY{normalized}"

    @classmethod
    def _neo4j_node_to_graph_node(cls, node: Any) -> dict[str, Any]:
        """将 Neo4j 节点映射为前端图谱节点。"""
        props = dict(getattr(node, "_properties", None) or dict(node))
        name = str(props.get("name") or props.get("title") or getattr(node, "element_id", "")).strip()
        chunks = [str(item) for item in props.get("chunks") or [] if str(item).strip()]
        attributes = [str(item) for item in props.get("attributes") or [] if str(item).strip()]
        node_id = f"entity:{props.get('kg') or ''}:{name}"
        return {
            "id": node_id,
            "label": name or node_id,
            "type": "Entity",
            "score": 1.0,
            "properties": cls._safe_metadata({
                "knowledge_id": props.get("kg"),
                "chunks": chunks,
                "attributes": attributes,
                "provider": WEKNORA_PROVIDER,
                "graph_backend": WEKNORA_NEO4J_GRAPH_BACKEND,
            }),
        }

    @classmethod
    def _neo4j_relation_to_graph_edge(cls, relation: Any, source: Any, target: Any) -> dict[str, Any]:
        """将 Neo4j 关系映射为前端图谱边。"""
        source_node = cls._neo4j_node_to_graph_node(source)
        target_node = cls._neo4j_node_to_graph_node(target)
        rel_type = str(getattr(relation, "type", None) or "RELATED_TO")
        edge_id = f"{source_node['id']}->{rel_type}->{target_node['id']}"
        return {
            "id": edge_id,
            "source": source_node["id"],
            "target": target_node["id"],
            "type": rel_type,
            "weight": 1.0,
            "properties": cls._safe_metadata({
                **dict(getattr(relation, "_properties", None) or {}),
                "provider": WEKNORA_PROVIDER,
                "graph_backend": WEKNORA_NEO4J_GRAPH_BACKEND,
            }),
        }

    @staticmethod
    def _neo4j_configured() -> bool:
        """判断 WeKnora Neo4j 增强是否已配置。"""
        return bool(
            settings.weknora_neo4j_uri
            and settings.weknora_neo4j_username
            and settings.weknora_neo4j_password
        )

    @staticmethod
    def _redact_neo4j_uri(value: str) -> str:
        """隐藏 Neo4j URI 中可能出现的凭据信息。"""
        if not value:
            return ""
        return re.sub(r"//[^/@]+@", "//***@", value)

    @staticmethod
    def _normalize_node_type(item: dict[str, Any]) -> str:
        """规范前端图谱节点类型。"""
        properties = item.get("properties") or {}
        raw = str(item.get("type") or properties.get("entity_type") or "Entity").strip()
        aliases = {
            "paper": "Paper",
            "document": "Paper",
            "doc": "Paper",
            "chunk": "Chunk",
            "text": "Chunk",
            "material": "Material",
            "polymer": "Polymer",
            "property": "Property",
            "metric": "PerformanceMetric",
            "performancemetric": "PerformanceMetric",
            "performance_metric": "PerformanceMetric",
        }
        key = raw.replace(" ", "").replace("-", "_").lower()
        return aliases.get(key, raw or "Entity")

    @staticmethod
    def _normalize_wiki_node_type(page_type: str) -> str:
        """将 WeKnora Wiki 页面类型映射为前端图谱节点类型。

        Args:
            page_type: WeKnora Wiki 页面的 page_type。

        Returns:
            前端显示用节点类型。
        """
        aliases = {
            "summary": "Summary",
            "entity": "Entity",
            "concept": "Concept",
            "synthesis": "Synthesis",
            "comparison": "Comparison",
            "index": "Index",
        }
        return aliases.get(str(page_type or "").strip().lower(), "WikiPage")

    @staticmethod
    def _normalize_knowledge_base(item: dict[str, Any]) -> KnowledgeSystem:
        """将 WeKnora 知识库记录映射为本地知识库体系。"""
        system_id = str(item.get("id") or item.get("corpus_id") or item.get("system_id") or "").strip()
        document_count = int(item.get("knowledge_count") or item.get("document_count") or item.get("indexed_document_count") or 0)
        chunk_count = int(item.get("chunk_count") or item.get("graph_chunk_count") or 0)
        is_processing = bool(item.get("is_processing") or int(item.get("processing_count") or 0) > 0)
        if is_processing:
            status = "indexing"
        elif document_count <= 0:
            status = "empty"
        else:
            status = "ready"
        return KnowledgeSystem(
            system_id=system_id,
            name=str(item.get("name") or system_id),
            domain=str(item.get("type") or item.get("domain") or "knowledge"),
            material_family=str(item.get("material_family") or item.get("type") or "general"),
            description=str(item.get("description") or ""),
            is_demo=False,
            backend=WEKNORA_PROVIDER,
            graph_backend=WEKNORA_GRAPH_BACKEND,
            source_mode=WEKNORA_SOURCE_MODE,
            tags=list(item.get("tags") or []),
            document_count=document_count,
            entity_count=chunk_count,
            relation_count=0,
            graph_node_count=chunk_count,
            graph_relationship_count=0,
            graph_paper_count=document_count,
            graph_chunk_count=chunk_count,
            graph_entity_count=chunk_count,
            data_source_id=f"{WEKNORA_PROVIDER}:{system_id}",
            provider=WEKNORA_PROVIDER,
            corpus_id=system_id,
            status=status,
            capabilities=["query", "streaming", "graph", "suggestions", "search"],
            health_message="WeKnora 正在处理部分知识条目。" if is_processing else "",
            last_indexed_at=str(item.get("updated_at") or item.get("created_at") or "") or None,
            indexed_document_count=document_count,
        )

    @classmethod
    def _safe_hit(cls, item: dict[str, Any]) -> dict[str, Any]:
        """清洗 WeKnora 检索命中，避免暴露敏感字段。"""
        metadata = cls._safe_metadata(item.get("metadata") or {})
        source = item.get("knowledge_source") or item.get("source") or item.get("url")
        url = item.get("url") or (source if isinstance(source, str) and source.startswith(("http://", "https://")) else None)
        return {
            "source_id": str(item.get("knowledge_id") or item.get("source_id") or item.get("document_id") or item.get("id") or ""),
            "title": str(
                item.get("knowledge_title")
                or item.get("knowledge_filename")
                or item.get("title")
                or item.get("source_id")
                or "Untitled source"
            ),
            "snippet": str(item.get("content") or item.get("matched_content") or item.get("snippet") or item.get("text") or "")[:500],
            "source": source,
            "doi": item.get("doi") or metadata.get("doi"),
            "url": url,
            "journal": item.get("journal") or metadata.get("journal"),
            "year": cls._safe_int(item.get("year") or metadata.get("year")),
            "authors": cls._safe_authors(item.get("authors") or metadata.get("authors")),
            "score": float(item.get("score") or 0.0),
            "metadata": metadata
            | {
                "chunk_id": item.get("id") or item.get("chunk_id"),
                "parent_chunk_id": item.get("parent_chunk_id"),
                "chunk_index": item.get("chunk_index"),
                "knowledge_base_id": item.get("knowledge_base_id"),
                "match_type": item.get("match_type"),
                "chunk_type": item.get("chunk_type"),
                "knowledge_filename": item.get("knowledge_filename"),
                "knowledge_channel": item.get("knowledge_channel"),
            },
        }

    @classmethod
    def _safe_citation(cls, item: dict[str, Any]) -> dict[str, Any]:
        """清洗 WeKnora 引用数据。"""
        hit = cls._safe_hit(item)
        return {
            "source_id": hit["source_id"],
            "title": hit["title"],
            "doi": hit.get("doi"),
            "url": hit.get("url"),
            "journal": hit.get("journal"),
            "year": hit.get("year"),
            "authors": hit.get("authors") or [],
            "chunk_id": str(hit["metadata"].get("chunk_id") or hit["metadata"].get("parent_chunk_id") or "") or None,
        }

    @staticmethod
    def _raw_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
        """从 WeKnora 响应中取列表数据。"""
        data = raw.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [item for item in data["items"] if isinstance(item, dict)]
        if isinstance(raw.get("items"), list):
            return [item for item in raw["items"] if isinstance(item, dict)]
        return []

    @staticmethod
    def _unwrap(raw: Any) -> dict[str, Any]:
        """兼容 ApiResponse 与 WeKnora JSON 响应。"""
        return raw if isinstance(raw, dict) else {}

    def _list_weknora_knowledge_bases(self, base_url: str) -> dict[str, Any]:
        """请求 WeKnora 知识库列表。"""
        with self._client(base_url) as client:
            response = client.get("/knowledge-bases")
            response.raise_for_status()
            return self._unwrap(response.json())

    def _create_session(self, base_url: str, question: str) -> str:
        """创建 WeKnora 临时问答会话。"""
        with self._client(base_url) as client:
            response = client.post(
                "/sessions",
                json={
                    "title": self._compact_label(question, limit=60) or "PolyAgent 知识问答",
                    "description": "PolyAgent 知识库适配层创建的临时会话",
                },
            )
            response.raise_for_status()
            raw = self._unwrap(response.json())
        data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
        session_id = str((data or {}).get("id") or (data or {}).get("session_id") or "").strip()
        if not session_id:
            raise RuntimeError("WeKnora 创建会话响应缺少 session id")
        return session_id

    def _consume_chat_stream(
        self,
        base_url: str,
        session_id: str,
        payload: KnowledgeQueryRequest,
    ) -> tuple[str, list[dict[str, Any]]]:
        """消费 WeKnora SSE 并聚合答案与引用。"""
        answer_parts: list[str] = []
        references: list[dict[str, Any]] = []
        for event in self._iter_chat_stream(base_url, session_id, payload):
            event_type = str(event.get("response_type") or "")
            if event_type == "answer":
                answer_parts.append(str(event.get("content") or ""))
            elif event_type == "references":
                references = list(event.get("knowledge_references") or [])
            elif event_type == "error":
                raise RuntimeError(str(event.get("content") or "WeKnora 知识问答失败"))
        if not references:
            references = self._search_knowledge(base_url, payload.system_id, payload.question, limit=payload.top_k)
        return "".join(answer_parts), references

    @classmethod
    def _merge_reference_items(cls, *groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按知识片段身份合并 WeKnora 引用，保留先返回证据的展示顺序。"""
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                if not isinstance(item, dict):
                    continue
                key = cls._reference_item_key(item)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged

    @staticmethod
    def _reference_item_key(item: dict[str, Any]) -> str:
        """生成 WeKnora 引用去重键。"""
        metadata = item.get("metadata") or {}
        parts = [
            item.get("knowledge_id"),
            item.get("source_id"),
            item.get("document_id"),
            item.get("id"),
            item.get("chunk_id"),
            item.get("parent_chunk_id"),
            metadata.get("chunk_id") if isinstance(metadata, dict) else None,
            metadata.get("parent_chunk_id") if isinstance(metadata, dict) else None,
        ]
        identity = "|".join(str(part).strip() for part in parts if str(part or "").strip())
        if identity:
            return identity
        return "|".join([
            str(item.get("knowledge_filename") or item.get("title") or "").strip(),
            str(item.get("content") or item.get("snippet") or item.get("text") or "").strip()[:160],
        ])

    def _iter_chat_stream(
        self,
        base_url: str,
        session_id: str,
        payload: KnowledgeQueryRequest,
    ) -> Iterator[dict[str, Any]]:
        """逐条解析 WeKnora knowledge-chat SSE 事件。"""
        request_body = {
            "query": payload.question,
            "knowledge_base_ids": [payload.system_id],
            "knowledge_ids": [],
            "disable_title": True,
            "channel": "api",
        }
        with self._client(base_url, stream=True) as client:
            with client.stream("POST", f"/knowledge-chat/{session_id}", json=request_body) as response:
                response.raise_for_status()
                data_lines: list[str] = []
                for line in response.iter_lines():
                    line_text = line.decode("utf-8") if isinstance(line, bytes) else str(line)
                    if not line_text:
                        if data_lines:
                            raw_data = "\n".join(data_lines)
                            data_lines = []
                            try:
                                event = json.loads(raw_data)
                            except json.JSONDecodeError:
                                continue
                            if isinstance(event, dict):
                                yield event
                        continue
                    if line_text.startswith("data:"):
                        data_lines.append(line_text[5:].strip())
                if data_lines:
                    try:
                        event = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        return
                    if isinstance(event, dict):
                        yield event

    def _search_knowledge(self, base_url: str, system_id: str, query: str, *, limit: int) -> list[dict[str, Any]]:
        """调用 WeKnora 无总结检索接口。"""
        return self._search_knowledge_many(base_url, [system_id], query, limit=limit)

    def _search_knowledge_many(
        self,
        base_url: str,
        system_ids: list[str],
        query: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """调用 WeKnora 无总结多知识库检索接口。

        Args:
            base_url: WeKnora API 基础地址。
            system_ids: WeKnora 知识库 ID 列表。
            query: 用户检索问题。
            limit: 最大返回命中数。

        Returns:
            WeKnora 返回的原始命中列表。
        """
        normalized_ids = self._normalize_system_ids(system_ids)
        if not normalized_ids:
            return []
        with self._client(base_url) as client:
            response = client.post(
                "/knowledge-search",
                json={
                    "query": query,
                    "knowledge_base_ids": normalized_ids,
                },
            )
            response.raise_for_status()
            raw = self._unwrap(response.json())
        return self._raw_items(raw)[: max(1, min(limit, 100))]

    @staticmethod
    def _normalize_system_ids(system_ids: list[str]) -> list[str]:
        """清洗并去重知识库 ID 列表。

        Args:
            system_ids: 原始知识库 ID 列表。

        Returns:
            清洗后的知识库 ID 列表。
        """
        normalized: list[str] = []
        for system_id in system_ids or []:
            value = str(system_id or "").strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    @classmethod
    def _base_url(cls) -> str:
        """解析 WeKnora API 基础地址。"""
        raw = (
            os.getenv("WEKNORA_BASE_URL", "").strip()
            or settings.weknora_base_url
        ).rstrip("/")
        if not raw:
            return ""
        return raw if raw.endswith("/api/v1") else f"{raw}/api/v1"

    @staticmethod
    def _client(base_url: str, *, stream: bool = False) -> httpx.Client:
        """创建带 WeKnora API Key 的 HTTP 客户端。"""
        api_key = KnowledgeService._api_key()
        headers = {"X-API-Key": api_key} if api_key else {}
        timeout = httpx.Timeout(30.0, read=None) if stream else httpx.Timeout(30.0)
        return httpx.Client(base_url=base_url, headers=headers, timeout=timeout)

    @staticmethod
    def _api_key() -> str:
        """解析 WeKnora API Key。"""
        for value in (os.getenv("WEKNORA_API_KEY", "").strip(), settings.weknora_api_key):
            if value and value.lower() not in PLACEHOLDER_API_KEYS:
                return value
        return ""

    def _require_base_url(self) -> str:
        """获取 WeKnora 基础地址，未配置时抛出 HTTP 异常。"""
        base_url = self._base_url()
        if not base_url:
            raise HTTPException(status_code=503, detail="WeKnora 服务未配置")
        return base_url

    def _get_system(self, system_id: str) -> KnowledgeSystem:
        """按知识库 ID 获取本地兼容体系。"""
        for item in self.list_systems().items:
            if item.system_id == system_id:
                return item
        raise HTTPException(status_code=404, detail=f"WeKnora 知识库 '{system_id}' 不存在")

    def _ensure_known_system(self, system_id: str) -> None:
        """校验知识库 ID 存在。"""
        self._get_system(system_id)

    @staticmethod
    def _default_system_id() -> str | None:
        """解析默认知识库 ID。"""
        return (
            os.getenv("WEKNORA_DEFAULT_KB_ID", "").strip()
            or settings.weknora_default_kb_id
            or os.getenv("KNOWLEDGE_DEFAULT_SYSTEM_ID", "").strip()
            or None
        )

    @staticmethod
    def _safe_metadata(value: Any) -> dict[str, Any]:
        """过滤不应暴露给前端的元数据字段。"""
        if not isinstance(value, dict):
            return {}
        blocked = {
            "storage_uri",
            "object_key",
            "api_key",
            "token",
            "secret",
            "password",
            "index_path",
            "embedding",
        }
        return {str(key): val for key, val in value.items() if str(key).lower() not in blocked and val is not None}

    @staticmethod
    def _safe_authors(value: Any) -> list[str]:
        """规范作者列表字段。"""
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in value.split(";") if item.strip()]
        return []

    @staticmethod
    def _safe_string_list(value: Any) -> list[str]:
        """规范字符串列表字段。"""
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item or "").strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        """将输入安全转换为整数。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_allowed_file_resource(file_path: str) -> bool:
        """判断文件资源路径是否属于 WeKnora 受保护资源协议。"""
        allowed_prefixes = (
            "resource://",
            "storage://",
            "local://",
            "minio://",
            "s3://",
            "cos://",
            "tos://",
            "oss://",
            "obs://",
            "ks3://",
        )
        return bool(file_path) and file_path.startswith(allowed_prefixes) and ".." not in file_path

    @staticmethod
    def _compact_label(value: str, *, limit: int = 48) -> str:
        """生成适合节点标题的短文本。"""
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    @staticmethod
    def _compact_wiki_content(value: str, *, limit: int = 900) -> str:
        """生成适合节点详情展示的 Wiki 正文预览。"""
        text = str(value or "")
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
        text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
        text = re.sub(r"[*_`>#|~-]+", " ", text)
        text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    @staticmethod
    def _stream_label(event_type: str) -> str:
        """将 WeKnora 内部事件映射为中文进度标签。"""
        labels = {
            "thinking": "WeKnora 正在分析问题",
            "tool_call": "WeKnora 正在调用工具",
            "tool_result": "WeKnora 已获得工具结果",
            "reflection": "WeKnora 正在反思答案",
        }
        return labels.get(event_type, "WeKnora 正在处理")

    @staticmethod
    def _ndjson(event: dict[str, Any]) -> str:
        """序列化前端 NDJSON 事件。"""
        return json.dumps(event, ensure_ascii=False) + "\n"
