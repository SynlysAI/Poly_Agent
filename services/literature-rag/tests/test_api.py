from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.query import extract_graph_query_terms
from app.main import create_app, create_default_service
from app.service import LiteratureRagService
from app.storage import MemoryGraphStore, MemoryObjectStore, MemoryRepository


def build_client() -> tuple[TestClient, LiteratureRagService]:
    settings = Settings(
        query_api_key="query-secret",
        admin_api_key="admin-secret",
        default_corpus_id="krf_photoresist",
        backend="memory",
    )
    service = LiteratureRagService(
        settings=settings,
        repository=MemoryRepository(),
        object_store=MemoryObjectStore(),
        graph_store=MemoryGraphStore(),
    )
    return TestClient(create_app(settings=settings, service=service)), service


def test_health_and_corpus_contract() -> None:
    client, _ = build_client()
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["data"]["status"] == "ready"

    response = client.get("/api/v1/corpora", headers={"Authorization": "Bearer query-secret"})
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["corpus_id"] == "krf_photoresist"
    assert item["provider"] == "literature-rag"
    assert item["data_source_id"] == "literature-rag:krf_photoresist"
    assert item["backend"] == "memory"
    assert item["graph_backend"] == "memory"
    assert item["source_mode"] == "seed_manifest"
    assert item["is_demo"] is True
    assert item["status"] == "empty"
    assert item["capabilities"] == ["query", "streaming", "graph", "suggestions"]


def test_memory_backend_can_seed_from_manifest(tmp_path) -> None:
    manifest = tmp_path / "corpus_manifest.json"
    manifest.write_text(
        """
        {
          "corpus_id": "krf_photoresist",
          "items": [
            {
              "selected": true,
              "approval_status": "approved",
              "doi": "10.1000/krf-seed",
              "title": "KrF photoresist seed",
              "journal": "Macromolecules",
              "year": 2024,
              "abstract": "KrF chemically amplified photoresists use photoacid generators to control sensitivity.",
              "source_url": "https://publisher.example/krf-seed.pdf"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    settings = Settings(
        query_api_key="query-secret",
        admin_api_key="admin-secret",
        default_corpus_id="krf_photoresist",
        backend="memory",
        memory_seed_manifest=str(manifest),
    )
    service = create_default_service(settings)
    client = TestClient(create_app(settings=settings, service=service))

    response = client.get("/api/v1/corpora", headers={"Authorization": "Bearer query-secret"})
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["corpus_id"] == "krf_photoresist"
    assert item["status"] == "ready"
    assert item["indexed_document_count"] == 1
    assert item["is_demo"] is True
    assert item["graph_backend"] == "memory"

    query = client.post("/api/v1/query", headers={"Authorization": "Bearer query-secret"}, json={
        "corpus_id": "krf_photoresist",
        "question": "What controls KrF sensitivity?",
        "top_k": 2,
    })
    assert query.status_code == 200
    assert query.json()["data"]["hits"][0]["doi"] == "10.1000/krf-seed"
    assert query.json()["data"]["hits"][0]["url"] == "https://publisher.example/krf-seed.pdf"

    graph = client.get(
        "/api/v1/corpora/krf_photoresist/graph/subgraph",
        params={"query": "KrF", "limit": 5},
        headers={"Authorization": "Bearer query-secret"},
    )
    assert graph.status_code == 200
    assert graph.json()["data"]["backend"] == "memory"
    assert graph.json()["data"]["graph_backend"] == "memory"
    assert graph.json()["data"]["source_mode"] == "seed_manifest"
    assert graph.json()["data"]["is_demo"] is True
    assert graph.json()["data"]["nodes"][0]["properties"]["source_url"] == "https://publisher.example/krf-seed.pdf"
    node_types = {node["type"] for node in graph.json()["data"]["nodes"]}
    assert "PhotoacidGenerator" in node_types
    assert "LithographyMetric" in node_types
    assert "Method" in node_types
    stats = graph.json()["data"]["stats"]
    assert stats["node_type_counts"]["PhotoacidGenerator"] >= 1
    assert stats["category_counts"]["Materials"] >= 1
    assert stats["category_counts"]["Properties"] >= 1


def test_admin_and_query_api_keys_are_separated() -> None:
    client, _ = build_client()
    payload = {"corpus_id": "test", "name": "Test", "description": "Test corpus"}
    assert client.post("/api/v1/corpora", json=payload).status_code == 401
    assert client.post(
        "/api/v1/corpora",
        json=payload,
        headers={"Authorization": "Bearer query-secret"},
    ).status_code == 403


def test_authorized_pdf_upload_is_idempotent_and_creates_job() -> None:
    client, _ = build_client()
    headers = {"Authorization": "Bearer admin-secret"}
    data = {
        "corpus_id": "krf_photoresist",
        "doi": "10.1000/krf-demo",
        "title": "KrF resist demo",
        "source_kind": "authorized_upload",
        "source_url": "https://doi.org/10.1000/krf-demo",
    }
    files = {"file": ("paper.pdf", b"%PDF-1.4 authorized demo", "application/pdf")}
    first = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers)
    second = client.post("/api/v1/documents/upload", data=data, files=files, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["data"]["document_id"] == second.json()["data"]["document_id"]

    job = client.post(
        "/api/v1/ingestion-jobs",
        json={"document_id": first.json()["data"]["document_id"]},
        headers=headers,
    )
    assert job.status_code == 201
    status = client.get(f"/api/v1/ingestion-jobs/{job.json()['data']['job_id']}", headers=headers)
    assert status.json()["data"]["status"] == "queued"


def test_query_returns_traceable_hits_citations_and_stream_events() -> None:
    client, service = build_client()
    service.seed_indexed_document(
        corpus_id="krf_photoresist",
        doi="10.1000/krf-evidence",
        title="Photoacid generators for KrF resists",
        journal="Macromolecules",
        year=2022,
        chunks=["KrF chemically amplified resists use photoacid generators to control sensitivity."],
    )
    payload = {
        "corpus_id": "krf_photoresist",
        "question": "Which component controls KrF resist sensitivity?",
        "mode": "hybrid",
        "top_k": 5,
        "include_graph_context": True,
    }
    headers = {"Authorization": "Bearer query-secret"}
    response = client.post("/api/v1/query", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["hits"][0]["doi"] == "10.1000/krf-evidence"
    assert data["citations"][0]["chunk_id"]
    assert data["graph_context"]["provenance"]["provider"] == "literature-rag"

    streamed = client.post("/api/v1/query/stream", json=payload, headers=headers)
    assert streamed.status_code == 200
    assert '"event": "evidence"' in streamed.text
    assert '"event": "answer_delta"' in streamed.text
    assert '"event": "completed"' in streamed.text


def test_subgraph_prioritizes_entities_before_chunks_and_covers_domain_lanes() -> None:
    client, service = build_client()
    service.seed_indexed_document(
        corpus_id="krf_photoresist",
        doi="10.1000/domain-graph",
        title="Methacrylate polymers and acid trap strategy for KrF lithography",
        journal="Journal of Photopolymer Science and Technology",
        year=2024,
        chunks=[
            (
                "KrF chemically amplified photoresist uses methacrylate polymers, "
                "phenolic resin and PAG photoacid generator for 248 nm exposure."
            ),
            (
                "An acid trap reagent and post exposure bake strategy improves "
                "dissolution contrast, sensitivity, exposure latitude, resolution and etch resistance."
            ),
        ],
    )

    response = client.get(
        "/api/v1/corpora/krf_photoresist/graph/subgraph",
        params={"query": "KrF", "limit": 100},
        headers={"Authorization": "Bearer query-secret"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    node_types = {node["type"] for node in data["nodes"]}
    assert {"Polymer", "Resin", "PhotoacidGenerator", "Method", "ProcessCondition", "LithographyMetric"} <= node_types
    assert any(node["type"] not in {"Paper", "Chunk"} for node in data["nodes"][:8])
    assert data["stats"]["node_type_counts"]["Polymer"] >= 1
    assert data["stats"]["category_counts"]["Materials"] >= 3
    assert data["stats"]["category_counts"]["Strategies"] >= 2
    assert data["stats"]["category_counts"]["Properties"] >= 3


def test_chinese_query_uses_domain_synonyms() -> None:
    client, service = build_client()
    service.seed_indexed_document(
        corpus_id="krf_photoresist",
        doi="10.1000/chinese-query",
        title="KrF photoresist overview",
        journal="Journal of Photopolymer Science and Technology",
        year=2024,
        chunks=["KrF photoresist materials use polymer resin and photoacid generators for 248 nm lithography."],
    )

    response = client.post("/api/v1/query", headers={"Authorization": "Bearer query-secret"}, json={
        "corpus_id": "krf_photoresist",
        "question": "KrF光刻胶是什么？",
        "top_k": 3,
    })

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "ok"
    assert data["hits"][0]["doi"] == "10.1000/chinese-query"
    assert data["citations"][0]["chunk_id"] == "chunk_00001"


def test_document_inventory_query_returns_indexed_document_list_without_internal_fields() -> None:
    client, service = build_client()
    for index in range(3):
        service.seed_indexed_document(
            corpus_id="krf_photoresist",
            doi=f"10.1000/inventory-{index}",
            title=f"Indexed KrF paper {index}",
            journal="Macromolecules",
            year=2020 + index,
            chunks=[f"KrF photoresist evidence {index}."],
        )

    response = client.post("/api/v1/query", headers={"Authorization": "Bearer query-secret"}, json={
        "corpus_id": "krf_photoresist",
        "question": "帮我找全部的文档",
        "top_k": 2,
    })

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "document_inventory"
    assert len(data["hits"]) == 3
    assert "Indexed KrF paper 0" in data["answer"]
    assert "storage_uri" not in response.text
    assert "object_key" not in response.text
    assert "content_hash" not in response.text


def test_unanswerable_query_still_reports_insufficient_evidence() -> None:
    client, service = build_client()
    service.seed_indexed_document(
        corpus_id="krf_photoresist",
        doi="10.1000/krf-only",
        title="KrF photoresist source",
        chunks=["KrF photoresist evidence about polymer resin."],
    )

    response = client.post("/api/v1/query", headers={"Authorization": "Bearer query-secret"}, json={
        "corpus_id": "krf_photoresist",
        "question": "What is the clinical dosage of this polymer?",
        "top_k": 3,
    })

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["message"] == "insufficient_evidence"
    assert data["hits"] == []


def test_disallowed_source_kind_returns_structured_error() -> None:
    client, _ = build_client()
    response = client.post(
        "/api/v1/documents/upload",
        data={
            "corpus_id": "krf_photoresist",
            "doi": "10.1000/disallowed",
            "title": "Disallowed source",
            "source_kind": "third_party_mirror",
        },
        files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
        headers={"Authorization": "Bearer admin-secret"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "SOURCE_NOT_ALLOWED"


def test_configured_answer_generator_receives_traceable_evidence() -> None:
    client, service = build_client()
    service.seed_indexed_document(
        corpus_id="krf_photoresist", doi="10.1000/generated", title="Generated answer source",
        chunks=["Photoacid generators control the sensitivity of chemically amplified KrF resists."],
    )
    captured = {}

    def generate(question, hits):
        captured["question"] = question
        captured["chunk_id"] = hits[0]["chunk_id"]
        return "The PAG controls sensitivity [1]."

    service.answer_generator = generate
    response = client.post("/api/v1/query", headers={"Authorization": "Bearer query-secret"}, json={
        "corpus_id": "krf_photoresist", "question": "What controls sensitivity?", "top_k": 3,
    })
    assert response.json()["data"]["answer"] == "The PAG controls sensitivity [1]."
    assert captured["chunk_id"] == "chunk_00001"


def test_query_with_mixed_chinese_graph_query_returns_graph_context() -> None:
    client, service = build_client()
    service.seed_indexed_document(
        corpus_id="krf_photoresist",
        doi="10.1000/graph-context",
        title="KrF photoresist graph source",
        chunks=["KrF chemically amplified photoresists use polymer resin and photoacid generators."],
    )

    class QueryAwareGraphStore:
        def subgraph(self, corpus_id: str, query: str, limit: int = 30):
            terms = extract_graph_query_terms(query)
            if not {"krf", "photoresist", "resin"} & set(terms):
                return {"nodes": [], "edges": []}
            return {
                "nodes": [
                    {
                        "id": "paper:graph-context",
                        "label": "KrF photoresist graph source",
                        "type": "Paper",
                        "score": 2.0,
                        "properties": {"document_id": "graph-context"},
                    },
                    {
                        "id": "entity:resin",
                        "label": "phenolic resin",
                        "type": "Resin",
                        "score": 2.0,
                        "properties": {"document_id": "graph-context"},
                    },
                ],
                "edges": [
                    {
                        "id": "edge:graph-context",
                        "source": "paper:graph-context",
                        "target": "entity:resin",
                        "type": "MENTIONS",
                        "weight": 2.0,
                        "properties": {},
                    }
                ],
            }

    service.graph_store = QueryAwareGraphStore()

    response = client.post("/api/v1/query", headers={"Authorization": "Bearer query-secret"}, json={
        "corpus_id": "krf_photoresist",
        "question": "KrF || 光刻胶 || resin",
        "top_k": 3,
        "include_graph_context": True,
    })

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["graph_context"] is not None
    assert data["graph_context"]["nodes"]
    assert any(node["type"] == "Resin" for node in data["graph_context"]["nodes"])


def test_same_pdf_can_be_registered_in_two_corpora() -> None:
    client, _ = build_client()
    admin = {"Authorization": "Bearer admin-secret"}
    client.post("/api/v1/corpora", headers=admin,
                json={"corpus_id": "second_corpus", "name": "Second", "description": "Second corpus"})
    files = {"file": ("paper.pdf", b"%PDF-1.4 shared content", "application/pdf")}
    first = client.post("/api/v1/documents/upload", headers=admin, data={
        "corpus_id": "krf_photoresist", "doi": "10.1000/shared-a", "title": "Shared A",
        "source_kind": "authorized_upload",
    }, files=files)
    second = client.post("/api/v1/documents/upload", headers=admin, data={
        "corpus_id": "second_corpus", "doi": "10.1000/shared-b", "title": "Shared B",
        "source_kind": "authorized_upload",
    }, files=files)
    assert first.json()["data"]["document_id"] != second.json()["data"]["document_id"]


def test_corpus_registry_returns_multiple_corpora_with_independent_stats() -> None:
    client, service = build_client()
    admin = {"Authorization": "Bearer admin-secret"}
    client.post("/api/v1/corpora", headers=admin, json={
        "corpus_id": "battery_polymer",
        "name": "Battery Polymer",
        "description": "Polymer electrolyte corpus",
        "domain": "energy",
        "material_family": "polymer_electrolyte",
        "tags": ["battery", "polymer"],
    })
    service.seed_indexed_document(
        corpus_id="krf_photoresist",
        doi="10.1000/krf-indexed",
        title="Indexed KrF paper",
        chunks=["KrF indexed evidence."],
    )

    response = client.get("/api/v1/corpora", headers={"Authorization": "Bearer query-secret"})
    assert response.status_code == 200
    by_id = {item["corpus_id"]: item for item in response.json()["data"]["items"]}
    assert set(by_id) == {"krf_photoresist", "battery_polymer"}
    assert by_id["krf_photoresist"]["indexed_document_count"] == 1
    assert by_id["krf_photoresist"]["status"] == "ready"
    assert by_id["battery_polymer"]["indexed_document_count"] == 0
    assert by_id["battery_polymer"]["status"] == "empty"
    assert by_id["battery_polymer"]["domain"] == "energy"
    assert by_id["battery_polymer"]["tags"] == ["battery", "polymer"]
