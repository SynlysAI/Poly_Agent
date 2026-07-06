"""优化 campaign 业务服务。"""

from __future__ import annotations

import csv
import io
import json
import hashlib
import math
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import (
    AuditEventRepository,
    ComputationRunRepository,
    OptimizationCampaignRepository,
    OptimizationCandidateRepository,
    OptimizationObservationRepository,
    OptimizationSuggestionRepository,
    utc_now,
)
from app.schemas.computation import ComputationCreateRequest, ComputationParameters, ComputationResources, MoleculeInput
from app.schemas.optimization import (
    CampaignHistoryData,
    CampaignHistoryEvent,
    CampaignCreateRequest,
    CampaignDetailData,
    CampaignListData,
    CampaignStatus,
    CampaignStatusChangeRequest,
    CandidateImportData,
    CandidateImportCsvRequest,
    CandidateImportDuplicateRow,
    CandidateImportFailedRow,
    CandidateImportRequest,
    CandidateImportItem,
    CreateObservationFromComputationData,
    ObservationCreateRequest,
    OptimizationCampaign,
    OptimizationCandidate,
    OptimizationObservation,
    OptimizationSuggestion,
    PlannerCandidate,
    PlannerConstraints,
    PlannerObservation,
    PlannerRequest,
    SubmitSuggestionComputationData,
    SuggestionFailureRequest,
    SuggestionRejectRequest,
    SuggestionCreateData,
    SuggestionCreateRequest,
)
from app.services.computation_service import ComputationService
from app.services.planner_adapters import run_planner


COMPUTATION_PRESETS: dict[str, dict] = {
    "local_xtb": {
        "workflow_type": "LOCAL_XTB",
        "engine": "XTB",
        "method": "GFN2-xTB",
        "resources": {"num_cores": 2, "memory_mb": 4096, "max_wallclock_seconds": 1800},
    },
    "orca": {
        "workflow_type": "ORCA_COMPUTE_ENGINE_LASER",
        "engine": "ORCA",
        "method": "ORCA_B3LYP_DEF2_SVP",
        "resources": {"num_cores": 4, "memory_mb": 8192, "max_wallclock_seconds": 7200},
    },
}
ORCA_PRESET_METHODS = {"ORCA_B3LYP_DEF2_SVP", "ORCA_PBE0_DEF2_SVP"}
ACTIVE_CAMPAIGN_STATUSES = {"running"}
IMPORTABLE_CAMPAIGN_STATUSES = {"draft", "running"}
BLOCKED_CAMPAIGN_STATUSES = {"paused", "completed", "failed", "archived"}
CAMPAIGN_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"running", "paused", "archived", "failed"},
    "running": {"paused", "completed", "failed", "archived"},
    "paused": {"running", "completed", "failed", "archived"},
    "completed": {"archived"},
    "failed": {"archived"},
    "archived": set(),
}


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
        planner_config = self._normalize_planner_config(payload.planner_config)
        campaign = OptimizationCampaign(
            campaign_id=self._new_id("camp"),
            name=payload.name,
            status="draft",
            planner_type=payload.planner_type,
            search_space={"kind": "discrete_molecule_library", "candidate_count": 0},
            objectives=payload.objectives,
            planner_config=planner_config,
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

    def list_campaigns(
        self,
        *,
        page: int,
        page_size: int,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> CampaignListData:
        """分页查询 campaign。"""
        filters = {} if is_admin or not actor_user_id else {"created_by": actor_user_id}
        items, total = OptimizationCampaignRepository.list_all(filters, page=page, page_size=page_size)
        return CampaignListData(
            items=[OptimizationCampaign(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_detail(
        self,
        campaign_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> CampaignDetailData:
        """查询 campaign 详情。"""
        campaign = self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        candidates = [OptimizationCandidate(**item) for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)]
        suggestions = [OptimizationSuggestion(**item) for item in OptimizationSuggestionRepository.list_by_campaign(campaign_id)]
        observations = [OptimizationObservation(**item) for item in OptimizationObservationRepository.list_by_campaign(campaign_id)]
        return CampaignDetailData(
            campaign=campaign,
            candidates=candidates,
            suggestions=suggestions,
            observations=observations,
        )

    def change_campaign_status(
        self,
        campaign_id: str,
        target_status: CampaignStatus,
        payload: CampaignStatusChangeRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> OptimizationCampaign:
        """变更 campaign lifecycle 状态。"""
        campaign = self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if campaign.status == target_status:
            return campaign
        allowed = CAMPAIGN_STATUS_TRANSITIONS.get(campaign.status, set())
        if target_status not in allowed:
            raise HTTPException(status_code=400, detail=f"Campaign 不能从 {campaign.status} 切换到 {target_status}")
        now = utc_now()
        OptimizationCampaignRepository.update_fields(
            campaign_id,
            {
                "status": target_status,
                "updated_at": now,
            },
        )
        self._audit(
            "campaign.status_changed",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            before={"status": campaign.status},
            after={"status": target_status, "reason": payload.reason},
        )
        return OptimizationCampaign(**OptimizationCampaignRepository.find_one({"campaign_id": campaign_id}))

    def import_candidates(
        self,
        campaign_id: str,
        payload: CandidateImportRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> CandidateImportData:
        """导入候选分子。"""
        campaign = self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        self._ensure_campaign_importable(campaign)
        now = utc_now()
        existing = {
            item["candidate_key"]: item
            for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)
        }
        imported: list[OptimizationCandidate] = []
        imported_count = 0
        updated_count = 0
        duplicate_rows: list[CandidateImportDuplicateRow] = []
        seen_keys: set[str] = set()
        for row_number, item in enumerate(payload.candidates, start=1):
            if item.candidate_key in seen_keys:
                duplicate_rows.append(
                    CandidateImportDuplicateRow(
                        row_number=row_number,
                        candidate_key=item.candidate_key,
                        reason="candidate_key 在本次导入中重复",
                    )
                )
                continue
            seen_keys.add(item.candidate_key)
            existing_item = existing.get(item.candidate_key)
            candidate_id = existing_item.get("candidate_id") if existing_item else self._new_id("cand")
            candidate = OptimizationCandidate(
                candidate_id=candidate_id,
                campaign_id=campaign_id,
                candidate_key=item.candidate_key,
                smiles=item.smiles,
                parameters=item.parameters,
                descriptors=self._build_descriptors(item.smiles),
                metadata=item.metadata,
                is_active=True,
                created_at=existing_item.get("created_at", now) if existing_item else now,
            )
            OptimizationCandidateRepository.save("candidate_id", candidate.model_dump(mode="python"))
            imported.append(candidate)
            if existing_item:
                updated_count += 1
            else:
                imported_count += 1
        OptimizationCampaignRepository.update_fields(
            campaign_id,
            {
                "status": "running" if campaign.status == "draft" else campaign.status,
                "updated_at": now,
                "search_space": {
                    "kind": "discrete_molecule_library",
                    "candidate_count": len(OptimizationCandidateRepository.list_by_campaign(campaign_id)),
                },
            },
        )
        self._audit(
            "candidate.imported",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            after={
                "imported_count": imported_count,
                "updated_count": updated_count,
                "failed_count": 0,
                "duplicate_count": len(duplicate_rows),
            },
        )
        return CandidateImportData(
            imported_count=imported_count,
            updated_count=updated_count,
            failed_rows=[],
            duplicate_rows=duplicate_rows,
            items=imported,
        )

    def import_candidates_csv(
        self,
        campaign_id: str,
        payload: CandidateImportCsvRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> CandidateImportData:
        """从 CSV 文本导入候选分子。"""
        items, failed_rows, duplicate_rows = self._parse_candidate_csv(payload.csv_text)
        if items:
            report = self.import_candidates(
                campaign_id,
                CandidateImportRequest(candidates=items),
                actor_user_id=actor_user_id,
                request_id=request_id,
                is_admin=is_admin,
            )
        else:
            self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
            report = CandidateImportData(imported_count=0, updated_count=0, items=[])
        duplicate_rows.extend(report.duplicate_rows)
        self._audit(
            "candidate.import_reported",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            after={
                "source": "csv",
                "imported_count": report.imported_count,
                "updated_count": report.updated_count,
                "failed_count": len(failed_rows),
                "duplicate_count": len(duplicate_rows),
            },
        )
        return CandidateImportData(
            imported_count=report.imported_count,
            updated_count=report.updated_count,
            failed_rows=failed_rows,
            duplicate_rows=duplicate_rows,
            items=report.items,
        )

    def generate_suggestions(
        self,
        campaign_id: str,
        payload: SuggestionCreateRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> SuggestionCreateData:
        """使用配置的 planner 生成推荐。"""
        campaign = self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        self._ensure_campaign_active(campaign, action="生成新 suggestion")
        candidates = [OptimizationCandidate(**item) for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)]
        suggestions = [OptimizationSuggestion(**item) for item in OptimizationSuggestionRepository.list_by_campaign(campaign_id)]
        observations = [OptimizationObservation(**item) for item in OptimizationObservationRepository.list_by_campaign(campaign_id)]
        evaluated_candidate_ids = {item.candidate_id for item in observations}
        pending_candidate_ids = {
            item.candidate_id
            for item in suggestions
            if item.status in {"suggested", "submitted"}
        }
        active_candidates = [
            item
            for item in candidates
            if item.is_active
        ]
        excluded_candidate_ids = sorted(evaluated_candidate_ids | pending_candidate_ids)
        eligible_count = len([item for item in active_candidates if item.candidate_id not in excluded_candidate_ids])
        if not eligible_count:
            raise HTTPException(status_code=400, detail="没有可推荐的未评价候选")
        planner_request = self._build_planner_request(
            campaign,
            candidates=active_candidates,
            observations=observations,
            batch_size=payload.batch_size,
            constraints={
                **(campaign.planner_config.get("constraints") or {}),
                "excluded_candidate_ids": excluded_candidate_ids,
                "excluded_counts": {
                    "evaluated": len(evaluated_candidate_ids),
                    "pending": len(pending_candidate_ids),
                },
            },
        )
        planner_response = run_planner(planner_request)
        if not planner_response.suggestions:
            raise HTTPException(status_code=400, detail="planner 未返回可推荐候选")
        now = utc_now()
        next_iteration = (max((item.iteration_index for item in suggestions), default=0) + 1)
        created: list[OptimizationSuggestion] = []
        candidate_by_id = {item.candidate_id: item for item in candidates}
        for offset, planner_item in enumerate(planner_response.suggestions):
            candidate = candidate_by_id.get(planner_item.candidate_id)
            if not candidate:
                continue
            suggestion = OptimizationSuggestion(
                suggestion_id=self._new_id("sug"),
                campaign_id=campaign_id,
                candidate_id=candidate.candidate_id,
                candidate_key=candidate.candidate_key,
                smiles=candidate.smiles,
                iteration_index=next_iteration + offset,
                status="suggested",
                planner_type=campaign.planner_type,
                planner_payload={
                    "snapshot_schema_version": "suggestion_planner_snapshot.v1",
                    "request_schema_version": planner_request.schema_version,
                    "response_schema_version": planner_response.schema_version,
                    "request": planner_request.model_dump(mode="json"),
                    "response": planner_response.model_dump(mode="json"),
                    "score": planner_item.score,
                    "reason": planner_item.reason,
                    "confidence": planner_item.confidence,
                    "iteration_metadata": planner_response.iteration_metadata,
                },
                created_at=now,
                updated_at=now,
            )
            OptimizationSuggestionRepository.save("suggestion_id", suggestion.model_dump(mode="python"))
            created.append(suggestion)
        if not created:
            raise HTTPException(status_code=400, detail="planner 返回候选不存在")
        self._audit(
            "suggestion.generated",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            after={"suggestion_count": len(created)},
        )
        return SuggestionCreateData(items=created)

    def get_history(
        self,
        campaign_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> CampaignHistoryData:
        """返回 campaign 的候选、推荐、observation 和 source run 历史。"""
        self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        candidates = [OptimizationCandidate(**item) for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)]
        suggestions = [OptimizationSuggestion(**item) for item in OptimizationSuggestionRepository.list_by_campaign(campaign_id)]
        observations = [OptimizationObservation(**item) for item in OptimizationObservationRepository.list_by_campaign(campaign_id)]
        audit_events, _ = AuditEventRepository.list_events(
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            event_type="campaign.status_changed",
            page=1,
            page_size=200,
        )
        items: list[CampaignHistoryEvent] = []
        for event in audit_events:
            items.append(
                CampaignHistoryEvent(
                    event_type="campaign.status_changed",
                    occurred_at=event["created_at"],
                    campaign_id=campaign_id,
                    summary={
                        "from_status": (event.get("before") or {}).get("status"),
                        "to_status": (event.get("after") or {}).get("status"),
                        "reason": (event.get("after") or {}).get("reason"),
                    },
                )
            )
        for candidate in candidates:
            items.append(
                CampaignHistoryEvent(
                    event_type="candidate.imported",
                    occurred_at=candidate.created_at,
                    campaign_id=campaign_id,
                    candidate_id=candidate.candidate_id,
                    summary={
                        "candidate_key": candidate.candidate_key,
                        "smiles": candidate.smiles,
                        "descriptor_status": candidate.descriptors.get("status"),
                    },
                )
            )
        for suggestion in suggestions:
            items.append(
                CampaignHistoryEvent(
                    event_type="suggestion.generated",
                    occurred_at=suggestion.created_at,
                    campaign_id=campaign_id,
                    candidate_id=suggestion.candidate_id,
                    suggestion_id=suggestion.suggestion_id,
                    source_run_id=suggestion.submitted_run_id,
                    summary={
                        "candidate_key": suggestion.candidate_key,
                        "status": suggestion.status,
                        "iteration_index": suggestion.iteration_index,
                    },
                )
            )
            if suggestion.status != "suggested":
                items.append(
                    CampaignHistoryEvent(
                        event_type=f"suggestion.{suggestion.status}",
                        occurred_at=suggestion.updated_at,
                        campaign_id=campaign_id,
                        candidate_id=suggestion.candidate_id,
                        suggestion_id=suggestion.suggestion_id,
                        source_run_id=suggestion.submitted_run_id,
                        summary={
                            "candidate_key": suggestion.candidate_key,
                            "status": suggestion.status,
                            "reason": (suggestion.planner_payload.get("rejection") or suggestion.planner_payload.get("failure") or {}).get("reason"),
                            "error_code": (suggestion.planner_payload.get("failure") or {}).get("error_code"),
                        },
                    )
                )
        for observation in observations:
            items.append(
                CampaignHistoryEvent(
                    event_type="observation.created",
                    occurred_at=observation.created_at,
                    campaign_id=campaign_id,
                    candidate_id=observation.candidate_id,
                    suggestion_id=observation.suggestion_id,
                    source_run_id=observation.source_run_id,
                    summary={"values": observation.values, "source_type": observation.source_type},
                )
            )
        items.sort(key=lambda item: item.occurred_at)
        return CampaignHistoryData(items=items)

    def create_observation_from_computation(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> CreateObservationFromComputationData:
        """从 completed laser run 生成 observation。"""
        run_doc = ComputationRunRepository.find_one({"run_id": run_id})
        if not run_doc:
            raise HTTPException(status_code=404, detail="计算任务不存在")
        if run_doc.get("status") != "completed":
            raise HTTPException(status_code=400, detail="仅 completed 计算任务可生成 observation")
        if run_doc.get("workflow_type") != "ORCA_COMPUTE_ENGINE_LASER":
            raise HTTPException(status_code=400, detail="仅 laser workflow 支持自动映射 observation")
        campaign_id = run_doc.get("campaign_id")
        suggestion_id = run_doc.get("suggestion_id")
        if not campaign_id or not suggestion_id:
            raise HTTPException(status_code=400, detail="计算任务缺少 campaign/suggestion 关联")
        self._ensure_campaign_access(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        suggestion_doc = OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id})
        if not suggestion_doc:
            raise HTTPException(status_code=404, detail="关联推荐不存在")
        existing = OptimizationObservationRepository.find_one({"source_type": "computation", "source_run_id": run_id})
        if existing:
            return CreateObservationFromComputationData(observation=OptimizationObservation(**existing))
        campaign = self._get_campaign(campaign_id)
        values = self._map_computation_observation_values(run_doc, campaign)
        observation = self.create_observation(
            campaign_id,
            ObservationCreateRequest(
                candidate_id=suggestion_doc["candidate_id"],
                suggestion_id=suggestion_id,
                source_type="computation",
                source_run_id=run_id,
                values=values,
                raw_result_ref=run_id,
            ),
            actor_user_id=actor_user_id,
            request_id=request_id,
            is_admin=is_admin,
        )
        return CreateObservationFromComputationData(observation=observation)

    def process_completed_computation(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        request_id: str | None = None,
    ) -> CreateObservationFromComputationData | None:
        """按 campaign 自动化配置处理 completed computation。"""
        run_doc = ComputationRunRepository.find_one({"run_id": run_id})
        if not run_doc or run_doc.get("status") != "completed":
            return None
        campaign_id = run_doc.get("campaign_id")
        if not campaign_id:
            return None
        campaign = self._get_campaign(campaign_id)
        automation = campaign.planner_config.get("automation") or {}
        if not automation.get("auto_create_observation", False):
            return None
        try:
            data = self.create_observation_from_computation(
                run_id,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        except HTTPException as exc:
            self._audit(
                "automation.observation_failed",
                actor_user_id=actor_user_id,
                request_id=request_id,
                entity_type="optimization_campaign",
                entity_id=campaign_id,
                related_ids={"run_id": run_id, "suggestion_id": run_doc.get("suggestion_id")},
                after={"reason": str(exc.detail)},
            )
            return None
        self._audit(
            "automation.observation_created",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_observation",
            entity_id=data.observation.observation_id,
            related_ids={
                "campaign_id": campaign_id,
                "suggestion_id": data.observation.suggestion_id,
                "run_id": run_id,
            },
            after={"values": data.observation.values},
        )
        if automation.get("auto_generate_suggestion", False):
            try:
                suggestions = self.generate_suggestions(
                    campaign_id,
                    SuggestionCreateRequest(batch_size=int(automation.get("suggestion_batch_size") or 1)),
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                )
            except HTTPException as exc:
                self._audit(
                    "automation.suggestion_skipped",
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                    entity_type="optimization_campaign",
                    entity_id=campaign_id,
                    related_ids={"run_id": run_id},
                    after={"reason": str(exc.detail)},
                )
            else:
                self._audit(
                    "automation.suggestion_triggered",
                    actor_user_id=actor_user_id,
                    request_id=request_id,
                    entity_type="optimization_campaign",
                    entity_id=campaign_id,
                    related_ids={"run_id": run_id},
                    after={"suggestion_count": len(suggestions.items)},
                )
        return data

    def create_observation(
        self,
        campaign_id: str,
        payload: ObservationCreateRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> OptimizationObservation:
        """写入 observation。"""
        campaign = self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        candidate = OptimizationCandidateRepository.find_one(
            {"campaign_id": campaign_id, "candidate_id": payload.candidate_id}
        )
        if not candidate:
            raise HTTPException(status_code=404, detail="候选不存在")
        self._validate_observation_values(campaign, payload.values)
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
        is_admin: bool = False,
    ) -> SubmitSuggestionComputationData:
        """将 suggestion 转为计算任务。"""
        suggestion_doc = OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id})
        if not suggestion_doc:
            raise HTTPException(status_code=404, detail="推荐不存在")
        suggestion = OptimizationSuggestion(**suggestion_doc)
        self._ensure_campaign_access(suggestion.campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        if suggestion.status in {"evaluated", "rejected", "failed"}:
            raise HTTPException(status_code=400, detail="当前推荐状态不允许提交计算")
        if suggestion.submitted_run_id:
            return SubmitSuggestionComputationData(
                suggestion_id=suggestion_id,
                run_id=suggestion.submitted_run_id,
                suggestion_status=suggestion.status,
            )
        campaign = self._get_campaign(suggestion.campaign_id)
        self._ensure_campaign_active(campaign, action="提交新 computation")
        computation_payload = self._build_suggestion_computation_payload(suggestion, campaign)
        created = self.computation_service.create_run(
            computation_payload,
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
            after={"computation_preset": computation_payload.source},
        )
        return SubmitSuggestionComputationData(
            suggestion_id=suggestion_id,
            run_id=created.run_id,
            suggestion_status="submitted",
        )

    def _build_suggestion_computation_payload(
        self,
        suggestion: OptimizationSuggestion,
        campaign: OptimizationCampaign,
    ) -> ComputationCreateRequest:
        """Build a computation request from the campaign-owned preset."""
        preset_key, preset = self._resolve_computation_preset(campaign.planner_config)
        method = self._resolve_preset_method(preset_key, preset, campaign.planner_config)
        resources = self._resolve_preset_resources(preset, campaign.planner_config)
        return ComputationCreateRequest(
            workflow_type=preset["workflow_type"],
            engine=preset["engine"],
            molecule=MoleculeInput(smiles=suggestion.smiles, name=suggestion.candidate_key),
            parameters=ComputationParameters(charge=0, multiplicity=1, method=method),
            resources=resources,
            source=f"optimization_suggestion:{preset_key}",
            campaign_id=suggestion.campaign_id,
            suggestion_id=suggestion.suggestion_id,
        )

    def _normalize_planner_config(self, planner_config: dict) -> dict:
        """Validate and normalize backend-owned computation preset config."""
        config = dict(planner_config or {})
        preset_key, _ = self._resolve_computation_preset(config)
        try:
            constraints = PlannerConstraints(**(config.get("constraints") or {}))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"planner_config.constraints 无效：{exc}") from exc
        config["constraints"] = constraints.model_dump(mode="json", exclude_none=True)
        preset_config = config.get("computation_preset")
        if isinstance(preset_config, dict):
            allowed_keys = {"preset_key", "method", "resources"}
            unexpected = set(preset_config) - allowed_keys
            if unexpected:
                raise HTTPException(status_code=400, detail="computation_preset 只能包含 preset_key/method/resources")
        else:
            config["computation_preset"] = preset_key
        return config

    def _resolve_computation_preset(self, planner_config: dict) -> tuple[str, dict]:
        raw = (planner_config or {}).get("computation_preset", "local_xtb")
        if isinstance(raw, str):
            preset_key = raw.strip() or "local_xtb"
        elif isinstance(raw, dict):
            preset_key = str(raw.get("preset_key") or raw.get("key") or "").strip()
        else:
            raise HTTPException(status_code=400, detail="computation_preset 必须是后端白名单 preset")
        if preset_key not in COMPUTATION_PRESETS:
            raise HTTPException(status_code=400, detail=f"不支持的 computation_preset：{preset_key}")
        return preset_key, COMPUTATION_PRESETS[preset_key]

    def _resolve_preset_method(self, preset_key: str, preset: dict, planner_config: dict) -> str:
        raw = (planner_config or {}).get("computation_preset")
        method = preset["method"]
        if isinstance(raw, dict) and raw.get("method"):
            method = str(raw["method"]).strip()
        if preset_key == "orca" and method not in ORCA_PRESET_METHODS:
            raise HTTPException(status_code=400, detail="ORCA preset method 必须来自后端白名单")
        return method

    def _resolve_preset_resources(self, preset: dict, planner_config: dict) -> ComputationResources:
        raw = (planner_config or {}).get("computation_preset")
        resource_payload = dict(preset["resources"])
        if isinstance(raw, dict) and isinstance(raw.get("resources"), dict):
            allowed_keys = {"num_cores", "memory_mb", "max_wallclock_seconds"}
            unexpected = set(raw["resources"]) - allowed_keys
            if unexpected:
                raise HTTPException(status_code=400, detail="resources 只能包含 num_cores/memory_mb/max_wallclock_seconds")
            resource_payload.update(raw["resources"])
        try:
            return ComputationResources(**resource_payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"computation_preset resources 无效：{exc}") from exc

    def reject_suggestion(
        self,
        suggestion_id: str,
        payload: SuggestionRejectRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> OptimizationSuggestion:
        """拒绝 suggested/submitted suggestion。"""
        suggestion = self._get_suggestion_for_update(
            suggestion_id,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        if suggestion.status in {"evaluated", "rejected", "failed"}:
            raise HTTPException(status_code=400, detail="当前推荐状态不允许拒绝")
        now = utc_now()
        planner_payload = {
            **suggestion.planner_payload,
            "rejection": {
                "reason": payload.reason,
                "rejected_by": actor_user_id,
                "rejected_at": now.isoformat(),
            },
        }
        OptimizationSuggestionRepository.update_fields(
            suggestion_id,
            {"status": "rejected", "planner_payload": planner_payload, "updated_at": now},
        )
        self._audit(
            "suggestion.rejected",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_suggestion",
            entity_id=suggestion_id,
            related_ids={"campaign_id": suggestion.campaign_id, "run_id": suggestion.submitted_run_id},
            before={"status": suggestion.status},
            after={"status": "rejected", "reason": payload.reason},
        )
        return OptimizationSuggestion(**OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id}))

    def mark_suggestion_failed(
        self,
        suggestion_id: str,
        payload: SuggestionFailureRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        is_admin: bool = False,
    ) -> OptimizationSuggestion:
        """标记 submitted/suggested suggestion 失败。"""
        suggestion = self._get_suggestion_for_update(
            suggestion_id,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        if suggestion.status in {"evaluated", "rejected", "failed"}:
            raise HTTPException(status_code=400, detail="当前推荐状态不允许标记失败")
        now = utc_now()
        planner_payload = {
            **suggestion.planner_payload,
            "failure": {
                "reason": payload.reason,
                "run_id": payload.run_id,
                "error_code": payload.error_code,
                "failed_by": actor_user_id,
                "failed_at": now.isoformat(),
            },
        }
        update_fields = {"status": "failed", "planner_payload": planner_payload, "updated_at": now}
        if payload.run_id and not suggestion.submitted_run_id:
            update_fields["submitted_run_id"] = payload.run_id
        OptimizationSuggestionRepository.update_fields(suggestion_id, update_fields)
        self._audit(
            "suggestion.failed",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_suggestion",
            entity_id=suggestion_id,
            related_ids={"campaign_id": suggestion.campaign_id, "run_id": payload.run_id or suggestion.submitted_run_id},
            before={"status": suggestion.status},
            after={"status": "failed", "reason": payload.reason, "error_code": payload.error_code},
        )
        return OptimizationSuggestion(**OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id}))

    def _build_descriptors(self, smiles: str) -> dict:
        """生成标准 candidate descriptor；RDKit 缺失时使用轻量 hash fingerprint。"""
        generated_at = utc_now().isoformat()
        parameters = {"kind": "morgan", "radius": 2, "n_bits": 2048}
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
        except ImportError:
            on_bits = self._build_smiles_hash_bits(smiles, n_bits=2048)
            return {
                "schema_version": "candidate_descriptor.v1",
                "status": "available",
                "generator": {"name": "smiles_hash_fingerprint", "version": "0.1.0"},
                "parameters": {"kind": "smiles_hash", "n_bits": 2048, "ngram_sizes": [1, 2, 3]},
                "values": {"on_bits": on_bits},
                "generated_at": generated_at,
            }
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            return {
                "schema_version": "candidate_descriptor.v1",
                "status": "failed",
                "generator": {"name": "rdkit_morgan", "version": getattr(Chem, "__version__", "unknown")},
                "parameters": parameters,
                "values": {"on_bits": []},
                "reason": "invalid_smiles",
                "generated_at": generated_at,
            }
        fingerprint = AllChem.GetMorganFingerprintAsBitVect(molecule, radius=2, nBits=2048)
        return {
            "schema_version": "candidate_descriptor.v1",
            "status": "available",
            "generator": {"name": "rdkit_morgan", "version": getattr(Chem, "__version__", "unknown")},
            "parameters": parameters,
            "values": {"on_bits": list(fingerprint.GetOnBits())},
            "generated_at": generated_at,
        }

    def _build_smiles_hash_bits(self, smiles: str, *, n_bits: int) -> list[int]:
        """构造稳定的轻量 SMILES 指纹，供无 RDKit 环境的 Tanimoto planner 使用。"""
        normalized = smiles.strip()
        if not normalized:
            return []
        tokens: set[str] = set()
        for size in (1, 2, 3):
            for index in range(0, max(len(normalized) - size + 1, 0)):
                tokens.add(normalized[index : index + size])
        if not tokens:
            tokens.add(normalized)
        return sorted(
            int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16) % n_bits
            for token in tokens
        )

    def _build_planner_request(
        self,
        campaign: OptimizationCampaign,
        *,
        candidates: list[OptimizationCandidate],
        observations: list[OptimizationObservation],
        batch_size: int,
        constraints: dict,
    ) -> PlannerRequest:
        """构造标准 planner 输入。"""
        return PlannerRequest(
            campaign_id=campaign.campaign_id,
            planner_type=campaign.planner_type,
            batch_size=batch_size,
            candidates=[
                PlannerCandidate(
                    candidate_id=item.candidate_id,
                    candidate_key=item.candidate_key,
                    smiles=item.smiles,
                    parameters=item.parameters,
                    descriptors=item.descriptors,
                )
                for item in candidates
            ],
            observations=[
                PlannerObservation(
                    observation_id=item.observation_id,
                    candidate_id=item.candidate_id,
                    suggestion_id=item.suggestion_id,
                    values=item.values,
                    uncertainty=item.uncertainty,
                    source_type=item.source_type,
                    source_run_id=item.source_run_id,
                )
                for item in observations
            ],
            objectives=campaign.objectives,
            constraints=PlannerConstraints(**constraints),
        )

    def _map_computation_observation_values(self, run_doc: dict, campaign: OptimizationCampaign) -> dict[str, float]:
        """按 campaign 白名单配置从 computation result_summary 提取 observation values。"""
        automation = campaign.planner_config.get("automation") or {}
        mapping = automation.get("observation_mapping") or {"gain_factor": "laser_metrics.gain_factor"}
        summary = run_doc.get("result_summary") or {}
        values: dict[str, float] = {}
        for target_name, source_path in mapping.items():
            raw_value = self._dig(summary, str(source_path))
            if isinstance(raw_value, (int, float)):
                values[str(target_name)] = float(raw_value)
        required_names = {objective.name for objective in campaign.objectives if objective.required}
        missing = sorted(required_names - set(values))
        if missing:
            raise HTTPException(status_code=400, detail=f"计算结果缺少必需 observation 指标：{', '.join(missing)}")
        return values

    def _parse_candidate_csv(
        self,
        csv_text: str,
    ) -> tuple[list[CandidateImportItem], list[CandidateImportFailedRow], list[CandidateImportDuplicateRow]]:
        """解析候选 CSV，保留行级失败报告。"""
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
        except csv.Error as exc:
            raise HTTPException(status_code=400, detail=f"CSV 无法解析：{exc}") from exc
        fieldnames = set(reader.fieldnames or [])
        required_fields = {"candidate_key", "smiles"}
        if not required_fields.issubset(fieldnames):
            raise HTTPException(status_code=400, detail="CSV 缺少必需字段：candidate_key, smiles")
        items: list[CandidateImportItem] = []
        failed_rows: list[CandidateImportFailedRow] = []
        duplicate_rows: list[CandidateImportDuplicateRow] = []
        seen_keys: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            candidate_key = str(row.get("candidate_key") or "").strip()
            smiles = str(row.get("smiles") or "").strip()
            if not candidate_key or not smiles:
                failed_rows.append(
                    CandidateImportFailedRow(
                        row_number=row_number,
                        candidate_key=candidate_key or None,
                        smiles=smiles or None,
                        reason="candidate_key 和 smiles 均不能为空",
                    )
                )
                continue
            if candidate_key in seen_keys:
                duplicate_rows.append(
                    CandidateImportDuplicateRow(
                        row_number=row_number,
                        candidate_key=candidate_key,
                        reason="candidate_key 在本次 CSV 中重复",
                    )
                )
                continue
            seen_keys.add(candidate_key)
            parameters = self._parse_json_cell(row.get("parameters"), default={})
            metadata = self._parse_json_cell(row.get("metadata"), default={})
            if parameters is None or metadata is None:
                failed_rows.append(
                    CandidateImportFailedRow(
                        row_number=row_number,
                        candidate_key=candidate_key,
                        smiles=smiles,
                        reason="parameters 或 metadata 不是合法 JSON object",
                    )
                )
                continue
            items.append(
                CandidateImportItem(
                    candidate_key=candidate_key,
                    smiles=smiles,
                    parameters=parameters,
                    metadata=metadata,
                )
            )
        if not items and not failed_rows and not duplicate_rows:
            raise HTTPException(status_code=400, detail="CSV 未包含候选数据行")
        return items, failed_rows, duplicate_rows

    def _parse_json_cell(self, value: str | None, *, default: dict) -> dict | None:
        """解析 CSV 中可选 JSON object 单元格。"""
        if value is None or not str(value).strip():
            return default
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _validate_observation_values(self, campaign: OptimizationCampaign, values: dict[str, float]) -> None:
        """校验 observation values 符合 campaign objective schema。"""
        objective_names = {objective.name for objective in campaign.objectives}
        unknown = sorted(set(values) - objective_names)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Observation 包含未知目标字段：{', '.join(unknown)}")
        required_names = {objective.name for objective in campaign.objectives if objective.required}
        missing = sorted(required_names - set(values))
        if missing:
            raise HTTPException(status_code=400, detail=f"Observation 缺少必需目标字段：{', '.join(missing)}")
        non_finite = [
            key
            for key, value in values.items()
            if not isinstance(value, (int, float)) or not math.isfinite(float(value))
        ]
        if non_finite:
            raise HTTPException(status_code=400, detail=f"Observation 数值必须是有限数字：{', '.join(sorted(non_finite))}")

    def _ensure_campaign_importable(self, campaign: OptimizationCampaign) -> None:
        """确保 campaign 可导入候选。"""
        if campaign.status not in IMPORTABLE_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail=f"{campaign.status} campaign 不允许导入候选")

    def _ensure_campaign_active(self, campaign: OptimizationCampaign, *, action: str) -> None:
        """确保 campaign 可继续闭环动作。"""
        if campaign.status not in ACTIVE_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail=f"{campaign.status} campaign 不允许{action}")

    def _dig(self, payload: dict, dotted_path: str):
        """读取 result_summary 中的点分路径。"""
        current = payload
        for part in dotted_path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _get_campaign(
        self,
        campaign_id: str,
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> OptimizationCampaign:
        """查询 campaign，不存在则 404。"""
        campaign = OptimizationCampaignRepository.find_one({"campaign_id": campaign_id})
        if not campaign:
            raise HTTPException(status_code=404, detail="campaign 不存在")
        if (
            actor_user_id
            and not is_admin
            and not actor_user_id.startswith("worker-")
            and campaign.get("created_by") != actor_user_id
        ):
            raise HTTPException(status_code=403, detail="无权限访问该 campaign")
        return OptimizationCampaign(**campaign)

    def _ensure_campaign_access(self, campaign_id: str, *, actor_user_id: str | None, is_admin: bool) -> None:
        """检查 campaign 数据权限。"""
        self._get_campaign(campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)

    def _get_suggestion_for_update(
        self,
        suggestion_id: str,
        *,
        actor_user_id: str | None,
        is_admin: bool,
    ) -> OptimizationSuggestion:
        """查询 suggestion 并校验所属 campaign 权限。"""
        suggestion_doc = OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id})
        if not suggestion_doc:
            raise HTTPException(status_code=404, detail="推荐不存在")
        suggestion = OptimizationSuggestion(**suggestion_doc)
        self._ensure_campaign_access(suggestion.campaign_id, actor_user_id=actor_user_id, is_admin=is_admin)
        return suggestion

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
