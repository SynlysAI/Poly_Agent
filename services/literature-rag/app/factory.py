from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .service import LiteratureRagService
from .storage import MemoryGraphStore, MemoryObjectStore, MemoryRepository


def create_default_service(settings: Settings) -> LiteratureRagService:
    answer_generator = None
    if settings.llm_model:
        from .llm import OpenAIAnswerGenerator

        answer_generator = OpenAIAnswerGenerator(api_key=settings.llm_api_key,
                                                 base_url=settings.llm_base_url, model=settings.llm_model)
    if settings.backend == "production":
        from .embeddings import create_embedding_provider
        from .storage_production import MinioObjectStore, MongoRepository, Neo4jGraphStore

        embeddings = create_embedding_provider(settings.embedding_model, settings.embedding_dimensions)
        return LiteratureRagService(
            settings=settings,
            repository=MongoRepository(settings.mongodb_uri, settings.mongodb_database),
            object_store=MinioObjectStore(settings.minio_endpoint, settings.minio_access_key,
                                          settings.minio_secret_key, settings.minio_bucket, settings.minio_secure),
            graph_store=Neo4jGraphStore(settings.neo4j_uri, settings.neo4j_username, settings.neo4j_password,
                                        embeddings, settings.embedding_dimensions),
            answer_generator=answer_generator,
        )
    service = LiteratureRagService(settings=settings, repository=MemoryRepository(),
                                   object_store=MemoryObjectStore(), graph_store=MemoryGraphStore(),
                                   answer_generator=answer_generator)
    seed_memory_service_from_manifest(service, settings)
    return service


def seed_memory_service_from_manifest(service: LiteratureRagService, settings: Settings) -> None:
    """Seed the local memory demo from the auditable corpus manifest when available."""
    manifest_path = (settings.memory_seed_manifest or "").strip()
    if manifest_path.lower() in {"", "0", "false", "none"}:
        return
    path = Path(manifest_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.is_file():
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    corpus_id = str(manifest.get("corpus_id") or settings.default_corpus_id).strip()
    if not corpus_id:
        return
    seeded = 0
    for item in manifest.get("items") or []:
        if not item.get("selected") or item.get("approval_status") != "approved":
            continue
        chunks = _manifest_chunks(item)
        if not chunks:
            continue
        service.seed_indexed_document(
            corpus_id=corpus_id,
            doi=str(item.get("doi") or ""),
            title=str(item.get("title") or item.get("doi") or "KrF literature source"),
            journal=item.get("journal"),
            year=item.get("year"),
            source_url=item.get("source_url"),
            chunks=chunks,
        )
        seeded += 1
    if seeded:
        service.repository.refresh_corpus_stats(corpus_id)


def _manifest_chunks(item: dict) -> list[str]:
    chunks = []
    title = str(item.get("title") or "").strip()
    abstract = str(item.get("abstract") or "").strip()
    if title:
        chunks.append(title)
    if abstract:
        chunks.append(abstract[:1400])
    return chunks
