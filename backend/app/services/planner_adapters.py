"""Lightweight optimization planner adapters."""

from __future__ import annotations

from app.schemas.optimization import PlannerRequest
from app.schemas.optimization import PlannerResponse
from app.schemas.optimization import PlannerSkippedItem
from app.schemas.optimization import PlannerSuggestionItem


def run_planner(request: PlannerRequest) -> PlannerResponse:
    """Dispatch a planner request to the configured lightweight adapter."""
    if request.planner_type == "tanimoto":
        return _run_tanimoto_planner(request)
    return _run_fallback_planner(request)


def _run_fallback_planner(request: PlannerRequest) -> PlannerResponse:
    """Select candidates in stable key order."""
    eligible, skipped = _eligible_candidates(request)
    eligible.sort(key=lambda item: item.candidate_key)
    suggestions = [
        PlannerSuggestionItem(
            candidate_id=candidate.candidate_id,
            candidate_key=candidate.candidate_key,
            score=0.0,
            reason="first unevaluated active candidate",
            confidence="high",
            metadata={"strategy": "first_unevaluated"},
        )
        for candidate in eligible[: request.batch_size]
    ]
    return PlannerResponse(
        planner_type="fallback",
        suggestions=suggestions,
        skipped=skipped,
        iteration_metadata={
            "candidate_count": len(request.candidates),
            "eligible_count": len(eligible),
            "skipped_count": len(skipped),
            "observation_count": len(request.observations),
        },
    )


def _run_tanimoto_planner(request: PlannerRequest) -> PlannerResponse:
    """Score eligible candidates by Tanimoto similarity to the best observed candidate."""
    eligible, skipped = _eligible_candidates(request)
    candidate_by_id = {candidate.candidate_id: candidate for candidate in request.candidates}
    best_observation = _best_observation(request)
    reference_candidate = candidate_by_id.get(best_observation.candidate_id) if best_observation else None
    reference_bits = _descriptor_bits(reference_candidate.descriptors) if reference_candidate else set()
    low_confidence_remaining = request.constraints.max_low_confidence_suggestions

    scored: list[PlannerSuggestionItem] = []
    for candidate in eligible:
        candidate_bits = _descriptor_bits(candidate.descriptors)
        if reference_bits and candidate_bits:
            score = _tanimoto(candidate_bits, reference_bits)
            confidence = "high"
            reason = f"Tanimoto similarity to best observed candidate {reference_candidate.candidate_key}"
            metadata = {
                "strategy": "tanimoto_similarity_to_best",
                "reference_candidate_id": reference_candidate.candidate_id,
                "reference_candidate_key": reference_candidate.candidate_key,
                "descriptor_status": candidate.descriptors.get("status"),
            }
            if request.constraints.minimum_similarity is not None and score < request.constraints.minimum_similarity:
                confidence = "low"
                reason = (
                    f"Tanimoto score {score:.3f} below minimum "
                    f"{request.constraints.minimum_similarity:.3f}"
                )
        else:
            score = 0.0
            confidence = "low"
            reason = "Tanimoto unavailable; descriptor or observation reference missing"
            metadata = {
                "strategy": "tanimoto_similarity_to_best",
                "descriptor_status": candidate.descriptors.get("status"),
            }
        if confidence == "low":
            if low_confidence_remaining <= 0:
                skipped.append(
                    PlannerSkippedItem(
                        candidate_id=candidate.candidate_id,
                        candidate_key=candidate.candidate_key,
                        reason=reason,
                        code="low_confidence",
                        metadata=metadata,
                    )
                )
                continue
            low_confidence_remaining -= 1
        scored.append(
            PlannerSuggestionItem(
                candidate_id=candidate.candidate_id,
                candidate_key=candidate.candidate_key,
                score=score,
                reason=reason,
                confidence=confidence,
                metadata=metadata,
            )
        )
    scored.sort(key=lambda item: (-item.score, item.candidate_key))
    return PlannerResponse(
        planner_type="tanimoto",
        suggestions=scored[: request.batch_size],
        skipped=skipped,
        iteration_metadata={
            "candidate_count": len(request.candidates),
            "eligible_count": len(eligible),
            "skipped_count": len(skipped),
            "observation_count": len(request.observations),
            "reference_candidate_id": reference_candidate.candidate_id if reference_candidate else None,
        },
    )


def _eligible_candidates(request: PlannerRequest):
    excluded = set(request.constraints.excluded_candidate_ids)
    allowed = set(request.constraints.allowed_candidate_ids or [])
    eligible = []
    skipped = []
    for candidate in request.candidates:
        if allowed and candidate.candidate_id not in allowed:
            skipped.append(
                PlannerSkippedItem(
                    candidate_id=candidate.candidate_id,
                    candidate_key=candidate.candidate_key,
                    reason="candidate not included in allowed_candidate_ids",
                    code="not_allowed",
                )
            )
            continue
        if candidate.candidate_id in excluded:
            skipped.append(
                PlannerSkippedItem(
                    candidate_id=candidate.candidate_id,
                    candidate_key=candidate.candidate_key,
                    reason="candidate excluded by planner constraints",
                    code="excluded_candidate",
                )
            )
            continue
        if request.constraints.require_descriptor and not _descriptor_bits(candidate.descriptors):
            skipped.append(
                PlannerSkippedItem(
                    candidate_id=candidate.candidate_id,
                    candidate_key=candidate.candidate_key,
                    reason="descriptor required but unavailable",
                    code="descriptor_unavailable",
                )
            )
            continue
        eligible.append(candidate)
    return eligible, skipped


def _best_observation(request: PlannerRequest):
    if not request.objectives:
        return None
    objective = request.objectives[0]
    observations = [
        observation
        for observation in request.observations
        if objective.name in observation.values
    ]
    if not observations:
        return None
    reverse = objective.direction == "max"
    return sorted(observations, key=lambda item: item.values[objective.name], reverse=reverse)[0]


def _descriptor_bits(descriptors: dict) -> set[int]:
    values = descriptors.get("values") or {}
    bits = values.get("on_bits", descriptors.get("on_bits", []))
    return {int(bit) for bit in bits if isinstance(bit, int)}


def _tanimoto(left: set[int], right: set[int]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
