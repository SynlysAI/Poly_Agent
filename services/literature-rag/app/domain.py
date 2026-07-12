from __future__ import annotations

import re
from dataclasses import dataclass


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)
ALLOWED_SOURCE_KINDS = {"authorized_upload", "publisher_oa", "openalex_oa", "unpaywall", "pmc", "europe_pmc"}


def normalize_doi(value: str | None) -> str:
    raw = (value or "").strip()
    match = DOI_PATTERN.search(raw)
    if not match:
        return ""
    doi = match.group(0).lower()
    doi = doi.split("#", maxsplit=1)[0].split("?", maxsplit=1)[0]
    doi = re.sub(r"\.pdf$", "", doi)
    return doi.rstrip(".,;)]}")


@dataclass(frozen=True)
class CandidateScoreInput:
    relevance: float
    journal_quality: float
    citation_impact: float
    recency_representativeness: float
    fulltext_availability: float


def score_candidate(value: CandidateScoreInput) -> float:
    fields = (
        value.relevance,
        value.journal_quality,
        value.citation_impact,
        value.recency_representativeness,
        value.fulltext_availability,
    )
    if any(item < 0 or item > 1 for item in fields):
        raise ValueError("candidate score inputs must be between 0 and 1")
    score = (
        value.relevance * 0.45
        + value.journal_quality * 0.25
        + value.citation_impact * 0.15
        + value.recency_representativeness * 0.10
        + value.fulltext_availability * 0.05
    )
    return round(score, 4)
