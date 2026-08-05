"""实验下发配置生命周期、候选运行与试运行服务。"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.core.time import utc_now
from app.infra.experiment_dispatch_profile_repositories import (
    ExperimentDispatchProfileRepository,
    ExperimentDispatchTargetRepository,
)
from app.infra.experiment_dispatch_repositories import ExperimentDispatchRepository
from app.infra.research_engine_repositories import AlgorithmRegistryRepository, AlgorithmRunRepository
from app.schemas.experiment_dispatch_profile import (
    DispatchTargetDefinition,
    DispatchTargetListData,
    ExperimentDispatchCandidate,
    ExperimentDispatchCandidateListData,
    ExperimentDispatchProfile,
    ExperimentDispatchProfileCreateRequest,
    ExperimentDispatchProfileEvaluation,
    ExperimentDispatchProfileEvaluationRequest,
    ExperimentDispatchProfileListData,
    ExperimentDispatchProfileSaveRequest,
    ExperimentDispatchProfileUpdateRequest,
)
from app.schemas.experiment_dispatch import (
    ExperimentDispatchManifest,
    ExperimentDispatchProfileRef,
    ExperimentDispatchProvenance,
    ExperimentDispatchSource,
    ExperimentDispatchTargetRef,
)
from app.services.experiment_dispatch_profile_engine import ExperimentDispatchProfileEngine, _MISSING
from app.services.research_engine_access import ensure_research_engine_doc_access


class ExperimentDispatchProfileService:
    """管理声明式下发配置；不包含任何实验领域逻辑。"""

    def __init__(self, *, seed_enabled: bool = True, engine: ExperimentDispatchProfileEngine | None = None) -> None:
        self.seed_enabled = seed_enabled
        self.engine = engine or ExperimentDispatchProfileEngine()

    def list(
        self,
        *,
        actor_user_id: str,
        is_admin: bool,
        page: int,
        page_size: int,
        status: str | None = None,
        target_id: str | None = None,
        keyword: str | None = None,
    ) -> ExperimentDispatchProfileListData:
        self._ensure_seed_data()
        docs, _ = ExperimentDispatchProfileRepository.list_all(page=1, page_size=10000)
        visible = [doc for doc in docs if self._can_view(doc, actor_user_id, is_admin)]
        if status:
            visible = [doc for doc in visible if doc.get("status") == status]
        if target_id:
            visible = [doc for doc in visible if doc.get("target_id") == target_id]
        if keyword:
            needle = keyword.strip().lower()
            visible = [doc for doc in visible if needle in " ".join(str(doc.get(key, "")) for key in ("name", "profile_id", "description")).lower()]
        visible.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        start = (page - 1) * page_size
        return ExperimentDispatchProfileListData(
            items=[self._profile_from_doc(item) for item in visible[start:start + page_size]],
            page=page,
            page_size=page_size,
            total=len(visible),
        )

    def get(
        self,
        profile_id: str,
        version: str | None,
        *,
        actor_user_id: str,
        is_admin: bool,
    ) -> ExperimentDispatchProfile:
        self._ensure_seed_data()
        doc = self._find_profile(profile_id, version)
        if not self._can_view(doc, actor_user_id, is_admin):
            raise HTTPException(status_code=403, detail="无权限访问该实验下发配置")
        return self._profile_from_doc(doc)

    def create(self, payload: ExperimentDispatchProfileCreateRequest, *, actor_user_id: str) -> ExperimentDispatchProfile:
        self._ensure_seed_data()
        profile_id = self._normalize_profile_id(payload.profile_id) if payload.profile_id else f"edp_{uuid4().hex[:12]}"
        if ExperimentDispatchProfileRepository.find_one({"profile_key": self._profile_key(profile_id, payload.version)}):
            raise HTTPException(status_code=409, detail="该下发配置版本已存在")
        now = utc_now()
        profile = ExperimentDispatchProfile(
            **payload.model_dump(exclude={"profile_id"}),
            profile_id=profile_id,
            status="draft",
            owner_id=actor_user_id,
            created_by=actor_user_id,
            created_at=now,
            updated_at=now,
        )
        self._save_profile(profile)
        return profile

    def update(
        self,
        profile_id: str,
        version: str,
        payload: ExperimentDispatchProfileUpdateRequest,
        *,
        actor_user_id: str,
    ) -> ExperimentDispatchProfile:
        current = self._owned_profile(profile_id, version, actor_user_id)
        if current.status != "draft":
            raise HTTPException(status_code=409, detail="已发布或归档的配置不可修改，请创建新版本")
        updated = current.model_copy(update={**payload.model_dump(), "updated_at": utc_now()})
        self._save_profile(updated)
        return updated

    def publish(self, profile_id: str, version: str, *, actor_user_id: str) -> ExperimentDispatchProfile:
        profile = self._owned_profile(profile_id, version, actor_user_id)
        if profile.status != "draft":
            raise HTTPException(status_code=409, detail="只有草稿配置可以发布")
        target = self._effective_target(profile)
        errors = self.validate_profile(profile, target)
        if errors:
            raise HTTPException(status_code=422, detail={"code": "PROFILE_INVALID", "message": "下发配置未通过校验", "errors": errors})
        now = utc_now()
        published = profile.model_copy(update={"status": "published", "published_at": now, "updated_at": now})
        self._save_profile(published)
        return published

    def clone_version(
        self,
        profile_id: str,
        source_version: str,
        new_version: str,
        *,
        actor_user_id: str,
    ) -> ExperimentDispatchProfile:
        source = self._owned_profile(profile_id, source_version, actor_user_id)
        if ExperimentDispatchProfileRepository.find_one({"profile_key": self._profile_key(profile_id, new_version)}):
            raise HTTPException(status_code=409, detail="目标版本已存在")
        now = utc_now()
        cloned = source.model_copy(update={
            "version": new_version,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "published_at": None,
        })
        self._save_profile(cloned)
        return cloned

    def set_visibility(self, profile_id: str, version: str, visibility: str, *, actor_user_id: str) -> ExperimentDispatchProfile:
        profile = self._owned_profile(profile_id, version, actor_user_id)
        updated = profile.model_copy(update={"visibility": visibility, "updated_at": utc_now()})
        self._save_profile(updated)
        return updated

    def list_targets(self) -> DispatchTargetListData:
        self._ensure_seed_data()
        docs, _ = ExperimentDispatchTargetRepository.list_all(page=1, page_size=1000)
        items = [self._target_from_doc(item) for item in docs]
        items.sort(key=lambda item: (item.name, self._version_key(item.version)))
        return DispatchTargetListData(items=items, total=len(items))

    def get_target(self, target_id: str, version: str | None = None) -> DispatchTargetDefinition:
        self._ensure_seed_data()
        docs, _ = ExperimentDispatchTargetRepository.list_all({"target_id": target_id}, page=1, page_size=1000)
        if version:
            docs = [item for item in docs if item.get("version") == version]
        if not docs:
            raise HTTPException(status_code=404, detail=f"目标接口契约 '{target_id}' 不存在")
        doc = max(docs, key=lambda item: self._version_key(str(item.get("version", ""))))
        return self._target_from_doc(doc)

    def evaluate(
        self,
        request: ExperimentDispatchProfileEvaluationRequest,
        *,
        actor_user_id: str,
        is_admin: bool,
    ) -> ExperimentDispatchProfileEvaluation:
        run = self._accessible_run(request.run_id, actor_user_id, is_admin)
        profile = self.get(request.profile_id, request.profile_version, actor_user_id=actor_user_id, is_admin=is_admin)
        if profile.status != "published" and profile.owner_id != actor_user_id:
            raise HTTPException(status_code=409, detail="只能试运行已发布配置或自己的草稿")
        if profile.source_contract.allowed_trigger_sources and run.get("trigger_source") not in profile.source_contract.allowed_trigger_sources:
            raise HTTPException(status_code=422, detail="运行来源不符合下发配置要求")
        target = self._effective_target(profile)
        result = self.engine.evaluate(
            profile,
            target,
            input_snapshot=run.get("input_snapshot") or {},
            output_summary=run.get("output_summary") or {},
            run_metadata=self._run_metadata(run),
            manual_values=request.manual_values,
        )
        profile_errors = self.validate_profile(profile, target)
        if profile_errors:
            result.errors.extend(profile_errors)
            result.is_valid = False
        digest_payload = {
            "run": {"run_id": run.get("run_id"), "input": run.get("input_snapshot"), "output": run.get("output_summary")},
            "profile": profile.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
            "manual_values": request.manual_values,
            "payload": result.payload,
        }
        digest = hashlib.sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return ExperimentDispatchProfileEvaluation(
            run_id=request.run_id,
            algorithm_id=str(run.get("algorithm_id") or ""),
            profile_id=profile.profile_id,
            profile_version=profile.version,
            target_id=target.target_id,
            target_version=target.version,
            result=result,
            preview_digest=digest,
        )

    def list_candidates(
        self,
        *,
        actor_user_id: str,
        is_admin: bool,
        trigger_source: str | None,
        algorithm_type: str | None,
        algorithm_family: str | None,
        algorithm_id: str | None,
        profile_id: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> ExperimentDispatchCandidateListData:
        runs, _ = AlgorithmRunRepository.list_runs(
            status="completed",
            trigger_source=trigger_source,
            algorithm_id=algorithm_id,
            created_by=None if is_admin else actor_user_id,
            page=1,
            page_size=10000,
        )
        profile = self.get(profile_id, None, actor_user_id=actor_user_id, is_admin=is_admin) if profile_id else None
        items: list[ExperimentDispatchCandidate] = []
        needle = str(keyword or "").strip().lower()
        for run in runs:
            algorithm = AlgorithmRegistryRepository.find_one({"algorithm_id": run.get("algorithm_id")}) or {}
            if algorithm_type and algorithm.get("type") != algorithm_type:
                continue
            if algorithm_family and algorithm.get("algorithm_family") != algorithm_family:
                continue
            if profile and not self._run_matches_profile(run, profile):
                continue
            haystack = " ".join(str(value or "") for value in (run.get("run_id"), run.get("algorithm_id"), algorithm.get("name"))).lower()
            if needle and needle not in haystack:
                continue
            items.append(ExperimentDispatchCandidate(
                run_id=str(run.get("run_id") or ""),
                algorithm_id=str(run.get("algorithm_id") or ""),
                algorithm_name=str(algorithm.get("name") or run.get("algorithm_id") or ""),
                algorithm_type=algorithm.get("type"),
                algorithm_family=algorithm.get("algorithm_family"),
                trigger_source=run.get("trigger_source"),
                source_kind=run.get("source_kind"),
                algorithm_version_id=run.get("algorithm_version_id"),
                created_at=run.get("created_at"),
                finished_at=run.get("finished_at"),
            ))
        start = (page - 1) * page_size
        return ExperimentDispatchCandidateListData(items=items[start:start + page_size], page=page, page_size=page_size, total=len(items))

    def save_dispatch(
        self,
        request: ExperimentDispatchProfileSaveRequest,
        *,
        actor_user_id: str,
        is_admin: bool,
    ) -> ExperimentDispatchManifest:
        evaluation_request = ExperimentDispatchProfileEvaluationRequest(**request.model_dump(exclude={"preview_digest", "experiment_name", "experiment_notes"}))
        evaluation = self.evaluate(evaluation_request, actor_user_id=actor_user_id, is_admin=is_admin)
        if evaluation.preview_digest != request.preview_digest:
            raise HTTPException(status_code=409, detail="预览已过期，请重新生成后再保存")
        if not evaluation.result.is_valid:
            raise HTTPException(status_code=422, detail={"code": "DISPATCH_INVALID", "message": "下发参数未通过校验", "errors": evaluation.result.errors})
        run = self._accessible_run(request.run_id, actor_user_id, is_admin)
        profile = self.get(request.profile_id, request.profile_version, actor_user_id=actor_user_id, is_admin=is_admin)
        target = self._effective_target(profile)
        created_at = utc_now()
        manifest = ExperimentDispatchManifest(
            dispatch_id=f"edsp_{uuid4().hex[:14]}",
            status="prepared",
            source=ExperimentDispatchSource(
                run_id=request.run_id,
                algorithm_id=str(run.get("algorithm_id") or ""),
                algorithm_version_id=run.get("algorithm_version_id"),
            ),
            profile=ExperimentDispatchProfileRef(profile_id=profile.profile_id, profile_version=profile.version),
            target=ExperimentDispatchTargetRef(target_id=target.target_id, target_version=target.version),
            experiment_name=request.experiment_name or str(evaluation.result.payload.get("experiment_name") or profile.name),
            experiment_notes=request.experiment_notes,
            parameters=evaluation.result.payload,
            execution_inputs=evaluation.result.payload,
            payload=evaluation.result.payload,
            mapping_trace=[item.model_dump(mode="python") for item in evaluation.result.trace],
            matched_rules=evaluation.result.matched_rules,
            warnings=evaluation.result.warnings,
            preview_digest=evaluation.preview_digest,
            provenance=ExperimentDispatchProvenance(
                parameter_bindings=[item.model_dump(mode="python") for item in evaluation.result.trace],
                source_run_snapshot={
                    "run_id": request.run_id,
                    "algorithm_id": run.get("algorithm_id"),
                    "algorithm_version_id": run.get("algorithm_version_id"),
                    "input_snapshot": run.get("input_snapshot") or {},
                    "output_summary": run.get("output_summary") or {},
                    "finished_at": run.get("finished_at"),
                },
                profile_snapshot=profile.model_dump(mode="json"),
                target_snapshot=target.model_dump(mode="json"),
            ),
            created_by=actor_user_id,
            created_at=created_at,
        )
        ExperimentDispatchRepository.save("dispatch_id", manifest.model_dump(mode="python"))
        return manifest

    def validate_profile(self, profile: ExperimentDispatchProfile, target: DispatchTargetDefinition) -> list[str]:
        errors: list[str] = []
        target_fields = {item.path: item for item in target.fields}
        assigned_paths = {item.target_path for item in profile.mappings}
        for mapping in profile.mappings:
            if not self._target_path_allowed(mapping.target_path, target_fields):
                errors.append(f"目标接口不存在字段 {mapping.target_path}")
        for branch in profile.branches:
            for action in branch.actions:
                if action.kind == "set" and action.target_path and not self._target_path_allowed(action.target_path, target_fields):
                    errors.append(f"规则 {branch.name} 设置了不存在的字段 {action.target_path}")
                if action.kind == "set" and action.target_path:
                    assigned_paths.add(action.target_path)
        for field in target.fields:
            if field.required and field.default_value is None and field.path not in assigned_paths:
                errors.append(f"必填目标字段 {field.path} 没有映射、规则赋值或默认值")
        return errors

    @staticmethod
    def _target_path_allowed(path: str, fields: dict[str, Any]) -> bool:
        if path in fields:
            return True
        return any(field.value_type == "object" and path.startswith(f"{parent}/") for parent, field in fields.items())

    def _effective_target(self, profile: ExperimentDispatchProfile) -> DispatchTargetDefinition:
        target = self.get_target(profile.target_id, profile.target_version)
        if profile.target_id == "generic_json" and profile.target_fields:
            return target.model_copy(update={"fields": profile.target_fields})
        return target

    def _run_matches_profile(self, run: dict[str, Any], profile: ExperimentDispatchProfile) -> bool:
        if profile.source_contract.allowed_trigger_sources and run.get("trigger_source") not in profile.source_contract.allowed_trigger_sources:
            return False
        context = {"input": run.get("input_snapshot") or {}, "output": run.get("output_summary") or {}, "run": self._run_metadata(run)}
        for field in profile.source_contract.required_fields:
            value = self.engine.resolve_pointer(context, field.path)
            if field.required and value is _MISSING:
                return False
            if value is not _MISSING and not self.engine._matches_type(value, field.value_type):
                return False
        return True

    def _accessible_run(self, run_id: str, actor_user_id: str, is_admin: bool) -> dict[str, Any]:
        run = AlgorithmRunRepository.find_one({"run_id": run_id})
        if not run:
            raise HTTPException(status_code=404, detail=f"AlgorithmRun '{run_id}' 不存在")
        ensure_research_engine_doc_access(run, actor_user_id=actor_user_id, is_admin=is_admin, resource_label="AlgorithmRun")
        if run.get("status") != "completed":
            raise HTTPException(status_code=422, detail="只有已完成的算法运行可以生成实验清单")
        return run

    @staticmethod
    def _run_metadata(run: dict[str, Any]) -> dict[str, Any]:
        return {key: run.get(key) for key in (
            "run_id", "algorithm_id", "algorithm_version_id", "trigger_source", "source_kind",
            "created_at", "finished_at",
        )}

    def _owned_profile(self, profile_id: str, version: str, actor_user_id: str) -> ExperimentDispatchProfile:
        profile = self.get(profile_id, version, actor_user_id=actor_user_id, is_admin=False)
        if profile.owner_id != actor_user_id:
            raise HTTPException(status_code=403, detail="只有配置所有者可以修改")
        return profile

    def _find_profile(self, profile_id: str, version: str | None) -> dict[str, Any]:
        docs, _ = ExperimentDispatchProfileRepository.list_all({"profile_id": profile_id}, page=1, page_size=1000)
        if version:
            docs = [item for item in docs if item.get("version") == version]
        if not docs:
            raise HTTPException(status_code=404, detail=f"实验下发配置 '{profile_id}' 不存在")
        if version:
            return docs[0]
        published = [item for item in docs if item.get("status") == "published"]
        return max(published or docs, key=lambda item: self._version_key(str(item.get("version", ""))))

    @staticmethod
    def _can_view(doc: dict[str, Any], actor_user_id: str, is_admin: bool) -> bool:
        return is_admin or doc.get("owner_id") == actor_user_id or (doc.get("visibility") == "public" and doc.get("status") == "published")

    @staticmethod
    def _normalize_profile_id(value: str | None) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,99}", normalized):
            raise HTTPException(status_code=422, detail="profile_id 只能包含小写字母、数字、点、下划线和连字符")
        return normalized

    @staticmethod
    def _profile_key(profile_id: str, version: str) -> str:
        return f"{profile_id}@{version}"

    def _save_profile(self, profile: ExperimentDispatchProfile) -> None:
        payload = profile.model_dump(mode="python")
        payload["profile_key"] = self._profile_key(profile.profile_id, profile.version)
        ExperimentDispatchProfileRepository.save("profile_key", payload)

    @staticmethod
    def _profile_from_doc(doc: dict[str, Any]) -> ExperimentDispatchProfile:
        return ExperimentDispatchProfile.model_validate({key: value for key, value in doc.items() if key != "profile_key"})

    @staticmethod
    def _target_from_doc(doc: dict[str, Any]) -> DispatchTargetDefinition:
        return DispatchTargetDefinition.model_validate({key: value for key, value in doc.items() if key != "target_key"})

    @staticmethod
    def _version_key(value: str) -> tuple:
        return tuple(int(part) if part.isdigit() else part for part in value.replace("-", ".").split("."))

    def _ensure_seed_data(self) -> None:
        if not self.seed_enabled:
            return
        self._load_seed_directory(
            settings.backend_root / "config" / "experiment_dispatch_targets",
            DispatchTargetDefinition,
            ExperimentDispatchTargetRepository,
            "target_key",
            lambda item: f"{item.target_id}@{item.version}",
        )
        self._load_seed_directory(
            settings.backend_root / "config" / "experiment_dispatch_profiles",
            ExperimentDispatchProfile,
            ExperimentDispatchProfileRepository,
            "profile_key",
            lambda item: self._profile_key(item.profile_id, item.version),
        )

    @staticmethod
    def _load_seed_directory(directory: Path, model_type, repository, key_field: str, key_factory) -> None:
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            try:
                item = model_type.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as exc:
                raise RuntimeError(f"实验下发种子配置 {path.name} 无法加载: {exc}") from exc
            key = key_factory(item)
            if repository.find_one({key_field: key}):
                continue
            payload = item.model_dump(mode="python")
            payload[key_field] = key
            repository.save(key_field, payload)


experiment_dispatch_profile_service = ExperimentDispatchProfileService()
