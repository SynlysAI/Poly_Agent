"""算法对接任务与模板包服务。"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import AlgorithmHandoffRepository
from app.schemas.research_engine import (
    AlgorithmHandoff,
    AlgorithmHandoffCreate,
    AlgorithmHandoffListData,
    AlgorithmHandoffValidationResult,
    AlgorithmIOSchema,
    AlgorithmPackageCreate,
    AlgorithmPackageExample,
    AlgorithmPackageExampleListData,
    AlgorithmResourceBinding,
)
from app.services.algorithm_runtimes.base import AlgorithmRuntimeError
from app.services.research_engine_algorithm_package_service import AlgorithmPackageService, MAX_PACKAGE_BYTES


EXAMPLE_DEFINITIONS = [
    AlgorithmPackageExample(
        example_id="batch_formulation_predictor",
        name="批量配方预测模型",
        description="适合电解液、聚合物配方、添加剂组合等批量 formulation 输入，输出 results 列表。",
        input_pattern='{"formulations": [...]}',
        output_pattern='{"results": [...]}',
        zip_filename="batch-formulation-predictor-example.zip",
    ),
    AlgorithmPackageExample(
        example_id="smiles_property_predictor",
        name="SMILES 性质预测模型",
        description="适合单分子或批量 SMILES 输入的性质预测模型。",
        input_pattern='{"smiles": "C=C(F)F"}',
        output_pattern='{"prediction": {...}}',
        zip_filename="smiles-property-predictor-example.zip",
    ),
    AlgorithmPackageExample(
        example_id="file_based_predictor",
        name="文件输入预测模型",
        description="适合结构文件、谱图、CSV 等文件引用输入，输出结构化预测结果。",
        input_pattern='{"file_ref": "minio/path/file.csv"}',
        output_pattern='{"prediction": {...}, "artifacts": [...]}',
        zip_filename="file-based-predictor-example.zip",
    ),
    AlgorithmPackageExample(
        example_id="http_service_adapter",
        name="HTTP 服务适配模板",
        description="适合算法团队自建服务，由平台侧适配请求、鉴权和响应结构。",
        input_pattern='{"payload": {...}}',
        output_pattern='{"prediction": {...}}',
        zip_filename="http-service-adapter-example.zip",
    ),
    AlgorithmPackageExample(
        example_id="generic_python_predictor",
        name="通用 Python 预测模型",
        description="适合尚未归类的 Python 推理脚本，保留最小 load/predict 契约。",
        input_pattern='{"smiles": "C=C(F)F"}',
        output_pattern='{"prediction": {...}}',
        zip_filename="generic-python-predictor-example.zip",
    ),
]


class AlgorithmHandoffService:
    """面向算法对接人的模板、预填包和自测服务。"""

    def __init__(self) -> None:
        self.package_service = AlgorithmPackageService()

    def list_examples(self) -> AlgorithmPackageExampleListData:
        return AlgorithmPackageExampleListData(items=EXAMPLE_DEFINITIONS)

    def get_example(self, example_id: str) -> AlgorithmPackageExample:
        for item in EXAMPLE_DEFINITIONS:
            if item.example_id == example_id:
                return item
        raise HTTPException(status_code=404, detail=f"算法接入模板 '{example_id}' 不存在")

    def download_example_package(self, example_id: str) -> tuple[str, bytes]:
        example = self.get_example(example_id)
        payload = self._payload_for_example(example_id)
        return example.zip_filename, self._build_prefilled_zip(payload, example_id=example_id, requirements_hint=[])

    def create_handoff(self, payload: AlgorithmHandoffCreate, *, actor_user_id: str) -> AlgorithmHandoff:
        self.get_example(payload.example_id)
        now = utc_now()
        handoff_id = f"ahf_{uuid4().hex[:12]}"
        doc = {
            "handoff_id": handoff_id,
            "algorithm_id": payload.algorithm_id,
            "name": payload.name,
            "version": payload.version,
            "example_id": payload.example_id,
            "owner_name": payload.owner_name,
            "owner_contact": payload.owner_contact,
            "description": payload.description,
            "material_scope": payload.material_scope,
            "input_schema": payload.input_schema.model_dump(),
            "output_schema": payload.output_schema.model_dump(),
            "sample_input": payload.sample_input or self._default_sample_input(payload.example_id),
            "requirements_hint": payload.requirements_hint,
            "status": "draft",
            "handoff_url": f"/vertical-prediction?tab=handoff&handoff_id={handoff_id}",
            "last_validation": None,
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        AlgorithmHandoffRepository.save("handoff_id", doc)
        return AlgorithmHandoff(**doc)

    def get_handoff(self, handoff_id: str) -> AlgorithmHandoff:
        doc = AlgorithmHandoffRepository.find_one({"handoff_id": handoff_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"算法对接任务 '{handoff_id}' 不存在")
        return AlgorithmHandoff(**doc)

    def list_handoffs(
        self,
        *,
        status: str | None = None,
        example_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AlgorithmHandoffListData:
        items, total = AlgorithmHandoffRepository.list_handoffs(
            status=status,
            example_id=example_id,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        return AlgorithmHandoffListData(
            items=[AlgorithmHandoff(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def download_handoff_package(self, handoff_id: str) -> tuple[str, bytes]:
        handoff = self.get_handoff(handoff_id)
        payload = self._payload_for_handoff(handoff)
        content = self._build_prefilled_zip(
            payload,
            example_id=handoff.example_id,
            requirements_hint=handoff.requirements_hint,
        )
        if handoff.status == "draft":
            AlgorithmHandoffRepository.update_fields(
                handoff_id,
                {"status": "package_downloaded", "updated_at": utc_now()},
            )
        return f"{handoff.algorithm_id}-{handoff.version}-handoff.zip", content

    def validate_handoff_package(
        self,
        handoff_id: str,
        *,
        filename: str,
        content: bytes,
        resource_bindings: list[AlgorithmResourceBinding | dict[str, Any]] | None = None,
    ) -> AlgorithmHandoffValidationResult:
        self.get_handoff(handoff_id)
        if not filename.endswith(".zip"):
            raise HTTPException(status_code=422, detail="仅支持 .zip 算法包")
        if len(content) > MAX_PACKAGE_BYTES:
            raise HTTPException(status_code=413, detail="算法包超过 20MB 限制")

        checks: list[dict[str, Any]] = []
        logs: list[str] = []
        fixes: list[str] = []
        output_preview: dict[str, Any] = {}
        ok = False
        temp_root = Path(tempfile.mkdtemp(prefix="handoff-validate-", dir=settings.runtime_root))
        try:
            zip_path = temp_root / "source.zip"
            extract_dir = temp_root / "extracted"
            zip_path.write_bytes(content)
            extract_dir.mkdir(parents=True, exist_ok=True)

            self.package_service._safe_extract(zip_path, extract_dir)
            checks.append(self._check("标准 ZIP 解压", True, "文件结构可读取"))

            contract = self.package_service._load_contract(extract_dir)
            self.package_service._validate_contract(contract)
            checks.append(self._check("平台契约", True, "polyagent.algorithm.yaml 可解析"))

            requirements = self.package_service._read_requirements(extract_dir)
            self.package_service._validate_requirements_policy(requirements)
            checks.append(self._check("依赖声明", True, "requirements.txt 未包含外部 URL 或 editable 来源"))

            sample_input = self.package_service._load_sample_input(extract_dir, contract)
            checks.append(self._check("样例输入", True, "tests/sample_input.json 可读取"))

            sample_input_files, parsed_inputs = self.package_service._load_sample_input_assets(extract_dir, contract)
            validation_output_dir = extract_dir / ".polyagent_handoff_outputs"
            if validation_output_dir.exists():
                shutil.rmtree(validation_output_dir)
            validation_output_dir.mkdir(parents=True, exist_ok=True)

            runtime_backend = self.package_service._runtime_backend()
            resource_context, _ = self.package_service._resource_asset_context(
                contract,
                resource_bindings=resource_bindings,
            )
            result = runtime_backend.predict(
                package_path=extract_dir,
                entrypoint=contract["entrypoint"],
                loader=contract.get("loader"),
                inputs=sample_input,
                timeout_seconds=int((contract.get("runtime") or {}).get("timeout_seconds", 30)),
                input_files=sample_input_files,
                output_dir=validation_output_dir,
                resource_assets=resource_context,
                context={
                    "algorithm_id": contract["algorithm_id"],
                    "version": contract["version"],
                    "phase": "handoff_self_test",
                    "parsed_inputs": parsed_inputs,
                },
            )
            output, output_artifacts = self.package_service._parse_result_envelope(result.output, contract)
            self.package_service._validate_output(output, contract.get("output_schema") or {})
            self.package_service._validate_declared_output_artifacts(
                validation_output_dir,
                output_artifacts,
                contract,
            )
            checks.append(self._check("样例推理", True, "predict() 返回结构满足 output_schema"))
            logs.append(f"自测通过，runtime={runtime_backend.backend_name}")
            output_preview = output
            ok = True
        except Exception as exc:  # noqa: BLE001 - self-test should return provider-friendly guidance.
            checks.append(self._check("自测失败", False, str(exc)))
            fixes.extend(self._fix_suggestions(exc))
            logs.append(f"自测失败：{exc}")
            if isinstance(exc, AlgorithmRuntimeError) and exc.traceback_tail:
                logs.append(exc.traceback_tail[-1200:])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        status = "self_test_passed" if ok else "self_test_failed"
        result_payload = {
            "handoff_id": handoff_id,
            "ok": ok,
            "status": status,
            "package_filename": filename,
            "checks": checks,
            "logs": logs,
            "fixes": fixes,
            "output_preview": output_preview,
        }
        AlgorithmHandoffRepository.update_fields(
            handoff_id,
            {
                "status": status,
                "last_validation": result_payload,
                "updated_at": utc_now(),
            },
        )
        return AlgorithmHandoffValidationResult(**result_payload)

    def mark_submitted(self, handoff_id: str) -> AlgorithmHandoff:
        """标记对接任务已进入正式部署流程。"""
        self.get_handoff(handoff_id)
        AlgorithmHandoffRepository.update_fields(
            handoff_id,
            {"status": "submitted", "updated_at": utc_now()},
        )
        return self.get_handoff(handoff_id)

    def rewrite_package_with_handoff(self, handoff_id: str, content: bytes) -> bytes:
        """用已确认草案覆盖 ZIP 契约中的登记信息。"""
        handoff = self.get_handoff(handoff_id)
        output = io.BytesIO()
        found_contract = False
        found_sample_input = False
        with zipfile.ZipFile(io.BytesIO(content), "r") as source_zip:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                for member in source_zip.infolist():
                    member_content = source_zip.read(member.filename)
                    normalized_path = member.filename.replace("\\", "/").strip("/")
                    if normalized_path == "polyagent.algorithm.yaml":
                        contract = yaml.safe_load(member_content.decode("utf-8")) or {}
                        if not isinstance(contract, dict):
                            raise HTTPException(status_code=422, detail="polyagent.algorithm.yaml 必须是对象")
                        contract = self._merge_handoff_contract(contract, handoff)
                        member_content = yaml.safe_dump(contract, allow_unicode=True, sort_keys=False).encode("utf-8")
                        found_contract = True
                    elif normalized_path == "tests/sample_input.json":
                        member_content = json.dumps(handoff.sample_input, ensure_ascii=False, indent=2).encode("utf-8")
                        found_sample_input = True
                    target_zip.writestr(member, member_content)

                if not found_sample_input:
                    target_zip.writestr(
                        "tests/sample_input.json",
                        json.dumps(handoff.sample_input, ensure_ascii=False, indent=2).encode("utf-8"),
                    )
        if not found_contract:
            raise HTTPException(status_code=422, detail="ZIP 缺少 polyagent.algorithm.yaml")
        return output.getvalue()

    @staticmethod
    def _merge_handoff_contract(contract: dict[str, Any], handoff: AlgorithmHandoff) -> dict[str, Any]:
        updated = dict(contract)
        updated.update(
            {
                "algorithm_id": handoff.algorithm_id,
                "name": handoff.name,
                "version": handoff.version,
                "algorithm_family": updated.get("algorithm_family") or "vertical_prediction",
                "type": updated.get("type") or "predictor",
                "material_scope": handoff.material_scope,
                "input_schema": handoff.input_schema.model_dump(mode="python"),
                "output_schema": handoff.output_schema.model_dump(mode="python"),
                "sample_input_path": "tests/sample_input.json",
            }
        )
        if handoff.description:
            updated["description"] = handoff.description
        else:
            updated.pop("description", None)
        if handoff.owner_name:
            updated["developer"] = handoff.owner_name
        else:
            updated.pop("developer", None)
        if handoff.owner_contact:
            updated["developer_contact"] = handoff.owner_contact
        else:
            updated.pop("developer_contact", None)
        return updated

    def _build_prefilled_zip(
        self,
        payload: AlgorithmPackageCreate,
        *,
        example_id: str,
        requirements_hint: list[str],
    ) -> bytes:
        files, requirements = self._template_files(example_id)
        if requirements_hint:
            existing = requirements.decode("utf-8", errors="replace").splitlines()
            for item in requirements_hint:
                normalized = item.strip()
                if normalized and normalized not in existing:
                    existing.append(normalized)
            requirements = ("\n".join(existing).strip() + "\n").encode("utf-8")
        return self.package_service.build_standard_zip(payload, files=files, requirements=requirements)

    def _template_files(self, example_id: str) -> tuple[dict[str, bytes], bytes]:
        if example_id == "batch_formulation_predictor":
            example_dir = settings.project_root / "examples" / "algorithm_upload" / "electrolyte_formulation_predictor"
            if example_dir.is_dir():
                files: dict[str, bytes] = {}
                for path in example_dir.rglob("*"):
                    if path.is_dir() or "__pycache__" in path.parts:
                        continue
                    rel = path.relative_to(example_dir).as_posix()
                    if rel in {"polyagent.algorithm.yaml", "requirements.txt", "tests/sample_input.json"}:
                        continue
                    files[rel] = path.read_bytes()
                requirements = (example_dir / "requirements.txt").read_bytes()
                files["README.md"] = self._handoff_readme("批量配方预测模型").encode("utf-8")
                return files, requirements

        if example_id == "file_based_predictor":
            example_dir = settings.project_root / "examples" / "algorithm_upload" / "raman_structure_analyzer"
            if example_dir.is_dir():
                files = {}
                for path in example_dir.rglob("*"):
                    if path.is_dir() or "__pycache__" in path.parts:
                        continue
                    rel = path.relative_to(example_dir).as_posix()
                    if rel in {"polyagent.algorithm.yaml", "requirements.txt", "tests/sample_input.json"}:
                        continue
                    files[rel] = path.read_bytes()
                requirements = (example_dir / "requirements.txt").read_bytes()
                files["README.md"] = self._raman_handoff_readme().encode("utf-8")
                return files, requirements

        handler = self.package_service.demo_handler_source().encode("utf-8")
        return (
            {
                "src/handler.py": handler,
                "README.md": self._handoff_readme(self.get_example(example_id).name).encode("utf-8"),
                "model/.gitkeep": b"",
            },
            b"scikit-learn\n",
        )

    def _payload_for_handoff(self, handoff: AlgorithmHandoff) -> AlgorithmPackageCreate:
        if handoff.example_id == "file_based_predictor":
            return self._raman_file_based_payload(
                algorithm_id=handoff.algorithm_id,
                name=handoff.name,
                version=handoff.version,
                material_scope=handoff.material_scope,
                input_schema=handoff.input_schema,
                output_schema=handoff.output_schema,
                sample_input=handoff.sample_input,
                description=handoff.description,
                developer=handoff.owner_name,
                developer_contact=handoff.owner_contact,
            )
        return AlgorithmPackageCreate(
            algorithm_id=handoff.algorithm_id,
            name=handoff.name,
            version=handoff.version,
            material_scope=handoff.material_scope,
            input_schema=handoff.input_schema,
            output_schema=handoff.output_schema,
            sample_input=handoff.sample_input,
            description=handoff.description,
        )

    def _payload_for_example(self, example_id: str) -> AlgorithmPackageCreate:
        if example_id == "batch_formulation_predictor":
            return AlgorithmPackageCreate(
                algorithm_id="electrolyte_formulation_predictor",
                name="含氟电解液配方性能预测",
                version="0.1.0",
                material_scope=["fluoropolymer"],
                input_schema=AlgorithmIOSchema(fields={"formulations": "list"}, required=["formulations"]),
                output_schema=AlgorithmIOSchema(fields={"results": "list"}, required=["results"]),
                sample_input=self._default_sample_input(example_id),
                description="批量配方输入的多目标性质预测模板。",
            )
        if example_id == "file_based_predictor":
            return self._raman_file_based_payload(
                algorithm_id="raman_structure_analyzer",
                name="Raman Structure Analyzer",
                version="0.1.0",
                material_scope=["universal"],
                input_schema=self._raman_input_schema(),
                output_schema=self._raman_output_schema(),
                sample_input=self._default_sample_input(example_id),
                description="Raman/IR 光谱文件输入结构解析模板。",
            )
        return AlgorithmPackageCreate(
            algorithm_id=f"{example_id}_demo",
            name=self.get_example(example_id).name,
            version="0.1.0",
            input_schema=AlgorithmIOSchema(fields={"smiles": "string"}, required=["smiles"]),
            output_schema=AlgorithmIOSchema(fields={"prediction": "object"}, required=["prediction"]),
            sample_input=self._default_sample_input(example_id),
            description=self.get_example(example_id).description,
        )

    @staticmethod
    def _default_sample_input(example_id: str) -> dict[str, Any]:
        if example_id == "batch_formulation_predictor":
            return {
                "formulations": [
                    {
                        "formula_id": "TEST-001",
                        "task_type": "electrolyte",
                        "lithium_salt": "LiTFSI",
                        "lithium_salt_mol_L": 1.0,
                        "electrolyte_component_1": "FEC",
                        "electrolyte_component_1_mol_ratio": 1,
                        "electrolyte_component_2": "DME",
                        "electrolyte_component_2_mol_ratio": 1,
                    }
                ]
            }
        if example_id == "file_based_predictor":
            return {
                "spectype": "raman",
                "mode": "function_groups",
                "x0": 400,
                "x1": 1800,
                "k": 3,
                "transmittance": False,
                "device": "cpu",
            }
        return {"smiles": "C=C(F)F"}

    @staticmethod
    def _raman_input_schema() -> AlgorithmIOSchema:
        return AlgorithmIOSchema(
            fields={
                "spectype": "string",
                "mode": "string",
                "x0": "number",
                "x1": "number",
                "k": "integer",
                "transmittance": "boolean",
                "device": "string",
            },
            required=["spectype", "mode"],
            field_defaults={
                "spectype": "raman",
                "mode": "function_groups",
                "k": 3,
                "transmittance": False,
                "device": "cpu",
            },
            field_options={
                "spectype": ["raman"],
                "mode": ["function_groups"],
                "device": ["cpu", "cuda"],
            },
        )

    @staticmethod
    def _raman_output_schema() -> AlgorithmIOSchema:
        return AlgorithmIOSchema(
            fields={
                "candidates": "list",
                "point_count": "integer",
                "metadata": "object",
                "preprocessing": "object",
            },
            required=["candidates"],
        )

    def _raman_file_based_payload(
        self,
        *,
        algorithm_id: str,
        name: str,
        version: str,
        material_scope: list[str],
        input_schema: AlgorithmIOSchema,
        output_schema: AlgorithmIOSchema,
        sample_input: dict[str, Any],
        description: str | None,
        developer: str | None = None,
        developer_contact: str | None = None,
    ) -> AlgorithmPackageCreate:
        raman_sample_input = dict(sample_input or self._default_sample_input("file_based_predictor"))
        raman_sample_input["spectype"] = "raman"
        raman_sample_input["mode"] = "function_groups"
        return AlgorithmPackageCreate(
            algorithm_id=algorithm_id,
            name=name,
            version=version,
            material_scope=material_scope,
            trigger_modes=["human_workflow"],
            loader="src.handler:load",
            runtime={
                "python": "3.11",
                "resources": {"cpu": 2, "memory": "8Gi", "gpu": True},
                "timeout_seconds": 180,
            },
            input_schema=self._raman_input_schema(),
            output_schema=output_schema if output_schema.fields else self._raman_output_schema(),
            input_assets=[
                {
                    "key": "spectrum_file",
                    "label": "Spectrum data file",
                    "required": True,
                    "asset_role": "input",
                    "data_kind": "series",
                    "parser": "series_xy.v1",
                    "extensions": [".txt", ".dat", ".csv", ".xlsx"],
                    "mime_types": [
                        "text/plain",
                        "text/csv",
                        "application/octet-stream",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ],
                    "max_size_bytes": 10485760,
                    "sample_path": "tests/sample_assets/sample_spectrum.dat",
                }
            ],
            output_assets=[
                {
                    "key": "normalized_series",
                    "label": "Normalized input series",
                    "asset_role": "output",
                    "data_kind": "series",
                    "artifact_type": "series_json",
                    "mime_type": "application/json",
                },
                {
                    "key": "structure_candidates",
                    "label": "Structure candidates",
                    "asset_role": "output",
                    "data_kind": "json",
                    "artifact_type": "structure_json",
                    "mime_type": "application/json",
                },
                {
                    "key": "candidate_table",
                    "label": "Candidate table",
                    "asset_role": "output",
                    "data_kind": "table",
                    "artifact_type": "csv",
                    "mime_type": "text/csv",
                },
                {
                    "key": "run_report",
                    "label": "Run report",
                    "asset_role": "output",
                    "data_kind": "json",
                    "artifact_type": "report_json",
                    "mime_type": "application/json",
                },
            ],
            resource_assets=[
                {
                    "key": "raman_runtime_resources",
                    "label": "Raman runtime resources root",
                    "asset_role": "resource",
                    "data_kind": "binary",
                    "parser": "binary.v1",
                    "required": False,
                    "resource_type": "raman_runtime",
                    "required_files": [
                        "checkpoints/baseline_removal.pth",
                        "checkpoints/raman_fg.pth",
                    ],
                    "binding_required": False,
                    "description": (
                        "Optional managed binding. If omitted, the package reads RAMAN_RESOURCES_ROOT "
                        "or the service default Raman resource root. This function-group-only package "
                        "does not require raman_generation.pth or tokenizer files."
                    ),
                },
            ],
            result_envelope="polyagent_run_result.v1",
            sample_input=raman_sample_input,
            description=description or "Raman spectral functional group analysis packaged with generic file I/O assets.",
            developer=developer or "Raman Structure Analyzer 模型团队",
            developer_organization="嘉庚实验室 / 厦门大学",
            developer_contact=developer_contact,
            source_url="refer/raman",
            method_attributions=[
                {
                    "name": "Raman/IR structure analysis reference implementation",
                    "role": "implementation_source",
                    "organization": "Raman Reference Implementation",
                    "description": "Adapted from the local refer/raman reference code.",
                }
            ],
            logo_asset=None,
            logo_url=None,
        )

    @staticmethod
    def _handoff_readme(template_name: str) -> str:
        return (
            f"# {template_name} 接入包\n\n"
            "只需要替换这些位置：\n\n"
            "1. `src/predictor_service.py`：放真实模型加载、预处理、推理和后处理。\n"
            "2. `model/`：放模型权重文件。\n"
            "3. `requirements.txt`：补充运行依赖。\n"
            "4. `tests/sample_input.json`：放一个能代表真实调用的样例输入。\n\n"
            "通常不要修改 `src/handler.py`，它是 Poly Agent 平台入口适配层。\n"
            "上传前请确认 `predict()` 返回 JSON object，并包含输出契约里的必填字段。\n"
        )

    @staticmethod
    def _raman_handoff_readme() -> str:
        return (
            "# Raman Functional Group Analyzer 接入包\n\n"
            "这个模板用于文件输入型 Raman 光谱官能团分析。ZIP 只包含入口适配、轻量源码和样例光谱；"
            "模型权重不放入 ZIP，由平台作为 managed resource 注入。\n\n"
            "上传前请先在平台资源管理中登记一个 mounted path 资源。登记路径应为 Raman 资源父目录，"
            "不是 `checkpoints` 子目录：\n\n"
            "- `algorithm_id`: `raman_structure_analyzer`\n"
            "- `asset_key`: `raman_runtime_resources`\n"
            "- `path`: `/home/fangyikai/github_project/Spec_Agent/backend/resources/raman`\n"
            "- `resource_type`: `raman_runtime`\n"
            "- `required_files`: `checkpoints/baseline_removal.pth`, "
            "`checkpoints/raman_fg.pth`\n\n"
            "`path` 是运行 PolyAgent 后端服务的机器上的本地路径。当前测试环境请在 `10.26.15.93` "
            "上登记上述路径；生产环境服务运行在 `localhost` 时，在生产机本地登记同样的 Raman 资源父目录。\n\n"
            "`RAMAN_RESOURCES_ROOT` 可作为环境变量兜底。这个单模式包不需要 "
            "`raman_generation.pth`、检索数据库或 tokenizer 文件。\n\n"
            "样例文件位于 `tests/sample_assets/sample_spectrum.dat`，契约中的输入文件 key 为 `spectrum_file`。\n"
        )

    @staticmethod
    def _check(name: str, ok: bool, message: str) -> dict[str, Any]:
        return {"name": name, "ok": ok, "message": message}

    @staticmethod
    def _fix_suggestions(exc: Exception) -> list[str]:
        message = str(exc)
        suggestions: list[str] = []
        if "样例输入" in message or "sample_input" in message:
            suggestions.append("缺少 `tests/sample_input.json`，请放一个与需求文档请求示例一致的 JSON。")
        if "predict() 必须返回 dict" in message or "output must be an object" in message:
            suggestions.append('`predict()` 返回值必须是 object，请返回类似 `{"results": [...]}` 的 JSON object。')
        if "输出缺少必填字段" in message:
            suggestions.append("输出缺少必填字段，请检查 `src/handler.py` 返回值是否包含 output_schema.required 中的字段。")
        if "No module named" in message or "ModuleNotFoundError" in message:
            suggestions.append("当前运行环境可能缺少依赖，请检查 `requirements.txt` 并联系平台管理员补齐环境。")
        if "missing Raman service resources" in message:
            suggestions.append(
                "缺少 Raman 服务资源文件，请确认运行 PolyAgent 后端的测试机 10.26.15.93 上存在 "
                "/home/fangyikai/github_project/Spec_Agent/backend/resources/raman，并包含 "
                "checkpoints/baseline_removal.pth、checkpoints/raman_fg.pth；"
                "如路径不同，请配置 RAMAN_RESOURCES_ROOT 指向 Raman 资源父目录。"
            )
        elif "resource asset" in message or "managed Raman resources" in message or "RAMAN_" in message:
            suggestions.append(
                "缺少 managed resource 绑定，请在资源管理中登记 asset_key=raman_runtime_resources 的 "
                "Raman 资源父目录 mounted path，例如 "
                "/home/fangyikai/github_project/Spec_Agent/backend/resources/raman；"
                "如使用环境变量兜底，请配置 RAMAN_RESOURCES_ROOT，并确保资源父目录位于 "
                "POLYAGENT_ALGORITHM_RESOURCE_ROOTS 允许目录内。"
            )
        if "超过 20MB" in message:
            suggestions.append("ZIP 超过当前 20MB 限制，请压缩权重或改用后续远程服务/对象存储方案。")
        if not suggestions:
            suggestions.append("请先检查 ZIP 文件结构、入口函数 `src.handler:predict` 和样例输入是否与契约一致。")
        return suggestions
