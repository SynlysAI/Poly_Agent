"""计算智能业务服务。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

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
MOCK_STEP_LABELS = {
    "MOCK_VALIDATE_INPUT": "输入校验",
    "MOCK_GENERATE_STRUCTURE": "生成结构摘要",
    "MOCK_RESULT": "生成模拟结果",
}


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
        self.advance_mock_runs()
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
        self.advance_mock_runs()
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
        if artifact.artifact_type in {"result_json", "structure_json"}:
            with path.open("r", encoding="utf-8") as fp:
                preview = json.load(fp)
        elif artifact.artifact_type == "log_text":
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
        if artifact.artifact_type != "result_json":
            raise HTTPException(status_code=400, detail="该 artifact 不包含光谱数据")
        path = self.resolve_artifact_path(artifact)
        with path.open("r", encoding="utf-8") as fp:
            result = json.load(fp)
        spectrum = result.get("spectrum") or {
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

    def advance_mock_runs(self) -> None:
        """推进 mock 计算任务状态。"""
        candidates, _ = ComputationRunRepository.list_runs(
            status=None,
            workflow_type=None,
            engine="MOCK",
            keyword=None,
            page=1,
            page_size=100,
        )
        now = utc_now()
        for item in candidates:
            run = ComputationRun(**item)
            if run.status in TERMINAL_STATUSES:
                continue
            elapsed = (now - run.created_at).total_seconds()
            if run.status == "queued" and elapsed >= 2:
                started_at = run.created_at + timedelta(seconds=1)
                running_run = run.model_copy(update={"status": "running", "started_at": started_at})
                self._mark_running(run, started_at)
                self._finish_mock_run(running_run, now, worker_id="worker-local-mock")
            elif run.status == "queued" and elapsed >= 1:
                self._mark_running(run, now)
            elif run.status == "running" and run.started_at and (now - run.started_at).total_seconds() >= 1:
                self._finish_mock_run(run, now, worker_id="worker-local-mock")

    def initialize_acquired_run(self, run: ComputationRun, *, worker_id: str, now: datetime) -> ComputationRun:
        """初始化已由 worker 领取的 run timeline。"""
        steps = [
            ComputationStep(step_key=key, label=label, status="queued")
            for key, label in MOCK_STEP_LABELS.items()
        ]
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

    def finish_acquired_run(self, run: ComputationRun, *, worker_id: str, now: datetime) -> ComputationRun:
        """完成或失败一个已领取的 mock run。"""
        self._finish_mock_run(run, now, worker_id=worker_id)
        return self.get_run(run.run_id)

    def _mark_running(self, run: ComputationRun, now: datetime) -> None:
        """标记 mock 任务运行中。"""
        steps = [
            ComputationStep(step_key=key, label=label, status="queued")
            for key, label in MOCK_STEP_LABELS.items()
        ]
        steps[0].status = "running"
        steps[0].started_at = now
        ComputationRunRepository.update_fields(
            run.run_id,
            {
                "status": "running",
                "started_at": now,
                "updated_at": now,
                "external_refs": {**run.external_refs, "worker_id": "worker-local-mock"},
                "steps": [step.model_dump(mode="python") for step in steps],
            },
        )
        self._audit(
            "computation.status_changed",
            actor_user_id="worker-local-mock",
            request_id=None,
            entity_type="computation_run",
            entity_id=run.run_id,
            before={"status": run.status},
            after={"status": "running"},
        )

    def _finish_mock_run(self, run: ComputationRun, now: datetime, *, worker_id: str) -> None:
        """完成或失败 mock run。"""
        if run.mock_should_fail or run.parameters.method.upper() == "MOCK_FAIL":
            self._fail_mock_run(run, now, worker_id=worker_id)
            return
        self._complete_mock_run(run, now, worker_id=worker_id)

    def _complete_mock_run(self, run: ComputationRun, now: datetime, *, worker_id: str) -> None:
        """完成 mock 任务并生成 artifacts。"""
        existing = ComputationArtifactRepository.list_by_run(run.run_id)
        if existing:
            artifact_ids = [item["artifact_id"] for item in existing]
        else:
            artifact_ids = self._write_mock_artifacts(run, now, worker_id=worker_id)
        steps = []
        step_started = run.started_at or now
        for key, label in MOCK_STEP_LABELS.items():
            steps.append(
                ComputationStep(
                    step_key=key,
                    label=label,
                    status="completed",
                    started_at=step_started,
                    finished_at=now,
                ).model_dump(mode="python")
            )
        ComputationRunRepository.update_fields(
            run.run_id,
            {
                "status": "completed",
                "steps": steps,
                "artifact_ids": artifact_ids,
                "result_summary": self._build_mock_result_summary(run),
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
            after={"status": "completed"},
        )

    def _fail_mock_run(self, run: ComputationRun, now: datetime, *, worker_id: str) -> None:
        """失败 mock 任务并生成错误 artifact。"""
        artifact_ids = self._write_mock_error_artifact(run, now, "MOCK_FAILURE_TRIGGERED", worker_id=worker_id)
        steps = []
        step_started = run.started_at or now
        for index, (key, label) in enumerate(MOCK_STEP_LABELS.items()):
            status = "completed" if index == 0 else "failed"
            steps.append(
                ComputationStep(
                    step_key=key,
                    label=label,
                    status=status,
                    started_at=step_started,
                    finished_at=now,
                    error="Mock failure trigger requested" if status == "failed" else None,
                ).model_dump(mode="python")
            )
            if status == "failed":
                break
        ComputationRunRepository.update_fields(
            run.run_id,
            {
                "status": "failed",
                "steps": steps,
                "artifact_ids": artifact_ids,
                "result_summary": {},
                "error": {
                    "error_code": "MOCK_FAILURE_TRIGGERED",
                    "message": "Mock failure trigger requested",
                    "retryable": True,
                },
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
            after={"status": "failed"},
        )

    def _write_mock_artifacts(self, run: ComputationRun, now: datetime, *, worker_id: str) -> list[str]:
        """写入 mock artifacts。"""
        workdir = settings.outputs_root / "computations" / run.run_id
        workdir.mkdir(parents=True, exist_ok=True)
        artifacts: list[ComputationArtifact] = []
        files = [
            ("MOCK_GENERATE_STRUCTURE", "structure_json", "structure.json", self._build_mock_structure(run), "application/json"),
            ("MOCK_RESULT", "result_json", "result.json", self._build_mock_result_summary(run), "application/json"),
            ("MOCK_RESULT", "log_text", "worker.log", self._build_mock_log(run), "text/plain"),
        ]
        for step_key, artifact_type, filename, content, mime_type in files:
            path = workdir / filename
            if isinstance(content, str):
                path.write_text(content, encoding="utf-8")
            else:
                path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            artifact = ComputationArtifact(
                artifact_id=self._new_id("art"),
                run_id=run.run_id,
                step_key=step_key,
                artifact_type=artifact_type,
                name=filename,
                storage_uri=str(path),
                mime_type=mime_type,
                size_bytes=path.stat().st_size,
                checksum_sha256=self._sha256(path),
                parser_name="mock_parser",
                parser_version="0.1.0",
                metadata={"source": "mock", "source_step": step_key},
                created_at=now,
            )
            ComputationArtifactRepository.save("artifact_id", artifact.model_dump(mode="python"))
            artifacts.append(artifact)
            self._audit(
                "artifact.registered",
                actor_user_id=worker_id,
                request_id=None,
                entity_type="computation_artifact",
                entity_id=artifact.artifact_id,
                related_ids={"run_id": run.run_id},
            )
        return [artifact.artifact_id for artifact in artifacts]

    def _write_mock_error_artifact(
        self,
        run: ComputationRun,
        now: datetime,
        error_code: str,
        *,
        worker_id: str,
    ) -> list[str]:
        """写入 mock 错误 artifact。"""
        existing = ComputationArtifactRepository.list_by_run(run.run_id)
        if existing:
            return [item["artifact_id"] for item in existing]
        workdir = settings.outputs_root / "computations" / run.run_id
        workdir.mkdir(parents=True, exist_ok=True)
        path = workdir / "worker-error.log"
        path.write_text(
            "\n".join(
                [
                    f"run_id={run.run_id}",
                    f"workflow_type={run.workflow_type}",
                    f"error_code={error_code}",
                    "message=Mock failure trigger requested",
                ]
            ),
            encoding="utf-8",
        )
        artifact = ComputationArtifact(
            artifact_id=self._new_id("art"),
            run_id=run.run_id,
            step_key="MOCK_RESULT",
            artifact_type="log_text",
            name="worker-error.log",
            storage_uri=str(path),
            mime_type="text/plain",
            size_bytes=path.stat().st_size,
            checksum_sha256=self._sha256(path),
            parser_name="mock_error_parser",
            parser_version="0.1.0",
            metadata={"source": "mock", "source_step": "MOCK_RESULT", "error_code": error_code},
            created_at=now,
        )
        ComputationArtifactRepository.save("artifact_id", artifact.model_dump(mode="python"))
        self._audit(
            "artifact.registered",
            actor_user_id=worker_id,
            request_id=None,
            entity_type="computation_artifact",
            entity_id=artifact.artifact_id,
            related_ids={"run_id": run.run_id},
        )
        return [artifact.artifact_id]

    def _build_mock_result_summary(self, run: ComputationRun) -> dict:
        """构造确定性的 mock 结果摘要。"""
        digest = int(hashlib.sha256(run.molecule.smiles.encode("utf-8")).hexdigest()[:10], 16)
        energy = -float(20 + digest % 9000) / 100
        homo = -float(300 + digest % 420) / 100
        lumo = homo + float(150 + digest % 220) / 100
        summary = {
            "engine": run.engine,
            "workflow_type": run.workflow_type,
            "total_energy_ev": round(energy, 4),
            "homo_ev": round(homo, 4),
            "lumo_ev": round(lumo, 4),
            "gap_ev": round(lumo - homo, 4),
            "dipole_debye": round(float(10 + digest % 250) / 10, 3),
        }
        if run.workflow_type == "MOCK_LASER":
            summary["laser_metrics"] = {
                "gain_factor": float((digest % 900) + 100) * 1e-18,
                "s1_energy_ev": round(1.5 + (digest % 180) / 100, 3),
            }
        return summary

    def _build_mock_structure(self, run: ComputationRun) -> dict:
        """构造结构预览 JSON。"""
        atoms = [
            {"element": "C", "x": 0.0, "y": 0.0, "z": 0.0},
            {"element": "C", "x": 1.42, "y": 0.0, "z": 0.0},
            {"element": "H", "x": -0.52, "y": 0.93, "z": 0.0},
            {"element": "H", "x": 1.94, "y": 0.93, "z": 0.0},
        ]
        return {"name": run.molecule.name or run.run_id, "smiles": run.molecule.smiles, "atoms": atoms}

    def _build_mock_log(self, run: ComputationRun) -> str:
        """构造 worker 日志。"""
        return "\n".join(
            [
                f"run_id={run.run_id}",
                f"workflow_type={run.workflow_type}",
                "adapter=mock",
                "validated input",
                "generated structure preview",
                "generated deterministic result summary",
            ]
        )

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
