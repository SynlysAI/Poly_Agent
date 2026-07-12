from __future__ import annotations

import hmac
import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, Query, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse

from .config import Settings
from .schemas import ApiResponse, CandidateImportRequest, CorpusCreate, IngestionJobCreate, QueryRequest
from .service import LiteratureRagService, ServiceError
from .storage import MemoryGraphStore, MemoryObjectStore, MemoryRepository


def create_default_service(settings: Settings) -> LiteratureRagService:
    answer_generator = None
    if settings.llm_model:
        from .llm import OpenAIAnswerGenerator

        answer_generator = OpenAIAnswerGenerator(api_key=settings.llm_api_key,
                                                 base_url=settings.llm_base_url, model=settings.llm_model)
    if settings.backend == "production":
        from .embeddings import LocalEmbeddingProvider
        from .storage_production import MinioObjectStore, MongoRepository, Neo4jGraphStore

        embeddings = LocalEmbeddingProvider(settings.embedding_model)
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
    chunk_count = 0
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
        chunk_count += len(chunks)
    if seeded:
        service.repository.upsert_corpus({
            "corpus_id": corpus_id,
            "entity_count": seeded,
            "relation_count": chunk_count,
        })


def _manifest_chunks(item: dict) -> list[str]:
    chunks = []
    title = str(item.get("title") or "").strip()
    abstract = str(item.get("abstract") or "").strip()
    if title:
        chunks.append(title)
    if abstract:
        chunks.append(abstract[:1400])
    return chunks


def create_app(*, settings: Settings | None = None, service: LiteratureRagService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = service or create_default_service(settings)
    app = FastAPI(title="Literature RAG Service", version=settings.service_version)

    def authorize(expected: str, authorization: str | None, *, wrong_role_status: int = 401) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise ServiceError(401, "UNAUTHORIZED", "Bearer token required")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not expected or not hmac.compare_digest(supplied, expected):
            raise ServiceError(wrong_role_status, "FORBIDDEN" if wrong_role_status == 403 else "UNAUTHORIZED", "Invalid API key")

    def query_auth(authorization: str | None = Header(default=None)) -> None:
        authorize(settings.query_api_key, authorization)

    def admin_auth(authorization: str | None = Header(default=None)) -> None:
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization.removeprefix("Bearer ").strip()
            if settings.query_api_key and hmac.compare_digest(supplied, settings.query_api_key):
                raise ServiceError(403, "FORBIDDEN", "Query API key cannot access management endpoints")
        authorize(settings.admin_api_key, authorization)

    @app.exception_handler(ServiceError)
    async def service_error_handler(_, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422,
                            content={"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed",
                                               "details": jsonable_encoder(exc.errors())}})

    @app.get("/health")
    def health() -> ApiResponse:
        return ApiResponse(data=service.health())

    @app.get("/api/v1/corpora", dependencies=[Depends(query_auth)])
    def list_corpora() -> ApiResponse:
        return ApiResponse(data=service.list_corpora())

    @app.post("/api/v1/corpora", dependencies=[Depends(admin_auth)], status_code=201)
    def create_corpus(payload: CorpusCreate) -> ApiResponse:
        return ApiResponse(data=service.create_corpus(payload))

    @app.post("/api/v1/corpora/{corpus_id}/candidates/import", dependencies=[Depends(admin_auth)])
    def import_candidates(corpus_id: str, payload: CandidateImportRequest) -> ApiResponse:
        return ApiResponse(data=service.import_candidates(corpus_id, payload))

    @app.post("/api/v1/documents/upload", dependencies=[Depends(admin_auth)])
    async def upload_document(response: Response, corpus_id: str = Form(), doi: str = Form(default=""),
                              title: str = Form(default=""), source_kind: str = Form(),
                              source_url: str | None = Form(default=None), file: UploadFile = File()) -> ApiResponse:
        document, created = service.upload_document(corpus_id=corpus_id, doi=doi, title=title,
            source_kind=source_kind, source_url=source_url, filename=file.filename or "document.pdf",
            content=await file.read())
        response.status_code = 201 if created else 200
        return ApiResponse(data=document)

    @app.post("/api/v1/ingestion-jobs", dependencies=[Depends(admin_auth)])
    def create_job(payload: IngestionJobCreate, response: Response) -> ApiResponse:
        job, created = service.create_job(payload.document_id, force=payload.force)
        if created and settings.backend == "memory" and settings.memory_inline_worker:
            from .worker import IngestionWorker

            completed = IngestionWorker(settings=settings, repository=service.repository,
                                        object_store=service.object_store, graph_store=service.graph_store).run_once()
            if completed:
                job = completed
        response.status_code = 201 if created else 200
        return ApiResponse(data=job)

    @app.get("/api/v1/ingestion-jobs/{job_id}", dependencies=[Depends(admin_auth)])
    def get_job(job_id: str) -> ApiResponse:
        return ApiResponse(data=service.get_job(job_id))

    @app.post("/api/v1/query", dependencies=[Depends(query_auth)])
    def query(payload: QueryRequest) -> ApiResponse:
        return ApiResponse(data=service.query(payload))

    @app.post("/api/v1/query/stream", dependencies=[Depends(query_auth)])
    def stream_query(payload: QueryRequest) -> StreamingResponse:
        return StreamingResponse(service.stream_query(payload), media_type="application/x-ndjson")

    @app.get("/api/v1/corpora/{corpus_id}/graph/subgraph", dependencies=[Depends(query_auth)])
    def subgraph(corpus_id: str, query: str = Query(min_length=1, max_length=500),
                 limit: int = Query(default=30, ge=1, le=100)) -> ApiResponse:
        return ApiResponse(data=service.subgraph(corpus_id, query, limit))

    return app


app = create_app()
