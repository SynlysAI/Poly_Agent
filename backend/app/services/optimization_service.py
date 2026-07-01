"""优化 campaign 业务服务。"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.infra.computation_repositories import (
    AuditEventRepository,
    OptimizationCampaignRepository,
    OptimizationCandidateRepository,
    OptimizationObservationRepository,
    OptimizationSuggestionRepository,
    utc_now,
)
from app.schemas.computation import ComputationCreateRequest, ComputationParameters, ComputationResources, MoleculeInput
from app.schemas.optimization import (
    CampaignCreateRequest,
    CampaignDetailData,
    CampaignListData,
    CandidateImportData,
    CandidateImportRequest,
    ObservationCreateRequest,
    OptimizationCampaign,
    OptimizationCandidate,
    OptimizationObservation,
    OptimizationSuggestion,
    SubmitSuggestionComputationData,
    SuggestionCreateData,
    SuggestionCreateRequest,
)
from app.services.computation_service import ComputationService


class OptimizationService:
    """优化 campaign 服务。"""

    def __init__(self) -> None:
        self.computation_service = ComputationService()

    def create_campaign(
        self,
        payload: CampaignCreateRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> OptimizationCampaign:
        """创建 campaign。"""
        now = utc_now()
        campaign = OptimizationCampaign(
            campaign_id=self._new_id("camp"),
            name=payload.name,
            status="draft",
            planner_type=payload.planner_type,
            search_space={"kind": "discrete_molecule_library", "candidate_count": 0},
            objectives=payload.objectives,
            planner_config=payload.planner_config,
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        OptimizationCampaignRepository.save("campaign_id", campaign.model_dump(mode="python"))
        self._audit(
            "campaign.created",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign.campaign_id,
            after={"status": "draft"},
        )
        return campaign

    def list_campaigns(self, *, page: int, page_size: int) -> CampaignListData:
        """分页查询 campaign。"""
        items, total = OptimizationCampaignRepository.list_all(page=page, page_size=page_size)
        return CampaignListData(
            items=[OptimizationCampaign(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_detail(self, campaign_id: str) -> CampaignDetailData:
        """查询 campaign 详情。"""
        campaign = self._get_campaign(campaign_id)
        candidates = [OptimizationCandidate(**item) for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)]
        suggestions = [OptimizationSuggestion(**item) for item in OptimizationSuggestionRepository.list_by_campaign(campaign_id)]
        observations = [OptimizationObservation(**item) for item in OptimizationObservationRepository.list_by_campaign(campaign_id)]
        return CampaignDetailData(
            campaign=campaign,
            candidates=candidates,
            suggestions=suggestions,
            observations=observations,
        )

    def import_candidates(
        self,
        campaign_id: str,
        payload: CandidateImportRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> CandidateImportData:
        """导入候选分子。"""
        self._get_campaign(campaign_id)
        now = utc_now()
        existing = {
            item["candidate_key"]: item
            for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)
        }
        imported: list[OptimizationCandidate] = []
        for item in payload.candidates:
            candidate_id = existing.get(item.candidate_key, {}).get("candidate_id") or self._new_id("cand")
            candidate = OptimizationCandidate(
                candidate_id=candidate_id,
                campaign_id=campaign_id,
                candidate_key=item.candidate_key,
                smiles=item.smiles,
                parameters=item.parameters,
                descriptors={},
                metadata=item.metadata,
                is_active=True,
                created_at=existing.get(item.candidate_key, {}).get("created_at", now),
            )
            OptimizationCandidateRepository.save("candidate_id", candidate.model_dump(mode="python"))
            imported.append(candidate)
        OptimizationCampaignRepository.update_fields(
            campaign_id,
            {
                "status": "active",
                "updated_at": now,
                "search_space": {
                    "kind": "discrete_molecule_library",
                    "candidate_count": len(OptimizationCandidateRepository.list_by_campaign(campaign_id)),
                },
            },
        )
        self._audit(
            "candidates.imported",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            after={"imported_count": len(imported)},
        )
        return CandidateImportData(imported_count=len(imported), items=imported)

    def generate_suggestions(
        self,
        campaign_id: str,
        payload: SuggestionCreateRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> SuggestionCreateData:
        """使用 fallback planner 生成推荐。"""
        campaign = self._get_campaign(campaign_id)
        if campaign.planner_type != "fallback":
            raise HTTPException(status_code=400, detail="MVP 仅支持 fallback planner")
        candidates = [OptimizationCandidate(**item) for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)]
        suggestions = [OptimizationSuggestion(**item) for item in OptimizationSuggestionRepository.list_by_campaign(campaign_id)]
        observations = [OptimizationObservation(**item) for item in OptimizationObservationRepository.list_by_campaign(campaign_id)]
        evaluated_candidate_ids = {item.candidate_id for item in observations}
        pending_candidate_ids = {
            item.candidate_id
            for item in suggestions
            if item.status in {"suggested", "submitted"}
        }
        eligible = [
            item
            for item in candidates
            if item.is_active
            and item.candidate_id not in evaluated_candidate_ids
            and item.candidate_id not in pending_candidate_ids
        ]
        eligible.sort(key=lambda item: item.candidate_key)
        if not eligible:
            raise HTTPException(status_code=400, detail="没有可推荐的未评价候选")
        now = utc_now()
        next_iteration = (max((item.iteration_index for item in suggestions), default=0) + 1)
        created: list[OptimizationSuggestion] = []
        for offset, candidate in enumerate(eligible[: payload.batch_size]):
            suggestion = OptimizationSuggestion(
                suggestion_id=self._new_id("sug"),
                campaign_id=campaign_id,
                candidate_id=candidate.candidate_id,
                candidate_key=candidate.candidate_key,
                smiles=candidate.smiles,
                iteration_index=next_iteration + offset,
                status="suggested",
                planner_type="fallback",
                planner_payload={
                    "strategy": "first_unevaluated",
                    "reason": "first unevaluated active candidate",
                    "excluded_counts": {
                        "evaluated": len(evaluated_candidate_ids),
                        "pending": len(pending_candidate_ids),
                    },
                },
                created_at=now,
                updated_at=now,
            )
            OptimizationSuggestionRepository.save("suggestion_id", suggestion.model_dump(mode="python"))
            created.append(suggestion)
        self._audit(
            "suggestions.generated",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            after={"suggestion_count": len(created)},
        )
        return SuggestionCreateData(items=created)

    def create_observation(
        self,
        campaign_id: str,
        payload: ObservationCreateRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> OptimizationObservation:
        """写入 observation。"""
        self._get_campaign(campaign_id)
        candidate = OptimizationCandidateRepository.find_one(
            {"campaign_id": campaign_id, "candidate_id": payload.candidate_id}
        )
        if not candidate:
            raise HTTPException(status_code=404, detail="候选不存在")
        now = utc_now()
        observation = OptimizationObservation(
            observation_id=self._new_id("obs"),
            campaign_id=campaign_id,
            candidate_id=payload.candidate_id,
            suggestion_id=payload.suggestion_id,
            source_type=payload.source_type,
            source_run_id=payload.source_run_id,
            values=payload.values,
            uncertainty=payload.uncertainty,
            raw_result_ref=payload.raw_result_ref,
            confirmed_by=actor_user_id,
            created_at=now,
        )
        OptimizationObservationRepository.save("observation_id", observation.model_dump(mode="python"))
        if payload.suggestion_id:
            OptimizationSuggestionRepository.update_fields(
                payload.suggestion_id,
                {"status": "evaluated", "updated_at": now},
            )
        self._audit(
            "observation.created",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_observation",
            entity_id=observation.observation_id,
            related_ids={"campaign_id": campaign_id, "suggestion_id": payload.suggestion_id},
        )
        return observation

    def submit_suggestion_computation(
        self,
        suggestion_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> SubmitSuggestionComputationData:
        """将 suggestion 转为计算任务。"""
        suggestion_doc = OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id})
        if not suggestion_doc:
            raise HTTPException(status_code=404, detail="推荐不存在")
        suggestion = OptimizationSuggestion(**suggestion_doc)
        if suggestion.submitted_run_id:
            return SubmitSuggestionComputationData(
                suggestion_id=suggestion_id,
                run_id=suggestion.submitted_run_id,
                suggestion_status=suggestion.status,
            )
        if suggestion.status in {"evaluated", "rejected"}:
            raise HTTPException(status_code=400, detail="当前推荐状态不允许提交计算")
        payload = ComputationCreateRequest(
            workflow_type="MOCK_LASER",
            engine="MOCK",
            molecule=MoleculeInput(smiles=suggestion.smiles, name=suggestion.candidate_key),
            parameters=ComputationParameters(charge=0, multiplicity=1, method="GFN2-xTB"),
            resources=ComputationResources(num_cores=2, memory_mb=4096, max_wallclock_seconds=1800),
            source="optimization_suggestion",
            campaign_id=suggestion.campaign_id,
            suggestion_id=suggestion.suggestion_id,
        )
        created = self.computation_service.create_run(
            payload,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        now = utc_now()
        OptimizationSuggestionRepository.update_fields(
            suggestion_id,
            {"status": "submitted", "submitted_run_id": created.run_id, "updated_at": now},
        )
        self._audit(
            "suggestion.submitted_computation",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_suggestion",
            entity_id=suggestion_id,
            related_ids={"campaign_id": suggestion.campaign_id, "run_id": created.run_id},
        )
        return SubmitSuggestionComputationData(
            suggestion_id=suggestion_id,
            run_id=created.run_id,
            suggestion_status="submitted",
        )

    def _get_campaign(self, campaign_id: str) -> OptimizationCampaign:
        """查询 campaign，不存在则 404。"""
        campaign = OptimizationCampaignRepository.find_one({"campaign_id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="campaign 不存在")
        return OptimizationCampaign(**campaign)

    def _audit(
        self,
        event_type: str,
        *,
        actor_user_id: str,
        request_id: str | None,
        entity_type: str,
        entity_id: str,
        before: dict | None = None,
        after: dict | None = None,
        related_ids: dict | None = None,
    ) -> None:
        """写审计事件。"""
        AuditEventRepository.append(
            {
                "event_id": self._new_id("audit"),
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "actor_role": "user",
                "request_id": request_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "related_ids": related_ids or {},
                "before": before or {},
                "after": after or {},
                "metadata": {"source": "poly_agent"},
                "created_at": utc_now(),
            }
        )

    def _new_id(self, prefix: str) -> str:
        """生成业务 ID。"""
        return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d')}_{uuid4().hex[:10]}"
