"""基于 AlgorithmRun 和版本化模板生成实验方案转发清单。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.core.time import utc_now
from app.infra.experiment_dispatch_repositories import ExperimentDispatchRepository
from app.infra.research_engine_repositories import AlgorithmRunRepository
from app.schemas.experiment_dispatch import (
    ExperimentDispatchBuildRequest,
    ExperimentDispatchListData,
    ExperimentDispatchListItem,
    ExperimentDispatchManifest,
    ExperimentDispatchProvenance,
    ExperimentDispatchSelection,
    ExperimentDispatchSource,
    ExperimentDispatchTemplateRef,
    ExperimentTemplateDefinition,
    ExperimentTemplateListData,
)
from app.services.research_engine_access import ensure_research_engine_doc_access


_MISSING = object()


class ExperimentTemplateRegistry:
    """从目录加载并校验版本化实验模板。"""

    def __init__(self, template_dir: Path | None = None) -> None:
        self.template_dir = template_dir or settings.backend_root / "config" / "experiment_templates"

    def list_templates(self) -> list[ExperimentTemplateDefinition]:
        templates = self._load_templates()
        return sorted(templates.values(), key=lambda item: (item.template_id, self._version_key(item.template_version)))

    def get_template(self, template_id: str, version: str | None = None) -> ExperimentTemplateDefinition:
        templates = self._load_templates()
        matches = [
            item for (item_id, item_version), item in templates.items()
            if item_id == template_id and (version is None or item_version == version)
        ]
        if not matches:
            suffix = f"@{version}" if version else ""
            raise HTTPException(status_code=404, detail=f"实验模板 '{template_id}{suffix}' 不存在")
        return max(matches, key=lambda item: self._version_key(item.template_version))

    def _load_templates(self) -> dict[tuple[str, str], ExperimentTemplateDefinition]:
        if not self.template_dir.exists():
            raise RuntimeError(f"实验模板目录不存在: {self.template_dir}")
        templates: dict[tuple[str, str], ExperimentTemplateDefinition] = {}
        for path in sorted(self.template_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                template = ExperimentTemplateDefinition.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                raise RuntimeError(f"实验模板 {path.name} 无法加载: {exc}") from exc
            key = (template.template_id, template.template_version)
            if key in templates:
                raise RuntimeError(f"实验模板重复: {template.template_id}@{template.template_version}")
            self._validate_template(template)
            templates[key] = template
        return templates

    @staticmethod
    def _validate_template(template: ExperimentTemplateDefinition) -> None:
        binding_names = [item.name for item in template.parameter_bindings]
        if len(binding_names) != len(set(binding_names)):
            raise RuntimeError(f"实验模板 {template.template_id} 存在重复参数名")
        variant_ids = [item.variant_id for item in template.selector.variants]
        if len(variant_ids) != len(set(variant_ids)):
            raise RuntimeError(f"实验模板 {template.template_id} 存在重复变体 ID")
        ordered = sorted(template.selector.variants, key=lambda item: item.min_score)
        for previous, current in zip(ordered, ordered[1:]):
            if current.min_score <= previous.max_score:
                raise RuntimeError(f"实验模板 {template.template_id} 的评分区间重叠")

    @staticmethod
    def _version_key(value: str) -> tuple:
        return tuple(int(part) if part.isdigit() else part for part in value.replace("-", ".").split("."))


class ExperimentDispatchService:
    """构建、保存和查询实验方案转发清单。"""

    def __init__(self, registry: ExperimentTemplateRegistry | None = None) -> None:
        self.registry = registry or ExperimentTemplateRegistry()

    def list_templates(self) -> ExperimentTemplateListData:
        items = self.registry.list_templates()
        return ExperimentTemplateListData(items=items, total=len(items))

    def preview(
        self,
        run_id: str,
        request: ExperimentDispatchBuildRequest,
        *,
        actor_user_id: str,
        is_admin: bool = False,
    ) -> ExperimentDispatchManifest:
        return self._build_manifest(
            run_id,
            request,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            persist=False,
        )

    def create(
        self,
        run_id: str,
        request: ExperimentDispatchBuildRequest,
        *,
        actor_user_id: str,
        is_admin: bool = False,
    ) -> ExperimentDispatchManifest:
        manifest = self._build_manifest(
            run_id,
            request,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            persist=True,
        )
        ExperimentDispatchRepository.save("dispatch_id", manifest.model_dump(mode="python"))
        return manifest

    def get(
        self,
        dispatch_id: str,
        *,
        actor_user_id: str | None,
        is_admin: bool = False,
    ) -> ExperimentDispatchManifest:
        doc = ExperimentDispatchRepository.find_one({"dispatch_id": dispatch_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"实验方案 '{dispatch_id}' 不存在")
        if not is_admin and actor_user_id and doc.get("created_by") != actor_user_id:
            raise HTTPException(status_code=403, detail="无权限访问该实验方案")
        return ExperimentDispatchManifest.model_validate(doc)

    def list(
        self,
        *,
        run_id: str | None,
        template_id: str | None,
        actor_user_id: str | None,
        is_admin: bool,
        page: int,
        page_size: int,
        profile_id: str | None = None,
        keyword: str | None = None,
    ) -> ExperimentDispatchListData:
        if keyword:
            all_docs, _ = ExperimentDispatchRepository.list_dispatches(
                run_id=run_id, template_id=template_id, profile_id=profile_id,
                created_by=None if is_admin else actor_user_id, page=1, page_size=10000,
            )
            needle = keyword.strip().lower()
            docs = [doc for doc in all_docs if needle in " ".join(str(value or "") for value in (
                doc.get("dispatch_id"), doc.get("experiment_name"), doc.get("source", {}).get("run_id"),
                (doc.get("profile") or {}).get("profile_id"), (doc.get("template") or {}).get("template_id"),
            )).lower()]
            total = len(docs)
            start = (page - 1) * page_size
            docs = docs[start:start + page_size]
        else:
            docs, total = ExperimentDispatchRepository.list_dispatches(
                run_id=run_id, template_id=template_id, profile_id=profile_id,
                created_by=None if is_admin else actor_user_id, page=page, page_size=page_size,
            )
        items = [
            ExperimentDispatchListItem(
                dispatch_id=doc["dispatch_id"],
                status=doc["status"],
                run_id=doc.get("source", {}).get("run_id", ""),
                algorithm_id=doc.get("source", {}).get("algorithm_id", ""),
                template_id=(doc.get("template") or {}).get("template_id", ""),
                template_version=(doc.get("template") or {}).get("template_version", ""),
                variant_id=(doc.get("template") or {}).get("variant_id", ""),
                profile_id=(doc.get("profile") or {}).get("profile_id"),
                profile_version=(doc.get("profile") or {}).get("profile_version"),
                target_id=(doc.get("target") or {}).get("target_id"),
                experiment_name=doc.get("experiment_name", ""),
                parameter_count=len(doc.get("parameters", {})),
                created_by=doc.get("created_by", ""),
                created_at=doc["created_at"],
            )
            for doc in docs
        ]
        return ExperimentDispatchListData(items=items, page=page, page_size=page_size, total=total)

    def _build_manifest(
        self,
        run_id: str,
        request: ExperimentDispatchBuildRequest,
        *,
        actor_user_id: str,
        is_admin: bool,
        persist: bool,
    ) -> ExperimentDispatchManifest:
        run = AlgorithmRunRepository.find_one({"run_id": run_id})
        if not run:
            raise HTTPException(status_code=404, detail=f"AlgorithmRun '{run_id}' 不存在")
        ensure_research_engine_doc_access(
            run,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
            resource_label="AlgorithmRun",
        )
        if run.get("status") != "completed":
            raise HTTPException(
                status_code=422,
                detail={"code": "RUN_NOT_COMPLETED", "message": "只有已完成的算法运行可以生成实验方案"},
            )

        template = self.registry.get_template(request.template_id, request.template_version)
        context = {
            "input_snapshot": deepcopy(run.get("input_snapshot") or {}),
            "output_summary": deepcopy(run.get("output_summary") or {}),
            "run": {
                "run_id": run.get("run_id"),
                "algorithm_id": run.get("algorithm_id"),
                "algorithm_version_id": run.get("algorithm_version_id"),
            },
        }
        parameters, binding_trace = self._resolve_parameters(template, context, request.parameter_overrides)
        variant, selection = self._select_variant(template, context, request)
        experiment_name = request.experiment_name or template.name
        created_at = utc_now()
        return ExperimentDispatchManifest(
            dispatch_id=f"edsp_{uuid4().hex[:14]}" if persist else f"preview_{uuid4().hex[:12]}",
            status="prepared" if persist else "preview",
            source=ExperimentDispatchSource(
                run_id=run_id,
                algorithm_id=str(run.get("algorithm_id") or ""),
                algorithm_version_id=run.get("algorithm_version_id"),
            ),
            template=ExperimentDispatchTemplateRef(
                template_id=template.template_id,
                template_version=template.template_version,
                variant_id=variant.variant_id,
            ),
            experiment_name=experiment_name,
            experiment_notes=request.experiment_notes,
            parameters=parameters,
            execution_inputs={
                "experiment_name": experiment_name,
                "instruction_set_path": variant.instruction_set_path,
                "hardware_graph_path": variant.hardware_graph_path,
            },
            selection=selection,
            provenance=ExperimentDispatchProvenance(
                parameter_bindings=binding_trace,
                source_run_snapshot={
                    "run_id": run_id,
                    "algorithm_id": run.get("algorithm_id"),
                    "algorithm_version_id": run.get("algorithm_version_id"),
                    "input_snapshot": context["input_snapshot"],
                    "output_summary": context["output_summary"],
                    "finished_at": run.get("finished_at"),
                },
                template_snapshot=template.model_dump(mode="json"),
            ),
            created_by=actor_user_id,
            created_at=created_at,
        )

    def _resolve_parameters(
        self,
        template: ExperimentTemplateDefinition,
        context: dict[str, Any],
        overrides: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        bindings_by_name = {item.name: item for item in template.parameter_bindings}
        unknown = sorted(set(overrides) - set(bindings_by_name))
        if unknown:
            raise HTTPException(
                status_code=422,
                detail={"code": "UNKNOWN_PARAMETER_OVERRIDE", "message": f"模板未定义参数: {unknown}"},
            )
        parameters: dict[str, Any] = {}
        trace: list[dict[str, Any]] = []
        for binding in template.parameter_bindings:
            value = _MISSING
            source_path = None
            for path in binding.source_paths:
                candidate = self.resolve_json_pointer(context, path)
                if candidate is not _MISSING:
                    value = candidate
                    source_path = path
                    break
            if value is _MISSING and binding.default_value is not None:
                value = deepcopy(binding.default_value)
                source_path = "default_value"
            overridden = binding.name in overrides
            if overridden:
                value = overrides[binding.name]
                source_path = f"parameter_overrides.{binding.name}"
            if value is _MISSING:
                if binding.required:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": "REQUIRED_PARAMETER_MISSING",
                            "message": f"模板必填参数 '{binding.name}' 无法从运行结果解析",
                            "source_paths": binding.source_paths,
                        },
                    )
                continue
            self._validate_value_type(binding.name, value, binding.value_type)
            parameters[binding.name] = deepcopy(value)
            trace.append({
                "name": binding.name,
                "source_path": source_path,
                "value_type": binding.value_type,
                "overridden": overridden,
            })
        return parameters, trace

    def _select_variant(
        self,
        template: ExperimentTemplateDefinition,
        context: dict[str, Any],
        request: ExperimentDispatchBuildRequest,
    ):
        selector = template.selector
        if request.variant_id:
            variant = next((item for item in selector.variants if item.variant_id == request.variant_id), None)
            if not variant:
                raise HTTPException(status_code=422, detail={"code": "VARIANT_NOT_FOUND", "message": "指定执行变体不存在"})
            return variant, ExperimentDispatchSelection(
                score=None,
                source_path="variant_id",
                reason=variant.reason or "用户明确选择执行变体",
            )

        score = _MISSING
        source_path = None
        if selector.override_key in request.selection_inputs:
            score = request.selection_inputs[selector.override_key]
            source_path = f"selection_inputs.{selector.override_key}"
        elif selector.override_key in request.parameter_overrides:
            score = request.parameter_overrides[selector.override_key]
            source_path = f"parameter_overrides.{selector.override_key}"
        else:
            for path in selector.value_paths:
                candidate = self.resolve_json_pointer(context, path)
                if candidate is not _MISSING:
                    score = candidate
                    source_path = path
                    break
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise HTTPException(
                status_code=422,
                detail={"code": "SELECTION_SCORE_MISSING", "message": "缺少可用的数值评分，无法选择执行变体"},
            )
        numeric_score = float(score)
        variant = next(
            (item for item in selector.variants if item.min_score <= numeric_score <= item.max_score),
            None,
        )
        if not variant:
            raise HTTPException(
                status_code=422,
                detail={"code": "SELECTION_SCORE_OUT_OF_RANGE", "message": f"评分 {numeric_score:g} 未命中任何执行变体"},
            )
        return variant, ExperimentDispatchSelection(
            score=numeric_score,
            source_path=source_path,
            reason=variant.reason or f"评分命中 {variant.min_score:g}-{variant.max_score:g}",
        )

    @staticmethod
    def resolve_json_pointer(document: Any, pointer: str):
        """按 RFC 6901 的基本规则解析 JSON Pointer。"""
        if pointer == "":
            return document
        if not pointer.startswith("/"):
            return _MISSING
        current = document
        for raw_part in pointer[1:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
                current = current[int(part)]
            else:
                return _MISSING
        return current

    @staticmethod
    def _validate_value_type(name: str, value: Any, value_type: str) -> None:
        valid = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "any": True,
        }[value_type]
        if not valid:
            raise HTTPException(
                status_code=422,
                detail={"code": "PARAMETER_TYPE_MISMATCH", "message": f"参数 '{name}' 类型不符合模板定义"},
            )


experiment_dispatch_service = ExperimentDispatchService()
