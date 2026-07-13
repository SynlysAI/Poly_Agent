from __future__ import annotations

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


def test_neo4j_subgraph_pulls_mentions_from_matched_documents() -> None:
    store = Neo4jGraphStore.__new__(Neo4jGraphStore)
    store.driver = FakeDriver()

    data = store.subgraph("krf_photoresist", "KrF", limit=30)

    query_text = store.driver.session_obj.queries[0][0]
    assert "matched_papers" in query_text
    assert "MENTIONS" in query_text
    assert data["nodes"][1]["type"] == "Polymer"
    assert data["edges"][0]["type"] == "MENTIONS"


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
