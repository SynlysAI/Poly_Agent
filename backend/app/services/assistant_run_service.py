"""Persistent, user-serialized execution for LUI assistant answers."""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta
from typing import Any, Iterator
from uuid import uuid4

from fastapi import HTTPException

from app.core.logging import get_logger
from app.core.time import utc_now
from app.core import llm_client
from app.infra.research_engine_repositories import AssistantMessageRepository, AssistantRunRepository
from app.schemas.assistant import AssistantChatRequest
from app.schemas.assistant_chats import AssistantMessageCreate
from app.schemas.assistant_runs import AssistantRun, AssistantRunCreate, AssistantRunListData
from app.services.assistant_chat_service import actor_id, assistant_chat_service
from app.services.assistant_service import stream_chat_assistant


logger = get_logger("poly_agent.assistant_runs")
TERMINAL_STATUSES = {"completed", "failed", "canceled"}


class AssistantRunService:
    @staticmethod
    def _public(document: dict[str, Any]) -> AssistantRun:
        return AssistantRun.model_validate(document)

    @staticmethod
    def _owned(run_id: str, current_user: dict[str, str] | None) -> dict[str, Any]:
        document = AssistantRunRepository.find_one({"run_id": run_id})
        if not document:
            raise HTTPException(status_code=404, detail=f"回答任务 '{run_id}' 不存在")
        if document.get("created_by") != actor_id(current_user):
            raise HTTPException(status_code=403, detail="无权限访问该回答任务")
        return document

    def create(
        self,
        chat_id: str,
        payload: AssistantRunCreate,
        current_user: dict[str, str] | None,
    ) -> AssistantRun:
        owner_id = actor_id(current_user)
        assistant_chat_service._owned_chat(chat_id, owner_id)
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
        context = dict(payload.context)
        context["chat_id"] = chat_id
        model = context.get("model") or {}
        requested_provider_id = model.get("providerId") or model.get("provider_id")
        requested_model_id = model.get("modelId") or model.get("model_id")
        document = {
            "run_id": f"asrun_{uuid4().hex[:16]}",
            "chat_id": chat_id,
            "created_by": owner_id,
            "user_message_id": payload.user_message_id or "",
            "status": "queued",
            "active": True,
            "stage": "queued",
            "request_snapshot": {
                "content": payload.content.strip(),
                "messages": payload.messages,
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

    def list_for_chat(
        self, chat_id: str, current_user: dict[str, str] | None, *, page: int = 1, page_size: int = 20
    ) -> AssistantRunListData:
        owner_id = actor_id(current_user)
        assistant_chat_service._owned_chat(chat_id, owner_id)
        items, total = AssistantRunRepository.list_for_chat(chat_id, owner_id, page, page_size)
        active = next((item for item in items if item.get("status") in {"queued", "running"}), None)
        return AssistantRunListData(
            items=[self._public(item) for item in items],
            active=self._public(active) if active else None,
            total=total,
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
        self._owned(run_id, current_user)
        if after_seq > 0:
            AssistantRunRepository.increment_metric(run_id, "reconnect_count")
        cursor = max(0, after_seq)
        idle_polls = 0
        while True:
            events = AssistantRunRepository.events_after(run_id, cursor)
            for event in events:
                cursor = max(cursor, int(event.get("seq", 0)))
                yield event
            document = self._owned(run_id, current_user)
            if document.get("status") in TERMINAL_STATUSES and not AssistantRunRepository.events_after(run_id, cursor):
                return
            idle_polls += 1
            if idle_polls % 15 == 0:
                yield {"type": "heartbeat", "seq": cursor, "status": document.get("status")}
            time.sleep(1)

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
        request_messages = list(snapshot.get("messages") or [])
        if snapshot.get("content"):
            request_messages.append({"role": "user", "content": snapshot["content"]})
        request = AssistantChatRequest(messages=request_messages, context=snapshot.get("context") or {})
        final_data: dict[str, Any] | None = None
        failed_message = ""
        first_token_ms: int | None = None
        content = ""
        try:
            llm_client.reset_stream_usage()
            for event in stream_chat_assistant(
                request, {"user_id": document["created_by"], "role": document.get("actor_role") or "user"}
            ):
                current = AssistantRunRepository.find_one({"run_id": run_id}) or {}
                if current.get("status") != "running" or current.get("worker_id") != worker_id:
                    return
                now = utc_now()
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
                elif event.get("type") == "answer_delta":
                    content += str(event.get("delta") or "")
                    fields["partial_content"] = content
                    if first_token_ms is None:
                        first_token_ms = int((time.monotonic() - started) * 1000)
                        fields["first_token_ms"] = first_token_ms
                elif event.get("type") == "final":
                    final_data = dict(event.get("data") or {})
                    content = str(final_data.get("content") or content)
                    fields["partial_content"] = content
                elif event.get("type") == "error":
                    failed_message = str(event.get("message") or "回答生成失败")
                if not AssistantRunRepository.update_claim(run_id, worker_id, fields):
                    return
                self._event(run_id, event)
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
                    tool_call_ids=[call.get("call_id") for call in data.get("tool_calls") or [] if call.get("call_id")],
                    metadata={
                        "run_id": run_id,
                        "llm_route": ((data.get("grounding_facts") or {}).get("llm_route")) or {},
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
