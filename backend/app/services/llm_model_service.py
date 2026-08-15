"""LLM provider catalog, routing, and execution service."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from openai import OpenAI

from app.core.config import settings
from app.core.llm_context import record_message_metadata, reset_message_metadata
from app.infra.llm_repositories import LLMRoutingRepository
from app.schemas.llm_models import LLMModelCatalogData
from app.schemas.llm_models import LLMModelConfigInput
from app.schemas.llm_models import LLMModelInfo
from app.schemas.llm_models import LLMProviderConfigInput
from app.schemas.llm_models import LLMProviderInfo
from app.schemas.llm_models import LLMRoutingData
from app.schemas.llm_models import LLMRoutingUpdateRequest
from app.schemas.llm_models import LLMRoutePurpose
from app.schemas.llm_models import LLMRouteSelection


ROUTING_CONFIG_ID = "global"
CAPABILITY_ORDER = ["chat", "fast", "reasoning", "long_context", "structured_json", "tool_calling", "local"]


class LLMModelService:
    """Build sanitized LLM model catalogs and execute routed completions."""

    def get_catalog(self, *, probe: bool = False) -> LLMModelCatalogData:
        providers = self._build_providers()
        warnings: list[str] = []
        if probe:
            providers = [self._probe_provider(provider, warnings) for provider in providers]
        routing = self.get_routing(providers=providers)
        routing_dict = self._routing_to_catalog_dict(routing, providers)
        return LLMModelCatalogData(providers=providers, routing=routing_dict, warnings=warnings)

    def get_routing(self, *, providers: list[LLMProviderInfo] | None = None) -> LLMRoutingData:
        providers = providers or self._build_providers()
        persisted = LLMRoutingRepository.find_one({"config_id": ROUTING_CONFIG_ID}) or {}
        if persisted.get("routing"):
            return LLMRoutingData.model_validate(persisted["routing"])
        return self._default_routing(providers)

    def update_routing(self, payload: LLMRoutingUpdateRequest, *, actor_user_id: str = "system") -> LLMRoutingData:
        providers = self._build_providers()
        routing = self._merge_routing(self.get_routing(providers=providers), payload)
        self._validate_routing(routing, providers)
        now = datetime.now(timezone.utc)
        LLMRoutingRepository.save(
            "config_id",
            {
                "config_id": ROUTING_CONFIG_ID,
                "routing": routing.model_dump(mode="python"),
                "updated_by": actor_user_id,
                "updated_at": now,
            },
        )
        return routing

    def resolve_route(
        self,
        *,
        purpose: LLMRoutePurpose,
        requested_model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        providers = self._build_providers()
        requested_provider_id = str(
            (requested_model or {}).get("providerId") or (requested_model or {}).get("provider_id") or ""
        ).strip()
        requested_model_id = str(
            (requested_model or {}).get("modelId") or (requested_model or {}).get("model_id") or ""
        ).strip()
        if requested_model:
            if requested_provider_id and requested_model_id:
                provider = self._provider_by_id(providers, requested_provider_id)
                model = self._model_by_id(provider, requested_model_id)
                return self._route_payload(
                    provider,
                    model,
                    purpose=purpose,
                    route_reason="user_selected",
                    requested_provider_id=requested_provider_id,
                    requested_model_id=requested_model_id,
                )

        routing = self.get_routing(providers=providers)
        selection = getattr(routing, purpose, None)
        route_reason = "purpose_default"
        if not selection:
            default_routing = self._default_routing(providers)
            selection = getattr(default_routing, purpose, None)
            route_reason = self._default_selection_reason(providers, selection, purpose)
        if not selection:
            raise HTTPException(status_code=503, detail="LLM 模型路由未配置")
        provider = self._provider_by_id(providers, selection.provider_id)
        model = self._model_by_id(provider, selection.model_id)
        return self._route_payload(
            provider,
            model,
            purpose=purpose,
            route_reason=route_reason,
            requested_provider_id=requested_provider_id or None,
            requested_model_id=requested_model_id or None,
        )

    def resolve_tool_capable_route(
        self,
        *,
        purpose: LLMRoutePurpose,
        requested_model: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """优先返回原路由；若其缺少工具能力，则改选可调用工具的模型。

        Args:
            purpose: 当前助手用途（qa / deep / report）。
            requested_model: 用户显式选择的 provider/model。

        Returns:
            原路由或带 `tool_capability_override` reason 的新路由。
        """
        original = self.resolve_route(purpose=purpose, requested_model=requested_model)
        if "tool_calling" in (original.get("capabilities") or []):
            return original

        providers = self._build_providers()
        candidates: list[tuple[LLMProviderInfo, LLMModelInfo]] = []
        for provider in providers:
            for model in provider.models:
                if "tool_calling" in model.capabilities:
                    candidates.append((provider, model))
        if not candidates:
            return original

        provider, model = min(
            candidates,
            key=lambda item: (
                purpose not in (item[1].recommended_for or []),
                item[1].capability_source != "configured",
                item[0].provider_id,
                item[1].model_id,
            ),
        )
        return self._route_payload(
            provider,
            model,
            purpose=purpose,
            route_reason="tool_capability_override",
            requested_provider_id=original.get("requested_provider_id"),
            requested_model_id=original.get("requested_model_id"),
        )

    def complete_text(
        self,
        *,
        messages: list[dict[str, Any]],
        purpose: LLMRoutePurpose = "qa",
        provider_id: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> str:
        route = self._resolve_chat_route(purpose=purpose, provider_id=provider_id, model=model)
        client = self._chat_client(route)
        response = client.chat.completions.create(
            model=route["model_id"],
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def complete_message(
        self,
        *,
        messages: list[dict[str, Any]],
        purpose: LLMRoutePurpose = "qa",
        provider_id: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """返回完整的 chat completion message，保留 tool_calls 等结构化字段。"""
        route = self._resolve_chat_route(purpose=purpose, provider_id=provider_id, model=model)
        client = self._chat_client(route)
        reset_message_metadata()
        response = client.chat.completions.create(
            model=route["model_id"],
            messages=messages,
            **kwargs,
        )
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        record_message_metadata(
            {
                "finish_reason": choice.finish_reason,
                "usage": usage.model_dump(mode="python") if hasattr(usage, "model_dump") else None,
            }
        )
        return choice.message

    def stream_text(
        self,
        *,
        messages: list[dict[str, Any]],
        purpose: LLMRoutePurpose = "qa",
        provider_id: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> Iterator[str]:
        route = self._resolve_chat_route(purpose=purpose, provider_id=provider_id, model=model)
        client = self._chat_client(route)
        response = client.chat.completions.create(
            model=route["model_id"],
            messages=messages,
            stream=True,
            **kwargs,
        )
        for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                from app.core.llm_client import record_stream_usage
                record_stream_usage({
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                })
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    def _resolve_chat_route(
        self,
        *,
        purpose: LLMRoutePurpose,
        provider_id: str | None,
        model: str | None,
    ) -> dict[str, Any]:
        return self.resolve_route(
            purpose=purpose,
            requested_model={"provider_id": provider_id, "model_id": model} if provider_id and model else None,
        )

    def _chat_client(self, route: dict[str, Any]) -> OpenAI:
        provider_config = route["provider_config"]
        provider_type = route["provider_type"]
        if provider_type == "ollama":
            base_url = str(provider_config.get("base_url") or settings.report_ollama_base_url).rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"
            api_key = "ollama"
        else:
            base_url = provider_config.get("base_url") or settings.llm_base_url or None
            api_key = self._provider_api_key(provider_config)
        return OpenAI(api_key=api_key or "EMPTY", base_url=base_url)

    def _build_providers(self) -> list[LLMProviderInfo]:
        providers: list[LLMProviderInfo] = [
            self._provider_from_config(config.model_dump(mode="python"))
            for config in self._configured_provider_configs()
        ]

        if not providers and (settings.llm_model or settings.llm_base_url):
            providers.append(self._legacy_default_provider())

        if settings.report_ollama_base_url or settings.report_ollama_model:
            models = [settings.report_ollama_model] if settings.report_ollama_model else []
            providers.append(
                self._provider_from_config(
                    {
                        "provider_id": "local_ollama",
                        "display_name": "Local Ollama",
                        "provider_type": "ollama",
                        "base_url": settings.report_ollama_base_url,
                        "api_key_configured": False,
                        "api_key_ref": None,
                        "models": models,
                        "capabilities": ["chat", "local"],
                        "recommended_for": [],
                    }
                )
            )

        return self._dedupe_providers(providers)

    def _configured_provider_configs(self) -> list[LLMProviderConfigInput]:
        """加载文件和环境变量中的 LLM provider 定义。

        Returns:
            按优先级排序的 provider 配置列表，文件配置优先于 legacy env JSON。
        """
        configs = self._provider_configs_from_file()
        configs.extend(self._provider_configs_from_env_json())
        return self._dedupe_provider_configs(configs)

    def _provider_configs_from_file(self) -> list[LLMProviderConfigInput]:
        """从 providers.json 加载 provider 定义。

        Returns:
            文件中的 provider 配置列表；文件不存在或为空时返回空列表。
        """
        raw_path = str(getattr(settings, "llm_provider_configs_file", "") or "").strip()
        if not raw_path:
            return []
        path = Path(raw_path)
        if not path.is_absolute():
            path = settings.project_root / path
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            return []
        if not raw:
            return []
        payload = self._parse_provider_config_payload(raw, source=f"LLM_PROVIDER_CONFIGS_FILE({path})")
        return payload

    def _provider_configs_from_env_json(self) -> list[LLMProviderConfigInput]:
        """从 legacy 环境变量 JSON 加载 provider 定义。

        Returns:
            环境变量中的 provider 配置列表；未配置时返回空列表。
        """
        raw = str(getattr(settings, "llm_provider_configs_json", "") or "").strip()
        if not raw:
            return []
        return self._parse_provider_config_payload(raw, source="LLM_PROVIDER_CONFIGS_JSON")

    def _parse_provider_config_payload(
        self,
        raw: str,
        *,
        source: str,
    ) -> list[LLMProviderConfigInput]:
        """解析 provider 配置 JSON。

        Args:
            raw: JSON 文本。
            source: 配置来源标识，用于错误提示。

        Returns:
            解析后的 provider 配置列表。
        """
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"{source} 格式错误: {exc.msg}") from exc
        if not isinstance(payload, list):
            raise HTTPException(status_code=500, detail=f"{source} 必须是数组")
        return [LLMProviderConfigInput.model_validate(item) for item in payload if isinstance(item, dict)]

    def _dedupe_provider_configs(self, configs: list[LLMProviderConfigInput]) -> list[LLMProviderConfigInput]:
        """按 provider_id 去重 provider 配置，保留前面的定义。

        Args:
            configs: 待去重的 provider 配置列表。

        Returns:
            去重后的 provider 配置列表。
        """
        deduped: dict[str, LLMProviderConfigInput] = {}
        for config in configs:
            if config.provider_id not in deduped:
                deduped[config.provider_id] = config
        return list(deduped.values())

    def _legacy_default_provider(self) -> LLMProviderInfo:
        """构建 legacy 单一默认 provider。"""
        default_model = settings.llm_default_model or settings.llm_model
        return self._provider_from_config(
            {
                "provider_id": settings.llm_default_provider or "default_openai",
                "display_name": "Default chat model",
                "provider_type": "openai_compatible",
                "base_url": settings.llm_base_url,
                "api_key_configured": bool(settings.llm_api_key),
                "api_key_ref": "LLM_API_KEY" if settings.llm_api_key else None,
                "models": [default_model] if default_model else [],
                "capabilities": ["chat", "structured_json"],
                "recommended_for": ["qa", "deep"],
            }
        )

    def _provider_from_config(self, config: dict[str, Any]) -> LLMProviderInfo:
        provider_id = str(config.get("provider_id") or "").strip()
        provider_type = str(config.get("provider_type") or "openai_compatible").strip()
        capabilities = list(dict.fromkeys(config.get("capabilities") or ["chat"]))
        recommended_for = list(dict.fromkeys(config.get("recommended_for") or []))
        models = [
            self._model_info_from_config(
                model_config,
                provider_capabilities=capabilities,
                provider_recommended_for=recommended_for,
            )
            for model_config in self._model_configs_from_config(config)
        ]
        api_key_env = config.get("api_key_env")
        api_key_configured = bool(config.get("api_key_configured"))
        if api_key_env:
            api_key_configured = bool(os.getenv(str(api_key_env)))
        return LLMProviderInfo(
            provider_id=provider_id,
            display_name=str(config.get("display_name") or provider_id),
            provider_type=provider_type,  # type: ignore[arg-type]
            base_url_configured=bool(config.get("base_url")),
            base_url_label=self._safe_base_url_label(str(config.get("base_url") or "")),
            api_key_configured=api_key_configured,
            api_key_ref=str(api_key_env or config.get("api_key_ref") or "") or None,
            status="unknown" if models else "not_configured",
            models=models,
        )

    def _model_configs_from_config(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize provider model entries to per-model config objects.

        Args:
            config: Provider config whose models may be strings or objects.

        Returns:
            Deduplicated per-model config list preserving input order.
        """
        values: list[dict[str, Any]] = []
        for item in config.get("models") or []:
            if isinstance(item, str):
                model_id = item.strip()
                if model_id:
                    values.append({"model_id": model_id})
            elif isinstance(item, dict):
                model_id = str(item.get("model_id") or "").strip()
                if model_id:
                    values.append({**item, "model_id": model_id})
            elif isinstance(item, LLMModelConfigInput):
                values.append(item.model_dump(mode="python"))
        model = str(config.get("model") or "").strip()
        if model:
            values.insert(0, {"model_id": model})
        deduped: dict[str, dict[str, Any]] = {}
        for item in values:
            deduped.setdefault(item["model_id"], item)
        return list(deduped.values())

    def _model_info_from_config(
        self,
        model_config: dict[str, Any],
        *,
        provider_capabilities: list[str],
        provider_recommended_for: list[str],
    ) -> LLMModelInfo:
        """Build sanitized model metadata from per-model config.

        Args:
            model_config: Normalized per-model config.
            provider_capabilities: Provider-level capability fallback.
            provider_recommended_for: Provider-level purpose fallback.

        Returns:
            Catalog-facing model info with configured capability source.
        """
        model_id = str(model_config["model_id"])
        configured = model_config.get("capabilities")
        capabilities = self._sorted_capabilities(
            list(configured) if configured else self._capabilities_for_model(model_id, provider_capabilities)
        )
        return LLMModelInfo(
            model_id=model_id,
            display_name=str(model_config.get("display_name") or model_id),
            capabilities=capabilities,  # type: ignore[arg-type]
            recommended_for=list(
                dict.fromkeys(model_config.get("recommended_for") or provider_recommended_for)
            ),  # type: ignore[arg-type]
            context_window=self._positive_int_or_none(model_config.get("context_window")),
            max_output_tokens=self._positive_int_or_none(model_config.get("max_output_tokens")),
            tool_protocol=str(model_config.get("tool_protocol") or "").strip() or None,
            supports_parallel_tool_calls=model_config.get("supports_parallel_tool_calls"),
            capability_source="configured",
        )

    def _capabilities_for_model(self, model_id: str, configured: list[str]) -> list[str]:
        capabilities = [item for item in configured if item]
        normalized = model_id.lower()
        if any(token in normalized for token in ("flash", "turbo", "mini", "mtp")):
            capabilities.append("fast")
        if any(token in normalized for token in ("deepseek", "reasoner", "qwen3", "qwq", "o1", "o3")):
            capabilities.append("reasoning")
        if any(token in normalized for token in ("long", "128k", "qwen3.6")):
            capabilities.append("long_context")

        return self._sorted_capabilities(capabilities)

    @staticmethod
    def _sorted_capabilities(capabilities: list[str]) -> list[str]:
        """Sort and deduplicate capability labels by the catalog order."""
        return sorted(
            dict.fromkeys(capabilities),
            key=lambda item: CAPABILITY_ORDER.index(item) if item in CAPABILITY_ORDER else len(CAPABILITY_ORDER),
        )

    @staticmethod
    def _positive_int_or_none(value: Any) -> int | None:
        """Convert a positive integer config value, returning None when invalid."""
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _dedupe_providers(self, providers: list[LLMProviderInfo]) -> list[LLMProviderInfo]:
        deduped: dict[str, LLMProviderInfo] = {}
        for provider in providers:
            if provider.provider_id not in deduped:
                deduped[provider.provider_id] = provider
        return list(deduped.values())

    def _probe_provider(self, provider: LLMProviderInfo, warnings: list[str]) -> LLMProviderInfo:
        try:
            if provider.provider_type == "ollama":
                return self._probe_ollama_provider(provider)
            return self._probe_openai_compatible_provider(provider)
        except Exception as exc:
            data = provider.model_dump(mode="python")
            data["status"] = "down"
            data["warnings"] = [*provider.warnings, str(exc)[:300]]
            warnings.append(f"{provider.provider_id}: {type(exc).__name__}")
            return LLMProviderInfo.model_validate(data)

    def _probe_openai_compatible_provider(self, provider: LLMProviderInfo) -> LLMProviderInfo:
        config = self._provider_runtime_config(provider.provider_id)
        base_url = str(config.get("base_url") or "").rstrip("/")
        if not base_url:
            data = provider.model_dump(mode="python")
            data["status"] = "not_configured"
            return LLMProviderInfo.model_validate(data)
        headers = {}
        api_key = self._provider_api_key(config)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = httpx.get(f"{base_url}/models", headers=headers, timeout=8)
        response.raise_for_status()
        payload = response.json()
        remote_models = [
            str(item.get("id")).strip()
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
        return self._provider_with_models(provider, remote_models, status="available")

    def _probe_ollama_provider(self, provider: LLMProviderInfo) -> LLMProviderInfo:
        config = self._provider_runtime_config(provider.provider_id)
        base_url = str(config.get("base_url") or settings.report_ollama_base_url).rstrip("/")
        response = httpx.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        payload = response.json()
        remote_models = [
            str(item.get("name") or item.get("model")).strip()
            for item in payload.get("models", [])
            if isinstance(item, dict) and (item.get("name") or item.get("model"))
        ]
        return self._provider_with_models(provider, remote_models, status="available")

    def _provider_with_models(self, provider: LLMProviderInfo, model_ids: list[str], *, status: str) -> LLMProviderInfo:
        known = {model.model_id: model for model in provider.models}
        models = [
            known.get(model_id)
            or LLMModelInfo(
                model_id=model_id,
                display_name=model_id,
                capabilities=self._capabilities_for_model(model_id, ["chat"]),
                recommended_for=[],
                capability_source="inferred",
            )
            for model_id in model_ids or list(known)
        ]
        data = provider.model_dump(mode="python")
        data["status"] = status
        data["models"] = [model.model_dump(mode="python") for model in models]
        data["checked_at"] = datetime.now(timezone.utc).isoformat()
        return LLMProviderInfo.model_validate(data)

    def _default_routing(self, providers: list[LLMProviderInfo]) -> LLMRoutingData:
        qa = self._selection_from_env_or_first(
            providers,
            provider_id=settings.llm_default_provider or "default_openai",
            model_id=settings.llm_default_model or settings.llm_model,
            capability="chat",
            preferred_for="qa",
        )
        deep = self._selection_from_env_or_first(
            providers,
            provider_id=settings.llm_reasoning_provider,
            model_id=settings.llm_reasoning_model,
            capability="reasoning",
            preferred_for="deep",
        )
        report = self._selection_from_env_or_first(
            providers,
            provider_id=settings.report_llm_provider if settings.report_llm_provider != "openai_compatible" else (settings.llm_default_provider or "default_openai"),
            model_id=settings.report_llm_model or settings.llm_model,
            capability="structured_json",
            preferred_for="report",
        )
        return LLMRoutingData(qa=qa, deep=deep or qa, report=report or qa)

    def _selection_from_env_or_first(
        self,
        providers: list[LLMProviderInfo],
        *,
        provider_id: str,
        model_id: str,
        capability: str,
        preferred_for: str | None = None,
    ) -> LLMRouteSelection | None:
        if provider_id and model_id:
            for provider in providers:
                if provider.provider_id == provider_id and any(model.model_id == model_id for model in provider.models):
                    return LLMRouteSelection(provider_id=provider_id, model_id=model_id)
        if preferred_for:
            for provider in providers:
                for model in provider.models:
                    if preferred_for in model.recommended_for and capability in model.capabilities:
                        return LLMRouteSelection(provider_id=provider.provider_id, model_id=model.model_id)
        for provider in providers:
            for model in provider.models:
                if capability in model.capabilities:
                    return LLMRouteSelection(provider_id=provider.provider_id, model_id=model.model_id)
        for provider in providers:
            if provider.models:
                return LLMRouteSelection(provider_id=provider.provider_id, model_id=provider.models[0].model_id)
        return None

    def _default_selection_reason(
        self,
        providers: list[LLMProviderInfo],
        selection: LLMRouteSelection | None,
        purpose: LLMRoutePurpose,
    ) -> str:
        """Explain why a default routing selection was chosen.

        Args:
            providers: Current sanitized provider catalog.
            selection: Default route selection to classify.
            purpose: Route purpose.

        Returns:
            ``purpose_default`` for env/recommended/capability matches, else ``fallback``.
        """
        if not selection:
            return "fallback"
        env_provider_id, env_model_id = self._purpose_env_selection(purpose)
        if env_provider_id and env_model_id and selection.provider_id == env_provider_id and selection.model_id == env_model_id:
            return "purpose_default"
        try:
            provider = self._provider_by_id(providers, selection.provider_id)
            model = self._model_by_id(provider, selection.model_id)
        except HTTPException:
            return "fallback"
        if purpose in model.recommended_for:
            return "purpose_default"
        required_capability = {"qa": "chat", "deep": "reasoning", "report": "structured_json"}[purpose]
        return "purpose_default" if required_capability in model.capabilities else "fallback"

    @staticmethod
    def _purpose_env_selection(purpose: LLMRoutePurpose) -> tuple[str, str]:
        """Return the configured env provider/model pair for a purpose."""
        if purpose == "deep":
            return settings.llm_reasoning_provider or "", settings.llm_reasoning_model or ""
        if purpose == "report":
            provider_id = (
                settings.report_llm_provider
                if settings.report_llm_provider != "openai_compatible"
                else (settings.llm_default_provider or "default_openai")
            )
            return provider_id or "", settings.report_llm_model or settings.llm_model or ""
        return settings.llm_default_provider or "default_openai", settings.llm_default_model or settings.llm_model or ""

    def _merge_routing(self, existing: LLMRoutingData, update: LLMRoutingUpdateRequest) -> LLMRoutingData:
        data = existing.model_dump(mode="python")
        for key in ("qa", "deep", "report"):
            value = getattr(update, key)
            if value is not None:
                data[key] = value.model_dump(mode="python")
        return LLMRoutingData.model_validate(data)

    def _validate_routing(self, routing: LLMRoutingData, providers: list[LLMProviderInfo]) -> None:
        for purpose in ("qa", "deep", "report"):
            selection = getattr(routing, purpose)
            if not selection:
                continue
            provider = self._provider_by_id(providers, selection.provider_id)
            self._model_by_id(provider, selection.model_id)

    def _routing_to_catalog_dict(
        self,
        routing: LLMRoutingData,
        providers: list[LLMProviderInfo],
    ) -> dict[LLMRoutePurpose, dict[str, str | bool | None]]:
        output: dict[LLMRoutePurpose, dict[str, str | bool | None]] = {}
        for purpose in ("qa", "deep", "report"):
            selection = getattr(routing, purpose)
            if not selection:
                continue
            reasoning_available = False
            try:
                provider = self._provider_by_id(providers, selection.provider_id)
                model = self._model_by_id(provider, selection.model_id)
                reasoning_available = "reasoning" in model.capabilities
            except HTTPException:
                pass
            output[purpose] = {
                "provider_id": selection.provider_id,
                "model_id": selection.model_id,
                "reasoning_model_available": reasoning_available if purpose == "deep" else None,
            }
        return output

    def _route_payload(
        self,
        provider: LLMProviderInfo,
        model: LLMModelInfo,
        *,
        purpose: str,
        route_reason: str,
        requested_provider_id: str | None = None,
        requested_model_id: str | None = None,
    ) -> dict[str, Any]:
        config = self._provider_runtime_config(provider.provider_id)
        return {
            "purpose": purpose,
            "route_reason": route_reason,
            "requested_provider_id": requested_provider_id,
            "requested_model_id": requested_model_id,
            "provider_id": provider.provider_id,
            "provider_type": provider.provider_type,
            "model_id": model.model_id,
            "capabilities": model.capabilities,
            "capability_source": model.capability_source,
            "tool_protocol": model.tool_protocol,
            "supports_parallel_tool_calls": model.supports_parallel_tool_calls,
            "context_window": model.context_window,
            "max_output_tokens": model.max_output_tokens,
            "reasoning_model_available": "reasoning" in model.capabilities,
            "provider_config": config,
        }

    def _provider_runtime_config(self, provider_id: str) -> dict[str, Any]:
        for config in self._configured_provider_configs():
            if config.provider_id == provider_id:
                data = config.model_dump(mode="python")
                data["api_key"] = os.getenv(config.api_key_env or "") if config.api_key_env else ""
                return data
        if provider_id == "local_ollama":
            return {
                "provider_id": provider_id,
                "provider_type": "ollama",
                "base_url": settings.report_ollama_base_url,
            }
        if provider_id == (settings.llm_default_provider or "default_openai") and (settings.llm_model or settings.llm_base_url):
            return {
                "provider_id": provider_id,
                "provider_type": "openai_compatible",
                "base_url": settings.llm_base_url,
                "api_key": settings.llm_api_key,
            }
        return {"provider_id": provider_id, "provider_type": "openai_compatible"}

    def _provider_api_key(self, config: dict[str, Any]) -> str:
        return str(config.get("api_key") or settings.llm_api_key or "EMPTY")

    def _provider_by_id(self, providers: list[LLMProviderInfo], provider_id: str) -> LLMProviderInfo:
        for provider in providers:
            if provider.provider_id == provider_id:
                return provider
        raise HTTPException(status_code=404, detail=f"未知 LLM provider: {provider_id}")

    def _model_by_id(self, provider: LLMProviderInfo, model_id: str) -> LLMModelInfo:
        for model in provider.models:
            if model.model_id == model_id:
                return model
        raise HTTPException(status_code=404, detail=f"未知 LLM 模型: {model_id}")

    def _safe_base_url_label(self, base_url: str) -> str | None:
        if not base_url:
            return None
        parsed = urlparse(base_url)
        if not parsed.netloc:
            return "configured"
        suffix = "/v1" if parsed.path.rstrip("/").endswith("/v1") else ""
        return f"{parsed.netloc}/...{suffix}"
