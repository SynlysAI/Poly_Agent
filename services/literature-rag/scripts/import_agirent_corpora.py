#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


ARXIV_API_URL = "https://export.arxiv.org/api/query"
USPTO_PDF_URL = "https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{publication_number}"
USER_AGENT = "Agirent-LiteratureRAG/0.1 (mailto:research-contact@example.com)"
TARGET_CORPUS_IDS = {
    "agirent_welding",
    "agirent_rare_earth",
    "agirent_surface_treatment",
}


def default_data_root() -> Path:
    return Path(os.getenv("AGIRENT_RAG_DATA_ROOT", str(Path.home() / "data" / "agirent_literature_rag"))).expanduser()


@dataclass(frozen=True)
class Scenario:
    corpus_id: str
    name: str
    description: str
    domain: str
    material_family: str
    tags: tuple[str, ...]
    arxiv_queries: tuple[str, ...]
    patent_numbers: tuple[str, ...]


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    title: str
    source_url: str
    source_kind: str
    filename: str
    year: int | None = None
    doi: str = ""


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        corpus_id="agirent_welding",
        name="安捷睿焊接文献与专利知识库",
        description="Welding metallurgy, weld quality, filler materials, laser/arc/friction stir welding, and process optimization.",
        domain="welding_materials",
        material_family="welding_materials",
        tags=("安捷睿", "焊接", "paper_target:24", "patent_target:6"),
        arxiv_queries=(
            'all:"friction stir welding"',
            'all:"laser welding" AND all:alloy',
            'all:"arc welding" AND all:materials',
            'all:"weld nugget" OR all:"weld pool"',
        ),
        patent_numbers=("11097380", "6516992", "8434661", "20150321294", "20100089977", "20120279441"),
    ),
    Scenario(
        corpus_id="agirent_rare_earth",
        name="安捷睿稀土文献与专利知识库",
        description="Rare-earth alloys, magnets, separations, phosphors, catalysis, and process-property relationships.",
        domain="rare_earth_materials",
        material_family="rare_earth_materials",
        tags=("安捷睿", "稀土", "paper_target:24", "patent_target:6"),
        arxiv_queries=(
            'all:"rare earth" AND all:magnet',
            'all:"rare-earth" AND all:alloy',
            'all:"lanthanide" AND all:materials',
            'all:"rare earth" AND all:catalyst',
        ),
        patent_numbers=("6491765", "7488393", "8734714", "5437709", "10323299", "5129945"),
    ),
    Scenario(
        corpus_id="agirent_surface_treatment",
        name="安捷睿表面处理文献与专利知识库",
        description="Surface treatment, coatings, plasma treatment, corrosion resistance, oxidation, and interface engineering.",
        domain="surface_treatment",
        material_family="surface_treatment",
        tags=("安捷睿", "表面处理", "paper_target:24", "patent_target:6"),
        arxiv_queries=(
            'all:"surface treatment" AND all:coating',
            'all:"plasma treatment" AND all:surface',
            'all:"corrosion resistant coating"',
            'all:"anodic oxidation" AND all:surface',
        ),
        patent_numbers=("6375726", "20150184304", "20140134426", "7524535", "7135075", "20100206745"),
    ),
)


def scenario_by_id(corpus_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.corpus_id == corpus_id:
            return scenario
    raise ValueError(f"Unknown Agirent corpus id: {corpus_id}")


def scenario_payload(scenario: Scenario) -> dict[str, Any]:
    return {
        "corpus_id": scenario.corpus_id,
        "name": scenario.name,
        "description": scenario.description,
        "domain": scenario.domain,
        "material_family": scenario.material_family,
        "tags": list(scenario.tags),
    }


def safe_filename(value: str, suffix: str = ".pdf") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return f"{cleaned[:160] or 'document'}{suffix}"


def is_pdf(content: bytes) -> bool:
    return content.startswith(b"%PDF")


def arxiv_documents(client: httpx.Client, scenario: Scenario, *, target: int, per_query: int = 15) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    seen: set[str] = set()
    for query in scenario.arxiv_queries:
        response = client.get(
            ARXIV_API_URL,
            params={"search_query": query, "start": 0, "max_results": per_query, "sortBy": "relevance"},
        )
        response.raise_for_status()
        documents.extend(parse_arxiv_feed(response.content, seen=seen))
        if len(documents) >= target:
            break
        time.sleep(3.1)
    return documents[:target]


def parse_arxiv_feed(content: bytes, *, seen: set[str] | None = None) -> list[SourceDocument]:
    seen = seen if seen is not None else set()
    root = ET.fromstring(content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    documents: list[SourceDocument] = []
    for entry in root.findall("a:entry", ns):
        entry_id = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        source_id = entry_id.rsplit("/", maxsplit=1)[-1]
        if not source_id or source_id in seen:
            continue
        pdf_url = ""
        for link in entry.findall("a:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        if not pdf_url:
            continue
        seen.add(source_id)
        title = " ".join((entry.findtext("a:title", default=source_id, namespaces=ns) or source_id).split())
        year = parse_year(entry.findtext("a:published", default="", namespaces=ns))
        documents.append(
            SourceDocument(
                source_id=source_id,
                title=title,
                source_url=pdf_url,
                source_kind="publisher_oa",
                filename=safe_filename(source_id),
                year=year,
            )
        )
    return documents


def patent_documents(scenario: Scenario, *, target: int) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    for publication_number in scenario.patent_numbers[:target]:
        normalized = publication_number.strip().upper()
        documents.append(
            SourceDocument(
                source_id=f"uspto-{normalized}",
                title=f"US patent publication {normalized} for {scenario.domain}",
                source_url=USPTO_PDF_URL.format(publication_number=quote(normalized, safe="")),
                source_kind="authorized_upload",
                filename=safe_filename(f"uspto-{normalized}"),
            )
        )
    return documents


def parse_year(value: str) -> int | None:
    match = re.match(r"(\d{4})", value or "")
    return int(match.group(1)) if match else None


def download_pdf(client: httpx.Client, document: SourceDocument, *, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / document.filename
    if path.exists() and path.stat().st_size > 0:
        content = path.read_bytes()
        if is_pdf(content):
            return path
    response = client.get(document.source_url, follow_redirects=True)
    response.raise_for_status()
    content = response.content
    if not is_pdf(content):
        raise RuntimeError(f"Downloaded content is not a PDF: {document.source_url}")
    path.write_bytes(content)
    return path


def create_corpus(client: httpx.Client, base_url: str, admin_key: str, scenario: Scenario) -> None:
    response = client.post(
        f"{base_url.rstrip('/')}/api/v1/corpora",
        headers=admin_headers(admin_key),
        json=scenario_payload(scenario),
    )
    if response.status_code not in {200, 201}:
        response.raise_for_status()


def upload_and_enqueue(
    client: httpx.Client,
    *,
    base_url: str,
    admin_key: str,
    scenario: Scenario,
    document: SourceDocument,
    path: Path,
) -> dict[str, Any]:
    with path.open("rb") as fh:
        upload = client.post(
            f"{base_url.rstrip('/')}/api/v1/documents/upload",
            headers=admin_headers(admin_key),
            data={
                "corpus_id": scenario.corpus_id,
                "doi": document.doi,
                "title": document.title,
                "source_kind": document.source_kind,
                "source_url": document.source_url,
            },
            files={"file": (path.name, fh, "application/pdf")},
        )
    upload.raise_for_status()
    document_id = upload.json()["data"]["document_id"]
    job = client.post(
        f"{base_url.rstrip('/')}/api/v1/ingestion-jobs",
        headers=admin_headers(admin_key),
        json={"document_id": document_id},
    )
    job.raise_for_status()
    return {"document_id": document_id, "job_id": job.json()["data"]["job_id"], "title": document.title}


def wait_for_jobs(
    client: httpx.Client,
    *,
    base_url: str,
    admin_key: str,
    jobs: list[dict[str, Any]],
    poll_interval: float,
    timeout: float,
) -> None:
    pending = {job["job_id"]: job for job in jobs}
    deadline = time.monotonic() + timeout
    terminal = {"completed", "failed", "needs_review"}
    while pending and time.monotonic() < deadline:
        for job_id, job in list(pending.items()):
            response = client.get(f"{base_url.rstrip('/')}/api/v1/ingestion-jobs/{job_id}", headers=admin_headers(admin_key))
            response.raise_for_status()
            data = response.json()["data"]
            status = data.get("status")
            if status in terminal:
                pending.pop(job_id, None)
                print("JOB", job["title"][:80], job_id, status, data.get("error") or data.get("message") or "")
        if pending:
            time.sleep(poll_interval)
    for job in pending.values():
        print("JOB_TIMEOUT", job["title"][:80], job["job_id"])


def verify_corpora(client: httpx.Client, *, base_url: str, query_key: str, expected_ids: set[str]) -> dict[str, Any]:
    response = client.get(f"{base_url.rstrip('/')}/api/v1/corpora", headers=query_headers(query_key))
    response.raise_for_status()
    items = response.json()["data"].get("items") or []
    by_id = {item.get("corpus_id"): item for item in items}
    missing = sorted(expected_ids - set(by_id))
    if missing:
        raise RuntimeError(f"Missing Agirent corpora: {missing}")
    return {corpus_id: by_id[corpus_id] for corpus_id in sorted(expected_ids)}


def admin_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key.strip()}"}


def query_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key.strip()}"}


def selected_scenarios(raw: str) -> list[Scenario]:
    if not raw or raw == "all":
        return list(SCENARIOS)
    return [scenario_by_id(item.strip()) for item in raw.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and import Agirent welding/rare-earth/surface-treatment corpora")
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--admin-api-key", required=True)
    parser.add_argument("--query-api-key", required=True)
    parser.add_argument("--scenario", default="all", help="all or comma-separated corpus ids")
    parser.add_argument("--papers-per-scenario", type=int, default=24)
    parser.add_argument("--patents-per-scenario", type=int, default=6)
    data_root = default_data_root()
    parser.add_argument("--download-dir", type=Path, default=data_root / "pdf_cache")
    parser.add_argument("--manifest-dir", type=Path, default=data_root / "manifests")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=8.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    args = parser.parse_args()

    if not args.admin_api_key.strip():
        raise SystemExit("ERROR: --admin-api-key is required and cannot be empty")
    if not args.query_api_key.strip():
        raise SystemExit("ERROR: --query-api-key is required and cannot be empty")

    scenarios = selected_scenarios(args.scenario)
    args.manifest_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=45.0, headers={"User-Agent": USER_AGENT}) as client:
        all_imported: dict[str, list[dict[str, Any]]] = {}
        for scenario in scenarios:
            print("SCENARIO", scenario.corpus_id, scenario.name)
            create_corpus(client, args.base_url, args.admin_api_key, scenario)
            documents = arxiv_documents(client, scenario, target=args.papers_per_scenario)
            documents.extend(patent_documents(scenario, target=args.patents_per_scenario))
            manifest = {"corpus": scenario_payload(scenario), "items": [document.__dict__ for document in documents]}
            (args.manifest_dir / f"{scenario.corpus_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            jobs: list[dict[str, Any]] = []
            for document in documents:
                try:
                    path = download_pdf(client, document, output_dir=args.download_dir / scenario.corpus_id)
                    if args.dry_run:
                        print("DRY_RUN", scenario.corpus_id, document.source_id, path)
                        continue
                    result = upload_and_enqueue(
                        client,
                        base_url=args.base_url,
                        admin_key=args.admin_api_key,
                        scenario=scenario,
                        document=document,
                        path=path,
                    )
                    jobs.append(result)
                    print("IMPORTED", scenario.corpus_id, document.source_id, result["job_id"])
                except Exception as exc:
                    print("FAILED", scenario.corpus_id, document.source_id, f"{type(exc).__name__}: {exc}")
            if args.wait and jobs:
                wait_for_jobs(
                    client,
                    base_url=args.base_url,
                    admin_key=args.admin_api_key,
                    jobs=jobs,
                    poll_interval=args.poll_interval,
                    timeout=args.timeout,
                )
            all_imported[scenario.corpus_id] = jobs
        if not args.dry_run:
            summary = verify_corpora(
                client,
                base_url=args.base_url,
                query_key=args.query_api_key,
                expected_ids={scenario.corpus_id for scenario in scenarios},
            )
            print("VERIFY", json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        print("SUMMARY", json.dumps({key: len(value) for key, value in all_imported.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
