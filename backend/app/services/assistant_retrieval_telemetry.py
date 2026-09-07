"""LUI 检索可观测性纯函数。

为知识库与联网检索构建稳定、有序、可判定的结果条目，并生成
`retrieval.result` 事件，支撑 Recall@K 与 used_in_answer 评测。
"""

from __future__ import annotations

from typing import Any


SNIPPET_MAX_CHARS = 240


def _clip_text(value: Any, limit: int = SNIPPET_MAX_CHARS) -> str:
    """截断文本以控制事件体积。

    Args:
        value: 原始文本。
        limit: 最大字符数。

    Returns:
        截断后的安全文本。
    """
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def knowledge_result_entries(outcome: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """把知识库检索结果转换为稳定有序条目。

    Args:
        outcome: KnowledgeOutcome，结果项需含 title/snippet/source_id/score。
        limit: 最多保留条数。

    Returns:
        含 id/rank/score/snippet 的结果条目列表。
    """
    entries: list[dict[str, Any]] = []
    for item in list(getattr(outcome, "results", None) or [])[:limit]:
        entry_id = str(getattr(item, "source_id", "") or getattr(item, "title", "") or "")
        if not entry_id:
            continue
        metadata = dict(getattr(item, "metadata", None) or {})
        entries.append(
            {
                "id": entry_id,
                "rank": len(entries) + 1,
                "score": getattr(item, "score", None),
                "rerank_score": metadata.get("rerank_score"),
                "retrieval_channels": metadata.get("retrieval_channels", []),
                "snippet": _clip_text(getattr(item, "snippet", "")),
            }
        )
    return entries


def web_result_entries(outcome: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """把联网检索结果转换为稳定有序条目。

    Args:
        outcome: SearchOutcome，结果项需含 title/url/snippet。
        limit: 最多保留条数。

    Returns:
        含 id/rank/snippet 的结果条目列表；web 证据暂无稳定分数。
    """
    entries: list[dict[str, Any]] = []
    for item in list(getattr(outcome, "results", None) or [])[:limit]:
        entry_id = str(getattr(item, "url", "") or "")
        if not entry_id:
            continue
        entries.append(
            {
                "id": entry_id,
                "rank": len(entries) + 1,
                "score": None,
                "snippet": _clip_text(getattr(item, "snippet", "")),
            }
        )
    return entries


def mark_used_in_answer(
    entries: list[dict[str, Any]],
    references: list[Any],
) -> list[dict[str, Any]]:
    """根据最终 references 标记检索条目是否被回答使用。

    Args:
        entries: retrieval.result 的结果条目。
        references: 最终回答引用列表，项含 source_id 或 target。

    Returns:
        补充 used_in_answer 布尔值后的条目列表。
    """
    used_keys: set[str] = set()
    for item in references or []:
        source_id = getattr(item, "source_id", None)
        target = getattr(item, "target", None)
        if isinstance(item, dict):
            source_id = item.get("source_id")
            target = item.get("target")
        if source_id:
            used_keys.add(str(source_id))
        if target:
            used_keys.add(str(target))
    return [
        {**entry, "used_in_answer": bool(entry.get("id") in used_keys)}
        for entry in entries
    ]


def retrieval_result_event(
    *,
    source: str,
    query_digest: str,
    status: str,
    entries: list[dict[str, Any]],
    retrieval_tier: str = "vector",
    rerank_applied: bool = False,
    upgrade_reason: str | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """构建 retrieval.result 事件。

    Args:
        source: 检索来源，knowledge 或 web。
        query_digest: 检索 query 摘要。
        status: 检索终态。
        entries: 已标记 used_in_answer 的稳定结果条目。
        retrieval_tier: 本次实际检索档位。
        rerank_applied: 是否应用确定性 rerank。
        upgrade_reason: 升级到混合检索的原因。
        fallback_reason: 混合检索或 rerank 的降级原因。

    Returns:
        可直接进入 LUI 事件流的字典。
    """
    return {
        "type": "retrieval.result",
        "source": source,
        "query_digest": query_digest,
        "status": status,
        "results": entries,
        "retrieval_tier": retrieval_tier,
        "rerank_applied": rerank_applied,
        "upgrade_reason": upgrade_reason,
        "fallback_reason": fallback_reason,
    }
