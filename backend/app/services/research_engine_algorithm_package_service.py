"""用户上传算法包服务。

实现 P0 的标准 ZIP 上传、网页打包助手、契约校验、版本登记和
本机 dry-run 调用。Docker/KServe 可在该服务边界后续替换。
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import textwrap
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmPackageRepository,
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
)
from app.schemas.research_engine import (
    AlgorithmIOSchema,
    AlgorithmAssetSpec,
    AlgorithmPackage,
    AlgorithmPackageCreate,
    AlgorithmPackageListData,
    AlgorithmRegistryEntry,
    AlgorithmResourceBinding,
    AlgorithmVersion,
    AlgorithmVersionListData,
)
from app.schemas.attribution import AttributionItem
from app.services.algorithm_resource_service import AlgorithmManagedResourceService
from app.services.algorithm_runtimes import (
    AlgorithmRuntimeBackend,
    LocalInProcessRuntimeBackend,
    LocalSandboxRuntimeBackend,
    RuntimeExecutionResult,
)
from app.services.algorithm_file_adapters import AlgorithmFileAdapterRegistry


MAX_PACKAGE_BYTES = 20 * 1024 * 1024
CONTRACT_FILENAME = "polyagent.algorithm.yaml"
ALLOWED_SUFFIXES = {
    ".py",
    ".txt",
    ".dat",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".csv",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".log",
    ".pkl",
    ".joblib",
    ".npy",
    ".npz",
    ".pt",
    ".bin",
}
FORBIDDEN_FILENAMES = {"Dockerfile", "dockerfile", ".env"}
FORBIDDEN_PARTS = {"__pycache__", ".git", ".venv", "venv", "node_modules"}
MAX_UNCOMPRESSED_PACKAGE_BYTES = MAX_PACKAGE_BYTES * 3
MAX_COMPRESSION_RATIO = 100
MIN_COMPRESSED_BOMB_BYTES = 1024 * 1024
MAX_OUTPUT_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_TOTAL_OUTPUT_ARTIFACT_BYTES = 200 * 1024 * 1024


class AlgorithmPackageService:
    """上传算法包业务服务。"""

    def create_template_zip(self) -> bytes:
        """生成标准算法模板 ZIP。"""
        payload = AlgorithmPackageCreate(
            algorithm_id="vertical_tg_predictor_demo",
            name="Polymer Tg Predictor Demo",
            version="0.1.0",
            input_schema=AlgorithmIOSchema(
                fields={"smiles": "string", "temperature_c": "number"},
                required=["smiles"],
            ),
            output_schema=AlgorithmIOSchema(
                fields={"prediction": "object", "feature_summary": "object"},
                required=["prediction"],
            ),
            sample_input={"smiles": "C=C(F)F", "temperature_c": 25},
        )
        return self.build_standard_zip(
            payload,
            files={
                "src/handler.py": self.demo_handler_source().encode("utf-8"),
                "README.md": self.template_readme().encode("utf-8"),
                "model/.gitkeep": b"",
                "tests/sample_assets/.gitkeep": b"",
            },
            requirements=b"scikit-learn\n",
        )

    def pack_from_sources(
        self,
        payload: AlgorithmPackageCreate,
        *,
        source_files: dict[str, bytes],
        requirements: bytes | None = None,
        readme: bytes | None = None,
    ) -> bytes:
        """网页打包助手：从原始脚本和表单生成标准 ZIP。"""
        if not source_files:
            raise HTTPException(status_code=422, detail="至少需要上传一个 Python 源文件")
        if not any(path.endswith(".py") for path in source_files):
            raise HTTPException(status_code=422, detail="上传文件中必须包含至少一个 .py 文件")
        files: dict[str, bytes] = {}
        for raw_path, content in source_files.items():
            normalized = self._normalize_archive_path(raw_path)
            if "/" not in normalized and normalized.endswith(".py"):
                normalized = f"src/{normalized}"
            files[normalized] = content
        if "README.md" not in files:
            files["README.md"] = readme or self.template_readme().encode("utf-8")
        return self.build_standard_zip(payload, files=files, requirements=requirements)

    def build_standard_zip(
        self,
        payload: AlgorithmPackageCreate,
        *,
        files: dict[str, bytes],
        requirements: bytes | None = None,
    ) -> bytes:
        """按平台契约生成标准 ZIP。"""
        contract = self._contract_from_payload(payload)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(CONTRACT_FILENAME, yaml.safe_dump(contract, allow_unicode=True, sort_keys=False))
            zf.writestr("tests/sample_input.json", json.dumps(payload.sample_input, ensure_ascii=False, indent=2))
            zf.writestr("requirements.txt", requirements or b"")
            for raw_path, content in files.items():
                safe_path = self._normalize_archive_path(raw_path)
                if safe_path in {CONTRACT_FILENAME, "requirements.txt", "tests/sample_input.json"}:
                    continue
                self._validate_archive_member(safe_path, len(content))
                zf.writestr(safe_path, content)
        return buffer.getvalue()

    def upload_package(
        self,
        *,
        filename: str,
        content: bytes,
        actor_user_id: str,
    ) -> AlgorithmPackage:
        """保存上传 ZIP，返回包记录。"""
        if not filename.endswith(".zip"):
            raise HTTPException(status_code=422, detail="仅支持 .zip 算法包")
        if len(content) > MAX_PACKAGE_BYTES:
            raise HTTPException(status_code=413, detail="算法包超过 20MB 限制")
        package_sha256 = hashlib.sha256(content).hexdigest()
        package_id = f"apkg_{uuid4().hex[:12]}"
        now = utc_now()
        package_dir = self._package_root(package_id)
        package_dir.mkdir(parents=True, exist_ok=True)
        zip_path = package_dir / "source.zip"
        zip_path.write_bytes(content)
        doc = {
            "package_id": package_id,
            "algorithm_id": None,
            "version": None,
            "version_id": None,
            "status": "uploaded",
            "package_sha256": package_sha256,
            "filename": filename,
            "storage_uri": str(zip_path),
            "size_bytes": len(content),
            "validation_errors": [],
            "validation_logs": ["算法包已上传，等待校验"],
            "build_logs": [],
            "deployment_logs": [],
            "image_digest": None,
            "package_digest": f"sha256:{package_sha256}",
            "environment_digest": None,
            "runtime_digest": None,
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        AlgorithmPackageRepository.save("package_id", doc)
        return AlgorithmPackage(**doc)

    def get_package(self, package_id: str) -> AlgorithmPackage:
        """获取算法包记录。"""
        doc = AlgorithmPackageRepository.find_one({"package_id": package_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"算法包 '{package_id}' 不存在")
        return AlgorithmPackage(**doc)

    def download_package(self, package_id: str) -> tuple[str, bytes]:
        """读取已上传或平台生成的标准算法 ZIP。"""
        package = self.get_package(package_id)
        package_path = Path(package.storage_uri)
        if not package_path.is_file():
            raise HTTPException(status_code=404, detail="算法包文件不存在")
        return package.filename, package_path.read_bytes()

    def list_packages(
        self,
        *,
        algorithm_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AlgorithmPackageListData:
        """分页查询上传包。"""
        items, total = AlgorithmPackageRepository.list_packages(
            algorithm_id=algorithm_id,
            status=status,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        return AlgorithmPackageListData(
            items=[AlgorithmPackage(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def validate_package(
        self,
        package_id: str,
        *,
        resource_bindings: list[AlgorithmResourceBinding | dict[str, Any]] | None = None,
    ) -> AlgorithmPackage:
        """校验 ZIP、契约、入口函数和样例输入，创建 AlgorithmVersion。"""
        package = self.get_package(package_id)
        package_path = Path(package.storage_uri)
        extract_dir = self._package_root(package_id) / "extracted"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        logs = ["开始校验算法包"]
        errors: list[dict] = []
        try:
            self._safe_extract(package_path, extract_dir)
            contract = self._load_contract(extract_dir)
            self._validate_contract(contract)
            sample_input = self._load_sample_input(extract_dir, contract)
            sample_input_files, parsed_inputs = self._load_sample_input_assets(extract_dir, contract)
            validation_output_dir = extract_dir / ".polyagent_validation_outputs"
            if validation_output_dir.exists():
                shutil.rmtree(validation_output_dir)
            validation_output_dir.mkdir(parents=True, exist_ok=True)
            runtime_backend = self._runtime_backend()
            resource_context, resolved_resource_bindings = self._resource_asset_context(
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
                    "phase": "validation_dry_run",
                    "parsed_inputs": parsed_inputs,
                },
            )
            output, output_artifacts = self._parse_result_envelope(result.output, contract)
            self._validate_output(output, contract.get("output_schema") or {})
            self._validate_declared_output_artifacts(validation_output_dir, output_artifacts, contract)
            version_id = self._version_id(contract["algorithm_id"], contract["version"], package.package_sha256)
            now = utc_now()
            version_doc = {
                "version_id": version_id,
                "package_id": package_id,
                "algorithm_id": contract["algorithm_id"],
                "name": contract["name"],
                "version": contract["version"],
                "package_sha256": package.package_sha256,
                "image_digest": None,
                "package_digest": f"sha256:{package.package_sha256}",
                "environment_digest": None,
                "runtime_digest": None,
                "status": "validated",
                "runtime": contract.get("runtime") or {},
                "input_schema": contract.get("input_schema") or {},
                "output_schema": contract.get("output_schema") or {},
                "input_assets": contract.get("input_assets") or [],
                "output_assets": contract.get("output_assets") or [],
                "resource_assets": contract.get("resource_assets") or [],
                "resource_bindings": [
                    item.model_dump(mode="python") for item in resolved_resource_bindings
                ],
                "result_envelope": contract.get("result_envelope"),
                "entrypoint": contract["entrypoint"],
                "loader": contract.get("loader"),
                "package_path": str(extract_dir),
                "deployment": {},
                "runtime_logs": [self._runtime_log_summary("validation_dry_run", result)],
                "contract": contract,
                "developer_attribution": self._developer_attribution_from_contract(
                    contract,
                    created_by=package.created_by,
                ).model_dump(mode="python"),
                "method_attributions": [
                    item.model_dump(mode="python")
                    for item in self._method_attributions_from_contract(contract)
                ],
                "implementation_notes": contract.get("implementation_notes"),
                "created_by": package.created_by,
                "created_at": now,
                "updated_at": now,
            }
            AlgorithmVersionRepository.save("version_id", version_doc)
            logs.extend([
                "契约校验通过",
                f"样例输入 dry-run 通过（{runtime_backend.backend_name}）",
                f"已创建算法版本 {version_id}",
            ])
            update = {
                "algorithm_id": contract["algorithm_id"],
                "version": contract["version"],
                "version_id": version_id,
                "status": "validated",
                "validation_errors": [],
                "validation_logs": logs,
                "updated_at": now,
            }
            AlgorithmPackageRepository.update_fields(package_id, update)
        except Exception as exc:
            errors.append({"path": "package", "message": str(exc), "error_type": type(exc).__name__})
            AlgorithmPackageRepository.update_fields(
                package_id,
                {
                    "status": "validation_failed",
                    "validation_errors": errors,
                    "validation_logs": logs + [f"校验失败：{exc}"],
                    "updated_at": utc_now(),
                },
            )
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=422, detail=f"算法包校验失败: {exc}") from exc
        return self.get_package(package_id)

    def build_package(self, package_id: str) -> AlgorithmPackage:
        """P0 构建：记录可追踪 package/environment/runtime digest。"""
        package = self.get_package(package_id)
        if not package.version_id:
            raise HTTPException(status_code=409, detail="算法包尚未校验通过，不能构建")
        version = self.get_version(package.version_id)
        now = utc_now()
        runtime_backend = self._runtime_backend()
        requirements = self._read_requirements(Path(version.package_path))
        self._validate_requirements_policy(requirements)
        digests = runtime_backend.build(
            version_id=version.version_id,
            package_sha256=package.package_sha256,
            package_path=Path(version.package_path),
            runtime=version.runtime,
            requirements=requirements,
        )
        runtime_digest = digests["runtime_digest"]
        build_logs = [
            f"P0 {runtime_backend.backend_name} 构建开始",
            "已校验 Python 3.11 契约和样例 dry-run",
            f"package_digest={digests['package_digest']}",
            f"environment_digest={digests['environment_digest']}",
            f"runtime_digest={runtime_digest}",
        ]
        AlgorithmPackageRepository.update_fields(
            package_id,
            {
                "status": "built",
                "image_digest": runtime_digest,
                "package_digest": digests["package_digest"],
                "environment_digest": digests["environment_digest"],
                "runtime_digest": runtime_digest,
                "build_logs": build_logs,
                "updated_at": now,
            },
        )
        AlgorithmVersionRepository.update_fields(
            version.version_id,
            {
                "status": "built",
                "image_digest": runtime_digest,
                "package_digest": digests["package_digest"],
                "environment_digest": digests["environment_digest"],
                "runtime_digest": runtime_digest,
                "updated_at": now,
            },
        )
        return self.get_package(package_id)

    def deploy_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """P0 部署：登记本地 runtime 元数据。"""
        version = self.get_version(version_id)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        if version.status not in {"built", "deployed_staging", "active"}:
            raise HTTPException(status_code=409, detail="算法版本必须先完成构建")
        runtime_backend = self._runtime_backend()
        digests = {
            "package_digest": version.package_digest or f"sha256:{version.package_sha256}",
            "environment_digest": version.environment_digest,
            "runtime_digest": version.runtime_digest or version.image_digest,
        }
        deployment = runtime_backend.deploy(
            version_id=version.version_id,
            package_path=Path(version.package_path),
            runtime=version.runtime,
            digests=digests,
        )
        AlgorithmVersionRepository.update_fields(
            version_id,
            {"status": "deployed_staging", "deployment": deployment, "updated_at": utc_now()},
        )
        AlgorithmPackageRepository.update_fields(
            version.package_id,
            {
                "status": "deployed_staging",
                "deployment_logs": [f"{runtime_backend.backend_name} 已就绪，等待激活"],
                "updated_at": utc_now(),
            },
        )
        return self.get_version(version_id)

    def redeploy_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """重新登记 runtime metadata。active 版本 redeploy 后保持 active。"""
        version = self.get_version(version_id)
        previous_status = version.status
        if previous_status not in {"built", "deployed_staging", "active"}:
            raise HTTPException(status_code=409, detail="算法版本必须先完成构建")
        deployed = self.deploy_version(algorithm_id, version_id)
        if previous_status == "active":
            now = utc_now()
            AlgorithmVersionRepository.update_fields(version_id, {"status": "active", "updated_at": now})
            AlgorithmPackageRepository.update_fields(deployed.package_id, {"status": "active", "updated_at": now})
            return self.get_version(version_id)
        return deployed

    def version_health(self, algorithm_id: str, version_id: str) -> dict[str, Any]:
        """返回版本 runtime health。"""
        version = self.get_version(version_id)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        runtime_backend = self._runtime_backend(version.deployment.get("backend") if version.deployment else None)
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "status": version.status,
            "deployment": version.deployment,
            "health": runtime_backend.health(deployment=version.deployment),
        }

    def version_logs(self, algorithm_id: str, version_id: str) -> dict[str, Any]:
        """返回版本生命周期和 runtime 日志摘要。"""
        version = self.get_version(version_id)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        package = self.get_package(version.package_id)
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "validation_logs": package.validation_logs,
            "build_logs": package.build_logs,
            "deployment_logs": package.deployment_logs,
            "runtime_logs": version.runtime_logs,
            "deployment": version.deployment,
        }

    def activate_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """激活算法版本，并写入 AlgorithmRegistry。"""
        version = self.get_version(version_id)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        if version.status not in {"deployed_staging", "active"}:
            raise HTTPException(status_code=409, detail="算法版本必须先部署到 staging")
        contract = version.contract
        now = utc_now()
        registry_entry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        previous_version_id = (registry_entry or {}).get("active_version_id")
        if previous_version_id and previous_version_id != version_id:
            previous_version = self.get_version(previous_version_id)
            AlgorithmVersionRepository.update_fields(
                previous_version_id,
                {"status": "deployed_staging", "updated_at": now},
            )
            AlgorithmPackageRepository.update_fields(
                previous_version.package_id,
                {"status": "deployed_staging", "updated_at": now},
            )
        registry_doc = {
            "algorithm_id": algorithm_id,
            "name": contract.get("name", algorithm_id),
            "type": contract.get("type", "predictor"),
            "algorithm_family": contract.get("algorithm_family", "vertical_prediction"),
            "material_scope": contract.get("material_scope") or ["universal"],
            "task_scope": contract.get("task_scope") or ["COMPUTE_PREDICT"],
            "input_schema": contract.get("input_schema") or {},
            "output_schema": contract.get("output_schema") or {},
            "input_assets": contract.get("input_assets") or [],
            "output_assets": contract.get("output_assets") or [],
            "resource_assets": contract.get("resource_assets") or [],
            "result_envelope": contract.get("result_envelope"),
            "call_method": str((version.deployment or {}).get("backend") or "LOCAL_PYTHON_ADAPTER").upper(),
            "trigger_modes": contract.get("trigger_modes") or ["human_workflow"],
            "runtime_dependency": "uploaded_python_package",
            "version": contract.get("version", version.version),
            "validation_metric": {},
            "owner": version.created_by,
            "status": "active",
            "description": contract.get("description"),
            "active_version_id": version_id,
            "source": "uploaded_package",
            "deployment_status": "active",
            "developer_attribution": (
                version.developer_attribution.model_dump(mode="python")
                if version.developer_attribution
                else self._developer_attribution_from_contract(
                    contract,
                    created_by=version.created_by,
                ).model_dump(mode="python")
            ),
            "framework_attributions": contract.get("framework_attributions") or [],
            "method_attributions": [item.model_dump(mode="python") for item in version.method_attributions],
            "implementation_notes": version.implementation_notes or contract.get("implementation_notes"),
        }
        AlgorithmRegistryRepository.save("algorithm_id", registry_doc)
        AlgorithmVersionRepository.update_fields(version_id, {"status": "active", "updated_at": now})
        AlgorithmPackageRepository.update_fields(version.package_id, {"status": "active", "updated_at": now})
        return self.get_version(version_id)

    def rollback_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """回滚本质上是重新激活一个历史版本。"""
        return self.activate_version(algorithm_id, version_id)

    def freeze_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """冻结算法版本，禁止新任务继续选择该版本。"""
        return self._set_unavailable_status(algorithm_id, version_id, "frozen")

    def decommission_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """下线算法版本，保留历史运行追溯信息。"""
        return self._set_unavailable_status(algorithm_id, version_id, "decommissioned")

    def get_version(self, version_id: str) -> AlgorithmVersion:
        """获取算法版本。"""
        doc = AlgorithmVersionRepository.find_one({"version_id": version_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"算法版本 '{version_id}' 不存在")
        return AlgorithmVersion(**doc)

    def list_versions(
        self,
        *,
        algorithm_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AlgorithmVersionListData:
        """分页查询算法版本。"""
        items, total = AlgorithmVersionRepository.list_versions(
            algorithm_id=algorithm_id,
            status=status,
            created_by=created_by,
            page=page,
            page_size=page_size,
        )
        return AlgorithmVersionListData(
            items=[AlgorithmVersion(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def resolve_active_version(self, algorithm_id: str, version_id: str | None = None) -> AlgorithmVersion | None:
        """解析待调用算法版本。内置算法返回 None。"""
        if version_id:
            version = self.get_version(version_id)
            if version.status not in {"active", "deployed_staging"}:
                raise HTTPException(status_code=409, detail=f"算法版本状态为 '{version.status}'，不可用于新任务")
            return version
        entry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        active_version_id = (entry or {}).get("active_version_id")
        if not active_version_id:
            return None
        version = self.get_version(active_version_id)
        if version.status != "active":
            raise HTTPException(status_code=409, detail="算法当前没有可调用的 active 版本")
        return version

    def _set_unavailable_status(
        self,
        algorithm_id: str,
        version_id: str,
        status: str,
    ) -> AlgorithmVersion:
        """更新不可用状态，并在必要时清理注册表 active 指针。"""
        version = self.get_version(version_id)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        if version.status == "decommissioned" and status != "decommissioned":
            raise HTTPException(status_code=409, detail="已下线版本不能恢复为其他状态")

        now = utc_now()
        AlgorithmVersionRepository.update_fields(version_id, {"status": status, "updated_at": now})
        AlgorithmPackageRepository.update_fields(version.package_id, {"status": status, "updated_at": now})

        registry_entry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        if (registry_entry or {}).get("active_version_id") == version_id:
            AlgorithmRegistryRepository.update_fields(
                algorithm_id,
                {
                    "active_version_id": None,
                    "status": status,
                    "deployment_status": status,
                },
            )
        return self.get_version(version_id)

    def run_version(self, version: AlgorithmVersion, inputs: dict) -> dict:
        """运行上传算法版本。"""
        return self.run_version_with_metadata(version, inputs).output

    def run_version_with_metadata(
        self,
        version: AlgorithmVersion,
        inputs: dict,
        *,
        input_files: dict[str, str] | None = None,
        parsed_inputs: dict[str, Any] | None = None,
        output_dir: Path | None = None,
    ) -> RuntimeExecutionResult:
        """运行上传算法版本，并返回 runtime metadata/logs。"""
        runtime_backend = self._runtime_backend(version.deployment.get("backend") if version.deployment else None)
        resource_context, _ = self._resource_asset_context(
            version.contract or {},
            resource_bindings=version.resource_bindings,
        )
        return runtime_backend.predict(
            package_path=Path(version.package_path),
            entrypoint=version.entrypoint,
            loader=version.loader,
            inputs=inputs,
            timeout_seconds=int((version.runtime or {}).get("timeout_seconds", 30)),
            input_files=input_files or {},
            output_dir=output_dir,
            resource_assets=resource_context,
            context={
                "algorithm_id": version.algorithm_id,
                "version_id": version.version_id,
                "version": version.version,
                "parsed_inputs": parsed_inputs or {},
            },
        )

    @staticmethod
    def execute_version_path(
        *,
        package_path: Path,
        entrypoint: str,
        loader: str | None,
        inputs: dict,
        timeout_seconds: int,
    ) -> dict:
        """Compatibility wrapper for dev/test in-process execution."""
        return LocalInProcessRuntimeBackend().predict(
            package_path=package_path,
            entrypoint=entrypoint,
            loader=loader,
            inputs=inputs,
            timeout_seconds=timeout_seconds,
        ).output

    @staticmethod
    def _runtime_backend(name: str | None = None) -> AlgorithmRuntimeBackend:
        backend_name = (name or settings.algorithm_runtime_backend or "local_sandbox_runtime").strip()
        if backend_name in {"local_sandbox", "local_sandbox_runtime"}:
            return LocalSandboxRuntimeBackend()
        if backend_name in {"local_inprocess", "local_python_adapter"}:
            return LocalInProcessRuntimeBackend()
        raise HTTPException(status_code=500, detail=f"未知算法运行时 backend: {backend_name}")

    @staticmethod
    def _read_requirements(package_path: Path) -> str:
        requirements_path = package_path / "requirements.txt"
        if not requirements_path.exists():
            return ""
        return requirements_path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _runtime_log_summary(phase: str, result: RuntimeExecutionResult) -> dict[str, Any]:
        return {
            "phase": phase,
            "runtime": result.runtime,
            "stdout": result.logs.stdout,
            "stderr": result.logs.stderr,
            "truncated": result.logs.truncated,
        }

    @staticmethod
    def demo_handler_source() -> str:
        """Demo Tg 预测算法源码。"""
        return textwrap.dedent(
            '''
            from __future__ import annotations

            from sklearn.ensemble import RandomForestRegressor


            def _features(smiles: str) -> list[float]:
                length = len(smiles)
                c = smiles.count("C")
                f = smiles.count("F")
                o = smiles.count("O")
                n = smiles.count("N")
                double_bonds = smiles.count("=")
                ring_marks = sum(ch.isdigit() for ch in smiles)
                fluorine_ratio = f / max(length, 1)
                return [length, c, f, o, n, double_bonds, ring_marks, fluorine_ratio]


            def load(context: dict):
                samples = ["CCO", "C=C(F)F", "FC(F)=C(F)F", "CC(C)(F)F", "C1=CC=CC=C1"]
                targets = [68.0, 102.0, 118.0, 96.0, 82.0]
                model = RandomForestRegressor(n_estimators=24, random_state=7)
                model.fit([_features(s) for s in samples], targets)
                return model


            def predict(inputs: dict, context: dict, model=None) -> dict:
                smiles = str(inputs.get("smiles", "")).strip()
                if not smiles:
                    raise ValueError("smiles is required")
                if model is None:
                    model = load(context)
                feats = _features(smiles)
                tg_c = float(model.predict([feats])[0])
                return {
                    "prediction": {
                        "property": "glass_transition_temperature",
                        "tg_c": round(tg_c, 2),
                        "uncertainty": 8.5,
                        "model_version": "demo-rf-0.1.0",
                    },
                    "feature_summary": {
                        "length": feats[0],
                        "carbon_count": feats[1],
                        "fluorine_count": feats[2],
                        "fluorine_ratio": round(feats[7], 4),
                    },
                }
            '''
        ).strip() + "\n"

    @staticmethod
    def template_readme() -> str:
        return (
            "# Poly Agent Algorithm Package\n\n"
            "Implement `load(context)` and `predict(inputs, context, model=None)` in `src/handler.py`.\n"
        )

    def _safe_extract(self, zip_path: Path, target_dir: Path) -> None:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            if not members:
                raise ValueError("ZIP 包为空")
            total_uncompressed = 0
            for member in members:
                path = self._normalize_archive_path(member.filename)
                if self._is_zip_symlink(member):
                    raise ValueError(f"禁止上传符号链接: {path}")
                self._validate_archive_member(path, member.file_size)
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_PACKAGE_BYTES:
                    raise ValueError("ZIP 解压后体积超过限制")
                if (
                    member.compress_size
                    and member.file_size > MIN_COMPRESSED_BOMB_BYTES
                    and member.file_size / max(member.compress_size, 1) > MAX_COMPRESSION_RATIO
                ):
                    raise ValueError(f"疑似压缩炸弹文件: {path}")
                target = target_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                if not member.is_dir():
                    with zf.open(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

    @staticmethod
    def _load_contract(extract_dir: Path) -> dict:
        contract_path = extract_dir / CONTRACT_FILENAME
        if not contract_path.exists():
            raise ValueError(f"缺少 {CONTRACT_FILENAME}")
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("算法契约必须是 YAML object")
        return data

    @staticmethod
    def _load_sample_input(extract_dir: Path, contract: dict) -> dict:
        sample_path = extract_dir / str(contract.get("sample_input_path", "tests/sample_input.json"))
        if not sample_path.exists():
            raise ValueError("缺少样例输入文件")
        data = json.loads(sample_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("样例输入必须是 JSON object")
        return data

    @staticmethod
    def _load_sample_input_assets(extract_dir: Path, contract: dict) -> tuple[dict[str, str], dict[str, Any]]:
        input_files: dict[str, str] = {}
        parsed_inputs: dict[str, Any] = {}
        adapter_registry = AlgorithmFileAdapterRegistry()
        for spec in contract.get("input_assets") or []:
            if not isinstance(spec, dict):
                raise ValueError("input_assets 每一项必须是 object")
            key = str(spec.get("key") or "").strip()
            if not key:
                raise ValueError("input_assets 缺少 key")
            asset_spec = AlgorithmAssetSpec(**spec)
            sample_rel = str(spec.get("sample_path") or f"tests/sample_assets/{key}").strip()
            sample_path = (extract_dir / sample_rel).resolve()
            if bool(spec.get("required")) and not sample_path.is_file():
                raise ValueError(f"required input asset '{key}' 缺少 sample asset: {sample_rel}")
            if sample_path.is_file():
                AlgorithmPackageService._validate_asset_path_within(sample_path, extract_dir, f"input asset '{key}'")
                input_files[key] = str(sample_path)
                parsed = adapter_registry.parse(spec=asset_spec, path=sample_path, filename=sample_path.name)
                if parsed:
                    parsed_inputs[key] = parsed.payload
        return input_files, parsed_inputs

    @staticmethod
    def _resource_asset_context(
        contract: dict,
        *,
        resource_bindings: list[AlgorithmResourceBinding | dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[AlgorithmResourceBinding]]:
        return AlgorithmManagedResourceService().resolve_resource_context(
            contract,
            algorithm_id=str(contract.get("algorithm_id") or "").strip() or None,
            resource_bindings=resource_bindings,
        )

    @staticmethod
    def _parse_result_envelope(output: dict, contract: dict) -> tuple[dict, list[dict]]:
        if contract.get("result_envelope") == "polyagent_run_result.v1":
            summary = output.get("output_summary") or {}
            artifacts = output.get("artifacts") or []
            if not isinstance(summary, dict):
                raise ValueError("result_envelope output_summary 必须是 object")
            if not isinstance(artifacts, list) or not all(isinstance(item, dict) for item in artifacts):
                raise ValueError("result_envelope artifacts 必须是 object 列表")
            return summary, artifacts
        return output, []

    @staticmethod
    def _validate_declared_output_artifacts(output_dir: Path, artifacts: list[dict], contract: dict) -> None:
        declared = {
            str(spec.get("key")): spec
            for spec in contract.get("output_assets") or []
            if isinstance(spec, dict) and spec.get("key")
        }
        total_size = 0
        for item in artifacts:
            key = str(item.get("key") or "").strip()
            rel_path = str(item.get("path") or "").strip()
            if not key:
                raise ValueError("输出 artifact 缺少 key")
            if declared and key not in declared:
                raise ValueError(f"输出 artifact '{key}' 未在 output_assets 声明")
            if not rel_path:
                raise ValueError(f"输出 artifact '{key}' 缺少 path")
            path = (output_dir / rel_path).resolve()
            AlgorithmPackageService._validate_asset_path_within(path, output_dir, f"output artifact '{key}'")
            if not path.is_file():
                raise ValueError(f"输出 artifact 文件不存在: {rel_path}")
            size_bytes = path.stat().st_size
            if size_bytes > MAX_OUTPUT_ARTIFACT_BYTES:
                raise ValueError(f"输出 artifact '{key}' 超过单文件大小限制")
            total_size += size_bytes
            if total_size > MAX_TOTAL_OUTPUT_ARTIFACT_BYTES:
                raise ValueError("输出 artifacts 总大小超过限制")

    @staticmethod
    def _validate_asset_path_within(path: Path, root: Path, label: str) -> None:
        root_resolved = root.resolve()
        if root_resolved not in path.parents and path != root_resolved:
            raise ValueError(f"{label} 路径越界")

    @staticmethod
    def _validate_resource_path(path: Path, key: str) -> None:
        status, message, _ = AlgorithmManagedResourceService().check_path(str(path), asset_key=key)
        if status != "active":
            raise ValueError(message)

    @staticmethod
    def _validate_contract(contract: dict) -> None:
        required = [
            "contract_version",
            "algorithm_id",
            "name",
            "version",
            "algorithm_family",
            "type",
            "material_scope",
            "task_scope",
            "trigger_modes",
            "entrypoint",
            "runtime",
            "input_schema",
            "output_schema",
            "sample_input_path",
        ]
        for field in required:
            if field not in contract:
                raise ValueError(f"契约缺少字段: {field}")
        if str(contract["contract_version"]) not in {"0.1", "0.2"}:
            raise ValueError("仅支持 contract_version=0.1 或 0.2")
        runtime = contract.get("runtime") or {}
        if str(runtime.get("python")) != "3.11":
            raise ValueError("P0 仅支持 Python 3.11")
        AlgorithmRegistryEntry(
            algorithm_id=contract["algorithm_id"],
            name=contract["name"],
            type=contract["type"],
            algorithm_family=contract["algorithm_family"],
            material_scope=contract.get("material_scope") or ["universal"],
            task_scope=contract.get("task_scope") or [],
            input_schema=AlgorithmIOSchema(**(contract.get("input_schema") or {})),
            output_schema=AlgorithmIOSchema(**(contract.get("output_schema") or {})),
            input_assets=contract.get("input_assets") or [],
            output_assets=contract.get("output_assets") or [],
            resource_assets=contract.get("resource_assets") or [],
            result_envelope=contract.get("result_envelope"),
            trigger_modes=contract.get("trigger_modes") or ["human_workflow"],
            runtime_dependency="uploaded_python_package",
            version=contract["version"],
            source="uploaded_package",
            developer_attribution=AlgorithmPackageService._developer_attribution_from_contract(
                contract,
                created_by="package_owner",
            ),
            method_attributions=AlgorithmPackageService._method_attributions_from_contract(contract),
            implementation_notes=contract.get("implementation_notes"),
        )
        AlgorithmPackageService._split_callable(contract["entrypoint"])
        if contract.get("loader"):
            AlgorithmPackageService._split_callable(contract["loader"])

    @staticmethod
    def _validate_output(output: dict, output_schema: dict) -> None:
        required = output_schema.get("required") or []
        for field in required:
            if field not in output:
                raise ValueError(f"输出缺少必填字段: {field}")

    @staticmethod
    def _split_callable(value: str | None) -> tuple[str, str]:
        if not value or ":" not in value:
            raise ValueError("入口函数必须使用 module:function 格式")
        module, func = value.split(":", 1)
        if not module or not func:
            raise ValueError("入口函数必须包含 module 和 function")
        return module, func

    @staticmethod
    def _version_id(algorithm_id: str, version: str, package_sha256: str) -> str:
        short_hash = package_sha256[:12]
        return f"aver_{algorithm_id}_{version}_{short_hash}".replace(".", "_").replace("-", "_")

    @staticmethod
    def _contract_from_payload(payload: AlgorithmPackageCreate) -> dict:
        runtime = {"python": "3.11", "resources": {"cpu": 1, "memory": "1Gi", "gpu": False}, "timeout_seconds": 30}
        runtime.update(payload.runtime or {})
        uses_assets = bool(payload.input_assets or payload.output_assets or payload.resource_assets or payload.result_envelope)
        return {
            "contract_version": "0.2" if uses_assets else "0.1",
            "algorithm_id": payload.algorithm_id,
            "name": payload.name,
            "version": payload.version,
            "algorithm_family": payload.algorithm_family,
            "type": payload.type,
            "material_scope": payload.material_scope,
            "task_scope": payload.task_scope,
            "trigger_modes": payload.trigger_modes,
            "entrypoint": payload.entrypoint,
            "loader": payload.loader,
            "runtime": runtime,
            "input_schema": payload.input_schema.model_dump(),
            "output_schema": payload.output_schema.model_dump(),
            "input_assets": [item.model_dump(mode="python") for item in payload.input_assets],
            "output_assets": [item.model_dump(mode="python") for item in payload.output_assets],
            "resource_assets": [item.model_dump(mode="python") for item in payload.resource_assets],
            "result_envelope": payload.result_envelope,
            "sample_input_path": "tests/sample_input.json",
            "description": payload.description,
            "developer": payload.developer,
            "developer_organization": payload.developer_organization,
            "developer_contact": payload.developer_contact,
            "source_url": payload.source_url,
            "citation": payload.citation,
            "method_attributions": [
                item.model_dump(mode="python")
                for item in payload.method_attributions
            ],
            "logo_asset": payload.logo_asset,
            "logo_url": payload.logo_url,
            "implementation_notes": payload.description,
        }

    @staticmethod
    def _developer_attribution_from_contract(contract: dict, *, created_by: str) -> AttributionItem:
        """从算法包契约构建开发者来源标注。"""
        developer = str(contract.get("developer") or "").strip() or created_by
        organization = str(contract.get("developer_organization") or "").strip() or None
        source_url = str(contract.get("source_url") or "").strip() or None
        citation = str(contract.get("citation") or "").strip() or None
        logo_asset = str(contract.get("logo_asset") or contract.get("logo_url") or "").strip() or None
        if organization:
            description = f"算法由 {organization} / {developer} 提供。"
        else:
            description = f"算法由 {developer} 提供；未提交机构 Logo 时显示文字来源牌。"
        return AttributionItem(
            name=developer,
            role="developer",
            organization=organization,
            description=description,
            url=source_url,
            citation_text=citation,
            logo_asset=logo_asset,
            logo_alt=organization or developer,
            visibility="prominent",
        )

    @staticmethod
    def _method_attributions_from_contract(contract: dict) -> list[AttributionItem]:
        """从算法包契约读取方法来源标注。"""
        raw_items = contract.get("method_attributions") or []
        items: list[AttributionItem] = []
        for raw in raw_items:
            if isinstance(raw, AttributionItem):
                items.append(raw)
            elif isinstance(raw, dict):
                items.append(AttributionItem(**raw))
        return items

    @staticmethod
    def _package_root(package_id: str) -> Path:
        return settings.runtime_root / "algorithm-packages" / package_id

    @staticmethod
    def _normalize_archive_path(raw_path: str) -> str:
        path = raw_path.replace("\\", "/").strip("/")
        if not path or path.startswith("../") or "/../" in path or path == "..":
            raise ValueError(f"非法 ZIP 路径: {raw_path}")
        return path

    @staticmethod
    def _validate_archive_member(path: str, size: int) -> None:
        parts = set(Path(path).parts)
        if parts & FORBIDDEN_PARTS:
            raise ValueError(f"禁止上传目录: {path}")
        if Path(path).name in FORBIDDEN_FILENAMES:
            raise ValueError(f"禁止上传文件: {path}")
        if size > MAX_PACKAGE_BYTES:
            raise ValueError(f"文件过大: {path}")
        suffix = Path(path).suffix
        if suffix and suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"不支持的文件类型: {path}")

    @staticmethod
    def _is_zip_symlink(member: zipfile.ZipInfo) -> bool:
        return ((member.external_attr >> 16) & 0o170000) == 0o120000

    @staticmethod
    def _validate_requirements_policy(requirements: str) -> None:
        for raw_line in requirements.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            lower = line.lower()
            if (
                lower.startswith("-e ")
                or lower.startswith("--editable")
                or lower.startswith("git+")
                or lower.startswith("http://")
                or lower.startswith("https://")
                or lower.startswith("file:")
                or "@ http://" in lower
                or "@ https://" in lower
            ):
                raise HTTPException(status_code=422, detail=f"requirements.txt 包含未授权依赖来源: {line}")
