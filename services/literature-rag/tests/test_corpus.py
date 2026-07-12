from __future__ import annotations

import json

from app.corpus import build_manifest, extract_notebook_dois


def test_notebook_doi_extraction_deduplicates_without_preserving_mirror_urls(tmp_path) -> None:
    notebook = {
        "cells": [{"source": ["https://sci.example/pdf/10.1000/KRF-ONE.pdf#view=FitH"],
                   "outputs": [{"text": ["doi:10.1000/krf-one"]}]}]
    }
    path = tmp_path / "source.ipynb"
    path.write_text(json.dumps(notebook), encoding="utf-8")
    assert extract_notebook_dois(path) == ["10.1000/krf-one"]


def test_manifest_requires_verified_fulltext_for_approval() -> None:
    records = [
        {
            "doi": "10.1000/high-quality",
            "title": "Polymer resin and photoacid generator design for KrF photoresists",
            "abstract": "Chemically amplified 248 nm lithography with dissolution contrast.",
            "journal": "Macromolecules",
            "year": 2024,
            "cited_by_count": 30,
            "is_oa": True,
            "fulltext_url": "https://publisher.example/paper.pdf",
        },
        {
            "doi": "10.1000/no-fulltext",
            "title": "KrF photoresist polymer processing",
            "abstract": "248 nm resist process.",
            "journal": "Chemistry of Materials",
            "year": 2023,
            "cited_by_count": 20,
            "is_oa": False,
            "fulltext_url": None,
        },
    ]
    manifest = build_manifest(records, target=30)
    assert manifest["items"][0]["approval_status"] == "approved"
    assert manifest["items"][0]["source_kind"] == "openalex_oa"
    assert manifest["items"][1]["approval_status"] == "pending"
    assert manifest["items"][1]["exclusion_reason"] == "authorized_fulltext_required"
