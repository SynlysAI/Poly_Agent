"""优化 campaign 业务服务。"""

from __future__ import annotations

import json
import hashlib
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
    PlannerCandidate,
    PlannerObservation,
    PlannerRequest,
    SubmitSuggestionComputationData,
    SuggestionCreateData,
    SuggestionCreateRequest,
)
from app.services.computation_service import ComputationService
from app.services.planner_adapters import run_planner


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
        """使用配置的 planner 生成推荐。"""
        campaign = self._get_campaign(campaign_id)
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
                    "request": planner_request.model_dump(mode="json"),
                    "response": planner_response.model_dump(mode="json"),
                    "score": planner_item.score,
                    "reason": planner_item.reason,
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
            constraints=constraints,
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

    def _dig(self, payload: dict, dotted_path: str):
        """读取 result_summary 中的点分路径。"""
        current = payload
        for part in dotted_path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

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
