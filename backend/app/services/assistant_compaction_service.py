"""Assistant conversation compaction service."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.time import utc_now
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantMessageRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant_commands import CompactionSnapshot
from app.services.assistant_context_assembler import estimate_tokens
from app.services.llm_model_service import LLMModelService


ACTIVE_RUN_STATUSES = {"queued", "running"}
ACTIVE_TOOL_PHASES = {"requested", "awaiting_input", "awaiting_confirmation", "queued", "running"}
RETAINED_MESSAGE_COUNT = 2
SUMMARY_PROMPT = (
    "你是会话上下文压缩器。请生成一份可直接替换旧历史的中文摘要，"
    "必须保留用户目标、Active Goal、Todo 状态、当前权限与模式、已完成任务、当前状态、"
    "关键结论、重要文件、关键配置、未完成任务和活跃工具结果；"
    "压缩重复对话、已解决的问题、无关过程信息和冗长工具返回。只输出摘要正文。"
)


class AssistantCompactionService:
    """Build and apply durable assistant conversation compaction snapshots."""

    def __init__(self) -> None:
        self.llm_model_service = LLMModelService()

    @staticmethod
    def _clip(value: Any, limit: int = 4_000) -> str:
        """Convert and clip one summary source value.

        Args:
            value: Raw value from a persisted document.
            limit: Maximum character count.

        Returns:
            Compact string representation.
        """
        text = str(value or "").strip()
        return text if len(text) <= limit else text[: limit - 1] + "…"

    @staticmethod
    def _sha256(value: str) -> str:
        """Calculate a stable SHA-256 digest.

        Args:
            value: Input text.

        Returns:
            Digest prefixed with the algorithm name.
        """
        return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _model_visible(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter command-owned messages out of compaction input.

        Args:
            messages: Persisted chat messages.

        Returns:
            Messages allowed to enter a model request.
        """
        return [
            item
            for item in messages or []
            if (item.get("metadata") or {}).get("model_visible") is not False
        ]

    @staticmethod
    def _after_cutoff(
        messages: list[dict[str, Any]],
        cutoff_message_id: str | None,
    ) -> list[dict[str, Any]]:
        """Return messages after a snapshot cutoff.

        Args:
            messages: Chronologically ordered persisted messages.
            cutoff_message_id: Previous snapshot cutoff.

        Returns:
            Messages after the cutoff, or all messages when no cutoff exists.
        """
        if not cutoff_message_id:
            return list(messages or [])
        for index, message in enumerate(messages or []):
            if message.get("message_id") == cutoff_message_id:
                return list(messages[index + 1 :])
        return list(messages or [])

    @staticmethod
    def _safe_route(route: dict[str, Any], *, unavailable: bool = False) -> dict[str, Any]:
        """Keep only replayable route fields.

        Args:
            route: Resolved LLM route.
            unavailable: Whether route resolution failed and fallback is used.

        Returns:
            A credential-free route snapshot.
        """
        keys = (
            "purpose",
            "provider_id",
            "model_id",
            "route_reason",
            "requested_provider_id",
            "requested_model_id",
        )
        safe = {key: route.get(key) for key in keys if route.get(key) is not None}
        if unavailable:
            safe.update({"purpose": "compact", "route_reason": "unavailable_fallback"})
        return safe

    @classmethod
    def _tool_context(
        cls,
        chat_id: str,
        owner_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Collect active and latest completed tool results.

        Args:
            chat_id: Chat ID.
            owner_id: Chat owner.

        Returns:
            (tool summaries, selected call IDs) tuple.
        """
        calls = AssistantToolCallRepository.list_for_chat(chat_id, created_by=owner_id)
        selected = [call for call in calls if call.get("phase") in ACTIVE_TOOL_PHASES]
        completed = [call for call in calls if call.get("phase") == "completed"]
        if completed and not selected:
            selected = completed[-1:]
        summaries = [
            {
                "call_id": call.get("call_id"),
                "tool_name": call.get("tool_name"),
                "phase": call.get("phase"),
                "result_summary": call.get("result_summary") or call.get("result"),
            }
            for call in selected
        ]
        return summaries, [str(call.get("call_id") or "") for call in selected if call.get("call_id")]

    @classmethod
    def _summary_source(
        cls,
        chat: dict[str, Any],
        messages: list[dict[str, Any]],
        previous_summary: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build the required summary input without irrelevant raw history.

        Args:
            chat: Current chat control document.
            messages: Candidate messages after the previous cutoff.
            previous_summary: Previous compaction summary.
            tools: Selected active or latest tool summaries.

        Returns:
            A JSON-serializable summary source.
        """
        users = [item for item in messages if item.get("role") == "user"]
        assistants = [item for item in messages if item.get("role") == "assistant"]
        files = sorted(
            set(
                match
                for message in messages
                for match in re.findall(
                    r"(?:/[A-Za-z0-9_./-]+|[A-Za-z0-9_.-]+\.(?:csv|xlsx|json|yaml|yml|md|txt|py|pdf))",
                    str(message.get("content") or ""),
                )
            )
        )[:20]
        goal = dict(chat.get("goal") or {})
        todos = list(chat.get("todos") or [])
        model = dict(chat.get("model") or {})
        return {
            "previous_summary": cls._clip(previous_summary),
            "用户目标": cls._clip(users[0].get("content") if users else goal.get("objective")),
            "Active Goal": {
                "objective": cls._clip(goal.get("objective")),
                "status": goal.get("status"),
            }
            if goal
            else None,
            "Todo 状态": [
                {"content": cls._clip(todo.get("content")), "status": todo.get("status")}
                for todo in todos
            ],
            "当前权限与模式": {
                "permission_mode": chat.get("permission_mode") or "workspace_write",
                "plan_mode": bool(chat.get("plan_mode", False)),
                "chat_mode": chat.get("mode"),
            },
            "已完成任务": [
                cls._clip(item.get("content"), 600)
                for item in assistants
                if re.search(r"完成|已解决|成功|通过", str(item.get("content") or ""))
            ][-5:],
            "当前状态": cls._clip(messages[-1].get("content") if messages else "", 800),
            "关键结论": [cls._clip(item.get("content"), 600) for item in assistants[-3:]],
            "重要文件": files,
            "关键配置": {
                "model": model,
                "knowledge_base_ids": chat.get("knowledge_base_ids") or [],
                "selected_tool_ids": chat.get("selected_tool_ids") or [],
            },
            "未完成任务": [
                {"content": cls._clip(todo.get("content")), "status": todo.get("status")}
                for todo in todos
                if todo.get("status") in {"pending", "in_progress"}
            ],
            "活跃工具结果": tools,
            "候选消息": [
                {"role": item.get("role"), "content": cls._clip(item.get("content"), 1_200)}
                for item in messages[-30:]
            ],
        }

    @classmethod
    def _deterministic_summary(cls, source: dict[str, Any]) -> str:
        """Render a stable summary when the compact route is unavailable.

        Args:
            source: Summary source produced by `_summary_source`.

        Returns:
            A summary containing every required state category.
        """

        def lines(key: str) -> list[str]:
            value = source.get(key)
            if value is None:
                return []
            if isinstance(value, list):
                return [cls._clip(item, 600) for item in value if item]
            if isinstance(value, dict):
                return [cls._clip(json.dumps(value, ensure_ascii=False, sort_keys=True), 600)]
            return [cls._clip(value, 600)]

        return "\n".join(
            [
                *([f"用户目标：{item}" for item in lines("用户目标")] or ["用户目标：无"]),
                *([f"Active Goal：{item}" for item in lines("Active Goal")] or ["Active Goal：无"]),
                *([f"Todo 状态：{item}" for item in lines("Todo 状态")] or ["Todo 状态：无"]),
                *([f"当前权限与模式：{item}" for item in lines("当前权限与模式")]),
                *([f"已完成任务：{item}" for item in lines("已完成任务")] or ["已完成任务：无"]),
                *([f"当前状态：{item}" for item in lines("当前状态")] or ["当前状态：无"]),
                *([f"关键结论：{item}" for item in lines("关键结论")] or ["关键结论：无"]),
                *([f"重要文件：{item}" for item in lines("重要文件")] or ["重要文件：无"]),
                *([f"关键配置：{item}" for item in lines("关键配置")]),
                *([f"未完成任务：{item}" for item in lines("未完成任务")] or ["未完成任务：无"]),
                *([f"活跃工具结果：{item}" for item in lines("活跃工具结果")] or ["活跃工具结果：无"]),
                "已压缩：重复对话、已解决问题、无关过程信息和冗长工具返回",
            ]
        )

    @staticmethod
    def _valid_summary(summary: str) -> bool:
        """Validate assistant-generated summary text.

        Args:
            summary: Raw compact route output.

        Returns:
            Whether the output can be persisted directly.
        """
        text = summary.strip()
        return 20 <= len(text) <= 20_000

    @classmethod
    def _estimate_history(cls, summary: str, messages: list[dict[str, Any]]) -> int:
        """Estimate tokens for one effective history.

        Args:
            summary: Compaction summary.
            messages: Full or retained messages.

        Returns:
            Conservative estimated token count.
        """
        return estimate_tokens(summary) + estimate_tokens(
            json.dumps(messages or [], ensure_ascii=False, sort_keys=True, default=str)
        )

    @classmethod
    def effective_history(
        cls,
        chat_id: str,
        owner_id: str,
        submitted_messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]] | None:
        """Rebuild model history from a durable compaction snapshot.

        Args:
            chat_id: Chat ID.
            owner_id: Chat owner.
            submitted_messages: Compatibility-only client history; never trusted.

        Returns:
            Effective history messages, or None when no snapshot exists.
        """
        del submitted_messages
        chat = AssistantChatRepository.find_one({"chat_id": chat_id, "created_by": owner_id})
        raw_snapshot = (chat or {}).get("compaction")
        if not raw_snapshot:
            return None
        snapshot = CompactionSnapshot.model_validate(raw_snapshot)
        messages, _ = AssistantMessageRepository.list_for_chat(
            chat_id,
            owner_id,
            page=1,
            page_size=10_000,
        )
        visible = cls._model_visible(messages)
        retained_ids = set(snapshot.retained_message_ids)
        selected: list[dict[str, Any]] = []
        for message in visible:
            if message.get("message_id") in retained_ids:
                selected.append(message)
        selected.extend(cls._after_cutoff(visible, snapshot.cutoff_message_id))
        ordered = []
        seen: set[str] = set()
        for message in selected:
            message_id = str(message.get("message_id") or "")
            if message_id in seen:
                continue
            seen.add(message_id)
            ordered.append(message)
        summary_message = {
            "role": "system",
            "content": f"COMPACTION_SUMMARY（digest={snapshot.summary_digest}）：\n{snapshot.summary}",
        }
        return [summary_message, *[{"role": item.get("role"), "content": item.get("content")} for item in ordered]]

    def compact(
        self,
        chat: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CompactionSnapshot:
        """Compact one chat without rewriting its original messages.

        Args:
            chat: Owned chat document.
            current_user: Current user.
            command_id: Slash command execution ID.

        Returns:
            The committed compaction snapshot.
        """
        chat_id = str(chat.get("chat_id") or "")
        owner_id = str(chat.get("created_by") or "")
        runs, _ = AssistantRunRepository.list_for_chat(chat_id, owner_id, page=1, page_size=10_000)
        active_runs = [run for run in runs if run.get("status") in ACTIVE_RUN_STATUSES]
        if active_runs:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "compaction_busy",
                    "message": "当前会话存在活动回答，请完成或取消后再压缩上下文",
                    "run_id": active_runs[0].get("run_id"),
                },
            )

        previous_raw = chat.get("compaction") or {}
        previous = CompactionSnapshot.model_validate(previous_raw) if previous_raw else None
        messages, _ = AssistantMessageRepository.list_for_chat(
            chat_id,
            owner_id,
            page=1,
            page_size=10_000,
        )
        candidates = self._model_visible(
            self._after_cutoff(messages, previous.cutoff_message_id if previous else None)
        )
        if not candidates and not previous:
            raise ValueError("当前会话没有可压缩的模型可见历史")

        tools, tool_call_ids = self._tool_context(chat_id, owner_id)
        previous_summary = previous.summary if previous else ""
        source = self._summary_source(chat, candidates, previous_summary, tools)
        original_estimate = self._estimate_history(previous_summary, candidates)
        route: dict[str, Any]
        summary = ""
        summary_method = "deterministic_fallback"
        prompt_tokens = 0
        try:
            route = self._safe_route(
                self.llm_model_service.resolve_route(purpose="compact")
            )
            request_messages = [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": json.dumps(source, ensure_ascii=False, sort_keys=True, default=str)},
            ]
            prompt_tokens = sum(estimate_tokens(item.get("content", "")) for item in request_messages)
            kwargs: dict[str, Any] = {
                "messages": request_messages,
                "purpose": "compact",
                "temperature": 0.1,
                "max_tokens": 1_600,
            }
            if route.get("provider_id"):
                kwargs["provider_id"] = route["provider_id"]
            if route.get("model_id"):
                kwargs["model_id"] = route["model_id"]
            summary = self.llm_model_service.complete_text(**kwargs)
            if self._valid_summary(summary):
                summary_method = "llm"
        except Exception:
            route = {"purpose": "compact", "route_reason": "unavailable_fallback"}

        if summary_method != "llm":
            summary = self._deterministic_summary(source)
            prompt_tokens = estimate_tokens(SUMMARY_PROMPT + json.dumps(source, ensure_ascii=False, default=str))

        retained = candidates[-RETAINED_MESSAGE_COUNT:]
        retained_ids = [str(item.get("message_id") or "") for item in retained if item.get("message_id")]
        compacted_estimate = self._estimate_history(summary, retained)
        completion_tokens = estimate_tokens(summary)
        now = utc_now()
        summary_digest = self._sha256(summary)
        canonical = json.dumps(
            {
                "summary": summary,
                "cutoff_message_id": candidates[-1].get("message_id") if candidates else previous_summary,
                "retained_message_ids": retained_ids,
                "original_token_estimate": original_estimate,
                "token_estimate": compacted_estimate,
                "route": route,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot = CompactionSnapshot(
            snapshot_id=f"compact_{uuid4().hex[:16]}",
            cutoff_message_id=str(candidates[-1].get("message_id")) if candidates else previous.cutoff_message_id,
            summary=summary,
            retained_message_ids=retained_ids,
            active_tool_call_ids=tool_call_ids,
            summary_digest=summary_digest,
            digest=self._sha256(canonical),
            summary_method=summary_method,
            token_estimate=compacted_estimate,
            original_token_estimate=original_estimate,
            route=route,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            created_by=owner_id or str((current_user or {}).get("user_id") or ""),
            created_at=now,
        )
        return self._commit(chat, snapshot, command_id)

    def _commit(
        self,
        chat: dict[str, Any],
        snapshot: CompactionSnapshot,
        command_id: str,
    ) -> CompactionSnapshot:
        """Commit a snapshot and its context event with rollback on event failure.

        Args:
            chat: Owned chat document.
            snapshot: Snapshot to persist.
            command_id: Command execution ID.

        Returns:
            The committed snapshot.
        """
        chat_id = str(chat.get("chat_id") or "")
        owner_id = str(chat.get("created_by") or "")
        payload = snapshot.model_dump(mode="python")
        previous = chat.get("compaction")
        if not AssistantChatRepository.update_owned(
            chat_id,
            owner_id,
            {"compaction": payload, "updated_at": utc_now()},
        ):
            raise ValueError("上下文压缩提交失败，会话状态未改变")
        try:
            AssistantCommandRunRepository.append_chat_event(
                chat,
                {
                    "type": "context.compacted",
                    "command_id": command_id,
                    "trace_id": command_id,
                    "chat_id": chat_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "cutoff_message_id": snapshot.cutoff_message_id,
                    "summary_digest": snapshot.summary_digest,
                    "digest": snapshot.digest,
                    "route": snapshot.route,
                    "token_estimate": snapshot.token_estimate,
                    "original_token_estimate": snapshot.original_token_estimate,
                    "token_reduction": snapshot.original_token_estimate - snapshot.token_estimate,
                },
            )
        except Exception:
            AssistantChatRepository.update_owned(
                chat_id,
                owner_id,
                {"compaction": previous, "updated_at": utc_now()},
            )
            raise ValueError("上下文压缩事件写入失败，有效历史未改变") from None
        return snapshot


assistant_compaction_service = AssistantCompactionService()
