"""Assistant request context assembler and request manifest builder."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.schemas.agent_tools import AgentTool
from app.services.assistant_tool_contract import build_function_tool, safe_function_name


DEFAULT_CONTEXT_TOKEN_BUDGET = 6144
DEFAULT_SECTION_TOKEN_BUDGETS = {
    "project_facts": 2764,
    "llm_route": 307,
    "selected_tools": 614,
    "knowledge_evidence": 1228,
    "web_evidence": 1228,
    "prior_tool_results": 921,
    "conversation_policy": 82,
}
SECTION_ORDER = tuple(DEFAULT_SECTION_TOKEN_BUDGETS)
SECTION_HEADERS = {
    "project_facts": "PROJECT_FACTS",
    "llm_route": "LLM_ROUTE",
    "selected_tools": "SELECTED_TOOLS",
    "knowledge_evidence": "KNOWLEDGE_EVIDENCE",
    "web_evidence": "WEB_EVIDENCE",
    "prior_tool_results": "PRIOR_TOOL_RESULTS",
    "conversation_policy": "CONVERSATION_POLICY",
}
SECTION_SOURCES = {
    "project_facts": "ProjectGroundingService",
    "llm_route": "LLMModelService.resolve_route",
    "selected_tools": "AgentToolService",
    "knowledge_evidence": "KnowledgeService",
    "web_evidence": "AssistantWebSearchService",
    "prior_tool_results": "AssistantToolCallRepository",
    "conversation_policy": "AssistantAnswerSynthesizer",
}


@dataclass(frozen=True)
class ContextSection:
    """One addressable context block sent to, or omitted from, a model request."""

    name: str
    source: str
    content: str
    token_estimate: int
    included: bool
    omitted_reason: str | None
    digest: str
    truncated: bool = False
    truncated_to_tokens: int | None = None


@dataclass(frozen=True)
class ContextAssembly:
    """Budgeted context assembly result for a single model request."""

    request_kind: str
    sections: tuple[ContextSection, ...]
    digest: str
    token_estimate: int
    native_tool_schema_token_estimate: int
    budget_token_estimate: int
    chars_per_token: float
    rendered: str


def estimate_tokens(text: str, chars_per_token: float = 4) -> int:
    """Estimate tokens conservatively from UTF-8 character length.

    Args:
        text: Text that may be included in a model request.
        chars_per_token: Estimated number of characters per token.

    Returns:
        Estimated token count.
    """
    divisor = max(0.1, float(chars_per_token or 4))
    return math.ceil(len(str(text or "")) / divisor)


def estimate_native_tool_schema_tokens(tools: Sequence[Any]) -> int:
    """Estimate native tool schema tokens for OpenAI-compatible requests.

    Args:
        tools: Tool definitions or AgentTool objects.

    Returns:
        Estimated token count of serialized native tool schemas.
    """
    definitions = [
        build_function_tool(tool) if hasattr(tool, "tool_id") else tool
        for tool in tools
    ]
    serialized = json.dumps(definitions, ensure_ascii=False, sort_keys=True, default=str)
    return estimate_tokens(serialized)


class AssistantContextAssembler:
    """Build deterministic, budgeted context and a replayable request manifest."""

    def assemble(
        self,
        *,
        request_kind: str,
        intent_scope: str,
        deep: bool,
        facts: Mapping[str, Any],
        route: Mapping[str, Any] | None = None,
        selected_tools: Sequence[AgentTool] | None = None,
        knowledge_evidence: Sequence[Mapping[str, Any]] | None = None,
        web_evidence: Sequence[Mapping[str, Any]] | None = None,
        prior_tool_messages: Sequence[Mapping[str, Any]] | None = None,
        total_token_budget: int | None = None,
        section_token_budgets: Mapping[str, int] | None = None,
        native_tool_schema_tokens: int | None = None,
        chars_per_token: float = 4,
        allow_section_truncation: bool = False,
    ) -> ContextAssembly:
        """Assemble built-in context sections under section and total budgets.

        Args:
            request_kind: Model request kind, such as ``tool_proposal``.
            intent_scope: Current answer scope.
            deep: Whether deep mode is enabled.
            facts: Project grounding facts.
            route: Safe resolved LLM route.
            selected_tools: Tools visible to this request.
            knowledge_evidence: Knowledge retrieval results.
            web_evidence: Web retrieval results.
            prior_tool_messages: Provider tool-result messages for continuation.
            total_token_budget: Optional total token budget override.
            section_token_budgets: Optional per-section token budget overrides.
            native_tool_schema_tokens: Estimated tokens consumed by native tools.
            chars_per_token: Estimator denominator used for explainability.
            allow_section_truncation: Whether over-budget sections may be truncated
                instead of omitted entirely.

        Returns:
            A deterministic assembly containing all section decisions.
        """
        safe_route = dict(route or {})
        budget = self._total_budget(total_token_budget, safe_route)
        divisor = max(0.1, float(chars_per_token or 4))
        native_tokens = max(0, int(native_tool_schema_tokens or 0))
        budgets = {**DEFAULT_SECTION_TOKEN_BUDGETS, **(section_token_budgets or {})}
        contents = {
            "project_facts": self._project_facts(facts),
            "llm_route": self._llm_route(safe_route),
            "selected_tools": self._selected_tools(selected_tools or []),
            "knowledge_evidence": self._knowledge_evidence(knowledge_evidence),
            "web_evidence": self._web_evidence(web_evidence),
            "prior_tool_results": self._prior_tool_results(prior_tool_messages or []),
            "conversation_policy": self._conversation_policy(intent_scope, deep),
        }

        sections: list[ContextSection] = []
        section_pool = max(0, budget - native_tokens)
        remaining = section_pool
        for name in SECTION_ORDER:
            content = contents[name]
            estimate = estimate_tokens(content, divisor)
            section_budget = max(0, int(budgets.get(name, 0)))
            truncated_to_tokens: int | None = None
            included = True
            omitted_reason: str | None = None
            if estimate > section_budget:
                if allow_section_truncation and section_budget > 0:
                    content = self._truncate_content(content, section_budget, divisor)
                    estimate = estimate_tokens(content, divisor)
                    truncated_to_tokens = estimate
                else:
                    included = False
                    omitted_reason = "section_budget_exceeded"
            if included and estimate > remaining:
                if allow_section_truncation and remaining > 0:
                    content = self._truncate_content(content, remaining, divisor)
                    estimate = estimate_tokens(content, divisor)
                    truncated_to_tokens = estimate
                else:
                    included = False
                    omitted_reason = "total_budget_exceeded"
            if included:
                remaining -= estimate
            sections.append(
                ContextSection(
                    name=name,
                    source=SECTION_SOURCES[name],
                    content=content,
                    token_estimate=estimate,
                    included=included,
                    omitted_reason=omitted_reason,
                    digest=self._digest(content),
                    truncated=truncated_to_tokens is not None,
                    truncated_to_tokens=truncated_to_tokens,
                )
            )

        included_sections = [section for section in sections if section.included]
        rendered = "\n".join(
            f"{SECTION_HEADERS[section.name]}:\n{section.content}"
            for section in included_sections
        )
        return ContextAssembly(
            request_kind=request_kind,
            sections=tuple(sections),
            digest=self._context_digest(included_sections),
            token_estimate=sum(section.token_estimate for section in included_sections),
            native_tool_schema_token_estimate=native_tokens,
            budget_token_estimate=sum(section.token_estimate for section in included_sections) + native_tokens,
            chars_per_token=divisor,
            rendered=rendered,
        )

    def build_manifest(
        self,
        *,
        run_id: str | None,
        request_kind: str,
        route: Mapping[str, Any],
        assembly: ContextAssembly,
        tools: Sequence[AgentTool] | None = None,
    ) -> dict[str, Any]:
        """Build the persisted request manifest for one model request.

        Args:
            run_id: Durable assistant run ID when available.
            request_kind: Model request kind.
            route: Safe resolved LLM route.
            assembly: Context assembly used by the model request.
            tools: Tools whose native schemas were rendered for the provider.

        Returns:
            A JSON-serializable manifest without prompt snapshots or credentials.
        """
        return {
            "schema_version": 1,
            "run_id": run_id,
            "request_kind": request_kind,
            "route": self._manifest_route(route),
            "context": {
                "digest": assembly.digest,
                "token_estimate": assembly.budget_token_estimate,
                "section_token_estimate": assembly.token_estimate,
                "native_tool_schema_token_estimate": assembly.native_tool_schema_token_estimate,
                "token_estimation": {
                    "method": "char_count",
                    "chars_per_token": assembly.chars_per_token,
                },
                "sections": [
                    {
                        "name": section.name,
                        "source": section.source,
                        "token_estimate": section.token_estimate,
                        "included": section.included,
                        "omitted_reason": section.omitted_reason,
                        "truncated": section.truncated,
                        "truncated_to_tokens": section.truncated_to_tokens,
                    }
                    for section in assembly.sections
                ],
            },
            "tools": [self._manifest_tool(tool) for tool in tools or []],
        }

    @staticmethod
    def _total_budget(
        explicit_budget: int | None,
        route: Mapping[str, Any],
    ) -> int:
        """Derive a conservative context budget from route context window."""
        if explicit_budget is not None:
            return max(0, int(explicit_budget))
        context_window = route.get("context_window")
        if not isinstance(context_window, int) or context_window <= 0:
            return DEFAULT_CONTEXT_TOKEN_BUDGET
        return max(512, min(DEFAULT_CONTEXT_TOKEN_BUDGET, context_window // 4))

    @staticmethod
    def _project_facts(facts: Mapping[str, Any]) -> str:
        """Render project facts without response-only metadata duplication."""
        compact = {
            key: value
            for key, value in dict(facts or {}).items()
            if key not in {"llm_route", "request_context", "context_assembly", "request_manifest"}
        }
        return json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _llm_route(route: Mapping[str, Any]) -> str:
        """Render only routing fields needed by the model."""
        keys = (
            "provider_id",
            "model_id",
            "purpose",
            "route_reason",
            "tool_protocol",
            "context_window",
        )
        compact = {key: route.get(key) for key in keys if route.get(key) is not None}
        return json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _selected_tools(tools: Sequence[AgentTool]) -> str:
        """Render a concise selected-tool catalog without full JSON schemas."""
        if not tools:
            return "not_selected"
        lines = []
        for tool in tools:
            lines.append(
                "- "
                f"id={tool.tool_id}; name={tool.name}; version={tool.version or 'unknown'}; "
                f"schema_digest={tool.schema_digest or 'unknown'}; description={tool.description}"
            )
        return "\n".join(lines)

    @staticmethod
    def _knowledge_evidence(items: Sequence[Mapping[str, Any]] | None) -> str:
        """Render knowledge evidence and its source IDs."""
        if not items:
            return "not_available"
        lines = []
        for index, item in enumerate(items, start=1):
            lines.append(
                f"[K{index}] {item.get('title', '')}\n"
                f"SOURCE_ID: {item.get('source_id', '')}\n"
                f"SCORE: {item.get('score', 0)}\n"
                f"SNIPPET: {item.get('snippet', '')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _web_evidence(items: Sequence[Mapping[str, Any]] | None) -> str:
        """Render web evidence and URLs."""
        if not items:
            return "not_available"
        lines = []
        for index, item in enumerate(items, start=1):
            lines.append(
                f"[{index}] {item.get('title', '')}\n"
                f"URL: {item.get('url', '')}\n"
                f"SNIPPET: {item.get('snippet', '')}\n"
                f"CONTENT: {item.get('content', '')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _prior_tool_results(messages: Sequence[Mapping[str, Any]]) -> str:
        """Render prior provider tool messages for continuation requests."""
        if not messages:
            return "not_available"
        lines = []
        for index, message in enumerate(messages, start=1):
            lines.append(f"[T{index}] role={message.get('role', 'tool')}\n{message.get('content', '')}")
        return "\n".join(lines)

    @staticmethod
    def _conversation_policy(intent_scope: str, deep: bool) -> str:
        """Render response and citation rules shared by assistant requests."""
        return (
            f"ANSWER_SCOPE: {intent_scope}; DEEP_MODE: {deep}; "
            "先给结论，再给依据，最后给可执行建议；"
            "知识库证据用 [K1] [K2] 引用，网页证据用 [1] [2] 引用；"
            "不要编造未提供的算法、事实或外部资料。"
        )

    @staticmethod
    def _manifest_route(route: Mapping[str, Any]) -> dict[str, Any]:
        """Keep manifest route fields aligned with PR-01 route snapshots."""
        return {
            "provider_id": route.get("provider_id"),
            "model_id": route.get("model_id"),
            "purpose": route.get("purpose"),
            "route_reason": route.get("route_reason"),
            "tool_protocol": route.get("tool_protocol"),
        }

    @staticmethod
    def _manifest_tool(tool: AgentTool) -> dict[str, Any]:
        """Record only identity and schema identity for replay."""
        return {
            "tool_id": tool.tool_id,
            "function_name": tool.function_name or safe_function_name(tool.tool_id),
            "version": tool.version,
            "schema_digest": tool.schema_digest,
        }

    @staticmethod
    def _digest(content: str) -> str:
        """Return a stable SHA-256 content digest."""
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _truncate_content(content: str, token_budget: int, chars_per_token: float) -> str:
        """Truncate text to a token budget while preserving a stable marker.

        Args:
            content: Original context content.
            token_budget: Maximum estimated tokens allowed.
            chars_per_token: Token estimator denominator.

        Returns:
            Truncated text with a deterministic suffix.
        """
        if token_budget <= 0:
            return ""
        max_chars = int(math.floor(token_budget * max(0.1, float(chars_per_token))))
        suffix = "\n[section_truncated]"
        available = max(0, max_chars - len(suffix))
        if available >= len(content):
            return content
        return content[:available] + suffix

    @staticmethod
    def _context_digest(sections: Iterable[ContextSection]) -> str:
        """Hash included section names and contents in deterministic order."""
        canonical = json.dumps(
            [{"name": section.name, "digest": section.digest} for section in sections],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
