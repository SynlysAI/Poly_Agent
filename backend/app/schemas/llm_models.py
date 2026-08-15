"""LLM model catalog and routing schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


LLMProviderType = Literal["openai_compatible", "ollama", "custom_http"]
LLMProviderStatus = Literal["available", "degraded", "down", "not_configured", "unknown"]
LLMCapability = Literal["chat", "fast", "reasoning", "structured_json", "tool_calling", "long_context", "local"]
LLMRoutePurpose = Literal["qa", "deep", "report"]
LLMCapabilitySource = Literal["configured", "probed", "inferred"]


class LLMModelInfo(BaseModel):
    """A selectable model exposed by an LLM provider."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200, description="模型 ID，用于请求 provider 时的 model 参数")
    display_name: str = Field(min_length=1, max_length=200, description="前端展示名称")
    capabilities: list[LLMCapability] = Field(
        default_factory=lambda: ["chat"],
        description="模型能力集合，至少包含 chat",
    )
    recommended_for: list[LLMRoutePurpose] = Field(
        default_factory=list,
        description="推荐用途路由（qa / deep / report）",
    )
    is_default: bool = Field(default=False, description="是否为该 provider 的默认模型")
    context_window: int | None = Field(default=None, ge=1, description="上下文窗口 token 上限")
    max_output_tokens: int | None = Field(default=None, ge=1, description="单次输出 token 上限")
    tool_protocol: str | None = Field(default=None, max_length=80, description="工具调用协议标识")
    supports_parallel_tool_calls: bool | None = Field(default=None, description="是否支持并行工具调用")
    capability_source: LLMCapabilitySource | None = Field(
        default=None,
        description="能力来源：configured / probed / inferred",
    )


class LLMModelConfigInput(BaseModel):
    """Per-model provider configuration entry."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200, description="模型 ID，用于请求 provider 时的 model 参数")
    display_name: str | None = Field(default=None, min_length=1, max_length=200, description="前端展示名称")
    capabilities: list[LLMCapability] | None = Field(default=None, description="模型能力集合")
    recommended_for: list[LLMRoutePurpose] | None = Field(default=None, description="推荐用途路由")
    context_window: int | None = Field(default=None, ge=1, description="上下文窗口 token 上限")
    max_output_tokens: int | None = Field(default=None, ge=1, description="单次输出 token 上限")
    tool_protocol: str | None = Field(default=None, max_length=80, description="工具调用协议标识")
    supports_parallel_tool_calls: bool | None = Field(default=None, description="是否支持并行工具调用")


class LLMProviderInfo(BaseModel):
    """Sanitized provider metadata for frontend model selection."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    provider_type: LLMProviderType
    base_url_configured: bool = False
    base_url_label: str | None = None
    api_key_configured: bool = False
    api_key_ref: str | None = None
    status: LLMProviderStatus = "unknown"
    models: list[LLMModelInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: str | None = None


class LLMModelCatalogData(BaseModel):
    """LLM provider catalog response."""

    providers: list[LLMProviderInfo] = Field(default_factory=list)
    routing: dict[LLMRoutePurpose, dict[str, str | bool | None]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class LLMRouteSelection(BaseModel):
    """Selected provider/model for a route purpose."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=200)


class LLMRoutingData(BaseModel):
    """Routing defaults for assistant/report model usage."""

    qa: LLMRouteSelection | None = None
    deep: LLMRouteSelection | None = None
    report: LLMRouteSelection | None = None


class LLMRoutingUpdateRequest(BaseModel):
    """Update routing defaults."""

    model_config = ConfigDict(extra="forbid")

    qa: LLMRouteSelection | None = None
    deep: LLMRouteSelection | None = None
    report: LLMRouteSelection | None = None


class LLMProviderConfigInput(BaseModel):
    """Provider config loaded from env JSON."""

    model_config = ConfigDict(extra="allow")

    provider_id: str = Field(min_length=1, max_length=120, description="唯一 provider ID")
    display_name: str | None = Field(default=None, max_length=160, description="前端展示名称")
    provider_type: LLMProviderType = Field(
        default="openai_compatible",
        description="provider 协议类型：openai_compatible / ollama / custom_http",
    )
    base_url: str | None = Field(default=None, max_length=500, description="OpenAI 兼容 API Base URL")
    api_key_env: str | None = Field(default=None, max_length=120, description="API Key 环境变量名，必须为大写标识")
    model: str | None = Field(default=None, max_length=200, description="兼容旧配置的单一模型 ID")
    models: list[str | LLMModelConfigInput] = Field(
        default_factory=list,
        description="模型 ID 字符串或 per-model 对象配置",
    )
    capabilities: list[LLMCapability] = Field(
        default_factory=lambda: ["chat"],
        description="provider 级能力集合；未单独配置的模型继承该集合",
    )
    recommended_for: list[LLMRoutePurpose] = Field(
        default_factory=list,
        description="provider 级推荐用途路由",
    )

    @field_validator("models", mode="before")
    @classmethod
    def normalize_models(cls, value: list[str | dict[str, object]] | None) -> list[str | dict[str, object]]:
        """Normalize legacy string model entries to per-model config objects.

        Args:
            value: Raw models list containing model id strings or config objects.

        Returns:
            Normalized list where each entry is an object config.
        """
        if value is None:
            return []
        normalized: list[str | dict[str, object]] = []
        for item in value:
            if isinstance(item, str):
                normalized.append({"model_id": item})
            else:
                normalized.append(item)
        return normalized

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if normalized != normalized.upper() or not normalized.replace("_", "").isalnum():
            raise ValueError("api_key_env must be an uppercase env var reference")
        return normalized


class LLMConfigFieldDoc(BaseModel):
    """面向 Admin 配置页的单字段文档元数据。"""

    field_name: str
    description: str
    type: str
    default_value: Any | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    error_path: str


class LLMConfigSchemaData(BaseModel):
    """从 Pydantic schema 生成的 LLM provider 配置字段目录。"""

    schema_version: int = 1
    generated_from: str = "backend.app.schemas.llm_models.LLMProviderConfigInput"
    provider_fields: list[LLMConfigFieldDoc] = Field(default_factory=list)
    per_model_fields: list[LLMConfigFieldDoc] = Field(default_factory=list)
