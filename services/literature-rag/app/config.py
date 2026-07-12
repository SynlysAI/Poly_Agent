from __future__ import annotations

import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    service_name: str = "literature-rag"
    service_version: str = "0.1.0"
    backend: str = "memory"
    default_corpus_id: str = "krf_photoresist"
    query_api_key: str = ""
    admin_api_key: str = ""
    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_database: str = "literature_rag"
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "literature-rag"
    minio_secure: bool = False
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "password"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimensions: int = Field(default=1024, ge=1)
    chunk_size: int = Field(default=700, ge=100)
    chunk_overlap: int = Field(default=100, ge=0)
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    worker_heartbeat_seconds: int = Field(default=15, ge=5)
    worker_max_attempts: int = Field(default=3, ge=1)
    memory_inline_worker: bool = False
    memory_seed_manifest: str = "data/corpus_manifest.json"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend=os.getenv("LITERATURE_RAG_BACKEND", "memory").strip().lower(),
            default_corpus_id=os.getenv("LITERATURE_RAG_DEFAULT_CORPUS_ID", "krf_photoresist").strip(),
            query_api_key=os.getenv("LITERATURE_RAG_QUERY_API_KEY", "").strip(),
            admin_api_key=os.getenv("LITERATURE_RAG_ADMIN_API_KEY", "").strip(),
            mongodb_uri=os.getenv("LITERATURE_RAG_MONGODB_URI", "mongodb://127.0.0.1:27017").strip(),
            mongodb_database=os.getenv("LITERATURE_RAG_MONGODB_DATABASE", "literature_rag").strip(),
            minio_endpoint=os.getenv("LITERATURE_RAG_MINIO_ENDPOINT", "127.0.0.1:9000").strip(),
            minio_access_key=os.getenv("LITERATURE_RAG_MINIO_ACCESS_KEY", "minioadmin").strip(),
            minio_secret_key=os.getenv("LITERATURE_RAG_MINIO_SECRET_KEY", "minioadmin").strip(),
            minio_bucket=os.getenv("LITERATURE_RAG_MINIO_BUCKET", "literature-rag").strip(),
            minio_secure=os.getenv("LITERATURE_RAG_MINIO_SECURE", "false").lower() in {"1", "true", "yes"},
            neo4j_uri=os.getenv("LITERATURE_RAG_NEO4J_URI", "bolt://127.0.0.1:7687").strip(),
            neo4j_username=os.getenv("LITERATURE_RAG_NEO4J_USERNAME", "neo4j").strip(),
            neo4j_password=os.getenv("LITERATURE_RAG_NEO4J_PASSWORD", "password").strip(),
            llm_api_key=os.getenv("LITERATURE_RAG_LLM_API_KEY", os.getenv("LLM_API_KEY", "")).strip(),
            llm_base_url=os.getenv("LITERATURE_RAG_LLM_BASE_URL", os.getenv("LLM_BASE_URL", "")).strip(),
            llm_model=os.getenv("LITERATURE_RAG_LLM_MODEL", os.getenv("LLM_MODEL", "")).strip(),
            embedding_model=os.getenv("LITERATURE_RAG_EMBEDDING_MODEL", "BAAI/bge-m3").strip(),
            embedding_dimensions=int(os.getenv("LITERATURE_RAG_EMBEDDING_DIMENSIONS", "1024")),
            memory_inline_worker=os.getenv("LITERATURE_RAG_MEMORY_INLINE_WORKER", "false").lower() in {"1", "true", "yes"},
            memory_seed_manifest=os.getenv("LITERATURE_RAG_MEMORY_SEED_MANIFEST", "data/corpus_manifest.json").strip(),
        )
