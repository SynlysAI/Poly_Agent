"""LLM model catalog and routing schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


LLMProviderType = Literal["openai_compatible", "ollama", "custom_http"]
LLMProviderStatus = Literal["available", "degraded", "down", "not_configured", "unknown"]
LLMCapability = Literal["chat", "fast", "reasoning", "structured_json", "tool_calling", "long_context", "local"]
LLMRoutePurpose = Literal["qa", "deep", "report"]
LLMCapabilitySource = Literal["configured", "probed", "inferred"]


class LLMModelInfo(BaseModel):
    """A selectable model exposed by an LLM provider."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    capabilities: list[LLMCapability] = Field(default_factory=lambda: ["chat"])
    recommended_for: list[LLMRoutePurpose] = Field(default_factory=list)
    is_default: bool = False
    context_window: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    tool_protocol: str | None = Field(default=None, max_length=80)
    supports_parallel_tool_calls: bool | None = None
    capability_source: LLMCapabilitySource | None = None


class LLMModelConfigInput(BaseModel):
    """Per-model provider configuration entry."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    capabilities: list[LLMCapability] | None = None
    recommended_for: list[LLMRoutePurpose] | None = None
    context_window: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    tool_protocol: str | None = Field(default=None, max_length=80)
    supports_parallel_tool_calls: bool | None = None


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

    provider_id: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=160)
    provider_type: LLMProviderType = "openai_compatible"
    base_url: str | None = Field(default=None, max_length=500)
    api_key_env: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    models: list[str | LLMModelConfigInput] = Field(default_factory=list)
    capabilities: list[LLMCapability] = Field(default_factory=lambda: ["chat"])
    recommended_for: list[LLMRoutePurpose] = Field(default_factory=list)

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
