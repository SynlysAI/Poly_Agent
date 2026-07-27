from __future__ import annotations

from app.query import extract_graph_query_terms
from app.storage_production import Neo4jGraphStore


class FakeRelationship:
    type = "MENTIONS"

    def __iter__(self):
        return iter([("chunk_ids", ["chunk_00001"])])


class FakeSession:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, query: str, **params):
        self.queries.append((query, params))
        if "paper_count" in query:
            return FakeResult([{
                "paper_count": 2,
                "chunk_count": 6,
                "entity_count": 4,
                "target_node_count": 10,
                "relationship_count": 12,
            }])
        return [
            {
                "p": {
                    "document_id": "doc_1",
                    "corpus_id": "krf_photoresist",
                    "title": "KrF matched paper",
                },
                "r": FakeRelationship(),
                "n": {
                    "source_id": "doc_1:polymer:pvp",
                    "label": "PVP",
                    "entity_type": "Polymer",
                    "document_id": "doc_1",
                    "embedding": [0.1, 0.2],
                    "storage_uri": "s3://secret",
                    "object_key": "hidden",
                    "content_hash": "hidden",
                },
            }
        ]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def single(self):
        return self.rows[0] if self.rows else None


class FakeDriver:
    def __init__(self) -> None:
        self.session_obj = FakeSession()

    def session(self):
        return self.session_obj


class EmptyThenFallbackSession(FakeSession):
    def run(self, query: str, **params):
        self.queries.append((query, params))
        if "matched_node" in query:
            return []
        return [
            {
                "p": {
                    "document_id": "doc_2",
                    "corpus_id": "krf_photoresist",
                    "title": "Representative KrF process paper",
                    "year": 2024,
                },
                "r": FakeRelationship(),
                "n": {
                    "source_id": "doc_2:metric:roughness",
                    "label": "line-edge roughness",
                    "entity_type": "LithographyMetric",
                    "document_id": "doc_2",
                },
                "score": 2,
            }
        ]


class EmptyThenFallbackDriver:
    def __init__(self) -> None:
        self.session_obj = EmptyThenFallbackSession()

    def session(self):
        return self.session_obj


def test_neo4j_subgraph_pulls_mentions_from_matched_documents() -> None:
    store = Neo4jGraphStore.__new__(Neo4jGraphStore)
    store.driver = FakeDriver()

    data = store.subgraph("krf_photoresist", "KrF", limit=30)

    query_text = store.driver.session_obj.queries[0][0]
    query_params = store.driver.session_obj.queries[0][1]
    assert "matched_terms" in query_text
    assert "MENTIONS" in query_text
    assert "krf" in query_params["search_terms"]
    assert "photoresist" in query_params["search_terms"]
    assert "248" in query_params["search_terms"]
    assert data["nodes"][1]["type"] == "Polymer"
    assert data["edges"][0]["type"] == "MENTIONS"
    assert "embedding" not in data["nodes"][1]["properties"]
    assert "storage_uri" not in data["nodes"][1]["properties"]
    assert "object_key" not in data["nodes"][1]["properties"]
    assert "content_hash" not in data["nodes"][1]["properties"]


def test_graph_query_terms_expand_chinese_and_or_style_input() -> None:
    terms = extract_graph_query_terms("KrF || 光刻胶 || 聚合物 || 树脂")

    assert "krf" in terms
    assert "photoresist" in terms
    assert "resist" in terms
    assert "resin" in terms
    assert "polymer" in terms
    assert "248" in terms


def test_graph_query_terms_expand_process_roughness_question() -> None:
    terms = extract_graph_query_terms("优化 KrF 光刻胶 显影 粗糙度 工艺")

    assert "krf" in terms
    assert "photoresist" in terms
    assert "development" in terms
    assert "roughness" in terms
    assert "ler" in terms
    assert "process" in terms
    assert "optimization" in terms


def test_neo4j_subgraph_falls_back_to_representative_graph_when_terms_do_not_match() -> None:
    store = Neo4jGraphStore.__new__(Neo4jGraphStore)
    store.driver = EmptyThenFallbackDriver()

    data = store.subgraph("krf_photoresist", "unmatched query", limit=30)

    assert len(store.driver.session_obj.queries) == 2
    assert data["nodes"][0]["type"] == "Paper"
    assert data["nodes"][1]["type"] == "LithographyMetric"
    assert data["edges"][0]["type"] == "MENTIONS"
    assert data["provenance"]["match_mode"] == "representative_fallback"


def test_neo4j_corpus_stats_counts_real_graph_records() -> None:
    store = Neo4jGraphStore.__new__(Neo4jGraphStore)
    store.driver = FakeDriver()

    stats = store.corpus_stats("krf_photoresist")

    assert stats == {
        "paper_count": 2,
        "chunk_count": 6,
        "entity_count": 4,
        "node_count": 12,
        "relationship_count": 12,
    }
