from __future__ import annotations

from app.domain import CandidateScoreInput, normalize_doi, score_candidate
from app.parsing import clean_pdf_text, chunk_text


def test_normalize_doi_removes_resolver_and_trailing_fragment() -> None:
    assert normalize_doi(" https://doi.org/10.1038/S41593-021-00813-9.pdf#view=FitH ") == (
        "10.1038/s41593-021-00813-9"
    )


def test_candidate_score_uses_fixed_plan_weights() -> None:
    score = score_candidate(
        CandidateScoreInput(
            relevance=1.0,
            journal_quality=0.8,
            citation_impact=0.6,
            recency_representativeness=0.4,
            fulltext_availability=1.0,
        )
    )
    assert score == 0.83


def test_clean_and_chunk_pdf_text_removes_repeated_headers_and_references() -> None:
    raw = """Journal of Lithography 12 (2024)\nIntroduction\nKrF chemically amplified resists use photoacid generators.\n\nJournal of Lithography 12 (2024)\nResults\nThe resin dissolution contrast improved after annealing.\nReferences\n[1] Example citation\n"""
    cleaned = clean_pdf_text(raw)
    assert "Journal of Lithography 12 (2024)" not in cleaned
    assert "Example citation" not in cleaned
    chunks = chunk_text(cleaned, chunk_size=12, overlap=3)
    assert len(chunks) >= 2
    assert all(chunk.chunk_id.startswith("chunk_") for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)
