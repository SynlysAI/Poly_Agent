"""从 ResearchEngine 派生对话算法工具目录并执行策略授权。"""

from __future__ import annotations

import sys
import time
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.time import utc_now
from app.infra.computation_repositories import AuditEventRepository
from app.infra.research_engine_repositories import (
    AgentToolPolicyRepository,
    AlgorithmRegistryRepository,
    AlgorithmRunRepository,
    AlgorithmVersionRepository,
)
from app.schemas.agent_tools import (
    AgentTool,
    AgentToolHealthStatus,
    AgentToolListData,
    AgentToolPolicy,
    AgentToolPolicyUpdate,
    AgentToolRegistryData,
    AgentToolRegistryItem,
    AgentToolSyncData,
)
from app.schemas.research_engine import AlgorithmAssetSpec, AlgorithmIOSchema
from app.services.assistant_tool_contract import (
    build_json_schema,
    safe_function_name,
    schema_digest,
)


UNAVAILABLE_DEPLOYMENT_STATUSES = {
    "unavailable",
    "failed",
    "error",
    "down",
    "decommissioned",
    "frozen",
    "disabled",
}
RECENT_RUN_SAMPLE_SIZE = 20
AGENT_TOOL_CACHE_TTL_SECONDS = 10.0

_agent_tool_cache: dict[str, Any] = {
    "registries": (0.0, []),
    "items": {},
}


def _cache_enabled() -> bool:
    """测试进程内关闭目录缓存，避免测试直接修改仓储后读到旧快照。"""
    return "pytest" not in sys.modules and "unittest" not in sys.modules


class AgentToolService:
    """算法工具目录服务。"""

    @staticmethod
    def _is_vertical_algorithm(document: dict[str, Any]) -> bool:
        return (
            document.get("algorithm_family") == "vertical_prediction"
            or document.get("capability_group") == "vertical_algorithm"
        )

    @staticmethod
    def _registries() -> list[dict[str, Any]]:
        """确保内置 registry 与用户部署条目都已写入后再派生目录。"""
        from app.services.research_engine_service import ResearchEngineService

        ResearchEngineService().seed_default_algorithms()
        items, _ = AlgorithmRegistryRepository.list_algorithms(page=1, page_size=10000)
        return items

    @classmethod
    def _cached_registries(cls) -> list[dict[str, Any]]:
        """返回短 TTL 缓存的 registry 文档，避免每次工具目录查询都重新建索引。"""
        if not _cache_enabled():
            return cls._registries()
        expires_at, items = _agent_tool_cache["registries"]
        if items and time.monotonic() < expires_at:
            return items
        items = cls._registries()
        _agent_tool_cache["registries"] = (time.monotonic() + AGENT_TOOL_CACHE_TTL_SECONDS, items)
        return items

    @classmethod
    def _cached_registry_item(cls, registry: dict[str, Any]) -> AgentToolRegistryItem:
        """按算法 ID 缓存派生后的工具目录条目。"""
        if not _cache_enabled():
            return cls._derive_registry_item(registry)
        algorithm_id = str(registry.get("algorithm_id") or "")
        cache = _agent_tool_cache["items"]
        cached = cache.get(algorithm_id)
        if cached and time.monotonic() < cached[0]:
            return cached[1]
        item = cls._derive_registry_item(registry)
        cache[algorithm_id] = (time.monotonic() + AGENT_TOOL_CACHE_TTL_SECONDS, item)
        return item

    @classmethod
    def _invalidate_derived(cls, algorithm_id: str | None = None) -> None:
        """失效指定或全部工具目录缓存。"""
        if algorithm_id:
            _agent_tool_cache["items"].pop(algorithm_id, None)
            return
        _agent_tool_cache["registries"] = (0.0, [])
        _agent_tool_cache["items"] = {}

    @classmethod
    def warm_cache(cls) -> None:
        """预热工具目录缓存，避免首个 LUI 请求承担完整派生开销。"""
        for registry in cls._cached_registries():
            if cls._is_vertical_algorithm(registry):
                cls._cached_registry_item(registry)

    @staticmethod
    def _actor_context(current_user: dict[str, str] | None) -> tuple[str, str, bool]:
        if not current_user:
            return "demo_user", "admin", True
        return (
            current_user.get("user_id", ""),
            current_user.get("role", "user"),
            current_user.get("role") == "admin",
        )

    @staticmethod
    def _policy(document: dict[str, Any]) -> AgentToolPolicy:
        return AgentToolPolicy.model_validate(document)

    @staticmethod
    def _health(
        registry: dict[str, Any],
        version: dict[str, Any] | None,
    ) -> tuple[AgentToolHealthStatus, str | None, dict[str, Any]]:
        """根据已保存的运行时摘要判断工具是否可以进入目录。"""
        deployment_status = str(registry.get("deployment_status") or "").strip().lower()
        if deployment_status in UNAVAILABLE_DEPLOYMENT_STATUSES:
            return "unavailable", f"部署状态为 {deployment_status}", {"status": deployment_status}
        if version is None:
            return "unavailable", "active 版本记录不存在", {"status": "missing_version"}
        deployment = version.get("deployment") or {}
        runtime_health = (
            deployment.get("health")
            or deployment.get("status")
            or registry.get("runtime_health")
            or "unknown"
        )
        normalized = str(runtime_health).strip().lower()
        if normalized in UNAVAILABLE_DEPLOYMENT_STATUSES:
            return "unavailable", f"运行时健康状态为 {normalized}", {"status": normalized}
        if normalized in {"ready", "healthy", "verified", "ok", "active"}:
            return "healthy", None, {"status": normalized, "backend": deployment.get("backend")}
        return "unknown", None, {"status": normalized, "backend": deployment.get("backend")}

    @staticmethod
    def _recent_success_metrics(algorithm_id: str) -> tuple[float | None, int]:
        """统计算法最近的 terminal run 成功率。

        Args:
            algorithm_id: 算法 ID。

        Returns:
            (成功率, 样本数) 元组；没有 terminal run 时成功率为 None。
        """
        runs, _ = AlgorithmRunRepository.list_runs(
            algorithm_id=algorithm_id,
            page=1,
            page_size=RECENT_RUN_SAMPLE_SIZE,
        )
        terminal_runs = [
            item for item in runs
            if item.get("status") in {"completed", "failed", "cancelled"}
        ]
        if not terminal_runs:
            return None, 0
        success_count = len([item for item in terminal_runs if item.get("status") == "completed"])
        return success_count / len(terminal_runs), len(terminal_runs)

    @classmethod
    def _derive_registry_item(cls, registry: dict[str, Any]) -> AgentToolRegistryItem:
        algorithm_id = str(registry.get("algorithm_id") or "")
        policy_doc, _ = AgentToolPolicyRepository.ensure_default(algorithm_id)
        policy = cls._policy(policy_doc)
        active_version_id = registry.get("active_version_id")
        version = (
            AlgorithmVersionRepository.find_one({"version_id": active_version_id})
            if active_version_id
            else None
        )
        reason: str | None = None
        if not registry.get("status") == "active":
            reason = f"算法状态为 {registry.get('status') or 'unknown'}"
            health_status: AgentToolHealthStatus = "unavailable"
            runtime_health = {"status": str(registry.get("status") or "unknown")}
        elif not active_version_id:
            reason = "未激活 active 版本"
            health_status = "unavailable"
            runtime_health = {"status": "missing_active_version"}
        elif not version:
            reason = "active 版本记录不存在"
            health_status = "unavailable"
            runtime_health = {"status": "missing_version"}
        elif version.get("status") != "active":
            reason = f"active 版本状态为 {version.get('status') or 'unknown'}"
            health_status = "unavailable"
            runtime_health = {"status": str(version.get("status") or "unknown")}
        else:
            health_status, reason, runtime_health = cls._health(registry, version)

        schema_source = version or registry
        owner = registry.get("owner") or (version or {}).get("created_by")
        tool = AgentToolRegistryItem(
            tool_id=f"algorithm:{algorithm_id}",
            algorithm_id=algorithm_id,
            name=str(registry.get("name") or algorithm_id),
            description=registry.get("description"),
            algorithm_family=str(registry.get("algorithm_family") or "vertical_prediction"),
            material_scope=list(registry.get("material_scope") or []),
            tool_type=str(registry.get("type") or "predictor"),
            source=str(registry.get("source") or "builtin"),
            source_kind=registry.get("source_kind") or (version or {}).get("source_kind"),
            visibility=str(registry.get("visibility") or "private"),
            active_version_id=active_version_id,
            version=(version or {}).get("version") or registry.get("version"),
            input_schema=AlgorithmIOSchema.model_validate(schema_source.get("input_schema") or {}),
            output_schema=AlgorithmIOSchema.model_validate(schema_source.get("output_schema") or {}),
            model_proposal=(
                schema_source.get("model_proposal")
                or (schema_source.get("contract") or {}).get("model_proposal")
                or (schema_source.get("contract") or {}).get("sample_input")
            ),
            input_assets=[AlgorithmAssetSpec.model_validate(item) for item in (schema_source.get("input_assets") or [])],
            output_assets=[AlgorithmAssetSpec.model_validate(item) for item in (schema_source.get("output_assets") or [])],
            developer_attribution=registry.get("developer_attribution"),
            framework_attributions=registry.get("framework_attributions") or [],
            method_attributions=registry.get("method_attributions") or [],
            policy=policy,
            requires_confirmation=policy.requires_confirmation,
            phase=("unavailable" if reason else ("disabled" if not policy.enabled else "available")),
            health_status=health_status,
            unavailable_reason=reason,
            owner=owner,
            status=str(registry.get("status") or "unknown"),
            deployment_status=registry.get("deployment_status"),
            runtime_health=runtime_health,
        )
        presentation = {
            "layout": "schema-form",
            "fields": dict(tool.input_schema.ui_hints or {}),
            "assets": [
                {
                    "key": item.key,
                    "label": item.label,
                    "required": item.required,
                    "data_kind": item.data_kind,
                    "mime_types": list(item.mime_types),
                    "extensions": list(item.extensions),
                    "description": item.description,
                }
                for item in tool.input_assets
            ],
        }
        recent_success_rate, recent_run_count = cls._recent_success_metrics(algorithm_id)
        return tool.model_copy(
            update={
                "function_name": safe_function_name(tool.tool_id),
                "input_json_schema": build_json_schema(tool),
                "schema_digest": schema_digest(tool),
                "presentation": presentation,
                "recent_success_rate": recent_success_rate,
                "recent_run_count": recent_run_count,
            }
        )

    @classmethod
    def _can_call(
        cls,
        item: AgentToolRegistryItem,
        *,
        user_id: str,
        role: str,
        is_admin: bool,
    ) -> bool:
        if item.phase != "available" or not item.policy.enabled:
            return False
        if role not in item.policy.allowed_roles:
            return False
        if item.policy.algorithm_id != item.algorithm_id:
            return False
        if item.owner and item.policy.algorithm_id and item.owner != user_id and item.visibility == "private":
            return is_admin
        return True

    @classmethod
    def list_tools(cls, current_user: dict[str, str] | None) -> AgentToolListData:
        """返回当前用户可以调用的已部署垂类算法。"""
        user_id, role, is_admin = cls._actor_context(current_user)
        registries = cls._cached_registries()
        items: list[AgentTool] = []
        for registry in registries:
            if not cls._is_vertical_algorithm(registry):
                continue
            item = cls._cached_registry_item(registry)
            visibility = str(registry.get("visibility") or "private")
            is_owner = bool(item.owner and item.owner == user_id)
            if visibility == "private" and not (is_admin or is_owner):
                continue
            if not cls._can_call(item, user_id=user_id, role=role, is_admin=is_admin):
                continue
            tool_data = item.model_dump()
            for field in ("owner", "status", "deployment_status", "runtime_health"):
                tool_data.pop(field, None)
            items.append(AgentTool.model_validate(tool_data))
        return AgentToolListData(items=items, total=len(items))

    @classmethod
    def resolve_callable(
        cls,
        algorithm_id: str,
        *,
        user_id: str,
        role: str,
        is_admin: bool,
    ) -> AgentTool | None:
        """按当前请求重新解析一个可调用工具，避免使用历史目录绕过授权。"""
        registry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        if not registry or not cls._is_vertical_algorithm(registry):
            return None
        item = cls._cached_registry_item(registry)
        visibility = str(registry.get("visibility") or "private")
        is_owner = bool(item.owner and item.owner == user_id)
        if visibility == "private" and not (is_admin or is_owner):
            return None
        if not cls._can_call(item, user_id=user_id, role=role, is_admin=is_admin):
            return None
        tool_data = item.model_dump()
        for field in ("owner", "status", "deployment_status", "runtime_health"):
            tool_data.pop(field, None)
        return AgentTool.model_validate(tool_data)

    @classmethod
    def list_registry(cls) -> AgentToolRegistryData:
        """返回管理员工具治理目录，包含不可用原因。"""
        registries = cls._cached_registries()
        items = [cls._cached_registry_item(item) for item in registries if cls._is_vertical_algorithm(item)]
        return AgentToolRegistryData(items=items, total=len(items))

    @classmethod
    def update_policy(
        cls,
        algorithm_id: str,
        payload: AgentToolPolicyUpdate,
        *,
        actor_user_id: str,
        request_id: str | None = None,
    ) -> AgentToolRegistryItem:
        registry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
        if not registry:
            raise HTTPException(status_code=404, detail=f"算法 '{algorithm_id}' 不存在")
        if not cls._is_vertical_algorithm(registry):
            raise HTTPException(status_code=409, detail="只有垂类算法可以注册为对话工具")
        cls._invalidate_derived(algorithm_id)
        current_item = cls._cached_registry_item(registry)
        if payload.enabled is True and current_item.phase == "unavailable":
            raise HTTPException(
                status_code=409,
                detail=current_item.unavailable_reason or "算法当前不可作为对话工具启用",
            )
        before, _ = AgentToolPolicyRepository.ensure_default(algorithm_id)
        requested = payload.model_dump(exclude_unset=True)
        fields = {**requested, "algorithm_id": algorithm_id, "updated_by": actor_user_id, "updated_at": utc_now()}
        AgentToolPolicyRepository.update_fields(algorithm_id, fields)
        after = AgentToolPolicyRepository.find_one({"algorithm_id": algorithm_id}) or fields
        AuditEventRepository.append(
            {
                "event_id": f"audit_{uuid4().hex[:12]}",
                "event_type": "agent_tool_policy_updated",
                "actor_user_id": actor_user_id,
                "actor_role": "admin",
                "request_id": request_id,
                "entity_type": "agent_tool_policy",
                "entity_id": algorithm_id,
                "related_ids": {"algorithm_id": algorithm_id},
                "before": before,
                "after": after,
                "metadata": {"source": "poly_agent"},
                "created_at": utc_now(),
            }
        )
        cls._invalidate_derived(algorithm_id)
        return cls._cached_registry_item(registry)

    @classmethod
    def sync(cls) -> AgentToolSyncData:
        """检查目录与策略一致性；目录本身按查询动态派生。"""
        cls._invalidate_derived()
        registries = cls._cached_registries()
        checked = available = unavailable = disabled = policies_created = 0
        for registry in registries:
            if not cls._is_vertical_algorithm(registry):
                continue
            checked += 1
            _, created = AgentToolPolicyRepository.ensure_default(str(registry.get("algorithm_id") or ""))
            policies_created += int(created)
            item = cls._cached_registry_item(registry)
            if item.phase == "available":
                available += 1
            elif item.phase == "disabled":
                disabled += 1
            else:
                unavailable += 1
        cls._invalidate_derived()
        return AgentToolSyncData(
            checked=checked,
            available=available,
            unavailable=unavailable,
            disabled=disabled,
            policies_created=policies_created,
        )


agent_tool_service = AgentToolService()
