from __future__ import annotations

import json
import time
from typing import Any, Iterator

from .config import Settings
from .domain import ALLOWED_SOURCE_KINDS, CandidateScoreInput, normalize_doi, score_candidate
from .parsing import chunk_text
from .query import is_document_inventory_query
from .schemas import CandidateImportRequest, CorpusCreate, QueryRequest
from .storage import MemoryGraphStore, MemoryObjectStore, MemoryRepository


class ServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class LiteratureRagService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: MemoryRepository,
        object_store: MemoryObjectStore,
        graph_store: MemoryGraphStore,
        answer_generator: Any = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store
        self.graph_store = graph_store
        self.answer_generator = answer_generator
        self.repository.upsert_corpus(self._default_corpus())

    def health(self) -> dict[str, Any]:
        return {"service": self.settings.service_name, "version": self.settings.service_version,
                "status": "ready", "backend": self.settings.backend,
                "default_corpus_id": self.settings.default_corpus_id}

    def create_corpus(self, payload: CorpusCreate) -> dict[str, Any]:
        return self.repository.upsert_corpus(payload.model_dump())

    def list_corpora(self) -> dict[str, Any]:
        items = self.repository.list_corpora()
        return {"items": items, "total": len(items)}

    def import_candidates(self, corpus_id: str, payload: CandidateImportRequest) -> dict[str, Any]:
        self._require_corpus(corpus_id)
        imported = []
        for item in payload.items:
            if item.source_kind and item.source_kind not in ALLOWED_SOURCE_KINDS:
                raise ServiceError(422, "SOURCE_NOT_ALLOWED", f"Source kind '{item.source_kind}' is not allowed")
            doi = normalize_doi(item.doi)
            if not doi:
                raise ServiceError(422, "INVALID_DOI", f"Invalid DOI: {item.doi}")
            score = score_candidate(CandidateScoreInput(
                relevance=item.relevance,
                journal_quality=item.journal_quality,
                citation_impact=item.citation_impact,
                recency_representativeness=item.recency_representativeness,
                fulltext_availability=item.fulltext_availability,
            ))
            imported.append(self.repository.upsert_candidate({**item.model_dump(), "corpus_id": corpus_id, "doi": doi, "score": score}))
        return {"items": imported, "total": len(imported)}

    def upload_document(self, *, corpus_id: str, doi: str, title: str, source_kind: str,
                        source_url: str | None, filename: str, content: bytes) -> tuple[dict[str, Any], bool]:
        self._require_corpus(corpus_id)
        if source_kind not in ALLOWED_SOURCE_KINDS:
            raise ServiceError(422, "SOURCE_NOT_ALLOWED", f"Source kind '{source_kind}' is not allowed")
        normalized_doi = normalize_doi(doi)
        if doi and not normalized_doi:
            raise ServiceError(422, "INVALID_DOI", "A valid DOI is required")
        if not content.startswith(b"%PDF"):
            raise ServiceError(422, "INVALID_PDF", "Uploaded file is not a PDF")
        document, created = self.repository.register_document({
            "corpus_id": corpus_id,
            "doi": normalized_doi,
            "title": title.strip() or normalized_doi or filename,
            "source_kind": source_kind,
            "source_url": source_url,
            "filename": filename,
        }, content)
        if created:
            key = f"corpora/{corpus_id}/documents/{document['document_id']}/original.pdf"
            uri = self.object_store.put(key, content, "application/pdf")
            document = self.repository.update_document(document["document_id"], {"object_key": key, "storage_uri": uri})
        return self._public_document(document), created

    def create_job(self, document_id: str, *, force: bool = False) -> tuple[dict[str, Any], bool]:
        if not self.repository.get_document(document_id):
            raise ServiceError(404, "DOCUMENT_NOT_FOUND", "Document not found")
        return self.repository.create_job(document_id, force=force)

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job:
            raise ServiceError(404, "JOB_NOT_FOUND", "Ingestion job not found")
        return job

    def query(self, payload: QueryRequest) -> dict[str, Any]:
        self._require_corpus(payload.corpus_id)
        if is_document_inventory_query(payload.question) and hasattr(self.repository, "list_indexed_documents"):
            documents = self.repository.list_indexed_documents(payload.corpus_id, 20)
            public_hits = [self._document_hit(item) for item in documents]
            citations = [self._document_citation(item) for item in documents]
            answer = self._document_inventory_digest(documents)
            graph_context = self.subgraph(payload.corpus_id, payload.question, payload.top_k * 4) if payload.include_graph_context else None
            return {"corpus_id": payload.corpus_id, "question": payload.question, "mode": payload.mode,
                    "answer": answer, "hits": public_hits, "citations": citations,
                    "graph_context": graph_context, "configured": True, "message": "document_inventory"}
        if hasattr(self.graph_store, "search"):
            hits = self.graph_store.search(payload.corpus_id, payload.question, payload.top_k, payload.mode)
        else:
            hits = self.repository.search_chunks(payload.corpus_id, payload.question, payload.top_k)
        public_hits = [self._hit(item) for item in hits]
        citations = [self._citation(item) for item in hits]
        if hits:
            if self.answer_generator:
                try:
                    answer = self.answer_generator(payload.question, hits)
                except Exception:
                    answer = self._evidence_digest(hits)
            else:
                answer = self._evidence_digest(hits)
            message = "ok"
        else:
            answer = "现有已索引文献中没有足够证据回答该问题。"
            message = "insufficient_evidence"
        graph_context = self.subgraph(payload.corpus_id, payload.question, payload.top_k * 4) if payload.include_graph_context else None
        return {"corpus_id": payload.corpus_id, "question": payload.question, "mode": payload.mode,
                "answer": answer, "hits": public_hits, "citations": citations,
                "graph_context": graph_context, "configured": True, "message": message}

    def stream_query(self, payload: QueryRequest) -> Iterator[str]:
        started = time.monotonic()
        result = self.query(payload)
        elapsed = lambda: round((time.monotonic() - started) * 1000)
        yield json.dumps({"event": "query_prepared", "label": "问题解析完成", "elapsed_ms": elapsed()}, ensure_ascii=False) + "\n"
        yield json.dumps({"event": "evidence", "hits": result["hits"], "citations": result["citations"],
                          "graph_context": result["graph_context"], "elapsed_ms": elapsed()}, ensure_ascii=False) + "\n"
        yield json.dumps({"event": "answer_delta", "content": result["answer"], "elapsed_ms": elapsed()}, ensure_ascii=False) + "\n"
        yield json.dumps({"event": "completed", "label": "检索问答完成", "elapsed_ms": elapsed()}, ensure_ascii=False) + "\n"

    def subgraph(self, corpus_id: str, query: str, limit: int) -> dict[str, Any]:
        self._require_corpus(corpus_id)
        data = self.graph_store.subgraph(corpus_id, query, limit)
        corpora = {item["corpus_id"]: item for item in self.repository.list_corpora()}
        corpus = corpora[corpus_id]
        return {"corpus_id": corpus_id, **data,
                "stats": {"entity_count": len(data["nodes"]), "relation_count": len(data["edges"]),
                          "document_count": corpus["document_count"]},
                "configured": True, "message": "ok",
                "provenance": {"provider": "literature-rag", "query": query}}

    def seed_indexed_document(self, *, corpus_id: str, doi: str, title: str, chunks: list[str],
                              journal: str | None = None, year: int | None = None,
                              source_url: str | None = None) -> dict[str, Any]:
        content = ("%PDF " + "\n".join(chunks)).encode()
        normalized_doi = normalize_doi(doi)
        document, _ = self.repository.register_document({"corpus_id": corpus_id, "doi": normalized_doi,
            "title": title, "journal": journal, "year": year, "source_kind": "authorized_upload",
            "source_url": source_url or f"https://doi.org/{normalized_doi}", "filename": "seed.pdf"}, content)
        chunk_records = [{"chunk_id": f"chunk_{index:05d}", "position": index - 1, "text": text}
                         for index, text in enumerate(chunks, start=1)]
        document = self.repository.update_document(document["document_id"], {"status": "indexed"})
        self.repository.save_chunks(document["document_id"], chunk_records)
        self.graph_store.index_document(document, chunk_records, [])
        return document

    def _require_corpus(self, corpus_id: str) -> None:
        if corpus_id not in {item["corpus_id"] for item in self.repository.list_corpora()}:
            raise ServiceError(404, "CORPUS_NOT_FOUND", f"Corpus '{corpus_id}' not found")

    def _default_corpus(self) -> dict[str, Any]:
        if self.settings.default_corpus_id == "krf_photoresist":
            return {
                "corpus_id": self.settings.default_corpus_id,
                "name": "KrF 248 nm 光刻胶文献库",
                "description": "KrF photoresist polymers, resins, PAGs and lithography processes.",
                "domain": "polymer_lithography",
                "material_family": "krf_photoresist",
                "tags": ["KrF", "248 nm", "photoresist", "polymer"],
            }
        return {
            "corpus_id": self.settings.default_corpus_id,
            "name": self.settings.default_corpus_id.replace("_", " ").title(),
            "description": "",
            "domain": "literature",
            "material_family": self.settings.default_corpus_id,
            "tags": [],
        }

    @staticmethod
    def _evidence_digest(hits: list[dict[str, Any]]) -> str:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in hits:
            if item["document_id"] in seen:
                continue
            seen.add(item["document_id"])
            unique.append(item)
        return "\n\n".join(
            f"- {item['title']}: {item['text'][:600].strip()} [{index}]"
            for index, item in enumerate(unique, start=1)
        )

    @staticmethod
    def _document_inventory_digest(documents: list[dict[str, Any]]) -> str:
        if not documents:
            return "当前知识库体系尚未发现已索引文献。"
        lines = []
        for index, item in enumerate(documents, start=1):
            meta = ", ".join(str(part) for part in (item.get("journal"), item.get("year"), item.get("doi")) if part)
            suffix = f" ({meta})" if meta else ""
            lines.append(f"- {item.get('title') or item.get('document_id')}{suffix} [{index}]")
        return "\n".join(lines)

    @staticmethod
    def _public_document(document: dict[str, Any]) -> dict[str, Any]:
        blocked = {"storage_uri", "object_key", "dedupe_key", "content_hash"}
        return {key: value for key, value in document.items() if key not in blocked}

    @staticmethod
    def _hit(item: dict[str, Any]) -> dict[str, Any]:
        return {"source_id": item["document_id"], "title": item["title"], "snippet": item["text"][:500],
                "source": item.get("source_url"), "doi": item.get("doi"), "url": item.get("source_url"),
                "journal": item.get("journal"), "year": item.get("year"), "authors": item.get("authors", []),
                "score": round(float(item["score"]), 4), "metadata": {"source_kind": item.get("source_kind"),
                "chunk_id": item["chunk_id"]}}

    @staticmethod
    def _citation(item: dict[str, Any]) -> dict[str, Any]:
        return {"source_id": item["document_id"], "title": item["title"], "doi": item.get("doi"),
                "url": item.get("source_url"), "journal": item.get("journal"), "year": item.get("year"),
                "authors": item.get("authors", []), "chunk_id": item["chunk_id"]}

    @staticmethod
    def _document_hit(item: dict[str, Any]) -> dict[str, Any]:
        parts = [item.get("journal"), item.get("year"), item.get("doi")]
        snippet = " · ".join(str(part) for part in parts if part)
        return {"source_id": item["document_id"], "title": item.get("title") or item["document_id"],
                "snippet": snippet or "已索引文献", "source": item.get("source_url"), "doi": item.get("doi"),
                "url": item.get("source_url"), "journal": item.get("journal"), "year": item.get("year"),
                "authors": item.get("authors", []), "score": 1.0,
                "metadata": {"source_kind": item.get("source_kind"), "status": item.get("status")}}

    @staticmethod
    def _document_citation(item: dict[str, Any]) -> dict[str, Any]:
        return {"source_id": item["document_id"], "title": item.get("title") or item["document_id"],
                "doi": item.get("doi"), "url": item.get("source_url"), "journal": item.get("journal"),
                "year": item.get("year"), "authors": item.get("authors", []), "chunk_id": None}
