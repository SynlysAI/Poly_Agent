"""计算智能业务服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.computation_adapters.base import AdapterRunResult
from app.computation_adapters.base import ArtifactSpec
from app.computation_adapters.registry import supported_workflow_engine_pairs
from app.core.config import settings
from app.infra.computation_repositories import (
    AuditEventRepository,
    ComputationArtifactRepository,
    ComputationRunRepository,
    utc_now,
)
from app.schemas.computation import (
    ArtifactStructureData,
    ArtifactSpectrumData,
    ArtifactPreviewData,
    AuditEvent,
    AuditEventListData,
    ComputationArtifact,
    ComputationCreateData,
    ComputationCreateRequest,
    ComputationListData,
    ComputationRun,
    ComputationStep,
)


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class ComputationService:
    """计算任务服务。"""

    def create_run(
        self,
        payload: ComputationCreateRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
        retry_of_run_id: str | None = None,
    ) -> ComputationCreateData:
        """创建计算任务。"""
        if (payload.workflow_type, payload.engine) not in supported_workflow_engine_pairs():
            raise HTTPException(
                status_code=400,
                detail=f"不支持的计算 workflow/engine 组合：{payload.workflow_type}/{payload.engine}",
            )
        now = utc_now()
        run_id = self._new_id("comp")
        run = ComputationRun(
            run_id=run_id,
            retry_of_run_id=retry_of_run_id,
            workflow_type=payload.workflow_type,
            engine=payload.engine,
            status="queued",
            molecule=payload.molecule,
            parameters=payload.parameters,
            resources=payload.resources,
            external_refs={"worker_id": None, "aiida_process_uuid": None, "speclabos_run_id": None},
            steps=[],
            artifact_ids=[],
            result_summary={},
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
            source=payload.source,
            campaign_id=payload.campaign_id,
            suggestion_id=payload.suggestion_id,
            mock_should_fail=payload.mock_should_fail,
        )
        ComputationRunRepository.save("run_id", run.model_dump(mode="python"))
        self._audit(
            "computation.created",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="computation_run",
            entity_id=run_id,
            after={"status": "queued"},
            related_ids={"campaign_id": payload.campaign_id, "suggestion_id": payload.suggestion_id},
        )
        return ComputationCreateData(run_id=run_id, status="queued")

    def list_runs(
        self,
        *,
        status: str | None,
        workflow_type: str | None,
        engine: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> ComputationListData:
        """分页查询计算任务。"""
        items, total = ComputationRunRepository.list_runs(
            status=status,
            workflow_type=workflow_type,
            engine=engine,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        return ComputationListData(
            items=[ComputationRun(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_run(self, run_id: str) -> ComputationRun:
        """查询计算任务详情。"""
        run = ComputationRunRepository.find_one({"run_id": run_id})
        if not run:
            raise HTTPException(status_code=404, detail="计算任务不存在")
        return ComputationRun(**run)

    def cancel_run(self, run_id: str, *, actor_user_id: str, request_id: str | None) -> ComputationRun:
        """取消计算任务。"""
        run = self.get_run(run_id)
        if run.status in TERMINAL_STATUSES:
            raise HTTPException(status_code=400, detail="终态计算任务不能取消")
        now = utc_now()
        ComputationRunRepository.update_fields(
            run_id,
            {
                "status": "cancelled",
                "updated_at": now,
                "finished_at": now,
                "error": {
                    "error_code": "USER_CANCELLED",
                    "message": "任务已由用户取消",
                    "retryable": True,
                },
            },
        )
        self._audit(
            "computation.cancelled",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="computation_run",
            entity_id=run_id,
            before={"status": run.status},
            after={"status": "cancelled"},
        )
        return self.get_run(run_id)

    def retry_run(self, run_id: str, *, actor_user_id: str, request_id: str | None) -> ComputationCreateData:
        """重试 failed/cancelled 计算任务。"""
        run = self.get_run(run_id)
        if run.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=400, detail="仅 failed/cancelled 任务允许重试")
        payload = ComputationCreateRequest(
            workflow_type=run.workflow_type,
            engine=run.engine,
            molecule=run.molecule,
            parameters=run.parameters,
            resources=run.resources,
            source="retry",
            campaign_id=run.campaign_id,
            suggestion_id=run.suggestion_id,
        )
        created = self.create_run(payload, actor_user_id=actor_user_id, request_id=request_id, retry_of_run_id=run_id)
        self._audit(
            "computation.retried",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="computation_run",
            entity_id=created.run_id,
            related_ids={"retry_of_run_id": run_id},
        )
        return created

    def list_artifacts(self, run_id: str) -> list[ComputationArtifact]:
        """查询任务 artifacts。"""
        self.get_run(run_id)
        return [ComputationArtifact(**item) for item in ComputationArtifactRepository.list_by_run(run_id)]

    def get_artifact(self, artifact_id: str) -> ComputationArtifact:
        """查询 artifact 元数据。"""
        artifact = ComputationArtifactRepository.find_one({"artifact_id": artifact_id})
        if not artifact:
            raise HTTPException(status_code=404, detail="artifact 不存在")
        return ComputationArtifact(**artifact)

    def list_audit_events(
        self,
        *,
        entity_type: str | None,
        entity_id: str | None,
        event_type: str | None,
        page: int,
        page_size: int,
    ) -> AuditEventListData:
        """查询审计事件。"""
        items, total = AuditEventRepository.list_events(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            page=page,
            page_size=page_size,
        )
        return AuditEventListData(
            items=[AuditEvent(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def preview_artifact(self, artifact_id: str) -> ArtifactPreviewData:
        """预览白名单 artifact。"""
        artifact = self.get_artifact(artifact_id)
        path = self.resolve_artifact_path(artifact)
        if artifact.artifact_type in {"result_json", "structure_json", "input_json", "error_json", "spectrum_json", "metrics_json"}:
            with path.open("r", encoding="utf-8") as fp:
                preview = json.load(fp)
        elif artifact.artifact_type in {"log_text", "xyz", "sdf"}:
            preview = path.read_text(encoding="utf-8")[:8000]
        else:
            raise HTTPException(status_code=400, detail="该 artifact 类型不支持预览")
        return ArtifactPreviewData(artifact=artifact, preview=preview)

    def get_artifact_structure(self, artifact_id: str) -> ArtifactStructureData:
        """读取结构 artifact。"""
        artifact = self.get_artifact(artifact_id)
        if artifact.artifact_type != "structure_json":
            raise HTTPException(status_code=400, detail="该 artifact 不是结构文件")
        path = self.resolve_artifact_path(artifact)
        with path.open("r", encoding="utf-8") as fp:
            structure = json.load(fp)
        return ArtifactStructureData(artifact=artifact, structure=structure)

    def get_artifact_spectrum(self, artifact_id: str) -> ArtifactSpectrumData:
        """读取 result artifact 的光谱/指标数据。"""
        artifact = self.get_artifact(artifact_id)
        if artifact.artifact_type not in {"result_json", "spectrum_json"}:
            raise HTTPException(status_code=400, detail="该 artifact 不包含光谱数据")
        path = self.resolve_artifact_path(artifact)
        with path.open("r", encoding="utf-8") as fp:
            result = json.load(fp)
        if artifact.artifact_type == "spectrum_json":
            spectrum = result
        else:
            spectrum = result.get("spectrum") or result.get("spectra", {}).get("spectrum") or {
                "kind": "mock_metric_sticks",
                "x_label": "metric",
                "y_label": "value",
                "points": [
                    {"x": key, "y": value}
                    for key, value in result.items()
                    if isinstance(value, (int, float))
                ],
            }
        return ArtifactSpectrumData(artifact=artifact, spectrum=spectrum)

    def audit_artifact_download(
        self,
        artifact: ComputationArtifact,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> None:
        """记录 artifact 下载审计。"""
        self._audit(
            "artifact.downloaded",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_type="computation_artifact",
            entity_id=artifact.artifact_id,
            related_ids={"run_id": artifact.run_id},
        )

    def resolve_artifact_path(self, artifact: ComputationArtifact) -> Path:
        """解析 artifact 文件路径并限制在 outputs_root 内。"""
        path = Path(artifact.storage_uri)
        if not path.is_absolute():
            path = (settings.project_root / path).resolve()
        else:
            path = path.resolve()
        output_root = settings.outputs_root.resolve()
        if output_root not in path.parents and path != output_root:
            raise HTTPException(status_code=400, detail="artifact 路径越界")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="artifact 文件不存在")
        return path

    def initialize_acquired_run(
        self,
        run: ComputationRun,
        *,
        worker_id: str,
        now: datetime,
        step_labels: dict[str, str],
    ) -> ComputationRun:
        """初始化已由 worker 领取的 run timeline。"""
        steps = [
            ComputationStep(step_key=key, label=label, status="queued")
            for key, label in step_labels.items()
        ]
        if steps:
            steps[0].status = "running"
            steps[0].started_at = now
        ComputationRunRepository.update_fields(
            run.run_id,
            {
                "steps": [step.model_dump(mode="python") for step in steps],
                "updated_at": now,
                "external_refs": {**run.external_refs, "worker_id": worker_id},
            },
        )
        self._audit(
            "computation.status_changed",
            actor_user_id=worker_id,
            request_id=None,
            entity_type="computation_run",
            entity_id=run.run_id,
            before={"status": "queued"},
            after={"status": "running"},
        )
        return self.get_run(run.run_id)

    def finish_acquired_run(
        self,
        run: ComputationRun,
        *,
        worker_id: str,
        now: datetime,
        adapter_result: AdapterRunResult,
    ) -> ComputationRun:
        """完成或失败一个已领取的 run。"""
        artifact_ids = self.register_artifacts(
            run,
            artifact_specs=adapter_result.artifact_specs,
            actor_worker_id=worker_id,
            created_at=now,
        )
        ComputationRunRepository.update_fields(
            run.run_id,
            {
                "status": adapter_result.status,
                "steps": [step.model_dump(mode="python") for step in adapter_result.steps],
                "artifact_ids": artifact_ids,
                "result_summary": adapter_result.result_summary,
                "error": adapter_result.error,
                "updated_at": now,
                "finished_at": now,
            },
        )
        self._audit(
            "computation.status_changed",
            actor_user_id=worker_id,
            request_id=None,
            entity_type="computation_run",
            entity_id=run.run_id,
            before={"status": run.status},
            after={"status": adapter_result.status},
        )
        return self.get_run(run.run_id)

    def register_artifacts(
        self,
        run: ComputationRun,
        *,
        artifact_specs: list[ArtifactSpec],
        actor_worker_id: str,
        created_at: datetime,
    ) -> list[str]:
        """登记 adapter 产物文件。"""
        existing = ComputationArtifactRepository.list_by_run(run.run_id)
        if existing:
            return [item["artifact_id"] for item in existing]
        artifacts: list[ComputationArtifact] = []
        for spec in artifact_specs:
            path = self._resolve_output_file_for_registration(spec.path)
            artifact = ComputationArtifact(
                artifact_id=self._new_id("art"),
                run_id=run.run_id,
                step_key=spec.step_key,
                artifact_type=spec.artifact_type,
                name=spec.name,
                storage_uri=str(path),
                mime_type=spec.mime_type,
                size_bytes=path.stat().st_size,
                checksum_sha256=self._sha256(path),
                parser_name=spec.parser_name,
                parser_version=spec.parser_version,
                metadata=spec.metadata,
                created_at=created_at,
            )
            ComputationArtifactRepository.save("artifact_id", artifact.model_dump(mode="python"))
            artifacts.append(artifact)
            self._audit(
                "artifact.registered",
                actor_user_id=actor_worker_id,
                request_id=None,
                entity_type="computation_artifact",
                entity_id=artifact.artifact_id,
                related_ids={"run_id": run.run_id},
            )
        return [artifact.artifact_id for artifact in artifacts]

    def _resolve_output_file_for_registration(self, path: Path) -> Path:
        """Resolve a produced artifact path and ensure it is under outputs_root."""
        resolved = path.resolve()
        output_root = settings.outputs_root.resolve()
        if output_root not in resolved.parents and resolved != output_root:
            raise HTTPException(status_code=400, detail="adapter artifact 路径越界")
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="adapter artifact 文件不存在")
        return resolved

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
                "actor_role": "system" if actor_user_id.startswith("worker-") else "user",
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

    def _sha256(self, path: Path) -> str:
        """计算文件 SHA256。"""
        digest = hashlib.sha256()
        with path.open("rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _new_id(self, prefix: str) -> str:
        """生成业务 ID。"""
        return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d')}_{uuid4().hex[:10]}"
