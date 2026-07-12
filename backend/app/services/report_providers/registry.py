"""Report provider registry."""

from __future__ import annotations

from app.core.config import settings
from app.services.report_providers.base import ReportGenerationProvider
from app.services.report_providers.codex_exec import CodexExecReportProvider
from app.services.report_providers.custom_http import CustomHttpReportProvider
from app.services.report_providers.local_ollama import LocalOllamaReportProvider
from app.services.report_providers.mock import MockReportProvider
from app.services.report_providers.openai_compatible import OpenAICompatibleReportProvider
from app.services.report_providers.openai_responses import OpenAIResponsesReportProvider


class ReportProviderRegistry:
    """Resolve report providers from backend configuration."""

    def get_provider(self, provider_name: str | None = None) -> ReportGenerationProvider:
        name = provider_name or settings.report_llm_provider
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
