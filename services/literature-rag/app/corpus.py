from __future__ import annotations

import json
import math
import re
from urllib.parse import quote
from pathlib import Path
from typing import Any, Iterable

import httpx

from .domain import CandidateScoreInput, normalize_doi, score_candidate


KRF_TERMS = {
    "krf", "248 nm", "248-nm", "photoresist", "photoresists", "chemically amplified",
    "photoacid", "pag", "lithography", "resist resin", "dissolution contrast",
}
PREMIUM_VENUES = ("nature", "science", "advanced materials", "advanced functional materials")
CORE_VENUES = (
    "macromolecules", "chemistry of materials", "acs applied materials", "journal of materials chemistry",
    "polymer", "journal of polymer science", "microelectronic engineering", "journal of photopolymer",
)


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def extract_notebook_dois(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dois: set[str] = set()
    for text in _walk_strings(payload):
        for raw in re.findall(r"10\.\d{4,9}/[^\s\"<>]+", text, re.IGNORECASE):
            doi = normalize_doi(raw)
            if _plausible_doi(doi):
                dois.add(doi)
    return sorted(dois)


def _plausible_doi(doi: str) -> bool:
    return bool(doi and 8 <= len(doi) <= 200 and not any(token in doi for token in ("please", "&lt;", "\\n", "%25")))


def relevance_score(record: dict[str, Any]) -> float:
    title = str(record.get("title") or "").lower()
    haystack = f"{title} {record.get('abstract', '')}".lower()
    matches = sum(term in haystack for term in KRF_TERMS)
    required = any(term in haystack for term in ("krf", "248 nm", "248-nm"))
    title_krf = any(term in title for term in ("krf", "248 nm", "248-nm"))
    title_resist = "resist" in title or "lithograph" in title
    title_bonus = 0.4 if title_krf and title_resist else 0.18 if title_resist else 0.0
    return min(1.0, (0.25 if required else 0.0) + title_bonus + matches * 0.08)


def topic_tier(record: dict[str, Any]) -> int:
    title = str(record.get("title") or "").lower()
    haystack = f"{title} {record.get('abstract', '')}".lower()
    title_krf = any(term in title for term in ("krf", "248 nm", "248-nm"))
    title_resist = "resist" in title or "lithograph" in title
    body_krf = any(term in haystack for term in ("krf", "248 nm", "248-nm"))
    if title_krf and title_resist:
        return 3
    if title_resist and body_krf:
        return 2
    if body_krf and ("resist" in haystack or "lithograph" in haystack):
        return 1
    return 0


def journal_score(journal: str | None) -> float:
    value = (journal or "").lower()
    if any(name in value for name in PREMIUM_VENUES):
        return 1.0
    if any(name in value for name in CORE_VENUES):
        return 0.85
    return 0.55 if value else 0.2


def build_manifest(records: list[dict[str, Any]], *, target: int = 30) -> dict[str, Any]:
    maximum_citations = max((int(item.get("cited_by_count") or 0) for item in records), default=1)
    current_year = 2026
    items = []
    seen: set[str] = set()
    for record in records:
        doi = normalize_doi(record.get("doi"))
        if not _plausible_doi(doi) or doi in seen:
            continue
        seen.add(doi)
        relevance = relevance_score(record)
        citations = int(record.get("cited_by_count") or 0)
        citation_impact = math.log1p(citations) / max(math.log1p(maximum_citations), 1)
        year = int(record.get("year") or 0)
        recency = max(0.0, min(1.0, 1 - max(current_year - year, 0) / 25)) if year else 0.2
        fulltext_url = record.get("fulltext_url") if record.get("is_oa") else None
        score = score_candidate(CandidateScoreInput(
            relevance=relevance,
            journal_quality=journal_score(record.get("journal")),
            citation_impact=citation_impact,
            recency_representativeness=recency,
            fulltext_availability=1.0 if fulltext_url else 0.0,
        ))
        items.append({
            "doi": doi,
            "title": record.get("title") or doi,
            "authors": record.get("authors") or [],
            "journal": record.get("journal"),
            "year": year or None,
            "abstract": record.get("abstract"),
            "cited_by_count": citations,
            "score": score,
            "topic_tier": topic_tier(record),
            "selected": False,
            "approval_status": "approved" if fulltext_url else "pending",
            "verification_status": "verified",
            "source_kind": "openalex_oa" if fulltext_url else "authorized_upload",
            "source_url": fulltext_url or f"https://doi.org/{doi}",
            "license": record.get("license"),
            "exclusion_reason": None if fulltext_url else "authorized_fulltext_required",
        })
    items = [item for item in items if item["topic_tier"] > 0]
    items.sort(key=lambda item: (item["topic_tier"], item["score"], item["cited_by_count"]), reverse=True)
    for item in items[:target]:
        item["selected"] = True
    return {
        "corpus_id": "krf_photoresist",
        "target_document_count": target,
        "selection_policy": "top_journal_priority_plus_domain_core",
        "fulltext_policy": "authorized_upload_or_verified_open_access",
        "items": items,
        "summary": {
            "candidate_count": len(items),
            "selected_count": min(target, len(items)),
            "approved_selected_count": sum(item["selected"] and item["approval_status"] == "approved" for item in items),
            "pending_authorized_upload_count": sum(item["selected"] and item["approval_status"] == "pending" for item in items),
        },
    }


def search_openalex(*, email: str, per_query: int = 100) -> list[dict[str, Any]]:
    queries = [
        "KrF photoresist polymer resin",
        "248 nm chemically amplified resist photoacid generator",
        "KrF lithography dissolution contrast",
        "KrF resist post exposure bake critical dimension",
    ]
    records: list[dict[str, Any]] = []
    with httpx.Client(base_url="https://api.openalex.org", timeout=30.0,
                      headers={"User-Agent": f"PolyAgent-LiteratureRAG/0.1 ({email})"}) as client:
        for query in queries:
            response = client.get("/works", params={"search": query, "per-page": per_query, "mailto": email})
            response.raise_for_status()
            records.extend(_openalex_record(item) for item in response.json().get("results", []))
    return records


def verify_crossref(doi: str, *, email: str, client: httpx.Client | None = None) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.Client(base_url="https://api.crossref.org", timeout=20.0,
                                    headers={"User-Agent": f"PolyAgent-LiteratureRAG/0.1 (mailto:{email})"})
    try:
        response = client.get(f"/works/{quote(doi, safe='')}", params={"mailto": email})
        if response.status_code == 404:
            return {"verification_status": "not_found"}
        response.raise_for_status()
        message = response.json().get("message") or {}
        title = " ".join(message.get("title") or [])
        return {"verification_status": "verified", "crossref_title": title or None,
                "crossref_publisher": message.get("publisher")}
    except httpx.HTTPError as exc:
        return {"verification_status": "manual_needed", "verification_note": type(exc).__name__}
    finally:
        if owns_client:
            client.close()


def resolve_unpaywall(doi: str, *, email: str, client: httpx.Client | None = None) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.Client(base_url="https://api.unpaywall.org", timeout=20.0)
    try:
        response = client.get(f"/v2/{quote(doi, safe='')}", params={"email": email})
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        best = payload.get("best_oa_location") or {}
        url = best.get("url_for_pdf")
        return {"fulltext_url": url, "license": best.get("license"), "is_oa": bool(url)}
    except httpx.HTTPError:
        return {}
    finally:
        if owns_client:
            client.close()


def _openalex_record(item: dict[str, Any]) -> dict[str, Any]:
    primary = item.get("primary_location") or {}
    source = primary.get("source") or {}
    best_oa = item.get("best_oa_location") or {}
    authors = [
        ((entry.get("author") or {}).get("display_name"))
        for entry in item.get("authorships") or []
        if (entry.get("author") or {}).get("display_name")
    ]
    return {
        "doi": item.get("doi"),
        "title": item.get("display_name"),
        "abstract": _rebuild_abstract(item.get("abstract_inverted_index")),
        "authors": authors,
        "journal": source.get("display_name"),
        "year": item.get("publication_year"),
        "cited_by_count": item.get("cited_by_count", 0),
        "is_oa": bool((item.get("open_access") or {}).get("is_oa") and best_oa.get("pdf_url")),
        "fulltext_url": best_oa.get("pdf_url"),
        "license": best_oa.get("license"),
    }


def _rebuild_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positions = [(position, word) for word, values in index.items() for position in values]
    return " ".join(word for _, word in sorted(positions))
