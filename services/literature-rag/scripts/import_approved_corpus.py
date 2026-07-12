#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Download approved OA PDFs and enqueue them for ingestion")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--admin-api-key", required=True)
    parser.add_argument("--authorized-pdf-dir", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    headers = {"Authorization": f"Bearer {args.admin_api_key}"}
    completed = 0
    failed = 0
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for item in manifest["items"]:
            if not item.get("selected") or item.get("approval_status") != "approved":
                continue
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
                completed += 1
                print("IMPORTED", item["doi"], job.json()["data"]["job_id"], job.json()["data"]["status"])
            except Exception as exc:
                failed += 1
                print("FAILED", item["doi"], f"{type(exc).__name__}: {exc}")
    print(f"SUMMARY imported={completed} failed={failed}")


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


if __name__ == "__main__":
    main()
