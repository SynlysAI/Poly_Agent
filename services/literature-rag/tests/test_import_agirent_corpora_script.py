from __future__ import annotations

from scripts.import_agirent_corpora import (
    SCENARIOS,
    TARGET_CORPUS_IDS,
    default_data_root,
    is_pdf,
    parse_arxiv_feed,
    patent_documents,
    safe_filename,
    scenario_payload,
    selected_scenarios,
)


def test_agirent_target_corpora_do_not_include_krf() -> None:
    assert TARGET_CORPUS_IDS == {
        "agirent_welding",
        "agirent_rare_earth",
        "agirent_surface_treatment",
    }
    assert "krf_photoresist" not in TARGET_CORPUS_IDS
    assert {item.corpus_id for item in SCENARIOS} == TARGET_CORPUS_IDS


def test_scenario_payload_keeps_corpus_metadata_isolated() -> None:
    payload = scenario_payload(selected_scenarios("agirent_welding")[0])

    assert payload["corpus_id"] == "agirent_welding"
    assert payload["domain"] == "welding_materials"
    assert payload["material_family"] == "welding_materials"
    assert "焊接" in payload["tags"]


def test_parse_arxiv_feed_extracts_pdf_link_and_deduplicates() -> None:
    feed = b"""<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2301.00001v1</id>
        <title> A useful welding paper </title>
        <published>2023-01-01T00:00:00Z</published>
        <link href="https://arxiv.org/pdf/2301.00001v1" rel="related" type="application/pdf" title="pdf"/>
      </entry>
      <entry>
        <id>http://arxiv.org/abs/2301.00001v1</id>
        <title> Duplicate </title>
        <link href="https://arxiv.org/pdf/2301.00001v1" rel="related" type="application/pdf" title="pdf"/>
      </entry>
    </feed>
    """

    docs = parse_arxiv_feed(feed)

    assert len(docs) == 1
    assert docs[0].source_id == "2301.00001v1"
    assert docs[0].source_url == "https://arxiv.org/pdf/2301.00001v1"
    assert docs[0].source_kind == "publisher_oa"
    assert docs[0].year == 2023


def test_pdf_validation_and_safe_filename() -> None:
    assert is_pdf(b"%PDF-1.7\n...")
    assert not is_pdf(b"<!DOCTYPE html>")
    assert safe_filename("10.1000/foo/bar baz") == "10.1000_foo_bar_baz.pdf"


def test_patent_documents_use_authorized_upload_source_kind() -> None:
    scenario = selected_scenarios("agirent_rare_earth")[0]
    docs = patent_documents(scenario, target=2)

    assert len(docs) == 2
    assert all(doc.source_kind == "authorized_upload" for doc in docs)
    assert all(doc.source_url.startswith("https://image-ppubs.uspto.gov/") for doc in docs)


def test_default_data_root_uses_home_data_not_project_data(monkeypatch) -> None:
    monkeypatch.delenv("AGIRENT_RAG_DATA_ROOT", raising=False)

    root = default_data_root()

    assert root.name == "agirent_literature_rag"
    assert root.parent.name == "data"
    assert "/services/literature-rag/data" not in str(root)
