"""Report provider registry."""

from __future__ import annotations

from app.core.config import settings
from app.services.llm_model_service import LLMModelService
from app.services.report_providers.base import ReportGenerationProvider
from app.services.report_providers.codex_exec import CodexExecReportProvider
from app.services.report_providers.custom_http import CustomHttpReportProvider
from app.services.report_providers.local_ollama import LocalOllamaReportProvider
from app.services.report_providers.mock import MockReportProvider
from app.services.report_providers.openai_compatible import OpenAICompatibleReportProvider
from app.services.report_providers.openai_responses import OpenAIResponsesReportProvider


class ReportProviderRegistry:
    """Resolve report providers from backend configuration."""

    def get_provider(self, provider_name: str | None = None, *, model_route: dict | None = None) -> ReportGenerationProvider:
        name = provider_name or settings.report_llm_provider
        if model_route:
            name = self._provider_name_from_route(model_route)
            provider_config = model_route.get("provider_config") or {}
            model = str(model_route.get("model_id") or "")
            if name == "openai_compatible":
                return OpenAICompatibleReportProvider(
                    api_key=str(provider_config.get("api_key") or settings.report_llm_api_key or "EMPTY"),
                    base_url=str(provider_config.get("base_url") or settings.report_llm_base_url or ""),
                    model=model or settings.report_llm_model,
                )
            if name == "local_ollama":
                return LocalOllamaReportProvider(
                    base_url=str(provider_config.get("base_url") or settings.report_ollama_base_url),
                    model=model or settings.report_ollama_model,
                )
            if name == "custom_http":
                return CustomHttpReportProvider(
                    endpoint_url=str(provider_config.get("base_url") or settings.report_llm_base_url),
                    api_key=str(provider_config.get("api_key") or settings.report_llm_api_key or ""),
                    model=model or settings.report_llm_model,
                )

        if name == "mock":
            return MockReportProvider(model=settings.report_llm_model)
        if name == "openai_compatible":
            return OpenAICompatibleReportProvider()
        if name == "openai_responses":
            return OpenAIResponsesReportProvider()
        if name == "local_ollama":
            return LocalOllamaReportProvider()
        if name == "codex_exec":
            return CodexExecReportProvider()
        if name == "custom_http":
            return CustomHttpReportProvider()
        raise ValueError(f"Unsupported report provider: {name}")

    def resolve_report_route(self, route_hint: dict | None = None) -> dict | None:
        """Resolve the persisted report LLM route into runtime provider config."""
        if settings.report_llm_provider == "mock":
            return None
        requested_model = None
        if route_hint:
            requested_model = {
                "provider_id": route_hint.get("provider_id"),
                "model_id": route_hint.get("model_id"),
            }
        return LLMModelService().resolve_route(purpose="report", requested_model=requested_model)

    def _provider_name_from_route(self, route: dict) -> str:
        provider_type = str(route.get("provider_type") or "")
        if provider_type == "ollama":
            return "local_ollama"
        if provider_type == "custom_http":
            return "custom_http"
        return "openai_compatible"
