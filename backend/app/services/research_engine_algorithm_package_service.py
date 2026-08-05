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
from app.core.llm_client import chat
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmPackageRepository,
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
)
from app.schemas.research_engine import (
    AlgorithmIOSchema,
    AlgorithmAssetSpec,
    AlgorithmContributor,
    AlgorithmPackage,
    AlgorithmPackageCreate,
    AlgorithmPackageListData,
    AlgorithmRegistryEntry,
    AlgorithmResourceBinding,
    AlgorithmVersion,
    AlgorithmVersionListData,
    AlgorithmSummary,
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

    def pack_new_version_from_sources(
        self,
        target_algorithm_id: str,
        version: str,
        *,
        source_files: dict[str, bytes],
        requirements: bytes | None = None,
    ) -> bytes:
        """Clone the active package and replace only selected source files."""
        if not source_files or not any(path.endswith(".py") for path in source_files):
            raise HTTPException(status_code=422, detail="新版本至少需要上传一个 Python 源文件")
        registry = AlgorithmRegistryRepository.find_one({"algorithm_id": target_algorithm_id})
        active_version_id = (registry or {}).get("active_version_id")
        if not active_version_id:
            raise HTTPException(status_code=409, detail="目标算法没有可继承的活动版本")
        active_version = self.get_version(active_version_id)
        source_package = self.get_package(active_version.package_id)
        source_path = Path(source_package.storage_uri)
        if not source_path.is_file():
            raise HTTPException(status_code=404, detail="当前版本算法包文件不存在")

        output = io.BytesIO()
        with zipfile.ZipFile(source_path) as source_zip:
            source_names = [member.filename for member in source_zip.infolist() if not member.is_dir()]
            replacements: dict[str, bytes] = {}
            for raw_path, content in source_files.items():
                normalized = self._normalize_archive_path(raw_path)
                if "/" not in normalized and normalized.endswith(".py"):
                    normalized = f"src/{normalized}"
                elif "/" not in normalized:
                    matching_paths = [path for path in source_names if Path(path).name == normalized]
                    if len(matching_paths) == 1:
                        normalized = matching_paths[0]
                    elif len(matching_paths) > 1:
                        raise HTTPException(
                            status_code=422,
                            detail=f"原包中存在多个同名文件 '{normalized}'，请改用标准 ZIP 上传新版本",
                        )
                replacements[normalized] = content

            contract = yaml.safe_load(source_zip.read(CONTRACT_FILENAME)) or {}
            if contract.get("algorithm_id") != target_algorithm_id:
                raise HTTPException(status_code=409, detail="当前版本契约与目标算法 ID 不一致")
            contract["version"] = version.strip()
            self._validate_contract(contract)
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                for member in source_zip.infolist():
                    if member.is_dir() or member.filename in replacements:
                        continue
                    if member.filename == CONTRACT_FILENAME:
                        target_zip.writestr(
                            CONTRACT_FILENAME,
                            yaml.safe_dump(contract, allow_unicode=True, sort_keys=False),
                        )
                    elif member.filename == "requirements.txt" and requirements is not None:
                        target_zip.writestr(member, requirements)
                    else:
                        target_zip.writestr(member, source_zip.read(member.filename))
                if requirements is not None and "requirements.txt" not in source_zip.namelist():
                    target_zip.writestr("requirements.txt", requirements)
                for path, content in replacements.items():
                    self._validate_archive_member(path, len(content))
                    target_zip.writestr(path, content)
        return output.getvalue()

    def upload_package(
        self,
        *,
        filename: str,
        content: bytes,
        actor_user_id: str,
        owner_user_id: str | None = None,
        visibility: str | None = None,
        target_algorithm_id: str | None = None,
        target_version: str | None = None,
    ) -> AlgorithmPackage:
        """保存上传 ZIP，返回包记录。"""
        if not filename.endswith(".zip"):
            raise HTTPException(status_code=422, detail="仅支持 .zip 算法包")
        if len(content) > MAX_PACKAGE_BYTES:
            raise HTTPException(status_code=413, detail="算法包超过 20MB 限制")
        if target_version:
            content = self._rewrite_contract_version(content, target_version)
        if len(content) > MAX_PACKAGE_BYTES:
            raise HTTPException(status_code=413, detail="重写版本后的算法包超过 20MB 限制")
        contract_metadata = self._peek_contract_metadata(content)
        normalized_visibility = self._normalize_visibility(
            visibility or contract_metadata.get("visibility") or "private"
        )
        package_sha256 = hashlib.sha256(content).hexdigest()
        package_id = f"apkg_{uuid4().hex[:12]}"
        now = utc_now()
        package_dir = self._package_root(package_id)
        package_dir.mkdir(parents=True, exist_ok=True)
        zip_path = package_dir / "source.zip"
        zip_path.write_bytes(content)
        doc = {
            "package_id": package_id,
            "target_algorithm_id": target_algorithm_id.strip() if target_algorithm_id else None,
            "algorithm_id": contract_metadata.get("algorithm_id"),
            "version": contract_metadata.get("version"),
            "resource_assets": contract_metadata.get("resource_assets") or [],
            "contributors": contract_metadata.get("contributors") or [],
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
            "visibility": normalized_visibility,
            "created_by": owner_user_id or actor_user_id,
            "uploaded_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        AlgorithmPackageRepository.save("package_id", doc)
        return AlgorithmPackage(**doc)

    def _rewrite_contract_version(self, content: bytes, version: str) -> bytes:
        """Rewrite only the semantic version in a targeted standard ZIP upload."""
        try:
            source_buffer = io.BytesIO(content)
            output = io.BytesIO()
            with zipfile.ZipFile(source_buffer) as source_zip:
                if CONTRACT_FILENAME not in source_zip.namelist():
                    raise HTTPException(status_code=422, detail=f"算法包缺少 {CONTRACT_FILENAME}")
                contract = yaml.safe_load(source_zip.read(CONTRACT_FILENAME)) or {}
                contract["version"] = version.strip()
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
                    for member in source_zip.infolist():
                        if member.is_dir():
                            continue
                        if member.filename == CONTRACT_FILENAME:
                            target_zip.writestr(
                                CONTRACT_FILENAME,
                                yaml.safe_dump(contract, allow_unicode=True, sort_keys=False),
                            )
                        else:
                            target_zip.writestr(member, source_zip.read(member.filename))
            return output.getvalue()
        except HTTPException:
            raise
        except (zipfile.BadZipFile, yaml.YAMLError) as exc:
            raise HTTPException(status_code=422, detail=f"无法读取算法包契约: {exc}") from exc

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
            contract["visibility"] = self._normalize_visibility(
                contract.get("visibility") or package.visibility or "private"
            )
            self._validate_contract(contract)
            if package.target_algorithm_id and contract["algorithm_id"] != package.target_algorithm_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"算法包契约 ID '{contract['algorithm_id']}' 与目标算法 ID "
                        f"'{package.target_algorithm_id}' 不一致"
                    ),
                )
            existing_model_version = AlgorithmVersionRepository.find_one(
                {"algorithm_id": contract["algorithm_id"]}
            )
            if (
                not package.target_algorithm_id
                and existing_model_version
                and existing_model_version.get("package_id") != package_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"模型 ID '{contract['algorithm_id']}' 已存在，"
                        "请从模型详情使用“上传新版本”流程"
                    ),
                )
            existing_version = AlgorithmVersionRepository.find_one(
                {"algorithm_id": contract["algorithm_id"], "version": contract["version"]}
            )
            if existing_version and existing_version.get("package_id") != package_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"语义版本 '{contract['version']}' 已存在，请选择新版本号",
                )
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
            developer_attribution = self._developer_attribution_from_contract(
                contract,
                created_by=package.created_by,
            )
            version_doc = {
                "version_id": version_id,
                "package_id": package_id,
                "source_kind": "uploaded_package",
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
                "visibility": contract["visibility"],
                "mentor_team": contract.get("mentor_team"),
                "contributors": [
                    item.model_dump(mode="python")
                    for item in self._contributors_from_contract(contract)
                ],
                "developer_attribution": (
                    developer_attribution.model_dump(mode="python")
                    if developer_attribution
                    else None
                ),
                "method_attributions": [
                    item.model_dump(mode="python")
                    for item in self._method_attributions_from_contract(contract)
                ],
                "implementation_notes": contract.get("implementation_notes"),
                "algorithm_summary": self._build_algorithm_summary(contract, validation_output=output).model_dump(
                    mode="python"
                ),
                "created_by": package.created_by,
                "uploaded_by": package.uploaded_by or package.created_by,
                "activated_at": None,
                "activation_kind": None,
                "previous_active_version_id": None,
                "rollback_status": None,
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
                "visibility": contract["visibility"],
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

    def activate_version(
        self,
        algorithm_id: str,
        version_id: str,
        *,
        activation_kind: str = "manual",
    ) -> AlgorithmVersion:
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
        if previous_version_id == version_id and version.status == "active":
            return version
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
        preserve_registry_metadata = bool(
            registry_entry and registry_entry.get("source") == "uploaded_package"
        )
        if preserve_registry_metadata:
            raw_attribution = registry_entry.get("developer_attribution")
            developer_attribution = (
                AttributionItem(**raw_attribution) if isinstance(raw_attribution, dict) else raw_attribution
            )
            contributors = registry_entry.get("contributors") or []
        else:
            developer_attribution = version.developer_attribution or self._developer_attribution_from_contract(
                contract,
                created_by=version.created_by,
            )
            contributors = version.contributors or self._contributors_from_contract(contract) or []

        def display_metadata(key: str, fallback: Any) -> Any:
            if preserve_registry_metadata and key in registry_entry:
                return registry_entry.get(key)
            return fallback

        registry_doc = {
            "algorithm_id": algorithm_id,
            "name": display_metadata("name", contract.get("name", algorithm_id)),
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
            "owner": (registry_entry or {}).get("owner") or version.created_by,
            "status": "active",
            "description": display_metadata("description", contract.get("description")),
            "active_version_id": version_id,
            "source": "uploaded_package",
            "source_kind": "uploaded_package",
            "deployment_status": "active",
            "visibility": self._normalize_visibility(display_metadata(
                "visibility",
                version.visibility or contract.get("visibility") or "private",
            )),
            "mentor_team": display_metadata("mentor_team", contract.get("mentor_team") or version.mentor_team),
            "contributors": [
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in contributors
            ],
            "developer_attribution": (
                developer_attribution.model_dump(mode="python")
                if developer_attribution
                else None
            ),
            "framework_attributions": contract.get("framework_attributions") or [],
            "method_attributions": [item.model_dump(mode="python") for item in version.method_attributions],
            "implementation_notes": version.implementation_notes or contract.get("implementation_notes"),
            "algorithm_summary": self._serialize_algorithm_summary(
                version.algorithm_summary
                or registry_entry.get("algorithm_summary")
                or self._build_algorithm_summary(contract)
            ),
        }
        AlgorithmRegistryRepository.save("algorithm_id", registry_doc)
        AlgorithmVersionRepository.update_fields(
            version_id,
            {
                "status": "active",
                "activated_at": now,
                "activation_kind": activation_kind,
                "previous_active_version_id": previous_version_id,
                "rollback_status": "completed" if activation_kind == "rollback" else None,
                "updated_at": now,
            },
        )
        AlgorithmPackageRepository.update_fields(version.package_id, {"status": "active", "updated_at": now})
        return self.get_version(version_id)

    def rollback_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """回滚本质上是重新激活一个历史版本。"""
        return self.activate_version(algorithm_id, version_id, activation_kind="rollback")

    def release_package(
        self,
        package_id: str,
        *,
        resource_bindings: list[AlgorithmResourceBinding | dict[str, Any]] | None = None,
    ) -> AlgorithmVersion:
        """校验、构建、部署并自动激活一个上传包。"""
        package = self.get_package(package_id)
        if not package.version_id or package.status in {"uploaded", "validation_failed"}:
            package = self.validate_package(package_id, resource_bindings=resource_bindings)
        version = self.get_version(package.version_id or "")
        if version.status == "validated":
            self.build_package(package_id)
            version = self.get_version(version.version_id)
        if version.status == "built":
            version = self.deploy_version(version.algorithm_id, version.version_id)
        if version.status == "deployed_staging":
            version = self.activate_version(
                version.algorithm_id,
                version.version_id,
                activation_kind="release",
            )
        if version.status != "active":
            raise HTTPException(status_code=409, detail=f"算法版本状态为 '{version.status}'，无法发布")
        return version

    def freeze_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """冻结算法版本，禁止新任务继续选择该版本。"""
        return self._set_unavailable_status(algorithm_id, version_id, "frozen")

    def decommission_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """下线算法版本，保留历史运行追溯信息。"""
        return self._set_unavailable_status(algorithm_id, version_id, "decommissioned")

    def delete_decommissioned_version(self, algorithm_id: str, version_id: str) -> dict[str, Any]:
        """删除已下线算法版本及其上传包记录，保留历史运行记录。"""
        version = self.get_version(version_id)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        if version.status != "decommissioned":
            raise HTTPException(status_code=409, detail="只能删除已下线算法版本")

        package_doc = AlgorithmPackageRepository.find_one({"package_id": version.package_id})
        package_root = self._package_root(version.package_id)
        AlgorithmVersionRepository.delete(version_id)
        if package_doc:
            AlgorithmPackageRepository.delete(version.package_id)
        self._remove_package_root(package_root)

        _remaining_items, remaining_total = AlgorithmVersionRepository.list_versions(
            algorithm_id=algorithm_id,
            page=1,
            page_size=1,
        )
        registry_entry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        registry_deleted = remaining_total == 0
        if registry_deleted:
            AlgorithmRegistryRepository.delete(algorithm_id)
        elif (registry_entry or {}).get("active_version_id") == version_id:
            AlgorithmRegistryRepository.update_fields(
                algorithm_id,
                {
                    "active_version_id": None,
                    "status": "decommissioned",
                    "deployment_status": "decommissioned",
                },
            )

        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "package_id": version.package_id,
            "registry_deleted": registry_deleted,
            "remaining_versions": remaining_total,
            "deleted": True,
        }

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

    def resolve_algorithm_owner(self, algorithm_id: str) -> str | None:
        """返回上传模型的固定归属用户。"""
        entry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        owner = str((entry or {}).get("owner") or "").strip()
        if owner:
            return owner
        version = self.resolve_active_version(algorithm_id)
        return version.created_by if version else None

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

    def _build_algorithm_summary(
        self,
        contract: dict[str, Any],
        *,
        validation_output: dict[str, Any] | None = None,
    ) -> AlgorithmSummary:
        if any(
            [
                settings.llm_model,
                settings.llm_base_url,
                settings.llm_provider_configs_file,
                settings.llm_provider_configs_json,
            ]
        ):
            try:
                return self._generate_algorithm_summary_with_llm(contract, validation_output=validation_output)
            except Exception:
                pass
        return self._rule_algorithm_summary(contract)

    def _generate_algorithm_summary_with_llm(
        self,
        contract: dict[str, Any],
        *,
        validation_output: dict[str, Any] | None = None,
    ) -> AlgorithmSummary:
        prompt_payload = {
            "algorithm_id": contract.get("algorithm_id"),
            "name": contract.get("name"),
            "version": contract.get("version"),
            "type": contract.get("type"),
            "algorithm_family": contract.get("algorithm_family"),
            "description": contract.get("description"),
            "developer": contract.get("developer"),
            "developer_organization": contract.get("developer_organization"),
            "mentor_team": contract.get("mentor_team"),
            "material_scope": contract.get("material_scope") or [],
            "task_scope": contract.get("task_scope") or [],
            "trigger_modes": contract.get("trigger_modes") or [],
            "input_schema": contract.get("input_schema") or {},
            "output_schema": contract.get("output_schema") or {},
            "resource_assets": contract.get("resource_assets") or [],
            "result_envelope": contract.get("result_envelope"),
            "implementation_notes": contract.get("implementation_notes"),
            "validation_output_preview": validation_output or {},
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是PolyAgent算法摘要助手。请基于输入信息生成适合单页展示的简洁中文摘要，"
                    "只返回JSON对象，不要Markdown，不要额外解释。"
                    "必须包含 overview、highlights、practices 三个字段。"
                    "overview 用一句话概括算法定位。"
                    "highlights 输出 2-4 条算法亮点。"
                    "practices 输出 2-4 条落地建议。"
                    "不要编造未提供的事实，优先突出当前算法自身的输入、输出、资源和使用方式。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, indent=2)},
        ]
        raw = chat(
            messages,
            purpose="qa",
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=500,
        )
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("算法摘要必须是 JSON object")
        overview = str(payload.get("overview") or "").strip()
        if not overview:
            raise ValueError("算法摘要缺少 overview")
        return AlgorithmSummary(
            overview=overview,
            highlights=self._normalize_summary_items(payload.get("highlights")),
            practices=self._normalize_summary_items(payload.get("practices")),
            generated_by="llm",
            generated_at=utc_now(),
        )

    @staticmethod
    def _rule_algorithm_summary(contract: dict[str, Any]) -> AlgorithmSummary:
        name = str(contract.get("name") or contract.get("algorithm_id") or "该算法").strip()
        description = str(contract.get("description") or "").strip()
        algorithm_type = str(contract.get("type") or "predictor").strip()
        material_scope = contract.get("material_scope") or []
        input_fields = AlgorithmPackageService._schema_field_names(contract.get("input_schema") or {})
        output_fields = AlgorithmPackageService._schema_field_names(contract.get("output_schema") or {})
        resource_assets = contract.get("resource_assets") or []
        task_scope = contract.get("task_scope") or []

        material_text = AlgorithmPackageService._join_labels(material_scope, limit=3)
        task_text = AlgorithmPackageService._join_labels(task_scope, limit=3)
        overview = description or f"{name} 是一个 {algorithm_type}，面向 {task_text or '当前任务'} 场景。"
        highlights = [
            f"输入契约：{AlgorithmPackageService._join_labels(input_fields, limit=4) or '无显式字段'}",
            f"输出契约：{AlgorithmPackageService._join_labels(output_fields, limit=4) or '按默认结果返回'}",
        ]
        if material_text:
            highlights.append(f"适用范围：{material_text}")
        if resource_assets:
            highlights.append(f"支持 {len(resource_assets)} 项受管资源绑定")

        practices = [
            "先用样例输入完成一次自测，确认字段名、类型和必填项一致。",
            "新版本上线后保留旧版本一段时间，确认结果稳定再冻结或下线。",
        ]
        if resource_assets:
            practices.append("大资源通过资源管理绑定，不要直接打进 ZIP 包。")
        if task_text:
            practices.append(f"围绕 {task_text} 场景补充更贴近真实业务的数据样例。")
        return AlgorithmSummary(
            overview=overview,
            highlights=highlights[:4],
            practices=practices[:4],
            generated_by="rule",
            generated_at=utc_now(),
        )

    @staticmethod
    def _serialize_algorithm_summary(summary: AlgorithmSummary | dict[str, Any] | None) -> dict[str, Any] | None:
        if summary is None:
            return None
        if isinstance(summary, AlgorithmSummary):
            return summary.model_dump(mode="python")
        return AlgorithmSummary.model_validate(summary).model_dump(mode="python")

    @staticmethod
    def _normalize_summary_items(value: Any) -> list[str]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, list):
            items = value
        else:
            items = []
        normalized = [str(item).strip() for item in items if str(item).strip()]
        return normalized[:4]

    @staticmethod
    def _schema_field_names(schema: dict[str, Any]) -> list[str]:
        fields = schema.get("fields") or {}
        if not isinstance(fields, dict):
            return []
        return [str(name).strip() for name in fields.keys() if str(name).strip()]

    @staticmethod
    def _join_labels(items: list[Any], *, limit: int = 3) -> str:
        values = [str(item).strip() for item in items if str(item).strip()]
        if not values:
            return ""
        if len(values) <= limit:
            return "、".join(values)
        return "、".join(values[:limit]) + " 等"

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
            visibility=AlgorithmPackageService._normalize_visibility(contract.get("visibility")),
            mentor_team=contract.get("mentor_team"),
            contributors=AlgorithmPackageService._contributors_from_contract(contract),
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
        contract = {
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
            "mentor_team": payload.mentor_team,
            "developer_contact": payload.developer_contact,
            "source_url": payload.source_url,
            "citation": payload.citation,
            "contributors": [item.model_dump(mode="python") for item in payload.contributors],
            "method_attributions": [
                item.model_dump(mode="python")
                for item in payload.method_attributions
            ],
            "logo_asset": payload.logo_asset,
            "logo_url": payload.logo_url,
            "visibility": payload.visibility,
            "implementation_notes": payload.description,
        }
        for key in (
            "loader",
            "result_envelope",
            "description",
            "developer",
            "developer_organization",
            "mentor_team",
            "developer_contact",
            "source_url",
            "citation",
            "contributors",
            "logo_asset",
            "logo_url",
            "implementation_notes",
        ):
            if contract.get(key) in (None, ""):
                contract.pop(key, None)
        return contract

    @staticmethod
    def _normalize_visibility(value: str | None) -> str:
        normalized = str(value or "private").strip().lower()
        if normalized not in {"private", "public"}:
            raise HTTPException(status_code=422, detail="visibility 仅支持 private 或 public")
        return normalized

    @staticmethod
    def _peek_contract_metadata(content: bytes) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                with zf.open(CONTRACT_FILENAME) as fp:
                    contract = yaml.safe_load(fp.read().decode("utf-8"))
        except Exception:
            return {}
        if not isinstance(contract, dict):
            return {}
        resource_assets = []
        for raw_spec in contract.get("resource_assets") or []:
            if not isinstance(raw_spec, dict):
                continue
            try:
                resource_assets.append(
                    AlgorithmAssetSpec(**raw_spec).model_dump(mode="python", exclude_none=True)
                )
            except ValueError:
                continue
        return {
            "algorithm_id": str(contract.get("algorithm_id") or "").strip() or None,
            "version": str(contract.get("version") or "").strip() or None,
            "visibility": str(contract.get("visibility") or "").strip().lower() or None,
            "resource_assets": resource_assets,
            "contributors": [
                item.model_dump(mode="python")
                for item in AlgorithmPackageService._contributors_from_contract(contract)
            ],
        }

    @staticmethod
    def _developer_attribution_from_contract(contract: dict, *, created_by: str) -> AttributionItem | None:
        """从算法包契约构建开发者来源标注。"""
        developer = str(contract.get("developer") or "").strip()
        organization = str(contract.get("developer_organization") or "").strip() or None
        mentor_team = str(contract.get("mentor_team") or "").strip() or None
        source_url = str(contract.get("source_url") or "").strip() or None
        citation = str(contract.get("citation") or "").strip() or None
        logo_asset = str(contract.get("logo_asset") or contract.get("logo_url") or "").strip() or None
        contributors = AlgorithmPackageService._contributors_from_contract(contract)
        if not any((developer, organization, mentor_team, source_url, citation, logo_asset)) and contributors:
            primary = next(
                (
                    item
                    for item in contributors
                    if item.role.lower() in {"developer", "author", "lead", "primary_developer"}
                ),
                contributors[0],
            )
            developer = primary.name
            organization = primary.organization
            mentor_team = mentor_team or (
                primary.mentor_relation if primary.role.lower() in {"mentor", "advisor", "supervisor"} else None
            )
            citation = primary.description or citation
        if not any((developer, organization, mentor_team, source_url, citation, logo_asset)):
            return None
        display_name = developer or organization or "算法开发者"
        if organization and mentor_team:
            description = f"算法由 {organization} / {mentor_team} / {display_name} 提供。"
        elif organization:
            description = f"算法由 {organization} / {display_name} 提供。"
        elif mentor_team:
            description = f"算法由 {mentor_team} / {display_name} 提供。"
        else:
            description = f"算法由 {display_name} 提供；未提交机构 Logo 时显示文字来源牌。"
        return AttributionItem(
            name=display_name,
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
    def _contributors_from_contract(contract: dict) -> list[AlgorithmContributor]:
        raw_items = contract.get("contributors") or []
        items: list[AlgorithmContributor] = []
        for raw in raw_items:
            if isinstance(raw, AlgorithmContributor):
                items.append(raw)
            elif isinstance(raw, dict):
                try:
                    items.append(AlgorithmContributor(**raw))
                except ValueError:
                    continue
        return items

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
    def _remove_package_root(package_root: Path) -> None:
        """删除受控 runtime 算法包目录。"""
        runtime_packages_root = (settings.runtime_root / "algorithm-packages").resolve()
        resolved_package_root = package_root.resolve()
        if runtime_packages_root not in resolved_package_root.parents:
            raise HTTPException(status_code=409, detail="拒绝删除非算法包运行目录")
        shutil.rmtree(resolved_package_root, ignore_errors=True)

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
