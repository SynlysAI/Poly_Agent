"""Managed resources for uploaded algorithm packages."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import AlgorithmManagedResourceRepository
from app.schemas.research_engine import (
    AlgorithmManagedResource,
    AlgorithmManagedResourceCreate,
    AlgorithmManagedResourceListData,
    AlgorithmResourceBinding,
)


class AlgorithmManagedResourceService:
    """Register and resolve large mounted resources for uploaded algorithms."""

    def create_resource(
        self,
        payload: AlgorithmManagedResourceCreate,
        *,
        actor_user_id: str,
    ) -> AlgorithmManagedResource:
        """Register a mounted path resource after validating it is usable."""
        status, message, resolved_path = self.check_path(
            payload.path,
            asset_key=payload.asset_key,
            required_files=payload.required_files,
        )
        if status != "active":
            raise HTTPException(status_code=422, detail=message)
        now = utc_now()
        resource_id = f"ares_{uuid4().hex[:12]}"
        doc = {
            "resource_id": resource_id,
            "algorithm_id": payload.algorithm_id,
            "asset_key": payload.asset_key,
            "name": payload.name,
            "storage_mode": payload.storage_mode,
            "path": str(resolved_path),
            "resource_type": payload.resource_type,
            "required_files": payload.required_files,
            "status": status,
            "status_message": message,
            "description": payload.description,
            "created_by": actor_user_id,
            "created_at": now,
            "updated_at": now,
        }
        AlgorithmManagedResourceRepository.save("resource_id", doc)
        return AlgorithmManagedResource(**doc)

    def get_resource(self, resource_id: str) -> AlgorithmManagedResource:
        """Return one registered resource."""
        doc = AlgorithmManagedResourceRepository.find_one({"resource_id": resource_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"算法资源 '{resource_id}' 不存在")
        return AlgorithmManagedResource(**doc)

    def list_resources(
        self,
        *,
        algorithm_id: str | None = None,
        asset_key: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AlgorithmManagedResourceListData:
        """List registered large resources."""
        items, total = AlgorithmManagedResourceRepository.list_resources(
            algorithm_id=algorithm_id,
            asset_key=asset_key,
            status=status,
            page=page,
            page_size=page_size,
        )
        return AlgorithmManagedResourceListData(
            items=[AlgorithmManagedResource(**item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    def check_resource(self, resource_id: str) -> AlgorithmManagedResource:
        """Refresh path health for a registered resource."""
        resource = self.get_resource(resource_id)
        status, message, resolved_path = self.check_path(
            resource.path,
            asset_key=resource.asset_key,
            required_files=resource.required_files,
        )
        update = {
            "path": str(resolved_path) if resolved_path else resource.path,
            "status": status,
            "status_message": message,
            "updated_at": utc_now(),
        }
        AlgorithmManagedResourceRepository.update_fields(resource_id, update)
        return self.get_resource(resource_id)

    def resolve_resource_context(
        self,
        contract: dict[str, Any],
        *,
        algorithm_id: str | None = None,
        resource_bindings: list[AlgorithmResourceBinding | dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[AlgorithmResourceBinding]]:
        """Resolve contract resource specs into runtime context and version bindings."""
        bindings_by_key: dict[str, str] = {}
        for raw in resource_bindings or []:
            binding = raw if isinstance(raw, AlgorithmResourceBinding) else AlgorithmResourceBinding(**raw)
            bindings_by_key[binding.asset_key] = binding.resource_id

        resolved_resources: dict[str, Any] = {}
        resolved_bindings: list[AlgorithmResourceBinding] = []
        contract_algorithm_id = algorithm_id or str(contract.get("algorithm_id") or "").strip() or None

        for spec in contract.get("resource_assets") or []:
            if not isinstance(spec, dict) or not spec.get("key"):
                continue
            key = str(spec["key"]).strip()
            resolved = dict(spec)
            required_files = [str(item) for item in spec.get("required_files") or []]

            resource = self._resource_for_key(
                algorithm_id=contract_algorithm_id,
                asset_key=key,
                explicit_resource_id=bindings_by_key.get(key),
            )
            if resource is not None:
                self._assert_resource_matches(resource, algorithm_id=contract_algorithm_id, asset_key=key)
                self._assert_resource_active(resource)
                resolved["path"] = resource.path
                resolved["resource_id"] = resource.resource_id
                resolved["storage_mode"] = resource.storage_mode
                resolved["resource_type"] = resource.resource_type or resolved.get("resource_type")
                resolved_resources[key] = resolved
                resolved_bindings.append(
                    AlgorithmResourceBinding(asset_key=key, resource_id=resource.resource_id)
                )
                continue

            env_var = str(spec.get("env_var") or "").strip()
            raw_path = os.getenv(env_var, "").strip() if env_var else ""
            if raw_path:
                status, message, path = self.check_path(raw_path, asset_key=key, required_files=required_files)
                if status != "active":
                    raise ValueError(message)
                resolved["path"] = str(path)
                resolved["storage_mode"] = "env_var"
                resolved_resources[key] = resolved
                continue

            if bool(spec.get("required")) or bool(spec.get("binding_required")) or env_var:
                hint = f" 或环境变量 {env_var}" if env_var else ""
                raise ValueError(
                    f"resource asset '{key}' 缺少平台资源绑定{hint}；"
                    "请在算法资源管理中登记 mounted_path 资源并绑定到该版本"
                )
            resolved_resources[key] = resolved

        return resolved_resources, resolved_bindings

    def check_path(
        self,
        raw_path: str,
        *,
        asset_key: str,
        required_files: list[str] | None = None,
    ) -> tuple[str, str, Path | None]:
        """Validate a mounted path and required relative files."""
        try:
            path = Path(raw_path).expanduser().resolve()
        except OSError as exc:
            return "invalid", f"resource asset '{asset_key}' 路径无效: {raw_path} ({exc})", None

        if not path.exists():
            return "missing", f"resource asset '{asset_key}' 路径不存在: {path}", path
        allowed_roots = self.allowed_resource_roots()
        if not any(root == path or root in path.parents for root in allowed_roots):
            return "invalid", f"resource asset '{asset_key}' 路径不在允许的资源目录内: {path}", path

        for required in required_files or []:
            rel = Path(str(required).strip())
            if not str(rel) or rel.is_absolute() or ".." in rel.parts:
                return "invalid", f"resource asset '{asset_key}' required_files 包含非法路径: {required}", path
            required_path = (path / rel).resolve()
            if path not in required_path.parents and required_path != path:
                return "invalid", f"resource asset '{asset_key}' required_files 路径越界: {required}", path
            if not required_path.exists():
                return "missing", f"resource asset '{asset_key}' 缺少必需文件: {required}", path

        return "active", "资源路径检查通过", path

    @staticmethod
    def allowed_resource_roots() -> list[Path]:
        """Return resolved roots allowed for mounted algorithm resources."""
        roots = [settings.runtime_root / "algorithm-resources"]
        raw_extra_roots = os.getenv("POLYAGENT_ALGORITHM_RESOURCE_ROOTS", "")
        for raw_root in raw_extra_roots.split(os.pathsep):
            if raw_root.strip():
                roots.append(Path(raw_root).expanduser())
        return [root.resolve() for root in roots]

    def _resource_for_key(
        self,
        *,
        algorithm_id: str | None,
        asset_key: str,
        explicit_resource_id: str | None,
    ) -> AlgorithmManagedResource | None:
        if explicit_resource_id:
            return self.get_resource(explicit_resource_id)
        if not algorithm_id:
            return None
        candidates = self.list_resources(
            algorithm_id=algorithm_id,
            asset_key=asset_key,
            status="active",
            page=1,
            page_size=1,
        ).items
        return candidates[0] if candidates else None

    @staticmethod
    def _assert_resource_matches(
        resource: AlgorithmManagedResource,
        *,
        algorithm_id: str | None,
        asset_key: str,
    ) -> None:
        if algorithm_id and resource.algorithm_id != algorithm_id:
            raise ValueError(
                f"resource asset '{asset_key}' 绑定资源 algorithm_id 不匹配: {resource.resource_id}"
            )
        if resource.asset_key != asset_key:
            raise ValueError(f"resource asset '{asset_key}' 绑定资源 asset_key 不匹配: {resource.resource_id}")

    def _assert_resource_active(self, resource: AlgorithmManagedResource) -> None:
        status, message, _ = self.check_path(
            resource.path,
            asset_key=resource.asset_key,
            required_files=resource.required_files,
        )
        if status != "active" or resource.status != "active":
            raise ValueError(
                f"resource asset '{resource.asset_key}' 绑定资源不可用: "
                f"{resource.resource_id} ({message})"
            )
