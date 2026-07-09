"""全局任务中心聚合服务。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.schemas.tasks import GlobalTaskCenterData, GlobalTaskItem
from app.services.computation_service import ComputationService
from app.services.optimization_service import OptimizationService
from app.services.research_engine_orchestrator import ResearchEngineOrchestrator
from app.services.research_engine_service import ResearchEngineService


MAX_AGGREGATE_PAGE_SIZE = 10000


class TaskCenterService:
    """聚合多个业务模块任务，提供统一搜索和分页。"""

    def __init__(self) -> None:
        self.computation_service = ComputationService()
        self.optimization_service = OptimizationService()
        self.research_service = ResearchEngineService()
        self.research_orchestrator = ResearchEngineOrchestrator()

    def list_tasks(
        self,
        *,
        module_id: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> GlobalTaskCenterData:
        """查询全局任务中心，先聚合再统一过滤、排序和分页。"""
        rows = self._collect_tasks(actor_user_id=actor_user_id, is_admin=is_admin)
        normalized_keyword = (keyword or "").strip().lower()
        filtered = [
            row
            for row in rows
            if self._matches(row, module_id=module_id, status=status, keyword=normalized_keyword)
        ]
        filtered.sort(key=self._sort_key, reverse=True)
        total = len(filtered)
        start = (page - 1) * page_size
        page_items = filtered[start : start + page_size]
        return GlobalTaskCenterData(
            items=page_items,
            page=page,
            page_size=page_size,
            total=total,
            summary=self._summarize(filtered),
        )

    def _collect_tasks(self, *, actor_user_id: str | None, is_admin: bool) -> list[GlobalTaskItem]:
        rows: list[GlobalTaskItem] = []
        rows.extend(self._computation_tasks(actor_user_id=actor_user_id, is_admin=is_admin))
        rows.extend(self._campaign_tasks(actor_user_id=actor_user_id, is_admin=is_admin))
        rows.extend(self._algorithm_run_tasks(actor_user_id=actor_user_id, is_admin=is_admin))
        rows.extend(self._research_run_tasks(actor_user_id=actor_user_id, is_admin=is_admin))
        return rows

    def _computation_tasks(self, *, actor_user_id: str | None, is_admin: bool) -> list[GlobalTaskItem]:
        data = self.computation_service.list_runs(
            status=None,
            workflow_type=None,
            engine=None,
            keyword=None,
            page=1,
            page_size=MAX_AGGREGATE_PAGE_SIZE,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        rows: list[GlobalTaskItem] = []
        for run in data.items:
            molecule = run.molecule.model_dump(mode="python") if hasattr(run.molecule, "model_dump") else dict(run.molecule)
            rows.append(GlobalTaskItem(
                task_id=run.run_id,
                task_type="计算智能",
                module_id="computation",
                module_name="计算智能",
                title=str(molecule.get("name") or run.run_id),
                summary=str(molecule.get("smiles") or "-"),
                status=run.status,
                status_text=run.status,
                created_at=run.created_at,
                updated_at=run.updated_at,
                route={"path": "/computations/runs", "query": {"run_id": run.run_id}},
                raw=run.model_dump(mode="python"),
            ))
        return rows

    def _campaign_tasks(self, *, actor_user_id: str | None, is_admin: bool) -> list[GlobalTaskItem]:
        data = self.optimization_service.list_campaigns(
            page=1,
            page_size=MAX_AGGREGATE_PAGE_SIZE,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        rows: list[GlobalTaskItem] = []
        for campaign in data.items:
            raw = campaign.model_dump(mode="python")
            if self._is_research_engine_container_campaign(raw):
                continue
            rows.append(
                GlobalTaskItem(
                    task_id=campaign.campaign_id,
                    task_type="湿实验优化",
                    module_id="wetlab-bayes",
                    module_name="湿实验贝叶斯优化",
                    title=campaign.name or campaign.campaign_id,
                    summary=", ".join(self._objective_name(item) for item in campaign.objectives) or "-",
                    status=campaign.status,
                    status_text=campaign.status,
                    created_at=campaign.created_at,
                    updated_at=campaign.updated_at,
                    route={"path": f"/optimization/campaigns/{campaign.campaign_id}"},
                    raw=raw,
                )
            )
        return rows

    def _algorithm_run_tasks(self, *, actor_user_id: str | None, is_admin: bool) -> list[GlobalTaskItem]:
        data = self.research_service.list_algorithm_runs(
            page=1,
            page_size=MAX_AGGREGATE_PAGE_SIZE,
            created_by=None if is_admin else actor_user_id,
        )
        return [
            GlobalTaskItem(
                task_id=run.run_id,
                task_type="算法运行",
                module_id="research-engine",
                module_name="ResearchEngine",
                title=f"算法运行: {run.algorithm_id}",
                summary=json.dumps(run.input_snapshot, ensure_ascii=False)[:80] if run.input_snapshot else "-",
                status=run.status,
                status_text=run.status,
                created_at=run.created_at,
                updated_at=run.updated_at,
                route={"path": "/research-engine", "query": {"run_id": run.run_id}},
                raw=run.model_dump(mode="python"),
            )
            for run in data.items
        ]

    def _research_run_tasks(self, *, actor_user_id: str | None, is_admin: bool) -> list[GlobalTaskItem]:
        data = self.research_orchestrator.list_research_runs(
            page=1,
            page_size=MAX_AGGREGATE_PAGE_SIZE,
            created_by=None if is_admin else actor_user_id,
        )
        rows: list[GlobalTaskItem] = []
        for run in data.items:
            query = {"research_run_id": run.run_id}
            if run.status == "blocked_approval":
                query["action"] = "approve"
            rows.append(
                GlobalTaskItem(
                    task_id=run.run_id,
                    task_type="自动研发",
                    module_id="research-engine",
                    module_name="ResearchEngine",
                    title=f"AutoResearch: {run.profile_id or '研发任务'}",
                    summary=f"当前阶段: {run.current_stage}" if run.current_stage else "-",
                    status=run.status,
                    status_text=run.status,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                    route={"path": "/research-engine", "query": query},
                    raw=run.model_dump(mode="python"),
                )
            )
        return rows

    @staticmethod
    def _is_research_engine_container_campaign(campaign: dict[str, Any]) -> bool:
        return bool(
            campaign.get("source") == "research_engine"
            or campaign.get("linked_problem_spec_id")
            or str(campaign.get("campaign_id") or "").startswith("ps_")
        )

    @staticmethod
    def _objective_name(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("name", ""))
        return str(getattr(item, "name", ""))

    @staticmethod
    def _matches(
        row: GlobalTaskItem,
        *,
        module_id: str | None,
        status: str | None,
        keyword: str,
    ) -> bool:
        if module_id and row.module_id != module_id:
            return False
        if status and row.status != status:
            return False
        if not keyword:
            return True
        haystack = f"{row.task_id} {row.task_type} {row.module_name} {row.title} {row.summary}".lower()
        return keyword in haystack

    @staticmethod
    def _sort_key(row: GlobalTaskItem) -> datetime:
        return row.updated_at or row.created_at or datetime.min

    @staticmethod
    def _summarize(rows: list[GlobalTaskItem]) -> dict[str, int]:
        counts = {"total": len(rows), "running": 0, "completed": 0, "pending": 0}
        for item in rows:
            if item.status == "running":
                counts["running"] += 1
            if item.status == "completed":
                counts["completed"] += 1
            if item.status in {"queued", "blocked_approval"}:
                counts["pending"] += 1
        return counts
