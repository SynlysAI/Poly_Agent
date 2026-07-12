from __future__ import annotations

from app.config import Settings
from app.service import LiteratureRagService
from app.storage import MemoryGraphStore, MemoryObjectStore, MemoryRepository
from app.worker import IngestionWorker


def build_worker(text: str):
    settings = Settings(default_corpus_id="krf_photoresist", backend="memory", chunk_size=100, chunk_overlap=20)
    repository = MemoryRepository()
    objects = MemoryObjectStore()
    graph = MemoryGraphStore()
    service = LiteratureRagService(settings=settings, repository=repository, object_store=objects, graph_store=graph)
    document, _ = service.upload_document(
        corpus_id="krf_photoresist",
        doi="10.1000/worker-demo",
        title="KrF worker demo",
        source_kind="authorized_upload",
        source_url="https://doi.org/10.1000/worker-demo",
        filename="demo.pdf",
        content=b"%PDF-1.4 worker demo",
    )
    job, _ = service.create_job(document["document_id"])
    worker = IngestionWorker(settings=settings, repository=repository, object_store=objects,
                             graph_store=graph, text_extractor=lambda _: text)
    return worker, repository, objects, graph, document, job


def test_worker_indexes_cleaned_chunks_and_domain_entities() -> None:
    text = "Introduction\n" + (
        "KrF chemically amplified photoresist polymer resin uses a photoacid generator. "
        "Post exposure bake controls dissolution contrast and critical dimension. " * 8
    )
    worker, repository, objects, graph, document, job = build_worker(text)

    result = worker.run_once()

    assert result["status"] == "completed"
    assert repository.get_job(job["job_id"])["status"] == "completed"
    assert repository.get_document(document["document_id"])["status"] == "indexed"
    assert repository.chunks[document["document_id"]]
    assert any(key.endswith("normalized.md") for key in objects.objects)
    assert any(entity["type"] == "PhotoacidGenerator" for entity in graph.documents[document["document_id"]]["entities"])


def test_worker_marks_low_text_pdf_for_review_without_indexing() -> None:
    worker, repository, _, _, document, job = build_worker("KrF short scan")

    result = worker.run_once()

    assert result["status"] == "needs_review"
    assert repository.get_job(job["job_id"])["status"] == "needs_review"
    assert repository.get_document(document["document_id"])["status"] == "needs_review"
    assert document["document_id"] not in repository.chunks


def test_stale_running_job_is_requeued_before_claim() -> None:
    worker, repository, _, _, _, job = build_worker("KrF short scan")
    repository.jobs[job["job_id"]].update(status="running", heartbeat_at="2000-01-01T00:00:00+00:00")
    requeued = repository.requeue_stale_jobs(stale_seconds=30, max_attempts=3)
    assert requeued == 1
    assert repository.get_job(job["job_id"])["status"] == "queued"
