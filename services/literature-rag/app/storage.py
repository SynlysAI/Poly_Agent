from __future__ import annotations

import hashlib
import re
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .query import has_domain_anchor, tokenize_query


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.corpora: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.chunks: dict[str, list[dict[str, Any]]] = {}

    def upsert_corpus(self, corpus: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            existing = self.corpora.get(corpus["corpus_id"], {})
            saved = {**existing, **deepcopy(corpus), "updated_at": utc_now()}
            saved.setdefault("created_at", saved["updated_at"])
            self.corpora[saved["corpus_id"]] = saved
            return deepcopy(saved)

    def list_corpora(self) -> list[dict[str, Any]]:
        with self._lock:
            items = []
            for corpus in self.corpora.values():
                item = deepcopy(corpus)
                docs = [d for d in self.documents.values() if d["corpus_id"] == item["corpus_id"]]
                indexed_docs = [d for d in docs if d.get("status") == "indexed"]
                item["document_count"] = len(indexed_docs)
                item["indexed_document_count"] = len(indexed_docs)
                item["entity_count"] = item.get("entity_count", 0)
                item["relation_count"] = item.get("relation_count", 0)
                item["status"] = item.get("status") or ("ready" if indexed_docs else "empty")
                item["capabilities"] = item.get("capabilities") or ["query", "streaming", "graph", "suggestions"]
                item["provider"] = item.get("provider") or "literature-rag"
                item["data_source_id"] = item.get("data_source_id") or f"literature-rag:{item['corpus_id']}"
                last_indexed_at = max((d.get("updated_at") or d.get("created_at") or "" for d in indexed_docs), default="")
                item["last_indexed_at"] = last_indexed_at or None
                items.append(item)
            return sorted(items, key=lambda item: item["corpus_id"])

    def refresh_corpus_stats(self, corpus_id: str) -> dict[str, int]:
        with self._lock:
            documents = [item for item in self.documents.values()
                         if item["corpus_id"] == corpus_id and item.get("status") == "indexed"]
            stats = {
                "entity_count": sum(int(item.get("entity_count", 0)) for item in documents),
                "relation_count": sum(int(item.get("entity_count", 0)) + int(item.get("chunk_count", 0))
                                      for item in documents),
            }
            self.corpora[corpus_id].update(stats, updated_at=utc_now())
            return stats

    def upsert_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        key = f"{candidate['corpus_id']}:{candidate['doi']}"
        with self._lock:
            existing = self.candidates.get(key, {})
            saved = {**existing, **deepcopy(candidate), "updated_at": utc_now()}
            saved.setdefault("candidate_id", uuid4().hex)
            self.candidates[key] = saved
            return deepcopy(saved)

    def register_document(self, document: dict[str, Any], content: bytes) -> tuple[dict[str, Any], bool]:
        content_hash = hashlib.sha256(content).hexdigest()
        key = f"{document['corpus_id']}:{document.get('doi') or content_hash}"
        with self._lock:
            for item in self.documents.values():
                if item.get("corpus_id") == document["corpus_id"] and (
                    item.get("dedupe_key") == key or item.get("content_hash") == content_hash
                ):
                    return deepcopy(item), False
            saved = deepcopy(document)
            saved.update(
                document_id=uuid4().hex,
                dedupe_key=key,
                content_hash=content_hash,
                status="uploaded",
                created_at=utc_now(),
            )
            self.documents[saved["document_id"]] = saved
            return deepcopy(saved), True

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self.documents.get(document_id)
            return deepcopy(item) if item else None

    def update_document(self, document_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.documents[document_id].update(deepcopy(updates))
            self.documents[document_id]["updated_at"] = utc_now()
            return deepcopy(self.documents[document_id])

    def create_job(self, document_id: str, *, force: bool = False) -> tuple[dict[str, Any], bool]:
        with self._lock:
            if not force:
                for job in self.jobs.values():
                    if job["document_id"] == document_id and job["status"] in {"queued", "running", "completed"}:
                        return deepcopy(job), False
            job = {
                "job_id": uuid4().hex,
                "document_id": document_id,
                "status": "queued",
                "attempts": 0,
                "created_at": utc_now(),
            }
            self.jobs[job["job_id"]] = job
            return deepcopy(job), True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self.jobs.get(job_id)
            return deepcopy(item) if item else None

    def claim_job(self) -> dict[str, Any] | None:
        with self._lock:
            queued = sorted((j for j in self.jobs.values() if j["status"] == "queued"), key=lambda j: j["created_at"])
            if not queued:
                return None
            job = queued[0]
            job.update(status="running", attempts=job["attempts"] + 1, heartbeat_at=utc_now())
            return deepcopy(job)

    def requeue_stale_jobs(self, *, stale_seconds: int, max_attempts: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
        requeued = 0
        with self._lock:
            for job in self.jobs.values():
                if job.get("status") != "running" or not job.get("heartbeat_at"):
                    continue
                heartbeat = datetime.fromisoformat(job["heartbeat_at"])
                if heartbeat >= cutoff:
                    continue
                if int(job.get("attempts", 0)) >= max_attempts:
                    job.update(status="failed", error="stale_worker_max_attempts_exceeded", updated_at=utc_now())
                else:
                    job.update(status="queued", updated_at=utc_now())
                    requeued += 1
        return requeued

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.jobs[job_id].update(deepcopy(updates))
            self.jobs[job_id]["updated_at"] = utc_now()
            return deepcopy(self.jobs[job_id])

    def save_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        with self._lock:
            self.chunks[document_id] = deepcopy(chunks)

    def list_indexed_documents(self, corpus_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            documents = [
                deepcopy(item) for item in self.documents.values()
                if item["corpus_id"] == corpus_id and item.get("status") == "indexed"
            ]
        return sorted(documents, key=lambda item: (item.get("year") or 0, item.get("title") or ""), reverse=True)[:limit]

    def search_chunks(self, corpus_id: str, question: str, top_k: int) -> list[dict[str, Any]]:
        terms = tokenize_query(question)
        if not terms or not has_domain_anchor(question):
            return []
        scored: list[dict[str, Any]] = []
        with self._lock:
            for document_id, chunks in self.chunks.items():
                document = self.documents[document_id]
                if document["corpus_id"] != corpus_id or document.get("status") != "indexed":
                    continue
                for chunk in chunks:
                    combined_text = f"{document.get('title', '')} {chunk['text']}".lower()
                    text_terms = set(re.findall(r"[a-z0-9][a-z0-9-]{1,}", combined_text))
                    overlap = len(terms & text_terms)
                    substring_matches = sum(1 for term in terms if term in combined_text)
                    title_text = str(document.get("title") or "").lower()
                    title_matches = sum(1 for term in terms if term in title_text)
                    score = (overlap / max(len(terms), 1)) + (substring_matches * 0.03) + (title_matches * 0.08)
                    if overlap > 0 and score >= 0.18:
                        scored.append({**deepcopy(chunk), **deepcopy(document), "score": score})
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, content_type: str) -> str:
        self.objects[key] = bytes(content)
        return f"memory://{key}"

    def get(self, key: str) -> bytes:
        return self.objects[key]


class MemoryGraphStore:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}

    def index_document(self, document: dict[str, Any], chunks: list[dict[str, Any]],
                       entities: list[dict[str, Any]] | None = None) -> None:
        self.documents[document["document_id"]] = {
            "document": deepcopy(document),
            "chunks": deepcopy(chunks),
            "entities": deepcopy(entities or []),
        }

    def subgraph(self, corpus_id: str, query: str, limit: int = 30) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for record in self.documents.values():
            document = record["document"]
            if document["corpus_id"] != corpus_id:
                continue
            paper_id = f"paper:{document['document_id']}"
            nodes.append({"id": paper_id, "label": document["title"], "type": "Paper", "score": 1.0,
                          "properties": {"document_id": document["document_id"], "doi": document.get("doi"),
                                         "source_url": document.get("source_url")}})
            for chunk in record["chunks"]:
                chunk_id = f"{document['document_id']}:{chunk['chunk_id']}"
                nodes.append({"id": chunk_id, "label": chunk["text"][:80], "type": "Chunk", "score": 1.0,
                              "properties": {"document_id": document["document_id"], "chunk_id": chunk["chunk_id"],
                                             "doi": document.get("doi"), "source_url": document.get("source_url")}})
                edges.append({"id": f"contains:{chunk_id}", "source": paper_id, "target": chunk_id,
                              "type": "CONTAINS", "weight": 1.0, "properties": {"chunk_id": chunk["chunk_id"]}})
                if len(nodes) >= limit:
                    break
            for entity in record.get("entities", []):
                if len(nodes) >= limit:
                    break
                entity_id = f"{document['document_id']}:{entity['id']}"
                nodes.append({"id": entity_id, "label": entity["label"], "type": entity["type"], "score": 1.0,
                              "properties": {"document_id": document["document_id"], "doi": document.get("doi"),
                                             "source_url": document.get("source_url"), "chunk_ids": entity.get("chunk_ids", [])}})
                edges.append({"id": f"mentions:{entity_id}", "source": paper_id, "target": entity_id,
                              "type": "MENTIONS", "weight": 1.0,
                              "properties": {"chunk_ids": entity.get("chunk_ids", [])}})
            if len(nodes) >= limit:
                break
        return {"nodes": nodes[:limit], "edges": edges[: max(limit - 1, 0)]}
