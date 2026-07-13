#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Download approved OA PDFs and enqueue them for ingestion")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-api-key", required=True)
    parser.add_argument("--query-api-key", default="", help="Query API key used for post-import corpus verification")
    parser.add_argument("--authorized-pdf-dir", type=Path)
    parser.add_argument("--include-approved-oa", action="store_true",
                        help="Import approved OpenAlex OA records even when selected=false")
    parser.add_argument("--limit", type=int, default=None,
                        help="Maximum records to import. With --include-approved-oa, use 30 for the first production KrF batch.")
    parser.add_argument("--wait", action="store_true", help="Poll ingestion jobs until they finish before printing verification")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--poly-agent-base-url", default="",
                        help="Optional Poly Agent backend URL for end-to-end knowledge-bases verification")
    args = parser.parse_args()

    admin_api_key = args.admin_api_key.strip()
    query_api_key = args.query_api_key.strip()
    if not admin_api_key:
        raise SystemExit("ERROR: --admin-api-key is required and cannot be empty")
    if args.query_api_key and not query_api_key:
        raise SystemExit("ERROR: --query-api-key was provided but is empty")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {admin_api_key}"}
    records = select_records(manifest["items"], include_approved_oa=args.include_approved_oa, limit=args.limit)
    completed = 0
    failed = 0
    jobs = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for item in records:
            try:
                content, filename = resolve_pdf(client, item, args.authorized_pdf_dir)
                upload = client.post(
                    f"{args.base_url.rstrip('/')}/api/v1/documents/upload",
                    headers=headers,
                    data={"corpus_id": manifest["corpus_id"], "doi": item["doi"], "title": item["title"],
                          "source_kind": item["source_kind"], "source_url": item["source_url"]},
                    files={"file": (filename, content, "application/pdf")},
                )
                upload.raise_for_status()
                document_id = upload.json()["data"]["document_id"]
                job = client.post(f"{args.base_url.rstrip('/')}/api/v1/ingestion-jobs", headers=headers,
                                  json={"document_id": document_id})
                job.raise_for_status()
                job_data = job.json()["data"]
                jobs.append({"doi": item["doi"], "document_id": document_id, "job_id": job_data["job_id"]})
                completed += 1
                print("IMPORTED", item["doi"], job_data["job_id"], job_data["status"])
            except Exception as exc:
                failed += 1
                print("FAILED", item["doi"], f"{type(exc).__name__}: {exc}")
    print(f"SUMMARY imported={completed} failed={failed}")
    if args.wait and jobs:
        wait_for_jobs(args.base_url, headers, jobs, poll_interval=args.poll_interval, timeout=args.timeout)
    if query_api_key:
        verify_literature_rag(args.base_url, query_api_key, manifest["corpus_id"], expected_indexed=args.limit or len(records))
    if args.poly_agent_base_url:
        verify_poly_agent(args.poly_agent_base_url, manifest["corpus_id"], expected_indexed=args.limit or len(records))


def select_records(items: list[dict], *, include_approved_oa: bool, limit: int | None) -> list[dict]:
    if include_approved_oa:
        selected = [
            item for item in items
            if item.get("approval_status") == "approved" and item.get("source_kind") == "openalex_oa"
        ]
    else:
        selected = [
            item for item in items
            if item.get("selected") and item.get("approval_status") == "approved"
        ]
    return selected[:limit] if limit else selected


def resolve_pdf(client: httpx.Client, item: dict, authorized_pdf_dir: Path | None) -> tuple[bytes, str]:
    if item["source_kind"] == "authorized_upload":
        if not authorized_pdf_dir:
            raise RuntimeError(f"Authorized PDF directory is required for {item['doi']}")
        path = authorized_pdf_dir / f"{item['doi'].replace('/', '_')}.pdf"
        return path.read_bytes(), path.name
    validate_public_https_url(item["source_url"])
    response = client.get(item["source_url"])
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise RuntimeError(f"Resolved OA URL is not a PDF: {item['doi']}")
    filename = f"{item['doi'].replace('/', '_')}.pdf"
    return response.content, filename


def validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(f"Only public HTTPS PDF URLs are allowed: {url}")
    addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise RuntimeError(f"Private or non-global PDF host is not allowed: {parsed.hostname}")


def wait_for_jobs(base_url: str, headers: dict[str, str], jobs: list[dict], *, poll_interval: float, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    terminal = {"completed", "failed", "needs_review"}
    pending = {job["job_id"]: job for job in jobs}
    with httpx.Client(timeout=30.0) as client:
        while pending and time.monotonic() < deadline:
            for job_id, job in list(pending.items()):
                response = client.get(f"{base_url.rstrip('/')}/api/v1/ingestion-jobs/{job_id}", headers=headers)
                response.raise_for_status()
                data = response.json()["data"]
                status = data.get("status")
                if status in terminal:
                    pending.pop(job_id, None)
                    detail = data.get("error") or data.get("message") or ""
                    print("JOB", job["doi"], job_id, status, detail)
            if pending:
                time.sleep(poll_interval)
    for job in pending.values():
        print("JOB_TIMEOUT", job["doi"], job["job_id"])


def verify_literature_rag(base_url: str, query_api_key: str, corpus_id: str, *, expected_indexed: int) -> None:
    headers = {"Authorization": f"Bearer {query_api_key}"}
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{base_url.rstrip('/')}/api/v1/corpora", headers=headers)
        response.raise_for_status()
        items = response.json()["data"].get("items") or []
    corpus = next((item for item in items if item.get("corpus_id") == corpus_id), None)
    if not corpus:
        print("VERIFY_FAILED", "corpus_not_found", corpus_id)
        return
    indexed = int(corpus.get("indexed_document_count") or corpus.get("document_count") or 0)
    graph_nodes = int(corpus.get("graph_node_count") or 0)
    graph_relationships = int(corpus.get("graph_relationship_count") or 0)
    print("VERIFY_LITERATURE_RAG", f"indexed={indexed}", f"expected={expected_indexed}",
          f"graph_nodes={graph_nodes}", f"graph_relationships={graph_relationships}",
          f"status={corpus.get('status')}")
    if indexed < expected_indexed or graph_nodes <= 0 or graph_relationships <= 0:
        print("VERIFY_FAILED", "literature_rag_counts_not_ready")


def verify_poly_agent(poly_agent_base_url: str, corpus_id: str, *, expected_indexed: int) -> None:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{poly_agent_base_url.rstrip('/')}/api/v1/knowledge-bases/systems")
        response.raise_for_status()
        items = response.json()["data"].get("items") or []
    system = next((item for item in items if item.get("system_id") == corpus_id), None)
    if not system:
        print("VERIFY_FAILED", "poly_agent_system_not_found", corpus_id)
        return
    indexed = int(system.get("indexed_document_count") or system.get("document_count") or 0)
    graph_nodes = int(system.get("graph_node_count") or 0)
    graph_relationships = int(system.get("graph_relationship_count") or 0)
    print("VERIFY_POLY_AGENT", f"indexed={indexed}", f"expected={expected_indexed}",
          f"graph_nodes={graph_nodes}", f"graph_relationships={graph_relationships}",
          f"status={system.get('status')}", f"graph_backend={system.get('graph_backend')}")
    if indexed < expected_indexed or graph_nodes <= 0 or graph_relationships <= 0:
        print("VERIFY_FAILED", "poly_agent_counts_not_ready")


if __name__ == "__main__":
    main()
