"""算法对接任务与模板包服务。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        payload = AlgorithmPackageCreate(
            algorithm_id=handoff.algorithm_id,
            name=handoff.name,
            version=handoff.version,
            material_scope=handoff.material_scope,
            input_schema=handoff.input_schema,
            output_schema=handoff.output_schema,
            sample_input=handoff.sample_input,
            description=handoff.description,
        )
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

            runtime_backend = self.package_service._runtime_backend()
            result = runtime_backend.predict(
                package_path=extract_dir,
                entrypoint=contract["entrypoint"],
                loader=contract.get("loader"),
                inputs=sample_input,
                timeout_seconds=int((contract.get("runtime") or {}).get("timeout_seconds", 30)),
                context={
                    "algorithm_id": contract["algorithm_id"],
                    "version": contract["version"],
                    "phase": "handoff_self_test",
                },
            )
            self.package_service._validate_output(result.output, contract.get("output_schema") or {})
            checks.append(self._check("样例推理", True, "predict() 返回结构满足 output_schema"))
            logs.append(f"自测通过，runtime={runtime_backend.backend_name}")
            output_preview = result.output
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

        handler = self.package_service.demo_handler_source().encode("utf-8")
        return (
            {
                "src/handler.py": handler,
                "README.md": self._handoff_readme(self.get_example(example_id).name).encode("utf-8"),
                "model/.gitkeep": b"",
            },
            b"scikit-learn\n",
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
        return {"smiles": "C=C(F)F"}

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
        if "超过 20MB" in message:
            suggestions.append("ZIP 超过当前 20MB 限制，请压缩权重或改用后续远程服务/对象存储方案。")
        if not suggestions:
            suggestions.append("请先检查 ZIP 文件结构、入口函数 `src.handler:predict` 和样例输入是否与契约一致。")
        return suggestions
