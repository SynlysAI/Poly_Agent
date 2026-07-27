from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from uuid import uuid4

from .query import expand_query_text, extract_graph_query_terms, has_domain_anchor, tokenize_query
from .storage import utc_now


class MongoRepository:
    def __init__(self, uri: str, database: str) -> None:
        from pymongo import ASCENDING, MongoClient

        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[database]
        self.corpora = self.db.corpora
        self.candidates = self.db.paper_candidates
        self.documents = self.db.documents
        self.jobs = self.db.ingestion_jobs
        self.chunks = self.db.chunks
        self.corpora.create_index("corpus_id", unique=True)
        self.candidates.create_index([("corpus_id", ASCENDING), ("doi", ASCENDING)], unique=True)
        self.documents.create_index([("corpus_id", ASCENDING), ("dedupe_key", ASCENDING)], unique=True)
        self.documents.create_index([("corpus_id", ASCENDING), ("content_hash", ASCENDING)], unique=True)
        self.jobs.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
        self.chunks.create_index([("corpus_id", ASCENDING), ("document_id", ASCENDING), ("chunk_id", ASCENDING)], unique=True)

    @staticmethod
    def _clean(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        cleaned = deepcopy(item)
        cleaned.pop("_id", None)
        return cleaned

    def upsert_corpus(self, corpus: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        self.corpora.update_one({"corpus_id": corpus["corpus_id"]}, {
            "$set": {**deepcopy(corpus), "updated_at": now}, "$setOnInsert": {"created_at": now},
        }, upsert=True)
        return self._clean(self.corpora.find_one({"corpus_id": corpus["corpus_id"]})) or {}

    def list_corpora(self) -> list[dict[str, Any]]:
        items = []
        for raw in self.corpora.find({}).sort("corpus_id", 1):
            item = self._clean(raw) or {}
            indexed_filter = {"corpus_id": item["corpus_id"], "status": "indexed"}
            indexed_count = self.documents.count_documents(indexed_filter)
            item["document_count"] = indexed_count
            item["indexed_document_count"] = indexed_count
            item.setdefault("entity_count", 0)
            item.setdefault("relation_count", 0)
            item["status"] = item.get("status") or ("ready" if indexed_count else "empty")
            item["capabilities"] = item.get("capabilities") or ["query", "streaming", "graph", "suggestions"]
            item["provider"] = item.get("provider") or "literature-rag"
            item["data_source_id"] = item.get("data_source_id") or f"literature-rag:{item['corpus_id']}"
            latest = self.documents.find(indexed_filter, {"updated_at": 1, "created_at": 1}).sort("updated_at", -1).limit(1)
            latest_doc = next(iter(latest), None)
            item["last_indexed_at"] = (latest_doc or {}).get("updated_at") or (latest_doc or {}).get("created_at")
            items.append(item)
        return items

    def refresh_corpus_stats(self, corpus_id: str) -> dict[str, int]:
        pipeline = [
            {"$match": {"corpus_id": corpus_id, "status": "indexed"}},
            {"$group": {"_id": None, "entity_count": {"$sum": {"$ifNull": ["$entity_count", 0]}},
                         "chunk_count": {"$sum": {"$ifNull": ["$chunk_count", 0]}}}},
        ]
        rows = list(self.documents.aggregate(pipeline))
        row = rows[0] if rows else {"entity_count": 0, "chunk_count": 0}
        stats = {"entity_count": int(row["entity_count"]),
                 "relation_count": int(row["entity_count"] + row["chunk_count"])}
        self.corpora.update_one({"corpus_id": corpus_id}, {"$set": {**stats, "updated_at": utc_now()}})
        return stats

    def upsert_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        key = {"corpus_id": candidate["corpus_id"], "doi": candidate["doi"]}
        self.candidates.update_one(key, {"$set": {**deepcopy(candidate), "updated_at": utc_now()},
                                         "$setOnInsert": {"candidate_id": uuid4().hex}}, upsert=True)
        return self._clean(self.candidates.find_one(key)) or {}

    def register_document(self, document: dict[str, Any], content: bytes) -> tuple[dict[str, Any], bool]:
        content_hash = hashlib.sha256(content).hexdigest()
        dedupe_key = f"{document['corpus_id']}:{document.get('doi') or content_hash}"
        existing = self.documents.find_one({"corpus_id": document["corpus_id"],
                                            "$or": [{"dedupe_key": dedupe_key}, {"content_hash": content_hash}]})
        if existing:
            return self._clean(existing) or {}, False
        saved = {**deepcopy(document), "document_id": uuid4().hex, "dedupe_key": dedupe_key,
                 "content_hash": content_hash, "status": "uploaded", "created_at": utc_now()}
        self.documents.insert_one(deepcopy(saved))
        return saved, True

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self._clean(self.documents.find_one({"document_id": document_id}))

    def update_document(self, document_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        self.documents.update_one({"document_id": document_id}, {"$set": {**deepcopy(updates), "updated_at": utc_now()}})
        return self.get_document(document_id) or {}

    def create_job(self, document_id: str, *, force: bool = False) -> tuple[dict[str, Any], bool]:
        if not force:
            existing = self.jobs.find_one({"document_id": document_id, "status": {"$in": ["queued", "running", "completed"]}})
            if existing:
                return self._clean(existing) or {}, False
        job = {"job_id": uuid4().hex, "document_id": document_id, "status": "queued", "attempts": 0,
               "created_at": utc_now()}
        self.jobs.insert_one(deepcopy(job))
        return job, True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self._clean(self.jobs.find_one({"job_id": job_id}))

    def claim_job(self) -> dict[str, Any] | None:
        from pymongo import ReturnDocument

        item = self.jobs.find_one_and_update({"status": "queued"}, {
            "$set": {"status": "running", "heartbeat_at": utc_now()}, "$inc": {"attempts": 1},
        }, sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
        return self._clean(item)

    def requeue_stale_jobs(self, *, stale_seconds: int, max_attempts: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()
        failed = self.jobs.update_many({"status": "running", "heartbeat_at": {"$lt": cutoff},
                                        "attempts": {"$gte": max_attempts}},
                                       {"$set": {"status": "failed", "error": "stale_worker_max_attempts_exceeded",
                                                  "updated_at": utc_now()}})
        requeued = self.jobs.update_many({"status": "running", "heartbeat_at": {"$lt": cutoff},
                                          "attempts": {"$lt": max_attempts}},
                                         {"$set": {"status": "queued", "updated_at": utc_now()}})
        return int(requeued.modified_count)

    def update_job(self, job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        self.jobs.update_one({"job_id": job_id}, {"$set": {**deepcopy(updates), "updated_at": utc_now()}})
        return self.get_job(job_id) or {}

    def save_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        document = self.get_document(document_id) or {}
        self.chunks.delete_many({"document_id": document_id})
        if chunks:
            self.chunks.insert_many([{**deepcopy(chunk), "document_id": document_id,
                                      "corpus_id": document["corpus_id"]} for chunk in chunks])

    def list_indexed_documents(self, corpus_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.documents.find({"corpus_id": corpus_id, "status": "indexed"}).sort([("year", -1), ("title", 1)]).limit(limit)
        return [self._clean(row) or {} for row in rows]

    def search_chunks(self, corpus_id: str, question: str, top_k: int) -> list[dict[str, Any]]:
        terms = tokenize_query(question)
        if not terms or not has_domain_anchor(question):
            return []
        results: list[dict[str, Any]] = []
        for raw in self.chunks.find({"corpus_id": corpus_id}).limit(10000):
            chunk = self._clean(raw) or {}
            document = self.get_document(chunk["document_id"])
            if not document or document.get("status") != "indexed":
                continue
            combined_text = f"{document.get('title', '')} {chunk['text']}".lower()
            text_terms = set(re.findall(r"[a-z0-9][a-z0-9-]{1,}", combined_text))
            overlap = len(terms & text_terms)
            substring_matches = sum(1 for term in terms if term in combined_text)
            title_text = str(document.get("title") or "").lower()
            title_matches = sum(1 for term in terms if term in title_text)
            score = (overlap / max(len(terms), 1)) + (substring_matches * 0.03) + (title_matches * 0.08)
            if overlap > 0 and score >= 0.18:
                results.append({**chunk, **document, "score": score})
        return sorted(results, key=lambda item: item["score"], reverse=True)[:top_k]


class MinioObjectStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool) -> None:
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio is required for the production object store") from exc
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def put(self, key: str, content: bytes, content_type: str) -> str:
        self.client.put_object(self.bucket, key, BytesIO(content), len(content), content_type=content_type)
        return f"s3://{self.bucket}/{key}"

    def get(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


class Neo4jGraphStore:
    def __init__(self, uri: str, username: str, password: str, embedding_provider: Any,
                 embedding_dimensions: int = 1024) -> None:
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("neo4j is required for the production graph store") from exc
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.embedding_provider = embedding_provider
        self.embedding_dimensions = embedding_dimensions
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT paper_document IF NOT EXISTS FOR (p:Paper) REQUIRE p.document_id IS UNIQUE")
            session.run("CREATE CONSTRAINT chunk_source IF NOT EXISTS FOR (c:Chunk) REQUIRE c.source_id IS UNIQUE")
            session.run("CREATE CONSTRAINT entity_source IF NOT EXISTS FOR (e:Entity) REQUIRE e.source_id IS UNIQUE")
            session.run(
                "CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS FOR (c:Chunk) ON c.embedding "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {embedding_dimensions}, `vector.similarity_function`: 'cosine'}}}}"
            )

    def index_document(self, document: dict[str, Any], chunks: list[dict[str, Any]],
                       entities: list[dict[str, Any]] | None = None) -> None:
        vectors = self.embedding_provider.embed_documents([chunk["text"] for chunk in chunks])
        with self.driver.session() as session:
            session.run("MATCH (p:Paper {document_id: $document_id}) DETACH DELETE p", document_id=document["document_id"])
            session.run("MERGE (p:Paper {document_id: $document_id}) SET p += $properties",
                        document_id=document["document_id"], properties=self._paper_properties(document))
            for chunk, vector in zip(chunks, vectors, strict=True):
                source_id = f"{document['document_id']}:{chunk['chunk_id']}"
                session.run(
                    "MATCH (p:Paper {document_id: $document_id}) "
                    "MERGE (c:Chunk {source_id: $source_id}) SET c += $properties, c.embedding = $embedding "
                    "MERGE (p)-[:CONTAINS]->(c)",
                    document_id=document["document_id"], source_id=source_id,
                    properties={**chunk, **self._paper_properties(document)}, embedding=vector,
                )
            for entity in entities or []:
                source_id = f"{document['document_id']}:{entity['id']}"
                session.run(
                    "MATCH (p:Paper {document_id: $document_id}) "
                    "MERGE (e:Entity {source_id: $source_id}) SET e += $properties "
                    "MERGE (p)-[:MENTIONS {chunk_ids: $chunk_ids}]->(e)",
                    document_id=document["document_id"], source_id=source_id,
                    properties={**entity, "entity_type": entity["type"]}, chunk_ids=entity.get("chunk_ids", []),
                )

    def search(self, corpus_id: str, question: str, top_k: int, mode: str) -> list[dict[str, Any]]:
        if not has_domain_anchor(question):
            return []
        vector = self.embedding_provider.embed_query(expand_query_text(question))
        with self.driver.session() as session:
            records = session.run(
                "CALL db.index.vector.queryNodes('chunk_embedding', $top_k, $embedding) YIELD node, score "
                "WHERE node.corpus_id = $corpus_id "
                "RETURN node, score ORDER BY score DESC",
                top_k=top_k, embedding=vector, corpus_id=corpus_id,
            )
            return [{**dict(record["node"]), "score": float(record["score"])} for record in records]

    def subgraph(self, corpus_id: str, query: str, limit: int = 30) -> dict[str, Any]:
        normalized_limit = max(1, min(int(limit or 30), 100))
        search_terms = extract_graph_query_terms(query, max_terms=32)
        with self.driver.session() as session:
            if search_terms:
                records = session.run(
                    "MATCH (p:Paper {corpus_id: $corpus_id})-[matched_rel:CONTAINS|MENTIONS]->(matched_node) "
                    "WITH p, matched_node, [term IN $search_terms WHERE "
                    "  ANY(value IN [p.title, p.doi, p.journal, matched_node.text, matched_node.label, "
                    "                matched_node.entity_type, matched_node.type] "
                    "      WHERE toLower(coalesce(toString(value), '')) CONTAINS term)] AS matched_terms "
                    "WHERE size(matched_terms) > 0 "
                    "WITH p, max(size(matched_terms)) AS paper_score "
                    "ORDER BY paper_score DESC, coalesce(p.year, 0) DESC, toLower(coalesce(p.title, '')) ASC "
                    "LIMIT $paper_limit "
                    "MATCH (p)-[r:MENTIONS|CONTAINS]->(n) "
                    "WITH p, r, n, paper_score, [term IN $search_terms WHERE "
                    "  ANY(value IN [p.title, n.text, n.label, n.entity_type, n.type] "
                    "      WHERE toLower(coalesce(toString(value), '')) CONTAINS term)] AS node_terms "
                    "RETURN p, r, n, paper_score + size(node_terms) AS score "
                    "ORDER BY score DESC, CASE type(r) WHEN 'MENTIONS' THEN 0 ELSE 1 END, "
                    "         toLower(coalesce(n.label, n.text, '')) ASC "
                    "LIMIT $limit",
                    corpus_id=corpus_id,
                    search_terms=search_terms,
                    paper_limit=max(1, min(normalized_limit, 12)),
                    limit=normalized_limit,
                )
                data = self._records_to_subgraph(records, normalized_limit)
                if data["nodes"]:
                    return data
            return self._representative_subgraph(session, corpus_id, normalized_limit)

    def _representative_subgraph(self, session: Any, corpus_id: str, limit: int) -> dict[str, Any]:
        records = session.run(
            "MATCH (p:Paper {corpus_id: $corpus_id})-[r:MENTIONS|CONTAINS]->(n) "
            "RETURN p, r, n, CASE type(r) WHEN 'MENTIONS' THEN 2 ELSE 1 END AS score "
            "ORDER BY CASE type(r) WHEN 'MENTIONS' THEN 0 ELSE 1 END, coalesce(p.year, 0) DESC, "
            "         toLower(coalesce(p.title, '')) ASC, toLower(coalesce(n.label, n.text, '')) ASC "
            "LIMIT $limit",
            corpus_id=corpus_id,
            limit=limit,
        )
        data = self._records_to_subgraph(records, limit)
        if data["nodes"]:
            data["provenance"] = {"match_mode": "representative_fallback"}
            return data
        paper_records = session.run(
            "MATCH (p:Paper {corpus_id: $corpus_id}) "
            "RETURN p, null AS r, null AS n, 1 AS score "
            "ORDER BY coalesce(p.year, 0) DESC, toLower(coalesce(p.title, '')) ASC "
            "LIMIT $limit",
            corpus_id=corpus_id,
            limit=limit,
        )
        data = self._records_to_subgraph(paper_records, limit)
        if data["nodes"]:
            data["provenance"] = {"match_mode": "paper_fallback"}
        return data

    @staticmethod
    def _records_to_subgraph(records: Any, limit: int) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges = []
        edge_index = 0
        for record in records:
            paper = dict(record["p"])
            score = float(record.get("score") or 1.0)
            paper_id = f"paper:{paper['document_id']}"
            nodes[paper_id] = {"id": paper_id, "label": paper.get("title") or paper_id, "type": "Paper",
                               "score": max(score, 1.0),
                               "properties": Neo4jGraphStore._public_graph_properties(paper)}
            raw_target = record.get("n")
            raw_relationship = record.get("r")
            if raw_target is None or raw_relationship is None:
                continue
            target = dict(raw_target)
            target_id = target.get("source_id") or f"{paper['document_id']}:{target.get('chunk_id') or target.get('label') or len(nodes)}"
            nodes[target_id] = {"id": target_id, "label": target.get("label") or target.get("text", "")[:80] or target_id,
                                "type": target.get("entity_type") or "Chunk", "score": max(score, 1.0),
                                "properties": Neo4jGraphStore._public_graph_properties(target)}
            edges.append({"id": f"edge:{edge_index}", "source": paper_id, "target": target_id,
                          "type": raw_relationship.type, "weight": score,
                          "properties": Neo4jGraphStore._public_graph_properties(dict(raw_relationship))})
            edge_index += 1
        return {"nodes": list(nodes.values())[:limit], "edges": edges[:limit]}

    @staticmethod
    def _public_graph_properties(properties: dict[str, Any]) -> dict[str, Any]:
        blocked = {"embedding", "storage_uri", "object_key", "content_hash", "_id"}
        return {key: value for key, value in properties.items() if key not in blocked}

    def corpus_stats(self, corpus_id: str) -> dict[str, int]:
        with self.driver.session() as session:
            record = session.run(
                "MATCH (p:Paper {corpus_id: $corpus_id}) "
                "OPTIONAL MATCH (p)-[r:CONTAINS|MENTIONS]->(n) "
                "RETURN count(DISTINCT p) AS paper_count, "
                "count(DISTINCT CASE WHEN n:Chunk THEN n END) AS chunk_count, "
                "count(DISTINCT CASE WHEN n:Entity THEN n END) AS entity_count, "
                "count(DISTINCT n) AS target_node_count, "
                "count(r) AS relationship_count",
                corpus_id=corpus_id,
            ).single()
            if not record:
                return {
                    "paper_count": 0,
                    "chunk_count": 0,
                    "entity_count": 0,
                    "node_count": 0,
                    "relationship_count": 0,
                }
            paper_count = int(record["paper_count"] or 0)
            target_node_count = int(record["target_node_count"] or 0)
            return {
                "paper_count": paper_count,
                "chunk_count": int(record["chunk_count"] or 0),
                "entity_count": int(record["entity_count"] or 0),
                "node_count": paper_count + target_node_count,
                "relationship_count": int(record["relationship_count"] or 0),
            }

    @staticmethod
    def _paper_properties(document: dict[str, Any]) -> dict[str, Any]:
        allowed = ("document_id", "corpus_id", "doi", "title", "journal", "year", "source_url", "source_kind")
        return {key: document.get(key) for key in allowed if document.get(key) is not None}
