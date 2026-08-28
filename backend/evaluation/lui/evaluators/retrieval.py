"""M3 检索召回 Recall@K 判定器。"""

from __future__ import annotations

from evaluation.lui.schemas import GoldenTask, MetricOutcome, ObservedFacts


def recall_at_k(relevant_ids: list[str], ranked_ids: list[str], k: int) -> float:
    """计算单任务 Recall@K。

    Args:
        relevant_ids: Golden 相关证据 ID 集合。
        ranked_ids: 按检索排序的观测 ID 列表。
        k: 截断位次。

    Returns:
        前 K 命中相关证据占全部相关证据的比例。
    """
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    hits = relevant.intersection(ranked_ids[:k])
    return round(len(hits) / len(relevant), 6)


def ranked_observed_ids(facts: ObservedFacts, source: str) -> list[str]:
    """汇总观测检索结果的稳定有序 ID。

    Args:
        facts: 任务级观测事实。
        source: 期望来源；any 表示知识库与联网合并。

    Returns:
        去重后按 rank 槽位展开的 ID 列表；缺失槽位以空串占位，
        保证列表位置与观测 rank 语义一致。
    """
    best_rank: dict[str, int] = {}
    for retrieval in facts.retrievals:
        if source != "any" and retrieval.source != source:
            continue
        for item in retrieval.results:
            current = best_rank.get(item.id)
            if current is None or item.rank < current:
                best_rank[item.id] = item.rank
    if not best_rank:
        return []
    slots: list[str | None] = [None] * max(best_rank.values())
    for item_id, rank in best_rank.items():
        if slots[rank - 1] is None:
            slots[rank - 1] = item_id
    return [item or "" for item in slots]


def evaluate(task: GoldenTask, facts: ObservedFacts) -> MetricOutcome:
    """执行 M3 Recall@K 判定。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。

    Returns:
        含 Recall@1/3/5 的判定结果；主口径取 K=5（无 5 时取最大 K）。
    """
    expected = task.expected.retrieval
    if not expected:
        return MetricOutcome(key="m3", applicable=False)
    ranked = ranked_observed_ids(facts, expected.source)
    recalls = {
        f"recall@{k}": recall_at_k(expected.relevant_ids, ranked, k)
        for k in expected.ks
    }
    primary_k = 5 if 5 in expected.ks else max(expected.ks)
    primary = recalls[f"recall@{primary_k}"]
    visible_ranked_ids = [item for item in ranked if item]
    return MetricOutcome(
        key="m3",
        applicable=True,
        passed=primary >= 1.0,
        score=primary,
        details={
            "primary_k": primary_k,
            **recalls,
            "ranked_ids": visible_ranked_ids,
            "relevant_ids": expected.relevant_ids,
        },
    )
