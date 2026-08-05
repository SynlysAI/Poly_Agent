"""远程接口型垂类模型的配置、连通性测试和调用适配器。"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmRegistryRepository,
    AlgorithmVersionRepository,
)
from app.schemas.research_engine import (
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


class RemoteInterfaceService:
    """管理远程接口版本并同步执行 HTTP/FastAPI 兼容请求。"""

    def create_interface(self, payload: AlgorithmInterfaceCreate, *, actor_user_id: str) -> AlgorithmInterfaceDetails:
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
            interface_config=payload.interface_config,
            sample_input=payload.sample_input,
            description=payload.description,
            visibility=payload.visibility,
            created_by=actor_user_id,
            now=now,
        )
        self._validate_interface_contract(
            payload.input_schema.model_dump(mode="python"),
            payload.output_schema.model_dump(mode="python"),
            payload.interface_config,
            payload.sample_input,
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
            interface_config=payload.interface_config,
            sample_input=payload.sample_input,
            description=payload.description if payload.description is not None else registry.get("description"),
            visibility=payload.visibility or registry.get("visibility") or "private",
            created_by=actor_user_id,
            now=now,
        )
        self._validate_interface_contract(
            payload.input_schema.model_dump(mode="python"),
            payload.output_schema.model_dump(mode="python"),
            payload.interface_config,
            payload.sample_input,
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
        interface_config = payload.interface_config or version.interface_config
        if interface_config is None:
            raise HTTPException(status_code=409, detail="接口版本缺少接口配置")
        sample_input = requested.get("sample_input", version.contract.get("sample_input", {}))
        description = requested["description"] if "description" in requested else version.contract.get("description")
        visibility = requested.get("visibility", version.visibility)

        self._validate_interface_contract(
            input_schema.model_dump(mode="python"),
            output_schema.model_dump(mode="python"),
            interface_config,
            sample_input or {},
        )
        now = utc_now()
        runtime_logs = [
            *list(version.runtime_logs or [])[-49:],
            {"event": "interface_config_updated", "updated_at": now},
        ]
        AlgorithmVersionRepository.update_fields(
            version_id,
            {
                "input_schema": input_schema.model_dump(mode="python"),
                "output_schema": output_schema.model_dump(mode="python"),
                "interface_config": interface_config.model_dump(mode="python"),
                "contract": {"sample_input": sample_input or {}, "description": description},
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
            output, metadata = self.invoke(version, input_snapshot if input_snapshot is not None else version.contract.get("sample_input", {}))
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

    def invoke(self, version: AlgorithmVersion, input_snapshot: dict) -> tuple[object, dict[str, Any]]:
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
        self._guard_endpoint(config.endpoint_url)
        query = self._mapped_values(config.query_bindings, input_snapshot)
        headers = dict(config.static_headers)
        headers.update(self._mapped_values(config.header_bindings, input_snapshot))
        for header_name, secret_ref in config.secret_refs.items():
            secret_value = os.getenv(secret_ref)
            if not secret_value:
                raise HTTPException(status_code=422, detail=f"接口凭据引用未配置: {secret_ref}")
            headers[header_name] = secret_value
        body = None if config.http_method == "GET" else input_snapshot
        started = time.monotonic()
        try:
            with httpx.Client(follow_redirects=False, timeout=config.timeout_seconds) as client:
                with client.stream(
                    config.http_method,
                    config.endpoint_url,
                    params=query or None,
                    headers=headers or None,
                    json=body,
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
        output = self._select_output(raw_output, config.response_selector)
        self._validate_output(output, version.output_schema.model_dump(mode="python"))
        return self._sanitize_output(output), {
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "protocol": config.protocol,
            "endpoint_host": urlparse(config.endpoint_url).hostname,
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
        interface_config: RemoteInterfaceConfig,
        sample_input: dict,
        description: str | None,
        visibility: str,
        created_by: str,
        now,
    ) -> dict[str, Any]:
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
            "input_assets": [],
            "output_assets": [],
            "resource_assets": [],
            "resource_bindings": [],
            "result_envelope": None,
            "entrypoint": "remote_interface:invoke",
            "loader": None,
            "package_path": "",
            "interface_config": interface_config.model_dump(mode="python"),
            "deployment": {"backend": "remote_http", "status": "validated"},
            "runtime_logs": [],
            "contract": {"sample_input": sample_input, "description": description},
            "visibility": visibility,
            "developer_attribution": None,
            "mentor_team": None,
            "contributors": [],
            "method_attributions": [],
            "implementation_notes": None,
            "algorithm_summary": None,
            "created_by": created_by,
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
            "input_assets": [],
            "output_assets": [],
            "resource_assets": [],
            "result_envelope": None,
            "call_method": payload.interface_config.protocol.upper(),
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
        if not (output_schema.get("fields") or output_schema.get("required")):
            raise HTTPException(status_code=422, detail="输出契约至少需要声明一个字段")
        RemoteInterfaceService._validate_input(sample_input, input_schema)

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
