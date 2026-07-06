"""外部服务集成配置契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import parse_qs
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


IntegrationServiceKey = Literal[
    "speclabos",
    "atlas",
    "alchemist-backend",
    "computation-worker",
    "artifact-store",
]
IntegrationServiceType = Literal["experiment", "provenance", "workflow", "worker", "artifact", "optimizer"]
IntegrationStatus = Literal["unknown", "disabled", "not_configured", "available", "up", "down", "degraded", "failed"]

SENSITIVE_KEY_MARKERS = ("token", "password", "api_key", "secret", "private_key", "credential")


class ServiceIntegrationUpsertRequest(BaseModel):
    """创建或更新外部服务集成配置摘要。"""

    display_name: str = Field(min_length=1, max_length=120)
    service_type: IntegrationServiceType
    enabled: bool = False
    endpoint: str | None = Field(default=None, max_length=500)
    config_summary: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        """规范化展示名称。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("集成名称不能为空")
        return normalized

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        """校验 endpoint，禁止把凭据放在 URL 里。"""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint 必须是 http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("endpoint 不能包含用户名或密码")
        query_keys = {key.lower() for key in parse_qs(parsed.query)}
        if any(any(marker in key for marker in SENSITIVE_KEY_MARKERS) for key in query_keys):
            raise ValueError("endpoint query 不能包含敏感凭据字段")
        return normalized

    @field_validator("config_summary")
    @classmethod
    def validate_config_summary(cls, value: dict[str, Any]) -> dict[str, Any]:
        """拒绝在配置摘要中保存敏感字段。"""
        _reject_sensitive_keys(value, path="config_summary")
        return value

    @field_validator("secret_refs")
    @classmethod
    def validate_secret_refs(cls, value: dict[str, str]) -> dict[str, str]:
        """secret_refs 只保存引用名，不保存明文密钥。"""
        for key, ref in value.items():
            normalized = ref.strip()
            if not normalized:
                raise ValueError(f"secret_refs.{key} 不能为空")
            if normalized != normalized.upper() or not normalized.replace("_", "").isalnum():
                raise ValueError(f"secret_refs.{key} 必须是环境变量或密钥引用名")
            value[key] = normalized
        return value


class ServiceIntegrationConfig(BaseModel):
    """外部服务集成配置摘要。"""

    service_key: IntegrationServiceKey
    display_name: str
    service_type: IntegrationServiceType
    enabled: bool
    endpoint: str | None = None
    config_summary: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    last_checked_at: datetime | None = None
    last_status: IntegrationStatus = "unknown"
    last_error_summary: str | None = None
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ServiceIntegrationListData(BaseModel):
    """外部服务集成配置列表响应。"""

    total: int
    items: list[ServiceIntegrationConfig]


class ServiceIntegrationCheckData(BaseModel):
    """外部服务集成健康检查响应。"""

    service_key: IntegrationServiceKey
    status: IntegrationStatus
    checked_at: datetime
    error_summary: str | None = None


def _reject_sensitive_keys(value: Any, *, path: str) -> None:
    """递归拒绝敏感键名，避免明文凭据进入摘要或审计。"""
    if isinstance(value, dict):
        for key, child in value.items():
            key_lower = str(key).lower()
            if any(marker in key_lower for marker in SENSITIVE_KEY_MARKERS):
                raise ValueError(f"{path}.{key} 不能保存敏感字段")
            _reject_sensitive_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_keys(child, path=f"{path}[{index}]")
