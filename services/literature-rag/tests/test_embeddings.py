from __future__ import annotations

from app.embeddings import create_embedding_provider


def test_hashing_embedding_provider_is_deterministic_and_normalized() -> None:
    provider = create_embedding_provider("hashing", 16)

    first = provider.embed_query("KrF photoresist polymer")
    second = provider.embed_query("KrF photoresist polymer")

    assert first == second
    assert len(first) == 16
    assert any(value != 0 for value in first)
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9
