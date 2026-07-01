"""优化 campaign 业务服务。"""

from __future__ import annotations

import json
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
    CandidateImportData,
    CandidateImportRequest,
    CandidateImportItem,
    CreateObservationFromComputationData,
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
                descriptors=self._build_descriptors(item.smiles),
                metadata=item.metadata,
                is_active=True,
                created_at=existing.get(item.candidate_key, {}).get("created_at", now),
            )
            OptimizationCandidateRepository.save("candidate_id", candidate.model_dump(mode="python"))
            imported.append(candidate)
        OptimizationCampaignRepository.update_fields(
            campaign_id,
            {
                "status": "running",
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
            "suggestion.generated",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="optimization_campaign",
            entity_id=campaign_id,
            after={"suggestion_count": len(created)},
        )
        return SuggestionCreateData(items=created)

    def get_history(self, campaign_id: str) -> CampaignHistoryData:
        """返回 campaign 的候选、推荐、observation 和 source run 历史。"""
        self._get_campaign(campaign_id)
        candidates = [OptimizationCandidate(**item) for item in OptimizationCandidateRepository.list_by_campaign(campaign_id)]
        suggestions = [OptimizationSuggestion(**item) for item in OptimizationSuggestionRepository.list_by_campaign(campaign_id)]
        observations = [OptimizationObservation(**item) for item in OptimizationObservationRepository.list_by_campaign(campaign_id)]
        items: list[CampaignHistoryEvent] = []
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

    def import_chemos_demo_candidates(
        self,
        campaign_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> CandidateImportData:
        """导入 ChemOS reference demo 分子库。"""
        items = self._load_chemos_demo_candidates()
        payload = CandidateImportRequest(candidates=items)
        return self.import_candidates(
            campaign_id,
            payload,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def create_observation_from_computation(
        self,
        run_id: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> CreateObservationFromComputationData:
        """从 completed MOCK_LASER run 生成 observation。"""
        run_doc = ComputationRunRepository.find_one({"run_id": run_id})
        if not run_doc:
            raise HTTPException(status_code=404, detail="计算任务不存在")
        if run_doc.get("status") != "completed":
            raise HTTPException(status_code=400, detail="仅 completed 计算任务可生成 observation")
        if run_doc.get("workflow_type") != "MOCK_LASER":
            raise HTTPException(status_code=400, detail="仅 MOCK_LASER 支持自动映射 observation")
        campaign_id = run_doc.get("campaign_id")
        suggestion_id = run_doc.get("suggestion_id")
        if not campaign_id or not suggestion_id:
            raise HTTPException(status_code=400, detail="计算任务缺少 campaign/suggestion 关联")
        suggestion_doc = OptimizationSuggestionRepository.find_one({"suggestion_id": suggestion_id})
        if not suggestion_doc:
            raise HTTPException(status_code=404, detail="关联推荐不存在")
        summary = run_doc.get("result_summary") or {}
        gain_factor = (summary.get("laser_metrics") or {}).get("gain_factor")
        if not isinstance(gain_factor, (int, float)):
            raise HTTPException(status_code=400, detail="计算结果缺少 laser_metrics.gain_factor")
        observation = self.create_observation(
            campaign_id,
            ObservationCreateRequest(
                candidate_id=suggestion_doc["candidate_id"],
                suggestion_id=suggestion_id,
                source_type="computation",
                source_run_id=run_id,
                values={"gain_factor": float(gain_factor)},
                raw_result_ref=run_id,
            ),
            actor_user_id=actor_user_id,
            request_id=request_id,
        )
        return CreateObservationFromComputationData(observation=observation)

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

    def _load_chemos_demo_candidates(self) -> list[CandidateImportItem]:
        """读取 ChemOS demo molecules.json；缺失时使用安全内置候选。"""
        molecules_path = (
            settings.project_root
            / "refer"
            / "ChemOS2.0-master"
            / "ChemOS2.0-simulation"
            / "job_files"
            / "molecules.json"
        )
        raw_items: list[dict] = []
        source_status = "molecules_json"
        if molecules_path.exists():
            with molecules_path.open("r", encoding="utf-8") as fp:
                raw = json.load(fp)
            if isinstance(raw, list):
                raw_items = [item for item in raw if isinstance(item, dict)]
            elif isinstance(raw, dict):
                raw_items = [item for item in raw.values() if isinstance(item, dict)]
        else:
            raw_items = self._fallback_chemos_candidates()
            source_status = "fallback_reference"

        candidates: list[CandidateImportItem] = []
        for index, item in enumerate(raw_items[:200], start=1):
            smiles = str(item.get("smiles") or item.get("SMILES") or "").strip()
            if not smiles:
                continue
            candidate_key = str(item.get("candidate_key") or item.get("name") or item.get("id") or f"CHEMOS_{index:03d}")
            candidates.append(
                CandidateImportItem(
                    candidate_key=candidate_key,
                    smiles=smiles,
                    parameters=item.get("parameters") or {},
                    metadata={
                        **(item.get("metadata") or {}),
                        "source": "ChemOS reference",
                        "source_status": source_status,
                    },
                )
            )
        if not candidates:
            raise HTTPException(status_code=400, detail="未找到可导入的 ChemOS demo 候选")
        return candidates

    def _fallback_chemos_candidates(self) -> list[dict]:
        """ChemOS reference 缺少 molecules.json 时的最小 demo 候选。"""
        csv_candidates = self._read_chemos_job_file_candidates()
        if csv_candidates:
            return csv_candidates
        return [
            {"candidate_key": "CHEMOS_DEMO_001", "smiles": "CCOC1=CC=CC=C1"},
            {"candidate_key": "CHEMOS_DEMO_002", "smiles": "COC1=CC=CC=C1"},
            {"candidate_key": "CHEMOS_DEMO_003", "smiles": "CCN(CC)C1=CC=CC=C1"},
        ]

    def _read_chemos_job_file_candidates(self) -> list[dict]:
        """从 ChemOS job_files CSV 提取轻量候选元数据。"""
        job_dir = settings.project_root / "refer" / "ChemOS2.0-master" / "ChemOS2.0-deploy" / "job_files"
        if not job_dir.exists():
            return []
        candidates: list[dict] = []
        default_smiles = ["CCOC1=CC=CC=C1", "COC1=CC=CC=C1", "CCN(CC)C1=CC=CC=C1"]
        for index, path in enumerate(sorted(job_dir.glob("*.csv"))[: len(default_smiles)], start=1):
            candidates.append(
                {
                    "candidate_key": f"CHEMOS_{path.stem.upper()}",
                    "smiles": default_smiles[index - 1],
                    "metadata": {"source_file": str(path.relative_to(settings.project_root))},
                }
            )
        return candidates

    def _build_descriptors(self, smiles: str) -> dict:
        """可选生成 RDKit Morgan fingerprint。"""
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
        except ImportError:
            return {"status": "not_available", "reason": "rdkit_not_installed"}
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            return {"status": "failed", "reason": "invalid_smiles"}
        fingerprint = AllChem.GetMorganFingerprintAsBitVect(molecule, radius=2, nBits=2048)
        return {
            "status": "available",
            "kind": "morgan",
            "radius": 2,
            "n_bits": 2048,
            "on_bits": list(fingerprint.GetOnBits()),
        }

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
