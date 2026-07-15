from __future__ import annotations

from app.query import expand_query_text, has_domain_anchor


def test_agirent_domain_queries_have_search_anchors() -> None:
    assert has_domain_anchor("What welding variables affect weld microstructure?")
    assert has_domain_anchor("What rare earth alloy properties are discussed?")
    assert has_domain_anchor("Which surface treatment improves corrosion resistance?")


def test_chinese_agirent_domain_queries_expand_to_english_anchors() -> None:
    assert has_domain_anchor("焊接工艺如何影响焊缝组织？")
    assert has_domain_anchor("稀土磁体有哪些关键性能？")
    assert has_domain_anchor("表面处理如何提升耐腐蚀涂层？")
    assert "welding" in expand_query_text("焊接材料")
    assert "rare-earth" in expand_query_text("稀土材料")
    assert "coating" in expand_query_text("表面处理")
