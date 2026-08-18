"""Persistent, user-serialized execution for LUI assistant answers."""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta
from typing import Any, Iterator
from uuid import uuid4

from fastapi import HTTPException

from app.core.llm_context import record_llm_observation_scope, reset_llm_observation_scope
from app.core.logging import get_logger
from app.core.time import utc_now
from app.core import llm_client
from app.infra.research_engine_repositories import (
    AssistantEventRepository,
    AssistantMessageRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant_chats import AssistantMessageCreate
from app.schemas.assistant_runs import (
    AssistantRun,
    AssistantRunCreate,
    AssistantRunListData,
    AssistantUsageSummary,
)
from app.services.assistant_compaction_service import assistant_compaction_service
from app.services.assistant_chat_service import actor_id, assistant_chat_service
from app.services.assistant_service import stream_chat_assistant
from app.services.assistant_tool_service import assistant_tool_call_service


logger = get_logger("poly_agent.assistant_runs")
TERMINAL_STATUSES = {"completed", "failed", "canceled"}
MAX_CONTINUATION_ATTEMPTS = 5
CONTINUATION_BACKOFF_BASE_SECONDS = 2
CONTINUATION_MAX_BACKOFF_SECONDS = 300
RUNNING_EVENT_POLL_INTERVAL_SECONDS = 0.2
QUEUED_EVENT_POLL_INTERVAL_SECONDS = 1.0
ANSWER_DELTA_PERSIST_INTERVAL_SECONDS = 0.2
ANSWER_DELTA_PERSIST_CHAR_THRESHOLD = 256


class AssistantRunService:
    @staticmethod
    def _public(document: dict[str, Any], *, include_events: bool = True) -> AssistantRun:
        payload = dict(document)
        if not include_events:
            payload["events"] = []
        return AssistantRun.model_validate(payload)

    @staticmethod
    def _owned(run_id: str, current_user: dict[str, str] | None) -> dict[str, Any]:
        document = AssistantRunRepository.find_one({"run_id": run_id})
        if not document:
            raise HTTPException(status_code=404, detail=f"回答任务 '{run_id}' 不存在")
        if document.get("created_by") != actor_id(current_user):
            raise HTTPException(status_code=403, detail="无权限访问该回答任务")
        return document

    @staticmethod
    def _owned_status(run_id: str, current_user: dict[str, str] | None) -> dict[str, Any]:
        """读取 run 状态与归属信息，避免 SSE 轮询加载完整 run 文档。"""
        document = AssistantRunRepository.find_status(run_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"回答任务 '{run_id}' 不存在")
        if document.get("created_by") != actor_id(current_user):
            raise HTTPException(status_code=403, detail="无权限访问该回答任务")
        return document

    @staticmethod
    def model_visible_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """过滤不进入模型请求历史的消息。

        Args:
            messages: 请求快照中的历史消息。

        Returns:
            metadata.model_visible 不为 false 的消息列表。
        """
        return [
            dict(item)
            for item in (messages or [])
            if (item.get("metadata") or {}).get("model_visible") is not False
        ]

    @staticmethod
    def continuation_user_content(
        message: dict[str, Any],
        source_context: dict[str, Any],
    ) -> str:
        """解析工具续答应使用的用户任务说明。

        Args:
            message: 工具调用关联的原始用户消息。
            source_context: 工具调用保存的来源上下文。

        Returns:
            优先返回 metadata.task_content，其次返回消息内容。
        """
        metadata_task = str((message.get("metadata") or {}).get("task_content") or "").strip()
        context_task = str((source_context or {}).get("task_content") or "").strip()
        return context_task or metadata_task or str(message.get("content") or "").strip()

    def create(
        self,
        chat_id: str,
        payload: AssistantRunCreate,
        current_user: dict[str, str] | None,
    ) -> AssistantRun:
        owner_id = actor_id(current_user)
        chat = assistant_chat_service._owned_chat(chat_id, owner_id)
        existing_user_message = None
        if payload.user_message_id:
            existing_user_message = AssistantMessageRepository.find_one({
                "message_id": payload.user_message_id,
                "chat_id": chat_id,
                "created_by": owner_id,
                "role": "user",
            })
            if not existing_user_message:
                raise HTTPException(status_code=422, detail="用于继续生成的用户消息不存在")
        now = utc_now()
        run_id = f"asrun_{uuid4().hex[:16]}"
        context = dict(payload.context)
        tool_call_ids = [str(item) for item in (context.get("tool_call_ids") or []) if str(item)]
        is_continuation = bool(tool_call_ids)
        trace_id = str(context.get("trace_id") or "") if is_continuation else run_id
        if is_continuation and not trace_id:
            first_call = AssistantToolCallRepository.find_one({"call_id": tool_call_ids[0]})
            trace_id = str(
                (first_call or {}).get("trace_id")
                or (first_call or {}).get("assistant_run_id")
                or ""
            )
        if not trace_id:
            trace_id = run_id
        effective_messages = self.model_visible_messages(payload.messages)
        compacted_history = assistant_compaction_service.effective_history(
            chat_id,
            owner_id,
            payload.messages,
        )
        if compacted_history is not None:
            effective_messages = compacted_history
        context["trace_id"] = trace_id
        context["chat_id"] = chat_id
        context["run_id"] = run_id
        model = context.get("model") or {}
        requested_provider_id = model.get("providerId") or model.get("provider_id")
        requested_model_id = model.get("modelId") or model.get("model_id")
        document = {
            "run_id": run_id,
            "trace_id": trace_id,
            "chat_id": chat_id,
            "created_by": owner_id,
            "user_message_id": payload.user_message_id or "",
            "status": "queued",
            "active": True,
            "stage": "queued",
            "request_snapshot": {
                "content": payload.content.strip(),
                "messages": effective_messages,
                "context": context,
            },
            "partial_content": "",
            "error": None,
            "assistant_message_id": None,
            "event_seq": 0,
            "events": [],
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "heartbeat_at": None,
            "queue_wait_ms": None,
            "duration_ms": None,
            "first_token_ms": None,
            "provider_id": requested_provider_id,
            "model_id": requested_model_id,
            "route": {
                "requested_provider_id": requested_provider_id,
                "requested_model_id": requested_model_id,
            },
            "request_manifests": {},
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "http_status": None,
            "rate_limited": False,
            "reconnect_count": 0,
            "worker_id": None,
            "actor_role": (current_user or {}).get("role", "admin"),
            "conflict_count": 0,
        }
        created, current = AssistantRunRepository.create_active(document)
        if not created:
            if current.get("run_id"):
                AssistantRunRepository.increment_metric(current["run_id"], "conflict_count")
            logger.info(
                "assistant run conflict owner=%s active_run_id=%s active_chat_id=%s",
                owner_id, current.get("run_id"), current.get("chat_id"),
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "当前用户已有活动回答",
                    "run_id": current.get("run_id"),
                    "chat_id": current.get("chat_id"),
                },
            )
        if existing_user_message:
            message_id = existing_user_message["message_id"]
        else:
            try:
                message = assistant_chat_service.create_message(
                    chat_id,
                    AssistantMessageCreate(role="user", content=payload.content.strip()),
                    current_user,
                )
                message_id = message.message_id
            except Exception:
                AssistantRunRepository.update_if_status(
                    document["run_id"], ["queued"], {
                        "status": "failed", "active": False, "finished_at": utc_now(), "updated_at": utc_now(),
                    }
                )
                raise
        document["user_message_id"] = message_id
        document["request_snapshot"]["context"]["message_id"] = message_id
        AssistantRunRepository.update_if_status(
            document["run_id"],
            ["queued"],
            {"user_message_id": message_id, "request_snapshot": document["request_snapshot"], "updated_at": utc_now()},
        )
        self._event(document["run_id"], {"type": "status", "stage": "queued", "message": "已进入回答队列"})
        self._event(document["run_id"], {"type": "route.requested", "route": document["route"]})
        return self.get(document["run_id"], current_user)

    def get(self, run_id: str, current_user: dict[str, str] | None) -> AssistantRun:
        return self._public(self._owned(run_id, current_user))

    def get_active(self, current_user: dict[str, str] | None) -> AssistantRun | None:
        document = AssistantRunRepository.find_active_for_user(actor_id(current_user))
        return self._public(document) if document else None

    @staticmethod
    def metrics(
        *, created_by: str | None = None, provider_id: str | None = None,
        model_id: str | None = None, status: str | None = None,
    ) -> dict[str, Any]:
        filters = {key: value for key, value in {
            "created_by": created_by, "provider_id": provider_id, "model_id": model_id, "status": status,
        }.items() if value}
        items, total = AssistantRunRepository.list_all(filters, page=1, page_size=10_000)
        durations = sorted(int(item["duration_ms"]) for item in items if item.get("duration_ms") is not None)

        def percentile(fraction: float) -> int | None:
            if not durations:
                return None
            return durations[min(len(durations) - 1, int((len(durations) - 1) * fraction))]

        def token_total(field: str) -> int | None:
            values = [int(item[field]) for item in items if item.get(field) is not None]
            return sum(values) if values else None

        return {
            "total": total,
            "active": sum(item.get("status") in {"queued", "running"} for item in items),
            "completed": sum(item.get("status") == "completed" for item in items),
            "failed": sum(item.get("status") == "failed" for item in items),
            "canceled": sum(item.get("status") == "canceled" for item in items),
            "rate_limited": sum(bool(item.get("rate_limited")) for item in items),
            "conflicts": sum(int(item.get("conflict_count", 0)) for item in items),
            "reconnects": sum(int(item.get("reconnect_count", 0)) for item in items),
            "duration_p50_ms": percentile(0.50),
            "duration_p95_ms": percentile(0.95),
            "prompt_tokens": token_total("prompt_tokens"),
            "completion_tokens": token_total("completion_tokens"),
            "total_tokens": token_total("total_tokens"),
        }

    def usage_for_chat(
        self,
        chat_id: str,
        current_user: dict[str, str] | None,
    ) -> AssistantUsageSummary:
        """汇总指定会话内所有真实 LLM 请求的 token 消耗。

        Args:
            chat_id: 会话 ID。
            current_user: 当前用户上下文。

        Returns:
            该会话的 usage 汇总，包含输入、输出、总计和去重后的事件数。
        """
        owner_id = actor_id(current_user)
        assistant_chat_service._owned_chat(chat_id, owner_id)
        return self._usage_for_chat(chat_id, owner_id)

    @staticmethod
    def _usage_for_chat(
        chat_id: str,
        owner_id: str,
        *,
        runs: list[dict[str, Any]] | None = None,
    ) -> AssistantUsageSummary:
        """基于会话全部 runs 与 usage 事件汇总 token 消耗。"""
        if runs is None:
            runs, _ = AssistantRunRepository.list_for_chat_light(
                chat_id,
                owner_id,
                page=1,
                page_size=10_000,
            )
        usage_events = AssistantEventRepository.list_for_chat_usage(chat_id, owner_id)
        return AssistantRunService._summarize_usage(runs, usage_events)

    @staticmethod
    def _usage_component(usage: Any, key: str) -> int:
        """把 usage 字段安全转换为非负整数。"""
        value = (usage or {}).get(key)
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _event_usage(event: dict[str, Any]) -> dict[str, Any] | None:
        """从统一或旧版事件中提取 usage，仅处理 usage 事件。"""
        if event.get("type") != "llm.usage.recorded":
            return None
        usage = event.get("usage") or (event.get("data") or {}).get("usage") or {}
        return usage if isinstance(usage, dict) else {}

    @classmethod
    def _summarize_usage(
        cls,
        runs: list[dict[str, Any]],
        usage_events: list[dict[str, Any]] | None = None,
    ) -> AssistantUsageSummary:
        """按事件去重累加 runs 的 usage，兼容历史 run 字段回退。"""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        usage_events_count = 0
        seen: set[str] = set()
        events_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in usage_events or []:
            events_by_run.setdefault(str(event.get("run_id") or ""), []).append(event)

        for run in runs:
            run_id = str(run.get("run_id") or "")
            events = events_by_run.get(run_id, [])
            if not events:
                events = run.get("events") or []

            had_usage_event = False
            for index, event in enumerate(events):
                usage = cls._event_usage(event)
                if usage is None:
                    continue
                event_id = event.get("event_id")
                key = str(event_id or "")
                if not key:
                    key = f"{run_id}:{event.get('seq') or index}:{event.get('request_id') or ''}"
                if key in seen:
                    continue
                seen.add(key)

                prompt = cls._usage_component(usage, "prompt_tokens")
                completion = cls._usage_component(usage, "completion_tokens")
                total = cls._usage_component(usage, "total_tokens")
                prompt_tokens += prompt
                completion_tokens += completion
                total_tokens += total if total else prompt + completion
                usage_events_count += 1
                had_usage_event = True

            if had_usage_event:
                continue

            prompt = cls._usage_component(run, "prompt_tokens")
            completion = cls._usage_component(run, "completion_tokens")
            total = cls._usage_component(run, "total_tokens")
            if not prompt and not completion and not total:
                continue
            fallback_key = f"run-fields:{run_id}"
            if fallback_key in seen:
                continue
            seen.add(fallback_key)
            prompt_tokens += prompt
            completion_tokens += completion
            total_tokens += total if total else prompt + completion

        return AssistantUsageSummary(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            usage_events=usage_events_count,
        )

    def list_for_chat(
        self, chat_id: str, current_user: dict[str, str] | None, *, page: int = 1, page_size: int = 20
    ) -> AssistantRunListData:
        owner_id = actor_id(current_user)
        assistant_chat_service._owned_chat(chat_id, owner_id)
        all_runs, total = AssistantRunRepository.list_for_chat_light(
            chat_id,
            owner_id,
            page=1,
            page_size=10_000,
        )
        start = (page - 1) * page_size
        items = all_runs[start : start + page_size]
        usage = self._usage_for_chat(chat_id, owner_id, runs=all_runs)
        active = next((item for item in items if item.get("status") in {"queued", "running"}), None)
        return AssistantRunListData(
            items=[self._public(item, include_events=False) for item in items],
            active=self._public(active, include_events=False) if active else None,
            total=total,
            usage=usage,
        )

    def cancel(self, run_id: str, current_user: dict[str, str] | None) -> AssistantRun:
        document = self._owned(run_id, current_user)
        if document.get("status") in TERMINAL_STATUSES:
            return self._public(document)
        now = utc_now()
        AssistantRunRepository.update_if_status(
            run_id,
            ["queued", "running"],
            {"status": "canceled", "active": False, "stage": "canceled", "finished_at": now, "updated_at": now},
        )
        self._event(run_id, {"type": "run_status", "status": "canceled", "stage": "canceled"})
        return self.get(run_id, current_user)

    def events(self, run_id: str, current_user: dict[str, str] | None, after_seq: int = 0) -> Iterator[dict[str, Any]]:
        self._owned_status(run_id, current_user)
        if after_seq > 0:
            AssistantRunRepository.increment_metric(run_id, "reconnect_count")
        cursor = max(0, after_seq)
        idle_polls = 0
        while True:
            events = AssistantRunRepository.events_after(run_id, cursor)
            for event in events:
                cursor = max(cursor, int(event.get("seq", 0)))
                yield event
            document = self._owned_status(run_id, current_user)
            if document.get("status") in TERMINAL_STATUSES and not AssistantRunRepository.events_after(run_id, cursor):
                return
            idle_polls += 1
            if idle_polls % 60 == 0:
                yield {"type": "heartbeat", "seq": cursor, "status": document.get("status")}
            poll_interval = (
                RUNNING_EVENT_POLL_INTERVAL_SECONDS
                if document.get("status") == "running"
                else QUEUED_EVENT_POLL_INTERVAL_SECONDS
            )
            time.sleep(poll_interval)

    def process_continuations(self, worker_id: str) -> int:
        """扫描 terminal 工具调用并创建服务端续答 run。

        Args:
            worker_id: 当前 assistant worker ID，仅用于日志。

        Returns:
            本轮成功创建的 continuation run 数量。
        """
        assistant_tool_call_service.reconcile_orphans()
        created = 0
        for call in AssistantToolCallRepository.list_continuation_pending(limit=20):
            call_id = str(call.get("call_id") or "")
            if not call_id:
                continue
            try:
                if self._ensure_continuation_run(call):
                    created += 1
                    logger.info(
                        "assistant continuation run created worker_id=%s call_id=%s",
                        worker_id,
                        call_id,
                    )
            except HTTPException as exc:
                if exc.status_code == 409:
                    self._defer_continuation(call, exc)
                    continue
                self._record_continuation_failure(call, exc)
            except Exception as exc:
                logger.exception("assistant continuation creation failed call_id=%s", call_id)
                self._record_continuation_failure(call, exc)
        return created

    def _ensure_continuation_run(self, call: dict[str, Any]) -> bool:
        """为一个工具调用幂等创建 continuation run。

        Args:
            call: completed/failed 工具调用文档。

        Returns:
            ``True`` 表示本轮新建 run；``False`` 表示已存在或仅补记关联。
        """
        call_id = str(call.get("call_id") or "")
        existing = AssistantRunRepository.find_by_continuation_key(call_id)
        if existing:
            self._record_continuation_run(call, str(existing.get("run_id") or ""))
            return False

        owner_id = str(call.get("created_by") or "")
        chat_id = str(call.get("chat_id") or "")
        if not owner_id or not chat_id:
            raise HTTPException(status_code=422, detail="工具调用缺少会话归属信息，无法自动续答")

        source_context = call.get("source_context") or {}
        message_id = str(source_context.get("original_user_message_id") or call.get("message_id") or "")
        if not message_id:
            raise HTTPException(status_code=422, detail="工具调用缺少原用户消息，无法自动续答")
        user_message = AssistantMessageRepository.find_one({
            "message_id": message_id,
            "chat_id": chat_id,
            "created_by": owner_id,
            "role": "user",
        })
        if not user_message:
            raise HTTPException(status_code=422, detail="原用户消息不存在，无法自动续答")

        command_owned = bool(
            call.get("command_id")
            or source_context.get("command_id")
            or source_context.get("origin") == "slash_command"
        )
        if command_owned:
            user_content = str(
                source_context.get("task_content")
                or (user_message.get("metadata") or {}).get("task_content")
                or ""
            ).strip()
            if not user_content:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "MISSING_TASK_CONTENT",
                        "message": "未提供任务说明，不自动生成续答",
                    },
                )
        else:
            user_content = self.continuation_user_content(user_message, source_context)
        request_messages = [{"role": "user", "content": user_content}] if user_content.strip() else []
        context = self._continuation_context(call, source_context, message_id)
        actor = {"user_id": owner_id, "role": call.get("_actor_role") or "user"}
        run = self.create(
            chat_id,
            AssistantRunCreate(
                content="",
                user_message_id=message_id,
                messages=request_messages,
                context=context,
            ),
            actor,
        )
        self._record_continuation_run(call, run.run_id)
        return True

    @staticmethod
    def _continuation_context(
        call: dict[str, Any],
        source_context: dict[str, Any],
        message_id: str,
    ) -> dict[str, Any]:
        """构造 continuation run 的请求上下文。"""
        route_snapshot = source_context.get("route_snapshot") or call.get("proposal_route") or {}
        trace_id = str(
            call.get("trace_id")
            or source_context.get("trace_id")
            or call.get("assistant_run_id")
            or ""
        )
        return {
            "trace_id": trace_id,
            "chat_id": call.get("chat_id"),
            "mode": source_context.get("mode") or "qa",
            "selected_tool_ids": list(source_context.get("selected_tool_ids") or [call.get("tool_id")]),
            "model": source_context.get("model_request") or {},
            "tool_call_ids": [call.get("call_id")],
            "command_id": call.get("command_id") or source_context.get("command_id"),
            "continuation_key": call.get("call_id"),
            "continuation_source": {
                "call_id": call.get("call_id"),
                "original_user_message_id": message_id,
                "context_manifest_digest": source_context.get("context_manifest_digest"),
                "route_snapshot": route_snapshot,
            },
        }

    @staticmethod
    def _record_continuation_run(call: dict[str, Any], run_id: str) -> None:
        """把 continuation run 关联写回工具调用。"""
        call_id = str(call.get("call_id") or "")
        if not call_id or not run_id:
            return
        current = AssistantToolCallRepository.find_one({"call_id": call_id}) or call
        if (
            current.get("continuation_run_id") == run_id
            and current.get("continuation_state") in {"scheduled", "completed"}
        ):
            return
        AssistantToolCallRepository.update_fields(
            call_id,
            {
                "continuation_state": "scheduled",
                "continuation_run_id": run_id,
                "continuation_attempts": 0,
                "continuation_next_retry_at": None,
                "continuation_dead_letter_reason": None,
                "continuation_error": None,
                "updated_at": utc_now(),
            },
        )
        AssistantToolCallRepository.append_event(
            call_id,
            {
                "type": "tool.continuation.run_created",
                "call_id": call_id,
                "continuation_run_id": run_id,
                "created_at": utc_now(),
            },
        )

    def _defer_continuation(self, call: dict[str, Any], exc: Exception) -> None:
        """对活动 run 冲突做指数退避，并在超过尝试上限后转入死信。"""
        call_id = str(call.get("call_id") or "")
        if not call_id:
            return
        attempts = int(call.get("continuation_attempts") or 0) + 1
        now = utc_now()
        error = {
            "error_type": type(exc).__name__,
            "message": str(exc)[:2000],
        }
        if attempts >= MAX_CONTINUATION_ATTEMPTS:
            update = {
                "continuation_state": "dead_letter",
                "continuation_attempts": attempts,
                "continuation_next_retry_at": None,
                "continuation_dead_letter_reason": "活动回答冲突重试超限",
                "continuation_error": error,
                "updated_at": now,
            }
            event_type = "tool.continuation.dead_letter"
        else:
            backoff_seconds = min(
                CONTINUATION_MAX_BACKOFF_SECONDS,
                CONTINUATION_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)),
            )
            update = {
                "continuation_state": "pending",
                "continuation_attempts": attempts,
                "continuation_next_retry_at": now + timedelta(seconds=backoff_seconds),
                "continuation_dead_letter_reason": None,
                "continuation_error": error,
                "updated_at": now,
            }
            event_type = "tool.continuation.retry_scheduled"
        AssistantToolCallRepository.update_fields(call_id, update)
        AssistantToolCallRepository.append_event(
            call_id,
            {
                "type": event_type,
                "call_id": call_id,
                "continuation_attempts": attempts,
                "continuation_error": error,
                "created_at": now,
            },
        )
        logger.info(
            "assistant continuation deferred call_id=%s attempts=%d",
            call_id,
            attempts,
        )

    @staticmethod
    def _record_continuation_failure(call: dict[str, Any], exc: Exception) -> None:
        """记录自动续答创建失败，避免同一调用反复重试。"""
        call_id = str(call.get("call_id") or "")
        if not call_id:
            return
        error = {
            "error_type": type(exc).__name__,
            "message": str(exc)[:2000],
        }
        AssistantToolCallRepository.update_fields(
            call_id,
            {
                "continuation_state": "failed",
                "continuation_error": error,
                "updated_at": utc_now(),
            },
        )
        AssistantToolCallRepository.append_event(
            call_id,
            {
                "type": "tool.continuation.failed",
                "call_id": call_id,
                "continuation_error": error,
                "created_at": utc_now(),
            },
        )

    @staticmethod
    def _finalize_continuation_calls(run_id: str, *, status: str, error: dict[str, Any] | None = None) -> None:
        """在 continuation run 结束后回写关联工具调用状态。"""
        if not run_id:
            return
        calls, _ = AssistantToolCallRepository.list_all(
            {"continuation_run_id": run_id},
            sort_field="updated_at",
            reverse=False,
            page=1,
            page_size=100,
        )
        state = "completed" if status == "completed" else "failed"
        for call in calls:
            call_id = str(call.get("call_id") or "")
            if not call_id:
                continue
            AssistantToolCallRepository.update_fields(
                call_id,
                {
                    "continuation_state": state,
                    "continuation_error": error,
                    "updated_at": utc_now(),
                },
            )
            AssistantToolCallRepository.append_event(
                call_id,
                {
                    "type": "tool.continuation.finished",
                    "call_id": call_id,
                    "continuation_state": state,
                    "continuation_error": error,
                    "created_at": utc_now(),
                },
            )

    def execute_next(self, worker_id: str) -> str | None:
        now = utc_now()
        document = AssistantRunRepository.claim_next(worker_id, now)
        if not document:
            return None
        run_id = document["run_id"]
        created_at = document["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        queue_wait_ms = max(0, int((now - created_at).total_seconds() * 1000))
        AssistantRunRepository.update_claim(run_id, worker_id, {"queue_wait_ms": queue_wait_ms})
        self._event(run_id, {"type": "run_status", "status": "running", "stage": "running"})
        self._execute(document)
        return run_id

    def _execute(self, document: dict[str, Any]) -> None:
        run_id = document["run_id"]
        worker_id = document["worker_id"]
        started = time.monotonic()
        snapshot = document.get("request_snapshot") or {}
        request_messages = self.model_visible_messages(snapshot.get("messages") or [])
        if snapshot.get("content"):
            request_messages.append({"role": "user", "content": snapshot["content"]})
        request = AssistantChatRequest(messages=request_messages, context=snapshot.get("context") or {})
        final_data: dict[str, Any] | None = None
        failed_message = ""
        first_token_ms: int | None = None
        content = ""
        pending_delta = ""
        last_delta_flush = time.monotonic()
        try:
            record_llm_observation_scope({"run_id": run_id})
            llm_client.reset_stream_usage()
            for event in stream_chat_assistant(
                request, {"user_id": document["created_by"], "role": document.get("actor_role") or "user"}
            ):
                current = AssistantRunRepository.find_one({"run_id": run_id}) or {}
                if current.get("status") != "running" or current.get("worker_id") != worker_id:
                    return
                now = utc_now()
                if event.get("type") == "answer_delta":
                    delta = str(event.get("delta") or "")
                    if first_token_ms is None:
                        first_token_ms = int((time.monotonic() - started) * 1000)
                    content += delta
                    pending_delta += delta
                    should_flush = (
                        len(pending_delta) >= ANSWER_DELTA_PERSIST_CHAR_THRESHOLD
                        or time.monotonic() - last_delta_flush >= ANSWER_DELTA_PERSIST_INTERVAL_SECONDS
                    )
                    if not should_flush:
                        continue
                    if not self._persist_answer_delta(
                        run_id,
                        worker_id,
                        content,
                        pending_delta,
                        now,
                        first_token_ms,
                    ):
                        return
                    pending_delta = ""
                    last_delta_flush = time.monotonic()
                    continue

                if pending_delta:
                    if not self._persist_answer_delta(
                        run_id,
                        worker_id,
                        content,
                        pending_delta,
                        now,
                        first_token_ms,
                    ):
                        return
                    pending_delta = ""
                    last_delta_flush = time.monotonic()

                fields: dict[str, Any] = {"heartbeat_at": now, "updated_at": now}
                if event.get("type") == "status":
                    fields["stage"] = event.get("stage") or "running"
                elif event.get("type") == "route.resolved":
                    route = dict(event.get("route") or {})
                    fields["route"] = route
                    if route.get("provider_id"):
                        fields["provider_id"] = route.get("provider_id")
                    if route.get("model_id"):
                        fields["model_id"] = route.get("model_id")
                elif event.get("type") == "context.assembled":
                    manifest = dict(event.get("manifest") or {})
                    request_kind = str(manifest.get("request_kind") or event.get("request_kind") or "")
                    if request_kind:
                        manifests = dict(current.get("request_manifests") or {})
                        manifests[request_kind] = manifest
                        fields["request_manifests"] = manifests
                elif event.get("type") == "final":
                    final_data = dict(event.get("data") or {})
                    content = str(final_data.get("content") or content)
                    fields["partial_content"] = content
                elif event.get("type") == "error":
                    failed_message = str(event.get("message") or "回答生成失败")
                if not AssistantRunRepository.update_claim(run_id, worker_id, fields):
                    return
                if event.get("type") == "final" and final_data.get("answer_mode") == "fallback":
                    self._event(
                        run_id,
                        {
                            "type": "route.fallback",
                            "reason": "final_answer_fallback",
                            "route": current.get("route") or {},
                        },
                    )
                self._event(run_id, event)
            if pending_delta:
                if not self._persist_answer_delta(
                    run_id,
                    worker_id,
                    content,
                    pending_delta,
                    utc_now(),
                    first_token_ms,
                ):
                    return
            if failed_message or not final_data:
                self._finish_failed(run_id, worker_id, failed_message or "回答未返回最终结果", started)
                return
            usage = llm_client.get_stream_usage()
            if usage:
                AssistantRunRepository.update_claim(run_id, worker_id, usage)
            self._finish_completed(document, final_data, content, started)
        except Exception as exc:
            logger.exception("assistant run failed run_id=%s", run_id)
            self._finish_failed(run_id, worker_id, str(exc), started, http_status=getattr(exc, "status_code", None))
        finally:
            reset_llm_observation_scope()

    @staticmethod
    def _persist_answer_delta(
        run_id: str,
        worker_id: str,
        content: str,
        delta: str,
        now: Any,
        first_token_ms: int | None,
    ) -> bool:
        """合并写入回答增量与 heartbeat，避免逐 token 产生大量数据库事件。

        Args:
            run_id: 回答任务 ID。
            worker_id: 当前 worker ID。
            content: 当前累积的完整回答正文。
            delta: 本次待持久化的增量文本。
            now: 当前时间。
            first_token_ms: 首个 token 耗时，若已写入可重复覆盖为相同值。

        Returns:
            更新认领是否成功。
        """
        if not delta:
            return True
        fields: dict[str, Any] = {
            "partial_content": content,
            "heartbeat_at": now,
            "updated_at": now,
        }
        if first_token_ms is not None:
            fields["first_token_ms"] = first_token_ms
        if not AssistantRunRepository.update_claim(run_id, worker_id, fields):
            return False
        AssistantRunService._event(run_id, {"type": "answer_delta", "delta": delta})
        return True

    def _finish_completed(self, document: dict[str, Any], data: dict[str, Any], content: str, started: float) -> None:
        run_id = document["run_id"]
        latest = AssistantRunRepository.find_one({"run_id": run_id}) or {}
        if latest.get("status") != "running" or latest.get("worker_id") != document.get("worker_id"):
            return
        assistant_message_id = latest.get("assistant_message_id")
        if not assistant_message_id:
            existing = AssistantMessageRepository.find_one({
                "chat_id": document["chat_id"], "created_by": document["created_by"], "metadata.run_id": run_id,
            })
            assistant_message_id = existing.get("message_id") if existing else None
        if not assistant_message_id:
            response_tool_call_ids = [
                call.get("call_id")
                for call in data.get("tool_calls") or []
                if call.get("call_id")
            ]
            continuation_tool_call_ids = (
                (document.get("request_snapshot") or {}).get("context") or {}
            ).get("tool_call_ids") or []
            tool_call_ids = list(dict.fromkeys([
                str(call_id)
                for call_id in [*response_tool_call_ids, *continuation_tool_call_ids]
                if str(call_id)
            ]))
            message = assistant_chat_service.create_message(
                document["chat_id"],
                AssistantMessageCreate(
                    role="assistant",
                    content=content,
                    references=data.get("references") or [],
                    reasoning_summary=data.get("reasoning_summary") or [],
                    answer_mode=data.get("answer_mode"),
                    answer_scope=data.get("answer_scope"),
                    retrieval_status=data.get("retrieval_status"),
                    tool_call_ids=tool_call_ids,
                    metadata={
                        "run_id": run_id,
                        "trace_id": document.get("trace_id"),
                        "llm_route": ((data.get("grounding_facts") or {}).get("llm_route")) or {},
                        "context_digest": (
                            (data.get("grounding_facts") or {}).get("context", {}).get("digest")
                        ),
                        "continuation_tool_call_ids": continuation_tool_call_ids,
                    },
                ),
                {"user_id": document["created_by"], "role": document.get("actor_role") or "user"},
            )
            assistant_message_id = message.message_id
        now = utc_now()
        duration_ms = int((time.monotonic() - started) * 1000)
        AssistantRunRepository.update_claim(
            run_id,
            document["worker_id"],
            {
                "status": "completed", "active": False, "stage": "completed", "assistant_message_id": assistant_message_id,
                "partial_content": content, "finished_at": now, "heartbeat_at": now, "updated_at": now,
                "duration_ms": duration_ms,
            },
        )
        self._event(run_id, {"type": "run_status", "status": "completed", "stage": "completed", "assistant_message_id": assistant_message_id})
        self._finalize_continuation_calls(run_id, status="completed")
        logger.info("assistant run completed run_id=%s duration_ms=%d", run_id, duration_ms)

    def _finish_failed(self, run_id: str, worker_id: str, message: str, started: float, http_status: int | None = None) -> None:
        now = utc_now()
        duration_ms = int((time.monotonic() - started) * 1000)
        rate_limited = http_status == 429 or "429" in message
        AssistantRunRepository.update_claim(
            run_id, worker_id,
            {"status": "failed", "active": False, "stage": "failed", "error": {"message": message}, "finished_at": now,
             "heartbeat_at": now, "updated_at": now, "duration_ms": duration_ms,
             "http_status": 429 if rate_limited else http_status, "rate_limited": rate_limited},
        )
        self._event(run_id, {"type": "run_status", "status": "failed", "stage": "failed", "error": {"message": message}})
        self._finalize_continuation_calls(
            run_id,
            status="failed",
            error={"message": message},
        )
        logger.warning("assistant run failed run_id=%s duration_ms=%d rate_limited=%s", run_id, duration_ms, rate_limited)

    @staticmethod
    def _event(run_id: str, event: dict[str, Any]) -> None:
        AssistantRunRepository.append_event(run_id, {**event, "at": utc_now()})

    @staticmethod
    def requeue_stale(stale_seconds: int = 120) -> int:
        now = utc_now()
        run_ids = AssistantRunRepository.requeue_stale(now - timedelta(seconds=stale_seconds), now)
        for run_id in run_ids:
            AssistantRunService._event(
                run_id, {"type": "reset", "stage": "queued", "message": "服务恢复，正在重新生成回答"}
            )
        return len(run_ids)


assistant_run_service = AssistantRunService()
