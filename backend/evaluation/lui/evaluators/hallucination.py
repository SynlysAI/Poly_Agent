"""M5 幻觉率判定器。"""

from __future__ import annotations

from evaluation.lui.schemas import GoldenTask, MetricOutcome, ObservedFacts


CITATION_REFERENCE_TYPES = {"knowledge", "web"}


def _resolve_reference_keys(reference: dict) -> set[str]:
    """提取引用可解析的稳定键。"""
    keys: set[str] = set()
    for field in ("source_id", "target"):
        value = reference.get(field)
        if value:
            keys.add(str(value))
    return keys


def evaluate(task: GoldenTask, facts: ObservedFacts) -> MetricOutcome:
    """执行 M5 幻觉判定。

    离线规则层检查：禁止声明不得出现；声明引用必须能解析到
    观测检索结果 ID。LLM/人工原子声明抽取在录制评测层叠加。

    Args:
        task: Golden 任务。
        facts: 任务级观测事实。

    Returns:
        含无依据声明数与检查总数的判定结果。
    """
    expected = task.expected.hallucination
    content = (facts.message.content if facts.message else "") or ""
    if not (expected.forbidden_claims or expected.require_citations):
        return MetricOutcome(key="m5", applicable=False)

    checked = 0
    unsupported = 0
    findings: list[str] = []
    normalized = content.strip()
    for claim in expected.forbidden_claims:
        checked += 1
        if claim.strip() and claim in normalized:
            unsupported += 1
            findings.append(f"forbidden claim present: {claim}")

    if expected.require_citations:
        retrieval_ids: set[str] = set()
        for retrieval in facts.retrievals:
            retrieval_ids.update(item.id for item in retrieval.results)
        references = (facts.message.references if facts.message else []) or []
        citation_refs = [
            item
            for item in references
            if str(item.get("type") or "") in CITATION_REFERENCE_TYPES
        ]
        if normalized and not citation_refs:
            checked += 1
            unsupported += 1
            findings.append("answer has no citation references")
        for reference in citation_refs:
            checked += 1
            if not _resolve_reference_keys(reference).intersection(retrieval_ids):
                unsupported += 1
                findings.append(
                    f"unresolved citation: {reference.get('source_id') or reference.get('target')}"
                )

    rate = round(unsupported / checked, 6) if checked else 0.0
    return MetricOutcome(
        key="m5",
        applicable=True,
        passed=unsupported == 0,
        score=1.0 - rate,
        details={
            "unsupported_claims": unsupported,
            "checked_claims": checked,
            "hallucination_rate": rate,
            "findings": findings,
            "manual_checks": expected.checks,
        },
    )
