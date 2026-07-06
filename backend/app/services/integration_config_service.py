"""外部服务集成配置服务。"""

from __future__ import annotations

import socket
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException

from app.infra.computation_repositories import AuditEventRepository
from app.infra.computation_repositories import ServiceIntegrationRepository
from app.infra.computation_repositories import utc_now
from app.schemas.integrations import IntegrationServiceKey
from app.schemas.integrations import IntegrationStatus
from app.schemas.integrations import SENSITIVE_KEY_MARKERS
from app.schemas.integrations import ServiceIntegrationCheckData
from app.schemas.integrations import ServiceIntegrationConfig
from app.schemas.integrations import ServiceIntegrationListData
from app.schemas.integrations import ServiceIntegrationUpsertRequest


SERVICE_DEFAULTS: dict[str, dict[str, str]] = {
    "speclabos": {"display_name": "SpecLabOS", "service_type": "experiment"},
    "atlas": {"display_name": "Atlas optimizer", "service_type": "optimizer"},
    "alchemist-backend": {"display_name": "ALchemist backend", "service_type": "optimizer"},
    "computation-worker": {"display_name": "Computation worker", "service_type": "worker"},
    "artifact-store": {"display_name": "Artifact store", "service_type": "artifact"},
}


class IntegrationConfigService:
    """管理外部服务集成配置摘要。"""

    def list_configs(self) -> ServiceIntegrationListData:
        """查询持久化配置列表，补齐未保存的默认集成项。"""
        persisted = {}
        for item in ServiceIntegrationRepository.list_configs():
            key = item.get("service_key")
            if key not in SERVICE_DEFAULTS:
                # 跳过已从代码中移除的服务（如 AiiDA）
                continue
            persisted[key] = ServiceIntegrationConfig.model_validate(item)
        items = []
        for service_key in SERVICE_DEFAULTS:
            if service_key in persisted:
                items.append(persisted[service_key])
            else:
                items.append(self._default_config(service_key))
        return ServiceIntegrationListData(total=len(items), items=items)

    def get_config(self, service_key: str) -> ServiceIntegrationConfig:
        """查询单个配置，未保存时返回默认摘要。"""
        normalized = self._normalize_service_key(service_key)
        document = ServiceIntegrationRepository.find_one({"service_key": normalized})
        if document:
            return ServiceIntegrationConfig.model_validate(document)
        return self._default_config(normalized)

    def upsert_config(
        self,
        service_key: str,
        payload: ServiceIntegrationUpsertRequest,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ServiceIntegrationConfig:
        """创建或更新集成配置摘要。"""
        normalized = self._normalize_service_key(service_key)
        self._reject_sensitive_config(payload.config_summary)
        self._validate_secret_refs(payload.secret_refs)

        now = utc_now()
        existing = ServiceIntegrationRepository.find_one({"service_key": normalized})
        before = self._public_document(existing) if existing else {}
        document = {
            "service_key": normalized,
            "display_name": payload.display_name,
            "service_type": payload.service_type,
            "enabled": payload.enabled,
            "endpoint": payload.endpoint,
            "config_summary": payload.config_summary,
            "secret_refs": payload.secret_refs,
            "last_checked_at": existing.get("last_checked_at") if existing else None,
            "last_status": existing.get("last_status", "unknown") if existing else "unknown",
            "last_error_summary": existing.get("last_error_summary") if existing else None,
            "updated_by": actor_user_id,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        ServiceIntegrationRepository.save("service_key", document)
        after = self._public_document(document)
        self._audit(
            "integration_config.updated",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_id=normalized,
            before=before,
            after=after,
        )
        return ServiceIntegrationConfig.model_validate(document)

    def check_config(
        self,
        service_key: str,
        *,
        actor_user_id: str,
        request_id: str | None,
    ) -> ServiceIntegrationCheckData:
        """按持久化配置执行一次轻量健康检查并写回摘要。"""
        config = self.get_config(service_key)
        checked_at = utc_now()
        status, error_summary = self._probe_config(config)
        before = config.model_dump(mode="python")
        fields = {
            "last_checked_at": checked_at,
            "last_status": status,
            "last_error_summary": error_summary,
            "updated_by": actor_user_id,
            "updated_at": checked_at,
        }
        updated = ServiceIntegrationRepository.update_fields(config.service_key, fields)
        if not updated:
            document = config.model_dump(mode="python")
            document.update(fields)
            ServiceIntegrationRepository.save("service_key", document)
        after = self.get_config(config.service_key).model_dump(mode="python")
        self._audit(
            "integration_config.checked",
            actor_user_id=actor_user_id,
            request_id=request_id,
            entity_id=config.service_key,
            before=before,
            after=after,
        )
        return ServiceIntegrationCheckData(
            service_key=config.service_key,
            status=status,
            checked_at=checked_at,
            error_summary=error_summary,
        )

    def _default_config(self, service_key: str) -> ServiceIntegrationConfig:
        """构造未持久化配置的只读默认摘要。"""
        normalized = self._normalize_service_key(service_key)
        defaults = SERVICE_DEFAULTS[normalized]
        now = datetime.utcnow()
        return ServiceIntegrationConfig(
            service_key=normalized,  # type: ignore[arg-type]
            display_name=defaults["display_name"],
            service_type=defaults["service_type"],  # type: ignore[arg-type]
            enabled=False,
            endpoint=None,
            config_summary={},
            secret_refs={},
            last_status="not_configured",
            created_at=now,
            updated_at=now,
        )

    def _probe_config(self, config: ServiceIntegrationConfig) -> tuple[IntegrationStatus, str | None]:
        """执行最小健康检查，避免复制上游响应数据。"""
        if not config.enabled:
            return "disabled", None
        if not config.endpoint:
            return "not_configured", "endpoint not configured"
        parsed = urlparse(config.endpoint)
        host = parsed.hostname
        if not host:
            return "failed", "endpoint host missing"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=0.8):
                return "up", None
        except OSError as exc:
            return "down", str(exc)[:300]

    def _normalize_service_key(self, service_key: str) -> IntegrationServiceKey:
        """校验 service key 白名单。"""
        normalized = service_key.strip().lower()
        if normalized not in SERVICE_DEFAULTS:
            raise HTTPException(status_code=404, detail="未知集成服务")
        return normalized  # type: ignore[return-value]

    def _reject_sensitive_config(self, value: Any, *, path: str = "config_summary") -> None:
        """拒绝敏感键名进入配置摘要。"""
        if isinstance(value, dict):
            for key, child in value.items():
                key_lower = str(key).lower()
                if any(marker in key_lower for marker in SENSITIVE_KEY_MARKERS):
                    raise HTTPException(status_code=400, detail=f"{path}.{key} 不能保存敏感字段")
                self._reject_sensitive_config(child, path=f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._reject_sensitive_config(child, path=f"{path}[{index}]")

    def _validate_secret_refs(self, refs: dict[str, str]) -> None:
        """确保 secret_refs 只保存引用名。"""
        for key, ref in refs.items():
            normalized = ref.strip()
            if not normalized:
                raise HTTPException(status_code=400, detail=f"secret_refs.{key} 不能为空")
            if normalized != normalized.upper() or not normalized.replace("_", "").isalnum():
                raise HTTPException(status_code=400, detail=f"secret_refs.{key} 必须是环境变量或密钥引用名")

    def _public_document(self, document: dict[str, Any] | None) -> dict[str, Any]:
        """返回可审计的脱敏文档。"""
        if not document:
            return {}
        public = dict(document)
        public.pop("_id", None)
        return public

    def _audit(
        self,
        event_type: str,
        *,
        actor_user_id: str,
        request_id: str | None,
        entity_id: str,
        before: dict | None = None,
        after: dict | None = None,
    ) -> None:
        """写配置审计事件。"""
        AuditEventRepository.append(
            {
                "event_id": self._new_id("audit"),
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "actor_role": "admin",
                "request_id": request_id,
                "entity_type": "service_integration",
                "entity_id": entity_id,
                "related_ids": {},
                "before": before or {},
                "after": after or {},
                "metadata": {"source": "poly_agent"},
                "created_at": utc_now(),
            }
        )

    def _new_id(self, prefix: str) -> str:
        """生成业务 ID。"""
        return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d')}_{uuid4().hex[:10]}"
