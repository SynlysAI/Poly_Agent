"""远程接口型垂类模型的配置、连通性测试和调用适配器。"""

from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import socket
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmRunRepository,
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
)
from app.schemas.research_engine import (
    AlgorithmAssetSpec,
    AlgorithmInterfaceCreate,
    AlgorithmInterfaceDetails,
    AlgorithmInterfaceListData,
    AlgorithmInterfaceTestResult,
    AlgorithmInterfaceVersionCreate,
    AlgorithmInterfaceVersionUpdate,
    AlgorithmRegistryEntry,
    AlgorithmVersion,
    RemoteInterfaceConfig,
)


DEFAULT_REMOTE_ARTIFACT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_REMOTE_ARTIFACT_TOTAL_BYTES = 100 * 1024 * 1024


class RemoteInterfaceService:
    """管理远程接口版本并同步执行 HTTP/FastAPI 兼容请求。"""

    def create_interface(
        self,
        payload: AlgorithmInterfaceCreate,
        *,
        actor_user_id: str,
        actor_user_name: str | None = None,
    ) -> AlgorithmInterfaceDetails:
        """创建一个接口型算法及首个版本。"""
        if AlgorithmRegistryRepository.find_one({"algorithm_id": payload.algorithm_id}):
            raise HTTPException(status_code=409, detail="算法 ID 已存在")
        now = utc_now()
        version_id = self._new_id("aiv")
        version_doc = self._version_document(
            version_id=version_id,
            algorithm_id=payload.algorithm_id,
            name=payload.name,
            version=payload.version,
            input_schema=payload.input_schema.model_dump(mode="python"),
            output_schema=payload.output_schema.model_dump(mode="python"),
            input_assets=[item.model_dump(mode="python") for item in payload.input_assets],
            output_assets=[item.model_dump(mode="python") for item in payload.output_assets],
            interface_config=payload.interface_config,
            sample_input=payload.sample_input,
            model_proposal=payload.model_proposal,
            description=payload.description,
            visibility=payload.visibility,
            created_by=actor_user_id,
            created_by_name=actor_user_name or actor_user_id,
            now=now,
        )
        self._validate_interface_contract(
            payload.input_schema.model_dump(mode="python"),
            payload.output_schema.model_dump(mode="python"),
            payload.interface_config,
            payload.sample_input,
            payload.input_assets,
            payload.output_assets,
        )
        registry_doc = self._registry_document(
            payload=payload,
            actor_user_id=actor_user_id,
            version_id=version_id,
            now=now,
        )
        AlgorithmVersionRepository.save("version_id", version_doc)
        AlgorithmRegistryRepository.save("algorithm_id", registry_doc)
        return self.get_interface(payload.algorithm_id)

    def create_version(
        self,
        algorithm_id: str,
        payload: AlgorithmInterfaceVersionCreate,
        *,
        actor_user_id: str,
        actor_user_name: str | None = None,
    ) -> AlgorithmVersion:
        """为已有接口模型创建不可变的新版本。"""
        registry = self._get_registry(algorithm_id)
        existing_versions, _ = AlgorithmVersionRepository.list_versions(algorithm_id=algorithm_id, page=1, page_size=1000)
        if any(str(item.get("version")) == payload.version for item in existing_versions):
            raise HTTPException(status_code=409, detail=f"接口版本 '{payload.version}' 已存在")
        if registry.get("source") != "remote_interface":
            raise HTTPException(status_code=409, detail="该算法不是接口调用模型")
        now = utc_now()
        version_id = self._new_id("aiv")
        version_doc = self._version_document(
            version_id=version_id,
            algorithm_id=algorithm_id,
            name=str(registry.get("name") or algorithm_id),
            version=payload.version,
            input_schema=payload.input_schema.model_dump(mode="python"),
            output_schema=payload.output_schema.model_dump(mode="python"),
            input_assets=[item.model_dump(mode="python") for item in payload.input_assets],
            output_assets=[item.model_dump(mode="python") for item in payload.output_assets],
            interface_config=payload.interface_config,
            sample_input=payload.sample_input,
            model_proposal=payload.model_proposal,
            description=payload.description if payload.description is not None else registry.get("description"),
            visibility=payload.visibility or registry.get("visibility") or "private",
            created_by=actor_user_id,
            created_by_name=actor_user_name or actor_user_id,
            now=now,
        )
        self._validate_interface_contract(
            payload.input_schema.model_dump(mode="python"),
            payload.output_schema.model_dump(mode="python"),
            payload.interface_config,
            payload.sample_input,
            payload.input_assets,
            payload.output_assets,
        )
        AlgorithmVersionRepository.save("version_id", version_doc)
        has_active_version = bool(registry.get("active_version_id"))
        AlgorithmRegistryRepository.update_fields(
            algorithm_id,
            {
                "status": (registry.get("status") or "active") if has_active_version else "in_development",
                "deployment_status": (registry.get("deployment_status") or "active") if has_active_version else "testing",
                "updated_at": now,
            },
        )
        return AlgorithmVersion(**version_doc)

    def update_version(
        self,
        algorithm_id: str,
        version_id: str,
        payload: AlgorithmInterfaceVersionUpdate,
    ) -> AlgorithmVersion:
        """原地更新尚未激活的远程接口版本草稿。"""
        version = self._get_version(algorithm_id, version_id)
        if version.source_kind != "remote_interface":
            raise HTTPException(status_code=409, detail="目标版本不是远程接口版本")
        if version.status not in {"validated", "deployed_staging"}:
            raise HTTPException(status_code=409, detail=f"接口版本状态为 '{version.status}'，无法编辑")

        requested = payload.model_dump(mode="python", exclude_unset=True)
        input_schema = payload.input_schema or version.input_schema
        output_schema = payload.output_schema or version.output_schema
        input_assets = payload.input_assets if payload.input_assets is not None else version.input_assets
        output_assets = payload.output_assets if payload.output_assets is not None else version.output_assets
        interface_config = payload.interface_config or version.interface_config
        if interface_config is None:
            raise HTTPException(status_code=409, detail="接口版本缺少接口配置")
        sample_input = requested.get("sample_input", version.contract.get("sample_input", {}))
        model_proposal = requested.get("model_proposal", version.model_proposal)
        description = requested["description"] if "description" in requested else version.contract.get("description")
        visibility = requested.get("visibility", version.visibility)

        self._validate_interface_contract(
            input_schema.model_dump(mode="python"),
            output_schema.model_dump(mode="python"),
            interface_config,
            sample_input or {},
            input_assets,
            output_assets,
        )
        now = utc_now()
        runtime_logs = [
            *list(version.runtime_logs or [])[-49:],
            {"event": "interface_config_updated", "updated_at": now},
        ]
        contract = {
            "sample_input": sample_input or {},
            "description": description,
        }
        if model_proposal is not None:
            contract["model_proposal"] = model_proposal
        AlgorithmVersionRepository.update_fields(
            version_id,
            {
                "input_schema": input_schema.model_dump(mode="python"),
                "output_schema": output_schema.model_dump(mode="python"),
                "input_assets": [item.model_dump(mode="python") for item in input_assets],
                "output_assets": [item.model_dump(mode="python") for item in output_assets],
                "interface_config": interface_config.model_dump(mode="python"),
                "contract": contract,
                "model_proposal": model_proposal,
                "visibility": visibility,
                "status": "validated",
                "deployment": {},
                "runtime_logs": runtime_logs,
                "updated_at": now,
            },
        )

        registry = self._get_registry(algorithm_id)
        if not registry.get("active_version_id"):
            AlgorithmRegistryRepository.update_fields(
                algorithm_id,
                {
                    "status": "in_development",
                    "deployment_status": "testing",
                    "integration_kind": "pending",
                    "input_schema": input_schema.model_dump(mode="python"),
                    "output_schema": output_schema.model_dump(mode="python"),
                    "input_assets": [item.model_dump(mode="python") for item in input_assets],
                    "output_assets": [item.model_dump(mode="python") for item in output_assets],
                    "interface_config": interface_config.model_dump(mode="python"),
                    "call_method": interface_config.protocol.upper(),
                    "version": version.version,
                    "description": description,
                    "visibility": visibility,
                    "updated_at": now,
                },
            )
        return self._get_version(algorithm_id, version_id)

    def list_interfaces(
        self,
        *,
        created_by: str | None,
        page: int = 1,
        page_size: int = 20,
    ) -> AlgorithmInterfaceListData:
        """分页查询可见的接口型垂类模型。"""
        items, total = AlgorithmRegistryRepository.list_algorithms(
            algorithm_family="vertical_prediction",
            source="remote_interface",
            page=page,
            page_size=page_size,
        )
        if created_by:
            items = [
                item for item in items
                if item.get("owner") == created_by or item.get("visibility") == "public"
            ]
            total = len(items)
        return AlgorithmInterfaceListData(
            items=[AlgorithmRegistryEntry(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_interface(self, algorithm_id: str) -> AlgorithmInterfaceDetails:
        """获取接口模型及其当前 active 版本。"""
        registry = self._get_registry(algorithm_id)
        algorithm = AlgorithmRegistryEntry(**registry)
        version = None
        version_id = registry.get("active_version_id")
        version_doc = AlgorithmVersionRepository.find_one({"version_id": version_id}) if version_id else None
        if version_doc is None:
            versions, _total = AlgorithmVersionRepository.list_versions(
                algorithm_id=algorithm_id,
                page=1,
                page_size=1,
            )
            version_doc = versions[0] if versions else None
        if version_doc:
            version = AlgorithmVersion(**version_doc)
        return AlgorithmInterfaceDetails(algorithm=algorithm, version=version)

    def test_version(
        self,
        algorithm_id: str,
        version_id: str,
        *,
        input_snapshot: dict | None = None,
        input_files: dict[str, dict[str, str]] | None = None,
        output_dir: Path | None = None,
    ) -> AlgorithmInterfaceTestResult:
        """对接口版本执行一次样例调用，不创建 AlgorithmRun。"""
        version = self._get_version(algorithm_id, version_id)
        config = version.interface_config
        if version.source_kind != "remote_interface" or config is None:
            raise HTTPException(status_code=409, detail="目标版本不是远程接口版本")
        if config.protocol == "mcp":
            raise HTTPException(
                status_code=501,
                detail={
                    "code": "REMOTE_PROTOCOL_NOT_SUPPORTED",
                    "message": "MCP 接口配置已保存，但首期暂不支持真实调用",
                },
            )
        try:
            output, metadata = self.invoke(
                version,
                input_snapshot if input_snapshot is not None else version.contract.get("sample_input", {}),
                input_files=input_files,
                output_dir=output_dir,
            )
            metadata.pop("_downloaded_artifacts", None)
            now = utc_now()
            registry = self._get_registry(algorithm_id)
            is_active_version = registry.get("active_version_id") == version_id
            next_status = "active" if is_active_version else "deployed_staging"
            AlgorithmVersionRepository.update_fields(
                version_id,
                {
                    "status": next_status,
                    "deployment": {"backend": "remote_http", "status": "verified", **metadata},
                    "runtime_logs": [
                        *list(version.runtime_logs or [])[-49:],
                        {"event": "interface_test_succeeded", **metadata},
                    ],
                    "updated_at": now,
                },
            )
            AlgorithmRegistryRepository.update_fields(
                algorithm_id,
                {"deployment_status": "active" if is_active_version else "verified", "updated_at": now},
            )
            return AlgorithmInterfaceTestResult(
                algorithm_id=algorithm_id,
                version_id=version_id,
                protocol=config.protocol,
                ok=True,
                status_code=metadata.get("status_code"),
                latency_ms=metadata.get("latency_ms"),
                output_preview=output,
                artifact_previews=metadata.get("artifact_previews") or [],
            )
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                error_code = str(detail.get("code") or "REMOTE_INTERFACE_TEST_FAILED")
                error_message = str(detail.get("message") or detail.get("detail") or detail)
            else:
                error_code = "REMOTE_INTERFACE_TEST_FAILED"
                error_message = str(detail)
            return AlgorithmInterfaceTestResult(
                algorithm_id=algorithm_id,
                version_id=version_id,
                protocol=config.protocol,
                ok=False,
                status_code=exc.status_code,
                error_code=error_code,
                error_message=error_message[:300],
            )
        except Exception as exc:
            return AlgorithmInterfaceTestResult(
                algorithm_id=algorithm_id,
                version_id=version_id,
                protocol=config.protocol,
                ok=False,
                error_code="REMOTE_INTERFACE_TEST_FAILED",
                error_message=str(exc)[:300],
            )

    def invoke(
        self,
        version: AlgorithmVersion,
        input_snapshot: dict,
        *,
        input_files: dict[str, dict[str, str]] | None = None,
        output_dir: Path | None = None,
    ) -> tuple[object, dict[str, Any]]:
        """同步调用远程接口并返回已提取的输出和非敏感运行元数据。"""
        config = version.interface_config
        if version.source_kind != "remote_interface" or config is None:
            raise HTTPException(status_code=409, detail="目标版本不是远程接口版本")
        if config.protocol == "mcp":
            raise HTTPException(
                status_code=501,
                detail={
                    "code": "REMOTE_PROTOCOL_NOT_SUPPORTED",
                    "message": "MCP 接口配置已保存，但首期暂不支持真实调用",
                },
            )
        self._validate_input(input_snapshot, version.input_schema.model_dump(mode="python"))
        normalized_files = self._validate_input_files(version.input_assets, input_files or {})
        self._guard_endpoint(config.endpoint_url)
        query = self._mapped_values(config.query_bindings, input_snapshot)
        headers = dict(config.static_headers)
        headers.update(self._mapped_values(config.header_bindings, input_snapshot))
        for header_name, secret_ref in config.secret_refs.items():
            secret_value = os.getenv(secret_ref)
            if not secret_value:
                raise HTTPException(status_code=422, detail=f"接口凭据引用未配置: {secret_ref}")
            headers[header_name] = secret_value
        started = time.monotonic()
        try:
            with httpx.Client(follow_redirects=False, timeout=config.timeout_seconds) as client:
                with ExitStack() as stack:
                    request_files = None
                    request_json = None if config.http_method == "GET" else input_snapshot
                    request_data = None
                    if config.body_mode == "multipart":
                        request_json = None
                        request_data = {config.multipart_json_field: json.dumps(input_snapshot, ensure_ascii=False)}
                        request_files = {}
                        for key, item in normalized_files.items():
                            handle = stack.enter_context(Path(item["path"]).open("rb"))
                            request_files[config.file_bindings[key]] = (
                                item["filename"],
                                handle,
                                item["mime_type"],
                            )
                    with client.stream(
                        config.http_method,
                        config.endpoint_url,
                        params=query or None,
                        headers=headers or None,
                        json=request_json,
                        data=request_data,
                        files=request_files,
                    ) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise HTTPException(status_code=502, detail=f"远程接口返回 HTTP {response.status_code}")
                        chunks: list[bytes] = []
                        response_size = 0
                        for chunk in response.iter_bytes():
                            response_size += len(chunk)
                            if response_size > settings.remote_interface_max_response_bytes:
                                raise HTTPException(status_code=502, detail="远程接口响应超过平台限制")
                            chunks.append(chunk)
                        response_content = b"".join(chunks)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="远程接口调用超时") from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail="远程接口网络请求失败") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            raw_output = json.loads(response_content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail="远程接口未返回合法 JSON") from exc
        selected_output = self._select_output(raw_output, config.response_selector)
        artifact_previews: list[dict[str, Any]] = []
        downloaded_artifacts: list[dict[str, Any]] = []
        if config.result_mode == "artifact_manifest":
            output, manifest_items = self._parse_artifact_manifest(selected_output, version.output_assets)
            if output_dir is not None:
                downloaded_artifacts, artifact_previews = self._download_manifest_artifacts(
                    config,
                    manifest_items,
                    version.output_assets,
                    output_dir,
                )
            else:
                artifact_previews = self._artifact_previews(manifest_items)
        else:
            output = selected_output
        self._validate_output(output, version.output_schema.model_dump(mode="python"))
        return self._sanitize_output(output), {
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "protocol": config.protocol,
            "endpoint_host": urlparse(config.endpoint_url).hostname,
            "artifact_previews": artifact_previews,
            "_downloaded_artifacts": downloaded_artifacts,
        }

    def activate_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """激活已验证的远程接口版本。"""
        version = self._get_version(algorithm_id, version_id)
        if version.source_kind != "remote_interface":
            raise HTTPException(status_code=409, detail="目标版本不是远程接口版本")
        if version.interface_config and version.interface_config.protocol == "mcp":
            raise HTTPException(status_code=409, detail="MCP 接口首期不能激活")
        if version.status not in {"validated", "deployed_staging", "active"}:
            raise HTTPException(status_code=409, detail=f"接口版本状态为 '{version.status}'，无法激活")
        now = utc_now()
        registry = self._get_registry(algorithm_id)
        previous_id = registry.get("active_version_id")
        if previous_id and previous_id != version_id:
            AlgorithmVersionRepository.update_fields(
                previous_id,
                {"status": "deployed_staging", "updated_at": now},
            )
        AlgorithmVersionRepository.update_fields(
            version_id,
            {
                "status": "active",
                "activated_at": now,
                "activation_kind": "manual",
                "previous_active_version_id": previous_id,
                "updated_at": now,
            },
        )
        AlgorithmRegistryRepository.update_fields(
            algorithm_id,
            {
                "status": "active",
                "active_version_id": version_id,
                "deployment_status": "active",
                "integration_kind": "real",
                "version": version.version,
                "input_schema": version.input_schema.model_dump(mode="python"),
                "output_schema": version.output_schema.model_dump(mode="python"),
                "interface_config": version.interface_config.model_dump(mode="python") if version.interface_config else None,
                "call_method": version.interface_config.protocol.upper() if version.interface_config else "HTTP",
                "description": version.contract.get("description") or registry.get("description"),
                "visibility": version.visibility,
                "updated_at": now,
            },
        )
        return self._get_version(algorithm_id, version_id)

    def freeze_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """冻结远程接口版本并停止新调用。"""
        return self._set_unavailable_status(algorithm_id, version_id, "frozen")

    def decommission_version(self, algorithm_id: str, version_id: str) -> AlgorithmVersion:
        """下线远程接口版本并保留历史运行记录。"""
        return self._set_unavailable_status(algorithm_id, version_id, "decommissioned")

    def delete_version(self, algorithm_id: str, version_id: str) -> dict[str, Any]:
        """删除已下线接口版本，保留 AlgorithmRun 追溯记录。"""
        version = self._get_version(algorithm_id, version_id)
        if version.status != "decommissioned":
            raise HTTPException(status_code=409, detail="只能删除已下线接口版本")
        AlgorithmVersionRepository.delete(version_id)
        remaining, total = AlgorithmVersionRepository.list_versions(
            algorithm_id=algorithm_id,
            page=1,
            page_size=1,
        )
        registry = self._get_registry(algorithm_id)
        registry_deleted = total == 0
        if registry_deleted:
            AlgorithmRegistryRepository.delete(algorithm_id)
        elif registry.get("active_version_id") == version_id:
            AlgorithmRegistryRepository.update_fields(
                algorithm_id,
                {"active_version_id": None, "status": "decommissioned", "deployment_status": "decommissioned"},
            )
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "package_id": None,
            "registry_deleted": registry_deleted,
            "remaining_versions": total,
            "deleted": True,
        }

    def get_id_availability(self, algorithm_id: str, *, actor_user_id: str, is_admin: bool) -> dict[str, Any]:
        """检查算法 ID 是否可用，并返回不泄露模型详情的操作建议。"""
        normalized = algorithm_id.strip()
        registry = AlgorithmRegistryRepository.find_one({"algorithm_id": normalized}) if normalized else None
        if not registry:
            return {"algorithm_id": normalized, "available": True, "recommended_action": "create_algorithm", "can_create_version": False, "suggestions": []}
        is_owner = is_admin or registry.get("owner") == actor_user_id
        return {
            "algorithm_id": normalized,
            "available": False,
            "recommended_action": "create_interface_version" if is_owner and registry.get("source") == "remote_interface" else "choose_another_id",
            "can_create_version": bool(is_owner and registry.get("source") == "remote_interface"),
            "suggestions": [f"{normalized}_v2", f"{normalized}_model", f"{normalized}_predictor"],
        }

    def delete_algorithm(self, algorithm_id: str, *, actor_user_id: str, is_admin: bool, confirm_algorithm_id: str) -> dict[str, Any]:
        """删除接口模型注册表和全部版本，保留历史运行与审计记录。"""
        if confirm_algorithm_id.strip() != algorithm_id:
            raise HTTPException(status_code=422, detail="确认模型 ID 不匹配")
        registry = self._get_registry(algorithm_id)
        if not is_admin and registry.get("owner") != actor_user_id:
            raise HTTPException(status_code=403, detail="无权限删除该接口模型")
        runs, _ = AlgorithmRunRepository.list_runs(algorithm_id=algorithm_id, page=1, page_size=1000)
        if any(item.get("status") in {"queued", "running"} for item in runs):
            raise HTTPException(status_code=409, detail="模型存在排队中或运行中的任务，请完成后再删除")
        versions, _ = AlgorithmVersionRepository.list_versions(algorithm_id=algorithm_id, page=1, page_size=1000)
        for version in versions:
            AlgorithmVersionRepository.delete(version["version_id"])
        AlgorithmRegistryRepository.delete(algorithm_id)
        return {"algorithm_id": algorithm_id, "deleted_versions": len(versions), "preserved_runs": len(runs), "registry_deleted": True, "deleted": True}

    def version_health(self, algorithm_id: str, version_id: str) -> dict[str, Any]:
        """返回远程接口版本的非敏感健康摘要。"""
        version = self._get_version(algorithm_id, version_id)
        config = version.interface_config
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "status": version.status,
            "deployment": version.deployment,
            "health": {
                "status": (version.deployment or {}).get("status", "not_tested"),
                "protocol": config.protocol if config else None,
                "endpoint_host": urlparse(config.endpoint_url).hostname if config else None,
            },
        }

    def version_logs(self, algorithm_id: str, version_id: str) -> dict[str, Any]:
        """返回远程接口版本的脱敏生命周期日志。"""
        version = self._get_version(algorithm_id, version_id)
        return {
            "algorithm_id": algorithm_id,
            "version_id": version_id,
            "validation_logs": [],
            "build_logs": [],
            "deployment_logs": [],
            "runtime_logs": version.runtime_logs,
            "deployment": version.deployment,
        }

    def _set_unavailable_status(self, algorithm_id: str, version_id: str, status: str) -> AlgorithmVersion:
        version = self._get_version(algorithm_id, version_id)
        now = utc_now()
        AlgorithmVersionRepository.update_fields(version_id, {"status": status, "updated_at": now})
        registry = self._get_registry(algorithm_id)
        if registry.get("active_version_id") == version_id:
            AlgorithmRegistryRepository.update_fields(
                algorithm_id,
                {
                    "active_version_id": None,
                    "status": status,
                    "deployment_status": status,
                    "updated_at": now,
                },
            )
        return self._get_version(algorithm_id, version_id)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:14]}"

    @staticmethod
    def _version_document(
        *,
        version_id: str,
        algorithm_id: str,
        name: str,
        version: str,
        input_schema: dict,
        output_schema: dict,
        input_assets: list[dict],
        output_assets: list[dict],
        interface_config: RemoteInterfaceConfig,
        sample_input: dict,
        model_proposal: dict | None,
        description: str | None,
        visibility: str,
        created_by: str,
        created_by_name: str | None,
        now,
    ) -> dict[str, Any]:
        """构建远程接口版本文档，仅显式提案会写入参数模板。"""
        contract = {
            "sample_input": sample_input,
            "description": description,
        }
        if model_proposal is not None:
            contract["model_proposal"] = model_proposal
        return {
            "version_id": version_id,
            "package_id": None,
            "source_kind": "remote_interface",
            "algorithm_id": algorithm_id,
            "name": name,
            "version": version,
            "package_sha256": None,
            "image_digest": None,
            "package_digest": None,
            "environment_digest": None,
            "runtime_digest": None,
            "status": "validated",
            "runtime": {"backend": "remote_http", "timeout_seconds": interface_config.timeout_seconds},
            "input_schema": input_schema,
            "output_schema": output_schema,
            "input_assets": input_assets,
            "output_assets": output_assets,
            "resource_assets": [],
            "resource_bindings": [],
            "result_envelope": None,
            "entrypoint": "remote_interface:invoke",
            "loader": None,
            "package_path": "",
            "interface_config": interface_config.model_dump(mode="python"),
            "deployment": {"backend": "remote_http", "status": "validated"},
            "runtime_logs": [],
            "contract": contract,
            "model_proposal": model_proposal,
            "visibility": visibility,
            "developer_attribution": None,
            "mentor_team": None,
            "contributors": [],
            "method_attributions": [],
            "implementation_notes": None,
            "algorithm_summary": None,
            "created_by": created_by,
            "created_by_name": created_by_name or created_by,
            "uploaded_by": created_by,
            "activated_at": None,
            "activation_kind": None,
            "previous_active_version_id": None,
            "rollback_status": None,
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def _registry_document(*, payload: AlgorithmInterfaceCreate, actor_user_id: str, version_id: str, now) -> dict[str, Any]:
        developer = payload.developer or payload.developer_organization
        attribution = None
        if developer:
            attribution = {
                "name": payload.developer or payload.developer_organization,
                "role": "developer",
                "organization": payload.developer_organization,
                "description": "远程接口服务开发者来源。",
                "url": payload.source_url,
                "citation_text": payload.citation,
                "logo_asset": payload.logo_url,
                "logo_alt": payload.developer or payload.developer_organization,
                "visibility": "prominent",
            }
        return {
            "algorithm_id": payload.algorithm_id,
            "name": payload.name,
            "type": payload.type,
            "algorithm_family": payload.algorithm_family,
            "material_scope": payload.material_scope,
            "task_scope": payload.task_scope,
            "input_schema": payload.input_schema.model_dump(mode="python"),
            "output_schema": payload.output_schema.model_dump(mode="python"),
            "input_assets": [item.model_dump(mode="python") for item in payload.input_assets],
            "output_assets": [item.model_dump(mode="python") for item in payload.output_assets],
            "resource_assets": [],
            "result_envelope": None,
            "call_method": payload.interface_config.protocol.upper(),
            "model_proposal": payload.model_proposal,
            "trigger_modes": payload.trigger_modes,
            "runtime_dependency": "remote_interface",
            "version": payload.version,
            "validation_metric": {},
            "owner": actor_user_id,
            "status": "in_development",
            "description": payload.description,
            "active_version_id": None,
            "source": "remote_interface",
            "source_kind": "remote_interface",
            "interface_config": payload.interface_config.model_dump(mode="python"),
            "deployment_status": "testing",
            "integration_kind": "pending",
            "capability_group": "vertical_algorithm",
            "visibility": payload.visibility,
            "mentor_team": payload.mentor_team,
            "developer_contact": payload.developer_contact,
            "contributors": [item.model_dump(mode="python") for item in payload.contributors],
            "developer_attribution": attribution,
            "framework_attributions": [],
            "method_attributions": [item.model_dump(mode="python") for item in payload.method_attributions],
            "implementation_notes": None,
            "algorithm_summary": None,
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def _get_registry(algorithm_id: str) -> dict[str, Any]:
        registry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        if not registry:
            raise HTTPException(status_code=404, detail=f"算法 '{algorithm_id}' 不存在")
        return registry

    @staticmethod
    def _get_version(algorithm_id: str, version_id: str) -> AlgorithmVersion:
        doc = AlgorithmVersionRepository.find_one({"version_id": version_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"算法版本 '{version_id}' 不存在")
        version = AlgorithmVersion(**doc)
        if version.algorithm_id != algorithm_id:
            raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
        return version

    @classmethod
    def _mapped_values(cls, bindings: dict[str, str], inputs: dict) -> dict[str, str]:
        return {remote_key: str(cls._read_path(inputs, field_path)) for remote_key, field_path in bindings.items()}

    @staticmethod
    def _validate_interface_contract(
        input_schema: dict,
        output_schema: dict,
        config: RemoteInterfaceConfig,
        sample_input: dict,
        input_assets: list,
        output_assets: list,
    ) -> None:
        """在保存时校验映射字段，避免把配置错误拖到真实调用阶段。"""
        input_fields = set((input_schema.get("fields") or {}).keys())
        for mapping_name, bindings in (
            ("query_bindings", config.query_bindings),
            ("header_bindings", config.header_bindings),
        ):
            for remote_name, field_path in bindings.items():
                root = str(field_path).split(".", 1)[0]
                if root not in input_fields:
                    raise HTTPException(
                        status_code=422,
                        detail=f"{mapping_name}.{remote_name} 引用了未声明的输入字段: {field_path}",
                    )
        input_asset_keys = {item.key for item in input_assets}
        unknown_bindings = sorted(set(config.file_bindings) - input_asset_keys)
        if unknown_bindings:
            raise HTTPException(status_code=422, detail=f"file_bindings 引用了未声明的输入文件: {', '.join(unknown_bindings)}")
        if config.body_mode == "multipart":
            missing_bindings = sorted(input_asset_keys - set(config.file_bindings))
            if missing_bindings:
                raise HTTPException(status_code=422, detail=f"输入文件缺少远程 part 映射: {', '.join(missing_bindings)}")
        elif input_assets:
            raise HTTPException(status_code=422, detail="声明输入文件时 body_mode 必须是 multipart")
        if config.result_mode == "artifact_manifest" and not output_assets:
            raise HTTPException(status_code=422, detail="文件产物模式至少需要声明一个输出文件")
        if not (output_schema.get("fields") or output_schema.get("required") or output_assets):
            raise HTTPException(status_code=422, detail="至少需要声明一个结构化输出字段或输出文件")
        RemoteInterfaceService._validate_input(sample_input, input_schema)

    @staticmethod
    def _validate_input_files(
        specs: list[AlgorithmAssetSpec],
        input_files: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """校验远程调用上传文件并返回受控文件元数据。"""
        declared = {spec.key: spec for spec in specs}
        unknown = sorted(set(input_files) - set(declared))
        if unknown:
            raise HTTPException(status_code=422, detail=f"未声明的输入文件: {', '.join(unknown)}")
        missing = sorted(spec.key for spec in specs if spec.required and spec.key not in input_files)
        if missing:
            raise HTTPException(status_code=422, detail=f"缺少必填输入文件: {', '.join(missing)}")
        normalized = {}
        for key, item in input_files.items():
            spec = declared[key]
            path = Path(str(item.get("path") or "")).resolve()
            if not path.is_file():
                raise HTTPException(status_code=422, detail=f"输入文件不存在: {key}")
            size = path.stat().st_size
            if spec.max_size_bytes and size > spec.max_size_bytes:
                raise HTTPException(status_code=413, detail=f"输入文件 {key} 超过大小限制")
            filename = str(item.get("filename") or key)
            mime_type = str(item.get("mime_type") or spec.mime_type or "application/octet-stream")
            suffix = path.suffix.lower()
            if spec.extensions and suffix not in {str(value).lower() for value in spec.extensions}:
                raise HTTPException(status_code=422, detail=f"输入文件 {key} 扩展名不受支持")
            if spec.mime_types and mime_type not in spec.mime_types:
                raise HTTPException(status_code=422, detail=f"输入文件 {key} MIME 类型不受支持")
            normalized[key] = {"path": str(path), "filename": filename, "mime_type": mime_type}
        return normalized

    @classmethod
    def _parse_artifact_manifest(
        cls,
        value: object,
        specs: list[AlgorithmAssetSpec],
    ) -> tuple[object, list[dict[str, Any]]]:
        """解析 polyagent_remote_result.v1 产物清单并校验声明。"""
        if not isinstance(value, dict) or value.get("output_summary") is None:
            raise HTTPException(status_code=502, detail="远程接口文件产物响应缺少 output_summary")
        raw_items = value.get("artifacts")
        if not isinstance(raw_items, list):
            raise HTTPException(status_code=502, detail="远程接口文件产物响应缺少 artifacts 列表")
        declared = {spec.key: spec for spec in specs}
        seen: set[str] = set()
        normalized: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise HTTPException(status_code=502, detail="远程接口产物清单项必须是 object")
            key = str(raw.get("key") or "").strip()
            if key not in declared:
                raise HTTPException(status_code=502, detail=f"远程接口返回了未声明的输出文件: {key}")
            if key in seen:
                raise HTTPException(status_code=502, detail=f"远程接口重复返回输出文件: {key}")
            url = str(raw.get("url") or "").strip()
            name = str(raw.get("name") or Path(urlparse(url).path).name or key)
            mime_type = str(raw.get("mime_type") or declared[key].mime_type or "application/octet-stream")
            size_bytes = int(raw.get("size_bytes") or 0)
            if not url or size_bytes < 0:
                raise HTTPException(status_code=502, detail=f"输出文件 {key} 缺少合法 url 或 size_bytes")
            normalized.append({"key": key, "url": url, "name": name, "mime_type": mime_type, "size_bytes": size_bytes, "sha256": raw.get("sha256")})
            seen.add(key)
        missing = sorted(spec.key for spec in specs if spec.required and spec.key not in seen)
        if missing:
            raise HTTPException(status_code=502, detail=f"远程接口缺少必填输出文件: {', '.join(missing)}")
        return cls._sanitize_output(value.get("output_summary")), normalized

    @staticmethod
    def _artifact_previews(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "key": item["key"],
                "name": item["name"],
                "mime_type": item["mime_type"],
                "size_bytes": item["size_bytes"],
                "sha256": item.get("sha256"),
            }
            for item in items
        ]

    @classmethod
    def _download_manifest_artifacts(
        cls,
        config: RemoteInterfaceConfig,
        items: list[dict[str, Any]],
        specs: list[AlgorithmAssetSpec],
        output_dir: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """安全下载远程产物并返回内部 ArtifactSpec 所需元数据。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        allowed_hosts = set(config.artifact_allowed_hosts) or {urlparse(config.endpoint_url).hostname or ""}
        declared = {spec.key: spec for spec in specs}
        total_bytes = 0
        downloaded: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            target_url = urljoin(config.endpoint_url, item["url"])
            parsed = urlparse(target_url)
            if parsed.scheme != "https" and settings.app_env not in {"dev", "development", "local", "test", "testing", "ci"}:
                raise HTTPException(status_code=502, detail="远程产物 URL 必须使用 HTTPS")
            if parsed.username or parsed.password or parsed.hostname not in allowed_hosts:
                raise HTTPException(status_code=502, detail="远程产物 URL 主机不在允许范围内")
            cls._guard_endpoint(target_url)
            spec = declared[item["key"]]
            max_size = spec.max_size_bytes or DEFAULT_REMOTE_ARTIFACT_MAX_BYTES
            target = output_dir / f"{index + 1:02d}_{cls._safe_filename(item['name'])}"
            digest = hashlib.sha256()
            received = 0
            try:
                with httpx.Client(follow_redirects=False, timeout=60.0) as client:
                    with client.stream("GET", target_url) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise HTTPException(status_code=502, detail=f"远程产物下载失败: HTTP {response.status_code}")
                        with target.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                received += len(chunk)
                                total_bytes += len(chunk)
                                if received > max_size or total_bytes > DEFAULT_REMOTE_ARTIFACT_TOTAL_BYTES:
                                    raise HTTPException(status_code=502, detail="远程产物超过平台大小限制")
                                digest.update(chunk)
                                handle.write(chunk)
            except httpx.TimeoutException as exc:
                raise HTTPException(status_code=504, detail="远程产物下载超时") from exc
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail="远程产物下载失败") from exc
            expected_size = item.get("size_bytes")
            expected_sha = str(item.get("sha256") or "").lower()
            actual_sha = digest.hexdigest()
            if expected_size and received != expected_size:
                raise HTTPException(status_code=502, detail=f"输出文件 {item['key']} 大小校验失败")
            if expected_sha and actual_sha != expected_sha:
                raise HTTPException(status_code=502, detail=f"输出文件 {item['key']} 校验和不匹配")
            downloaded.append({"key": item["key"], "path": str(target), "name": item["name"], "mime_type": item["mime_type"], "size_bytes": received, "sha256": actual_sha, "artifact_type": spec.artifact_type or "binary_file"})
        return downloaded, [
            {"key": item["key"], "name": item["name"], "mime_type": item["mime_type"], "size_bytes": item["size_bytes"], "sha256": item.get("sha256")}
            for item in downloaded
        ]

    @staticmethod
    def _safe_filename(value: str) -> str:
        return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value) or "artifact.dat"

    @staticmethod
    def _read_path(value: object, path: str) -> object:
        current = value
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise HTTPException(status_code=422, detail=f"输入字段不存在: {path}")
            current = current[part]
        return current

    @staticmethod
    def _select_output(value: object, selector: str | None) -> object:
        if not selector:
            return value
        try:
            return RemoteInterfaceService._read_path(value, selector)
        except HTTPException as exc:
            raise HTTPException(status_code=502, detail=f"远程接口响应路径不存在: {selector}") from exc

    @staticmethod
    def _validate_input(value: dict, schema: dict) -> None:
        if not isinstance(value, dict):
            raise HTTPException(status_code=422, detail="输入必须是 JSON object")
        for field in schema.get("required") or []:
            if field not in value or value.get(field) is None:
                raise HTTPException(status_code=422, detail=f"缺少必填字段: {field}")
        options = schema.get("field_options") or {}
        for field, allowed in options.items():
            if field in value and allowed and value[field] not in allowed:
                raise HTTPException(status_code=422, detail=f"字段 '{field}' 值不在允许范围内")
        for field, declared_type in (schema.get("fields") or {}).items():
            if field in value and value[field] is not None and not RemoteInterfaceService._matches_type(value[field], declared_type):
                raise HTTPException(status_code=422, detail=f"字段 '{field}' 类型不匹配")

    @staticmethod
    def _validate_output(value: object, schema: dict) -> None:
        if not schema.get("required") and not schema.get("fields"):
            return
        if not isinstance(value, dict):
            raise HTTPException(status_code=502, detail="远程接口输出不是 JSON object")
        for field in schema.get("required") or []:
            if field not in value or value.get(field) is None:
                raise HTTPException(status_code=502, detail=f"远程接口输出缺少字段: {field}")
        for field, declared_type in (schema.get("fields") or {}).items():
            if field in value and value[field] is not None and not RemoteInterfaceService._matches_type(value[field], declared_type):
                raise HTTPException(status_code=502, detail=f"远程接口输出字段类型不匹配: {field}")

    @staticmethod
    def _matches_type(value: object, declared_type: str) -> bool:
        normalized = str(declared_type or "").lower()
        if normalized in {"any", "json", "object", "dict"}:
            return isinstance(value, dict) if normalized in {"object", "dict"} else True
        if normalized in {"list", "array"} or normalized.startswith("list[") or normalized.startswith("array["):
            return isinstance(value, list)
        if normalized in {"number", "float", "double", "decimal"}:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if normalized in {"integer", "int"}:
            return isinstance(value, int) and not isinstance(value, bool)
        if normalized in {"boolean", "bool"}:
            return isinstance(value, bool)
        if normalized in {"string", "str", "text"}:
            return isinstance(value, str)
        return True

    @classmethod
    def _sanitize_output(cls, value: object, *, depth: int = 0) -> object:
        """只保留有限深度和大小的结果，遮蔽可能误传的凭据字段。"""
        if depth > 8:
            return "[TRUNCATED]"
        if isinstance(value, dict):
            sanitized = {}
            for key, item in list(value.items())[:200]:
                key_text = str(key)
                lowered = key_text.lower()
                if any(marker in lowered for marker in ("token", "password", "secret", "authorization", "api_key", "apikey", "credential")):
                    sanitized[key_text] = "[REDACTED]"
                else:
                    sanitized[key_text] = cls._sanitize_output(item, depth=depth + 1)
            return sanitized
        if isinstance(value, list):
            return [cls._sanitize_output(item, depth=depth + 1) for item in value[:200]]
        if isinstance(value, str):
            return value[:4000]
        return value

    @staticmethod
    def _guard_endpoint(endpoint_url: str) -> None:
        parsed = urlparse(endpoint_url)
        hostname = parsed.hostname
        if not hostname:
            raise HTTPException(status_code=422, detail="远程接口主机名缺失")
        if parsed.scheme != "https" and settings.app_env not in {"dev", "development", "local", "test", "testing", "ci"}:
            raise HTTPException(status_code=422, detail="生产环境远程接口必须使用 HTTPS")
        try:
            default_port = 443 if parsed.scheme == "https" else 80
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or default_port, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise HTTPException(status_code=422, detail="远程接口主机解析失败") from exc
        if settings.remote_interface_allow_private_network:
            return
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(status_code=422, detail="远程接口地址属于受限网络")
