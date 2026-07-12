from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .config import Settings
from .extraction import extract_domain_entities
from .parsing import chunk_text, clean_pdf_text


def extract_pdf_text(content: bytes) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF ingestion") from exc
    document = fitz.open(stream=content, filetype="pdf")
    try:
        return "\n\n".join(page.get_text("text", sort=True) for page in document)
    finally:
        document.close()


class IngestionWorker:
    def __init__(self, *, settings: Settings, repository: Any, object_store: Any, graph_store: Any,
                 text_extractor: Callable[[bytes], str] = extract_pdf_text,
                 entity_extractor: Callable[[list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]] | None = None) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store
        self.graph_store = graph_store
        self.text_extractor = text_extractor
        self.entity_extractor = entity_extractor

    def run_once(self) -> dict[str, Any] | None:
        self.repository.requeue_stale_jobs(
            stale_seconds=self.settings.worker_heartbeat_seconds * 4,
            max_attempts=self.settings.worker_max_attempts,
        )
        job = self.repository.claim_job()
        if not job:
            return None
        document = self.repository.get_document(job["document_id"])
        if not document:
            return self.repository.update_job(job["job_id"], {"status": "failed", "error": "document_not_found"})
        try:
            self.repository.update_job(job["job_id"], {"heartbeat_at": self._now(), "phase": "extracting"})
            content = self.object_store.get(document["object_key"])
            cleaned = clean_pdf_text(self.text_extractor(content))
            if len(cleaned) < 200:
                self.repository.update_document(document["document_id"], {
                    "status": "needs_review", "review_reason": "insufficient_extractable_text",
                })
                return self.repository.update_job(job["job_id"], {
                    "status": "needs_review", "message": "PDF text is too short or scanned",
                })
            chunks = [item.__dict__ for item in chunk_text(
                cleaned, chunk_size=self.settings.chunk_size, overlap=self.settings.chunk_overlap
            )]
            self.repository.update_job(job["job_id"], {"heartbeat_at": self._now(), "phase": "extracting_entities"})
            entities = extract_domain_entities(chunks, document)
            if self.entity_extractor:
                try:
                    llm_entities = self.entity_extractor(chunks, document)
                    existing = {(item["type"], item["label"].lower()) for item in entities}
                    entities.extend(item for item in llm_entities
                                    if (item["type"], item["label"].lower()) not in existing)
                except Exception:
                    pass
            prefix = f"corpora/{document['corpus_id']}/documents/{document['document_id']}"
            normalized_key = f"{prefix}/normalized.md"
            parsed_key = f"{prefix}/parsed.json"
            self.object_store.put(normalized_key, cleaned.encode("utf-8"), "text/markdown")
            self.object_store.put(parsed_key, json.dumps({
                "document_id": document["document_id"], "chunks": chunks, "entities": entities,
            }, ensure_ascii=False).encode("utf-8"), "application/json")
            document = self.repository.update_document(document["document_id"], {
                "status": "indexed", "normalized_object_key": normalized_key,
                "parsed_object_key": parsed_key, "chunk_count": len(chunks), "entity_count": len(entities),
            })
            self.repository.save_chunks(document["document_id"], chunks)
            self.repository.update_job(job["job_id"], {"heartbeat_at": self._now(), "phase": "indexing_graph"})
            self.graph_store.index_document(document, chunks, entities)
            self.repository.refresh_corpus_stats(document["corpus_id"])
            return self.repository.update_job(job["job_id"], {
                "status": "completed", "chunk_count": len(chunks), "entity_count": len(entities),
            })
        except Exception as exc:
            self.repository.update_document(document["document_id"], {"status": "failed"})
            return self.repository.update_job(job["job_id"], {
                "status": "failed", "error": f"{type(exc).__name__}: {exc}",
            })

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def run_forever(self) -> None:
        while True:
            if self.run_once() is None:
                time.sleep(self.settings.worker_poll_seconds)


def main() -> None:
    from .main import create_default_service

    settings = Settings.from_env()
    service = create_default_service(settings)
    entity_extractor = None
    if settings.llm_model:
        from .llm import OpenAIEntityExtractor

        entity_extractor = OpenAIEntityExtractor(api_key=settings.llm_api_key,
                                                 base_url=settings.llm_base_url, model=settings.llm_model)
    IngestionWorker(settings=settings, repository=service.repository,
                    object_store=service.object_store, graph_store=service.graph_store,
                    entity_extractor=entity_extractor).run_forever()


if __name__ == "__main__":
    main()
