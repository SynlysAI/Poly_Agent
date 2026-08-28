"""LUI Execution Trace 投影、快照与实时事件服务。"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.core.logging import get_logger
from app.core.time import utc_now
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantEventRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant_trace import (
    AssistantChatTraceData,
    AssistantTraceData,
    AssistantTraceCommand,
    AssistantTraceRun,
    AssistantTraceSourceRef,
    AssistantTraceStatus,
    AssistantTraceStep,
    AssistantTraceStepDetails,
    AssistantTraceStepStatus,
    AssistantTraceSummary,
    AssistantTraceToolCall,
)
from app.services.assistant_chat_service import actor_id


logger = get_logger("poly_agent.assistant_trace")

TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}
ACTIVE_RUN_STATUSES = {"queued", "running"}
WAITING_TOOL_PHASES = {"awaiting_input", "awaiting_confirmation"}
ACTIVE_TOOL_PHASES = {"queued", "running"}
TERMINAL_TOOL_PHASES = {"completed", "failed", "canceled"}
TRACE_POLL_INTERVAL_SECONDS = 0.5
TRACE_HEARTBEAT_INTERVAL_SECONDS = 15.0
SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|token|password|secret|authorization)\b\s*[:=]\s*\S+"
)


class AssistantTraceProjectionService:
    """从 append-only 事件构造用户可理解的执行轨迹。

    服务只做只读投影，不反向修改 AssistantRun、工具调用或统一事件日志。
    """

    def get(self, trace_id: str, current_user: dict[str, str] | None) -> AssistantTraceData:
        """读取一条用户请求的完整 Trace 快照。

        Args:
            trace_id: 初始 AssistantRun ID。
            current_user: 当前用户。

        Returns:
            标准 Trace 快照。

        Raises:
            HTTPException: Trace 不存在或无权限访问。
        """
        normalized_trace_id = str(trace_id or "").strip()
        runs = self._runs_for_trace(normalized_trace_id)
        root = runs[0] if runs else None
        if not root:
            raise HTTPException(status_code=404, detail=f"执行轨迹 '{trace_id}' 不存在")
        owner_id = actor_id(current_user)
        if root.get("created_by") != owner_id:
            raise HTTPException(status_code=403, detail="无权限访问该执行轨迹")

        run_ids = {str(item.get("run_id") or "") for item in runs}
        calls = self._calls_for_trace(normalized_trace_id, run_ids)
        events = self._events_for_trace(normalized_trace_id, runs, calls)
        steps, warnings = self._project_steps(normalized_trace_id, events, calls)
        status = self._derive_status(runs, calls, steps, events)
        summary = self._build_summary(steps, calls, events, status, warnings)

        timestamps = [self._event_time(event) for event in events]
        timestamps = [item for item in timestamps if item is not None]
        created_at = (
            self._min_datetime(timestamps)
            or self._parse_datetime(root.get("created_at"))
            or utc_now().replace(tzinfo=timezone.utc)
        )
        updated_at = (
            self._max_datetime(timestamps)
            or self._parse_datetime(root.get("updated_at"))
            or created_at
        )
        cursor = str(events[-1].get("event_id") or "") if events else ""

        return AssistantTraceData(
            trace_id=normalized_trace_id,
            chat_id=str(root.get("chat_id") or ""),
            user_message_id=str(root.get("user_message_id") or ""),
            root_run_id=str(root.get("run_id") or normalized_trace_id),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            runs=[self._trace_run(item) for item in runs],
            tool_calls=[self._trace_tool_call(item) for item in calls],
            steps=steps,
            summary=summary,
            cursor=cursor,
            replay_warnings=warnings,
        )

    def get_many(
        self,
        trace_ids: list[str],
        current_user: dict[str, str] | None,
    ) -> list[AssistantTraceData]:
        """批量读取当前用户有权限访问的 Trace 快照。

        Args:
            trace_ids: 需要恢复的 Trace ID 列表。
            current_user: 当前登录用户。

        Returns:
            可访问的 Trace 快照列表；不存在或无权限的 ID 会被忽略。
        """
        items: list[AssistantTraceData] = []
        for trace_id in list(dict.fromkeys(trace_ids)):
            if not trace_id:
                continue
            try:
                items.append(self.get(trace_id, current_user))
            except HTTPException:
                continue
        return items

    def get_chat(
        self,
        chat_id: str,
        current_user: dict[str, str] | None,
        *,
        after_seq: int = 0,
        event_types: set[str] | None = None,
    ) -> AssistantChatTraceData:
        """读取一个会话的命令、模型、工具与控制面统一 Trace。

        Args:
            chat_id: 会话 ID。
            current_user: 当前用户。
            after_seq: 会话级回放游标，只返回之后的事件投影。
            event_types: 可选事件类型白名单。

        Returns:
            会话级 Trace 快照与下一个游标。

        Raises:
            HTTPException: 会话不存在或无权限访问。
        """
        normalized_chat_id = str(chat_id or "").strip()
        owner_id = actor_id(current_user)
        chat = AssistantChatRepository.find_one({"chat_id": normalized_chat_id})
        if not chat:
            raise HTTPException(status_code=404, detail=f"会话 '{chat_id}' 不存在")
        if str(chat.get("created_by") or "") != owner_id:
            raise HTTPException(status_code=403, detail="无权限访问该会话轨迹")

        runs, _ = AssistantRunRepository.list_for_chat(
            normalized_chat_id,
            owner_id,
            page=1,
            page_size=10_000,
        )
        calls = AssistantToolCallRepository.list_for_chat(
            normalized_chat_id,
            created_by=owner_id,
        )
        command_documents, _ = AssistantCommandRunRepository.list_runs_for_chat(
            normalized_chat_id,
            owner_id,
            page=1,
            page_size=10_000,
        )
        events = self._events_for_chat(normalized_chat_id, owner_id, runs, calls)
        events = self._assign_chat_sequence(events)

        all_steps, warnings = self._project_steps(normalized_chat_id, events, calls)
        for step in all_steps:
            step.trace_id = normalized_chat_id

        eligible_events = [
            event
            for event in events
            if int(event.get("chat_seq") or 0) > int(after_seq)
            and (event_types is None or str(event.get("type") or "") in event_types)
        ]
        eligible_event_ids = {
            str(event.get("event_id") or "") for event in eligible_events
        }
        steps = [
            step
            for step in all_steps
            if any(ref.event_id in eligible_event_ids for ref in step.details.source_event_refs)
        ]
        next_after_seq = max(
            [
                int(event.get("chat_seq") or 0)
                for event in events
                if int(event.get("chat_seq") or 0) > int(after_seq)
            ],
            default=int(after_seq),
        )
        status = self._derive_status(runs, calls, all_steps, events)
        summary = self._build_summary(all_steps, calls, events, status, warnings)
        timestamps = [self._event_time(event) for event in events]
        timestamps = [item for item in timestamps if item is not None]
        created_at = (
            self._min_datetime(timestamps)
            or self._parse_datetime(chat.get("created_at"))
            or utc_now().replace(tzinfo=timezone.utc)
        )
        updated_at = (
            self._max_datetime(timestamps)
            or self._parse_datetime(chat.get("updated_at"))
            or created_at
        )

        return AssistantChatTraceData(
            chat_id=normalized_chat_id,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            runs=[self._trace_run(item) for item in runs],
            tool_calls=[self._trace_tool_call(item) for item in calls],
            commands=[self._trace_command(item) for item in command_documents],
            steps=steps,
            summary=summary,
            next_after_seq=next_after_seq,
            total_events=len(events),
            replay_warnings=warnings,
        )

    def events(
        self,
        trace_id: str,
        current_user: dict[str, str] | None,
        after_event_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """以 SSE payload 形式输出 Trace 增量事件。

        Args:
            trace_id: 初始 AssistantRun ID。
            current_user: 当前用户。
            after_event_id: 断线重连时最后确认的原始事件 ID。

        Yields:
            trace.step / trace.summary / trace.end / trace.heartbeat payload。
        """
        trace = self.get(trace_id, current_user)
        emitted: set[str] = set()
        cursor = str(after_event_id or "")
        if not cursor:
            yield from self._yield_steps(trace, emitted)
        last_heartbeat = time.monotonic()
        terminal_seen = False

        while not terminal_seen:
            new_event_ids = self._events_after_cursor(trace_id, cursor)
            if new_event_ids:
                trace = self.get(trace_id, current_user)
                yield from self._yield_steps(trace, emitted, new_event_ids)
                cursor = trace.cursor
                if trace.status in TERMINAL_RUN_STATUSES:
                    yield from self._terminal_trace_events(trace)
                    terminal_seen = True
                    break
            else:
                status_document = AssistantRunRepository.find_trace_status(trace_id)
                if str(status_document.get("status") or "") in TERMINAL_RUN_STATUSES:
                    trace = self.get(trace_id, current_user)
                    yield from self._terminal_trace_events(trace)
                    terminal_seen = True
                    break
            now = time.monotonic()
            if now - last_heartbeat >= TRACE_HEARTBEAT_INTERVAL_SECONDS:
                last_heartbeat = now
                yield {"type": "trace.heartbeat", "trace_id": trace.trace_id, "cursor": cursor}
            time.sleep(TRACE_POLL_INTERVAL_SECONDS)

    @staticmethod
    def _terminal_trace_events(trace: AssistantTraceData) -> Iterator[dict[str, Any]]:
        """输出 Trace 终态 summary 与 end 事件。"""
        yield {
            "type": "trace.summary",
            "trace_id": trace.trace_id,
            "status": trace.status,
            "summary": trace.summary.model_dump(mode="python"),
        }
        yield {"type": "trace.end", "trace_id": trace.trace_id, "status": trace.status}

    def _yield_steps(
        self,
        trace: AssistantTraceData,
        emitted: set[str],
        allowed_event_ids: set[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """输出符合 cursor 条件的 Trace step，并允许增量事件更新既有步骤。"""
        for step in trace.steps:
            if allowed_event_ids is None and step.step_id in emitted:
                continue
            refs = {item.event_id for item in step.details.source_event_refs}
            if allowed_event_ids is not None and not refs.intersection(allowed_event_ids):
                continue
            emitted.add(step.step_id)
            yield {
                "type": "trace.step",
                "trace_id": trace.trace_id,
                "step": step.model_dump(mode="python"),
            }

    def _events_after_cursor(self, trace_id: str, cursor: str) -> set[str]:
        """返回排序事件流中 cursor 之后的新事件 ID。"""
        events = AssistantEventRepository.list_for_trace(trace_id)
        ids = [str(item.get("event_id") or "") for item in events]
        if not cursor:
            return set(ids)
        if cursor not in ids:
            return set(ids)
        return set(ids[ids.index(cursor) + 1 :])

    @staticmethod
    def _runs_for_trace(trace_id: str) -> list[dict[str, Any]]:
        """查找 Trace 直接或历史关联的所有 AssistantRun。"""
        return AssistantRunRepository.list_for_trace(trace_id)

    @staticmethod
    def _calls_for_trace(trace_id: str, run_ids: set[str]) -> list[dict[str, Any]]:
        """查找 Trace 直接或历史关联的所有算法工具调用。"""
        return AssistantToolCallRepository.list_for_trace(trace_id, run_ids)

    def _events_for_trace(
        self,
        trace_id: str,
        runs: Iterable[dict[str, Any]],
        calls: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """聚合统一事件与旧 embedded 事件并按时间排序。"""
        run_items = list(runs)
        call_items = list(calls)
        run_ids = {str(item.get("run_id") or "") for item in run_items}
        call_ids = {str(item.get("call_id") or "") for item in call_items}
        events: dict[str, dict[str, Any]] = {}
        for event in AssistantEventRepository.list_for_trace(trace_id):
            event_id = str(event.get("event_id") or "")
            if event_id:
                events[event_id] = event

        unified_by_run: dict[str, list[dict[str, Any]]] = {}
        for event in AssistantEventRepository.list_for_run_ids(run_ids):
            event_id = str(event.get("event_id") or "")
            if event_id:
                events[event_id] = event
            unified_by_run.setdefault(str(event.get("run_id") or ""), []).append(event)

        unified_by_call: dict[str, list[dict[str, Any]]] = {}
        for event in AssistantEventRepository.list_for_call_ids(call_ids):
            event_id = str(event.get("event_id") or "")
            if event_id:
                events[event_id] = event
            unified_by_call.setdefault(str(event.get("call_id") or ""), []).append(event)

        for run in run_items:
            run_id = str(run.get("run_id") or "")
            unified = unified_by_run.get(run_id, [])
            unified_seqs = {int(item.get("seq") or 0) for item in unified}
            for event in run.get("events") or []:
                seq = int(event.get("seq") or 0)
                event_id = f"embedded:{run_id}:{seq}"
                if seq in unified_seqs:
                    continue
                events[event_id] = self._embedded_event(event, event_id, run_id=run_id, call_id="")
        for call in call_items:
            call_id = str(call.get("call_id") or "")
            unified_events = unified_by_call.get(call_id, [])
            unified_seqs = {
                int(item.get("seq") or 0)
                for item in unified_events
            }
            for event in call.get("events") or []:
                seq = int(event.get("seq") or 0)
                event_id = f"embedded:{call_id}:{seq}"
                if seq in unified_seqs:
                    continue
                events[event_id] = self._embedded_event(
                    event,
                    event_id,
                    run_id=str(call.get("assistant_run_id") or ""),
                    call_id=call_id,
                )
        ordered = list(events.values())
        return sorted(ordered, key=lambda item: (self._event_sort_text(item), str(item.get("event_id") or "")))

    def _events_for_chat(
        self,
        chat_id: str,
        owner_id: str,
        runs: Iterable[dict[str, Any]],
        calls: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """聚合一个会话内 run、tool、command 与旧 embedded 事件。

        Args:
            chat_id: 会话 ID。
            owner_id: 会话 owner。
            runs: 会话中的 AssistantRun 文档。
            calls: 会话中的 AssistantToolCall 文档。

        Returns:
            按时间稳定排序的事件列表。
        """
        events: dict[str, dict[str, Any]] = {}
        unified_events, _ = AssistantEventRepository.list_all(
            {"chat_id": chat_id, "created_by": owner_id},
            page=1,
            page_size=10_000,
        )
        unified_keys: set[tuple[str, str, int]] = set()
        legacy_tool_keys: set[tuple[str, int]] = set()
        for event in unified_events:
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            events[event_id] = event
            unified_keys.add(self._event_identity(event))
            if str(event.get("type") or "").startswith("tool."):
                legacy_tool_keys.add(
                    (str(event.get("run_id") or ""), int(event.get("seq") or 0))
                )

        for run in runs:
            run_id = str(run.get("run_id") or "")
            for event in run.get("events") or []:
                identity = (run_id, "", int(event.get("seq") or 0))
                if identity in unified_keys:
                    continue
                event_id = f"embedded:{run_id}:{identity[2]}"
                events[event_id] = self._embedded_event(
                    event,
                    event_id,
                    run_id=run_id,
                    call_id="",
                )

        for call in calls:
            call_id = str(call.get("call_id") or "")
            run_id = str(call.get("assistant_run_id") or "")
            for event in call.get("events") or []:
                identity = (run_id, call_id, int(event.get("seq") or 0))
                if identity in unified_keys:
                    continue
                if (run_id, identity[2]) in legacy_tool_keys:
                    continue
                event_id = f"embedded:call:{call_id}:{identity[2]}"
                events[event_id] = self._embedded_event(
                    event,
                    event_id,
                    run_id=run_id,
                    call_id=call_id,
                )

        ordered = list(events.values())
        return sorted(ordered, key=lambda item: (self._event_sort_text(item), str(item.get("event_id") or "")))

    @staticmethod
    def _event_identity(event: dict[str, Any]) -> tuple[str, str, int]:
        """生成去重身份键，避免不同 run/call 的本地 seq 互相误伤。"""
        return (
            str(event.get("run_id") or ""),
            str(event.get("call_id") or ""),
            int(event.get("seq") or 0),
        )

    @classmethod
    def _assign_chat_sequence(cls, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """为会话时间线生成连续、稳定的回放序号。

        Args:
            events: 已按时间稳定排序的事件。

        Returns:
            带 chat_seq 的事件副本。
        """
        result: list[dict[str, Any]] = []
        for index, event in enumerate(events, start=1):
            result.append({**event, "chat_seq": index})
        return result

    @staticmethod
    def _embedded_event(event: dict[str, Any], event_id: str, *, run_id: str, call_id: str) -> dict[str, Any]:
        """把旧 embedded 事件转换成投影用统一事件形状。"""
        payload = {key: value for key, value in event.items() if key not in {"seq", "at"}}
        return {
            "event_id": event_id,
            "run_id": run_id,
            "call_id": call_id or payload.get("call_id") or "",
            "trace_id": "",
            "seq": int(event.get("seq") or 0),
            "type": AssistantEventRepository.canonical_type(payload),
            "at": event.get("at") or event.get("created_at"),
            "data": payload,
        }

    def _project_steps(
        self,
        trace_id: str,
        events: list[dict[str, Any]],
        calls: list[dict[str, Any]],
    ) -> tuple[list[AssistantTraceStep], list[str]]:
        """把统一事件投影为标准步骤，并返回回放警告。"""
        calls_by_id = {str(item.get("call_id") or ""): item for item in calls}
        origin_run_ids = {
            str(item.get("assistant_run_id") or "")
            for item in calls
            if item.get("assistant_run_id")
        }
        accumulator: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        context_starts: set[str] = set()
        context_finished: set[str] = set()
        retrieval_starts: set[str] = set()
        retrieval_finished: set[str] = set()
        llm_started: set[str] = set()
        llm_finished: set[str] = set()

        for event in events:
            event_id = str(event.get("event_id") or "")
            event_type = str(event.get("type") or "")
            data = dict(event.get("data") or {})
            ref = self._source_ref(event)
            timestamp = self._event_time(event) or utc_now().replace(tzinfo=timezone.utc)

            if event_type in {"command.run", "command.done"}:
                command_id = str(data.get("command_id") or event.get("trace_id") or event_id)
                command_name = str(data.get("name") or "unknown")
                done = event_type == "command.done"
                command_status = str(data.get("status") or "")
                status = "running"
                if done:
                    status = {
                        "success": "success",
                        "interaction": "waiting",
                        "failed": "failed",
                    }.get(command_status, "failed")
                self._upsert(
                    accumulator,
                    step_id=f"command:{command_id}",
                    step_type="command",
                    title=f"Slash 命令 /{command_name}",
                    summary=(
                        self._safe_text(data.get("message"), 180)
                        or (f"/{command_name} 已开始" if not done else f"/{command_name} 已结束")
                    ),
                    status=status,
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        command_id=command_id,
                        command_name=command_name,
                    ),
                    started_at=None if done else timestamp,
                    ended_at=timestamp if done else None,
                )

            if event_type in {
                "plan.mode.changed",
                "goal.changed",
                "todo.changed",
                "permission.mode.changed",
                "session.reset",
                "session.clear",
            }:
                self._upsert(
                    accumulator,
                    step_id=f"control:{event_id}",
                    step_type="control",
                    title=self._control_title(event_type, data),
                    summary=self._control_summary(event_type, data),
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(event, command_id=data.get("command_id")),
                )

            if event_type.startswith("budget."):
                classification = dict(data.get("classification") or {})
                safe_classification = {
                    "category": classification.get("category"),
                    "confidence": classification.get("confidence"),
                    "fallback_reason": classification.get("fallback_reason"),
                }
                self._upsert(
                    accumulator,
                    step_id=f"budget:{event.get('run_id') or event_id}",
                    step_type="control",
                    title="动态计算预算",
                    summary=(
                        f"{data.get('effective_model_tier') or 'unknown'} 模型 · "
                        f"{data.get('effective_retrieval_tier') or 'unknown'} 检索 · "
                        f"{data.get('effective_execution_tier') or 'unknown'} 执行"
                    ),
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        result_summary={
                            "release_mode": data.get("release_mode"),
                            "rollout_eligible": data.get("rollout_eligible"),
                            "classification": safe_classification,
                            "recommended": data.get("recommended") or {},
                            "effective_model_tier": data.get("effective_model_tier"),
                            "effective_retrieval_tier": data.get("effective_retrieval_tier"),
                            "effective_execution_tier": data.get("effective_execution_tier"),
                            "user_overrides": data.get("user_overrides") or [],
                            "safety_guards": data.get("safety_guards") or [],
                            "fallback_reason": data.get("fallback_reason"),
                            "cost": data.get("cost") or {},
                            "route": data.get("route") or {},
                        },
                    ),
                )

            if event_type == "permission.decision":
                decision = str(data.get("decision") or "denied")
                reason = str(data.get("reason") or "")
                self._upsert(
                    accumulator,
                    step_id=f"permission:{data.get('call_id') or data.get('command_id') or event_id}",
                    step_type="approval",
                    title="权限决策",
                    summary=(
                        f"已允许 {data.get('tool_id') or '工具'} 执行"
                        if decision == "allowed"
                        else f"已阻断 {data.get('tool_id') or '工具'} 执行：{reason}"
                    ),
                    status="success" if decision == "allowed" else "failed",
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        command_id=data.get("command_id"),
                    ),
                )

            if event_type == "context.compacted":
                reduction = int(data.get("token_reduction") or 0)
                self._upsert(
                    accumulator,
                    step_id=f"compact:{data.get('command_id') or event_id}",
                    step_type="context",
                    title="上下文已压缩",
                    summary=f"估算 token 减少 {reduction}",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        command_id=data.get("command_id"),
                        result_summary={"token_reduction": reduction},
                    ),
                )

            if event_type == "session.exported":
                export_status = str(data.get("status") or "completed")
                self._upsert(
                    accumulator,
                    step_id=f"export:{data.get('command_id') or event_id}",
                    step_type="export",
                    title="会话导出",
                    summary=f"{str(data.get('format') or 'json').upper()} 导出{self._status_verb(export_status)}",
                    status="failed" if export_status == "failed" else (
                        "running" if export_status == "started" else "success"
                    ),
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        command_id=data.get("command_id"),
                    ),
                )

            if event_type == "feedback.recorded":
                self._upsert(
                    accumulator,
                    step_id=f"feedback:{data.get('command_id') or event_id}",
                    step_type="feedback",
                    title="会话反馈",
                    summary=f"已记录反馈：{'有帮助' if data.get('rating') == 'helpful' else '需改进'}",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        command_id=data.get("command_id"),
                    ),
                )

            if event_type in {"run.created", "status"} and str(data.get("stage") or "") in {"intent", "facts"}:
                stage = str(data.get("stage") or "intent")
                self._upsert(
                    accumulator,
                    step_id=f"think:{event.get('run_id') or ''}:{stage}",
                    step_type="think",
                    title="识别请求范围" if stage == "intent" else "准备项目事实",
                    summary=self._safe_text(data.get("message"), 160) or ("正在识别问题范围" if stage == "intent" else "正在收集项目事实"),
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                )

            if event_type == "context.assembly.started":
                request_kind = str(data.get("request_kind") or "final_answer")
                context_starts.add(request_kind)
                self._upsert(
                    accumulator,
                    step_id=f"context:{request_kind}",
                    step_type="context",
                    title="上下文准备",
                    summary="正在组装本轮上下文",
                    status="running",
                    timestamp=timestamp,
                    ref=ref,
                    details={"request_kind": request_kind},
                    started_at=timestamp,
                )
            elif event_type in {"context.assembled", "request.header"}:
                request_kind = str(
                    data.get("request_kind")
                    or (data.get("manifest") or {}).get("request_kind")
                    or "final_answer"
                )
                context_finished.add(request_kind)
                context = (data.get("manifest") or {}).get("context") or {}
                sections = (data.get("manifest") or {}).get("sections") or []
                self._upsert(
                    accumulator,
                    step_id=f"context:{request_kind}",
                    step_type="context",
                    title="上下文准备",
                    summary=f"已注入 {len(sections)} 个上下文 section",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details={
                        "request_kind": request_kind,
                        "sections": self._safe_sections(sections),
                        "schema_digest": context.get("digest"),
                    },
                    ended_at=timestamp,
                )
            elif event_type in {"tool.catalog.resolved", "tool.schema.rendered"}:
                request_kind = "tool_proposal"
                self._upsert(
                    accumulator,
                    step_id=f"context:{request_kind}",
                    step_type="context",
                    title="上下文准备",
                    summary="已解析算法工具目录与 schema",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details={"request_kind": request_kind, "tools": data.get("tools") or []},
                )

            if event_type == "retrieval.started":
                source = str(data.get("source") or "knowledge")
                digest = str(data.get("query_digest") or event_id)
                retrieval_starts.add(f"{source}:{digest}")
                self._upsert(
                    accumulator,
                    step_id=f"retrieval:{source}:{digest}",
                    step_type="tool_call",
                    title="知识库检索" if source == "knowledge" else "网页检索",
                    summary="正在检索相关证据",
                    tool_name="Knowledge Base" if source == "knowledge" else "Web Search",
                    tool_type="retrieval",
                    status="running",
                    timestamp=timestamp,
                    ref=ref,
                    details={"request_kind": "retrieval"},
                    started_at=timestamp,
                )
            elif event_type == "evidence":
                source = str(data.get("source") or ("web" if data.get("references") else "knowledge"))
                digest = str(data.get("query_digest") or event_id)
                retrieval_finished.add(f"{source}:{digest}")
                status = "failed" if data.get("status") == "failed" else "success"
                summary = self._safe_text(data.get("message"), 180) or ("检索完成" if status == "success" else "检索失败")
                self._upsert(
                    accumulator,
                    step_id=f"retrieval:{source}:{digest}",
                    step_type="tool_call",
                    title="知识库检索" if source == "knowledge" else "网页检索",
                    summary=summary,
                    tool_name="Knowledge Base" if source == "knowledge" else "Web Search",
                    tool_type="retrieval",
                    status=status,
                    timestamp=timestamp,
                    ref=ref,
                    ended_at=timestamp,
                )
                self._upsert(
                    accumulator,
                    step_id=f"retrieval-result:{source}:{digest}",
                    step_type="tool_result",
                    title="检索结果",
                    summary=f"返回 {len(data.get('references') or [])} 条引用",
                    status=status,
                    timestamp=timestamp,
                    ref=ref,
                    parent_step_id=f"retrieval:{source}:{digest}",
                    details={"result_summary": {"references": len(data.get("references") or [])}},
                )
            elif event_type == "retrieval.result":
                source = str(data.get("source") or "knowledge")
                digest = str(data.get("query_digest") or event_id)
                entries = data.get("results") or []
                used_count = sum(1 for item in entries if bool(item.get("used_in_answer")))
                self._upsert(
                    accumulator,
                    step_id=f"retrieval-result:{source}:{digest}",
                    step_type="tool_result",
                    title="检索结果",
                    summary=f"返回 {len(entries)} 条稳定结果条目，{used_count} 条用于回答",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    parent_step_id=f"retrieval:{source}:{digest}",
                    details={
                        "result_summary": {
                            "entry_count": len(entries),
                            "used_in_answer_count": used_count,
                            "entries": entries,
                        }
                    },
                )

            if event_type.startswith("agent_exec."):
                agent_run_id = str(data.get("run_id") or event_id)
                provider_id = str(data.get("provider_id") or "")
                step_status = "running"
                summary = "外部 Agent 文件任务已受理"
                if event_type == "agent_exec.provider_ready":
                    summary = "外部 Agent 连接器已就绪"
                elif event_type == "agent_exec.started":
                    summary = "外部 Agent 正在受限 workdir 内执行"
                elif event_type == "agent_exec.completed":
                    step_status = "success"
                    summary = "外部 Agent 任务已完成"
                elif event_type in {
                    "agent_exec.failed",
                    "agent_exec.cancelled",
                    "agent_exec.policy.rejected",
                    "agent_exec.provider_unavailable",
                }:
                    step_status = "failed"
                    summary = (
                        self._safe_text(data.get("message"), 180)
                        or self._safe_text(data.get("error_message"), 180)
                        or "外部 Agent 任务未执行成功"
                    )
                self._upsert(
                    accumulator,
                    step_id=f"agent_exec:{agent_run_id}",
                    step_type="agent_exec",
                    title="外部 Agent 文件任务",
                    summary=summary,
                    status=step_status,
                    timestamp=timestamp,
                    ref=ref,
                    details=self._event_details(
                        event,
                        command_id=data.get("command_id"),
                        result_summary={"provider_id": provider_id},
                    ),
                    started_at=None if step_status in {"success", "failed"} else timestamp,
                    ended_at=timestamp if step_status in {"success", "failed"} else None,
                )

            if event_type == "llm.request.started":
                request_id = str(data.get("request_id") or event_id)
                llm_started.add(request_id)
                provider = str(data.get("provider_id") or "")
                model = str(data.get("model_id") or "")
                self._upsert(
                    accumulator,
                    step_id=f"llm:{request_id}",
                    step_type="tool_call",
                    title="模型请求",
                    summary=f"正在请求 {provider or '默认服务'} / {model or '默认模型'}",
                    tool_name=" / ".join(item for item in [provider, model] if item) or "LLM",
                    tool_type="llm",
                    status="running",
                    timestamp=timestamp,
                    ref=ref,
                    details={
                        "provider_id": provider or None,
                        "model_id": model or None,
                        "request_kind": data.get("request_kind"),
                    },
                    started_at=timestamp,
                )
            elif event_type == "llm.usage.recorded":
                request_id = str(data.get("request_id") or event_id)
                llm_finished.add(request_id)
                self._upsert(
                    accumulator,
                    step_id=f"llm:{request_id}",
                    step_type="tool_call",
                    title="模型请求",
                    summary="模型请求完成",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                    details={"request_kind": data.get("request_kind")},
                    ended_at=timestamp,
                )
            elif event_type == "llm.request.failed":
                request_id = str(data.get("request_id") or event_id)
                llm_finished.add(request_id)
                self._upsert(
                    accumulator,
                    step_id=f"llm:{request_id}",
                    step_type="tool_call",
                    title="模型请求",
                    summary="模型请求失败",
                    status="failed",
                    timestamp=timestamp,
                    ref=ref,
                    ended_at=timestamp,
                )
                self._error_step(accumulator, event, timestamp, ref, "LLM", data.get("error_message"))

            if event_type.startswith("tool."):
                call_id = str(data.get("call_id") or event.get("call_id") or "")
                call = calls_by_id.get(call_id, {})
                if call_id:
                    self._project_tool_event(
                        accumulator,
                        event,
                        event_type,
                        data,
                        call,
                        timestamp,
                        ref,
                    )

            if event_type == "asset.uploaded":
                asset_id = str(data.get("asset_id") or event_id)
                self._upsert(
                    accumulator,
                    step_id=f"asset:{asset_id}",
                    step_type="write",
                    title="写入受管资产",
                    summary=f"已上传 {data.get('asset_key') or data.get('filename') or '输入附件'}",
                    tool_name="Runtime Asset",
                    tool_type="asset",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                )

            if event_type in {"tool.continuation.retry_scheduled", "tool.continuation.dead_letter"}:
                retry = event_type.endswith("retry_scheduled")
                self._upsert(
                    accumulator,
                    step_id=f"error:{event_id}",
                    step_type="error",
                    title="续答自动恢复" if retry else "续答重试终止",
                    summary="活动回答冲突，续答将自动重试" if retry else "续答重试超过上限，已转入死信",
                    status="running" if retry else "failed",
                    timestamp=timestamp,
                    ref=ref,
                    details={"retry_scheduled": retry},
                )
            elif event_type == "tool.continuation.run_created":
                continuation_run_id = str(data.get("continuation_run_id") or "")
                self._upsert(
                    accumulator,
                    step_id=f"continuation:{continuation_run_id}",
                    step_type="think",
                    title="准备服务端续答",
                    summary="工具执行结束，正在整理结果并生成最终回答",
                    status="success",
                    timestamp=timestamp,
                    ref=ref,
                )
            elif event_type == "run.failed":
                self._error_step(accumulator, event, timestamp, ref, "AssistantRun", data.get("error", {}).get("message"))

            if event_type == "assistant.finalized":
                run_id = str(event.get("run_id") or "")
                proposal_run = run_id in origin_run_ids
                if not calls or not proposal_run:
                    self._upsert(
                        accumulator,
                        step_id=f"final:{trace_id}",
                        step_type="final",
                        title="任务完成",
                        summary=self._safe_text(data.get("content"), 180) or "最终回答已生成",
                        status="success",
                        timestamp=timestamp,
                        ref=ref,
                        details={
                            "result_summary": {
                                "answer_mode": data.get("answer_mode"),
                                "retrieval_status": data.get("retrieval_status"),
                            }
                        },
                    )

        for request_kind in sorted(context_starts - context_finished):
            warnings.append(f"context.assembly.started 未找到完成事件: {request_kind}")
        for key in sorted(retrieval_starts - retrieval_finished):
            warnings.append(f"retrieval.started 未找到完成事件: {key}")
        for request_id in sorted(llm_started ^ llm_finished):
            warnings.append(f"LLM 事件缺少开始或结束配对: {request_id}")
        steps = [self._as_step(item) for item in accumulator.values()]
        for step in steps:
            step.trace_id = trace_id
        steps.sort(key=lambda item: (item.timestamp, item.step_id))
        return steps, warnings

    def _project_tool_event(
        self,
        accumulator: dict[str, dict[str, Any]],
        event: dict[str, Any],
        event_type: str,
        data: dict[str, Any],
        call: dict[str, Any],
        timestamp: datetime,
        ref: AssistantTraceSourceRef,
    ) -> None:
        """把工具事件投影为调用、审批、结果和 artifact 步骤。"""
        call_id = str(data.get("call_id") or event.get("call_id") or "")
        tool_name = str(data.get("tool_name") or call.get("tool_name") or call_id)
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else call.get("arguments") or {}
        common_details = {
            "argument_keys": sorted(str(key) for key in arguments),
            "schema_digest": data.get("schema_digest") or call.get("schema_digest"),
            "algorithm_id": str(call.get("algorithm_id") or call.get("tool_id") or "") or None,
            "algorithm_version": call.get("algorithm_version"),
        }
        tool_step_id = f"tool:{call_id}"
        phase = str(data.get("phase") or "")

        if event_type in {"tool.proposed", "tool.arguments.invalid"}:
            self._upsert(
                accumulator,
                step_id=tool_step_id,
                step_type="tool_call",
                title="算法工具调用",
                summary=f"已生成 {tool_name} 调用提案",
                tool_name=tool_name,
                tool_type="algorithm",
                status="waiting",
                timestamp=timestamp,
                ref=ref,
                details={**common_details, "next_action": "等待补充参数或确认执行"},
            )
        if event_type in {"tool.awaiting_input", "tool.awaiting_confirmation"}:
            next_action = "等待补充参数" if event_type == "tool.awaiting_input" else "等待用户确认后执行"
            self._upsert(
                accumulator,
                step_id=tool_step_id,
                step_type="tool_call",
                title="算法工具调用",
                summary=f"{tool_name} 已准备，等待用户处理",
                tool_name=tool_name,
                tool_type="algorithm",
                status="waiting",
                timestamp=timestamp,
                ref=ref,
                details={**common_details, "next_action": next_action},
            )
            self._upsert(
                accumulator,
                step_id=f"approval:{call_id}",
                step_type="approval",
                title="等待用户确认",
                summary=f"{tool_name} 需要补充参数或确认" if event_type == "tool.awaiting_input" else f"{tool_name} 等待确认执行",
                tool_name=tool_name,
                tool_type="algorithm",
                status="waiting",
                timestamp=timestamp,
                ref=ref,
                parent_step_id=tool_step_id,
                details={"next_action": next_action},
                started_at=timestamp,
            )
        elif event_type == "tool.confirmed":
            self._upsert(
                accumulator,
                step_id=f"approval:{call_id}",
                step_type="approval",
                title="用户已确认",
                summary=f"{tool_name} 参数已确认",
                tool_name=tool_name,
                tool_type="algorithm",
                status="success",
                timestamp=timestamp,
                ref=ref,
                parent_step_id=tool_step_id,
                details={"next_action": "提交算法运行", "argument_keys": sorted(str(key) for key in (data.get("arguments") or {}))},
                ended_at=timestamp,
            )
            self._upsert(
                accumulator,
                step_id=tool_step_id,
                step_type="tool_call",
                title="算法工具调用",
                summary=f"{tool_name} 已确认，准备执行",
                tool_name=tool_name,
                tool_type="algorithm",
                status="running",
                timestamp=timestamp,
                ref=ref,
                details=common_details,
            )
        elif event_type in {"tool.queued", "tool.started"}:
            self._upsert(
                accumulator,
                step_id=tool_step_id,
                step_type="tool_call",
                title="算法工具调用",
                summary=f"{tool_name} 正在排队" if event_type == "tool.queued" else f"{tool_name} 正在执行",
                tool_name=tool_name,
                tool_type="algorithm",
                status="running",
                timestamp=timestamp,
                ref=ref,
                details=common_details,
                started_at=timestamp,
            )
        elif event_type in {"tool.result", "tool.failed", "tool.canceled"}:
            failed = event_type in {"tool.failed", "tool.canceled"}
            status = "failed" if failed else "success"
            artifact_refs = data.get("artifact_refs") or call.get("artifact_refs") or []
            result_summary = data.get("result_summary") or call.get("result_summary") or {}
            self._upsert(
                accumulator,
                step_id=tool_step_id,
                step_type="tool_call",
                title="算法工具调用",
                summary=f"{tool_name} {'执行失败' if failed else '执行完成'}",
                tool_name=tool_name,
                tool_type="algorithm",
                status=status,
                timestamp=timestamp,
                ref=ref,
                details={**common_details, "result_summary": self._safe_map(result_summary), "artifact_refs": self._safe_artifacts(artifact_refs)},
                ended_at=timestamp,
            )
            self._upsert(
                accumulator,
                step_id=f"result:{call_id}",
                step_type="tool_result",
                title="算法结果",
                summary=self._safe_text(result_summary.get("message"), 180) or ("算法执行失败" if failed else "算法执行完成"),
                tool_name=tool_name,
                tool_type="algorithm",
                status=status,
                timestamp=timestamp,
                ref=ref,
                parent_step_id=tool_step_id,
                details={"result_summary": self._safe_map(result_summary), "artifact_refs": self._safe_artifacts(artifact_refs)},
            )
            for artifact in artifact_refs:
                artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "")
                if not artifact_id:
                    continue
                self._upsert(
                    accumulator,
                    step_id=f"asset:{artifact_id}",
                    step_type="write",
                    title="生成结果文件",
                    summary=f"已生成 {artifact.get('name') or artifact_id}",
                    tool_name=tool_name,
                    tool_type="asset",
                    status=status,
                    timestamp=timestamp,
                    ref=ref,
                    parent_step_id=f"result:{call_id}",
                    details={"artifact_refs": self._safe_artifacts([artifact])},
                )
            if failed:
                self._error_step(accumulator, event, timestamp, ref, tool_name, (data.get("error") or {}).get("message"))

    def _error_step(
        self,
        accumulator: dict[str, dict[str, Any]],
        event: dict[str, Any],
        timestamp: datetime,
        ref: AssistantTraceSourceRef,
        source: str,
        message: object,
    ) -> None:
        """生成不暴露堆栈和敏感值的错误步骤。"""
        event_id = str(event.get("event_id") or "")
        self._upsert(
            accumulator,
            step_id=f"error:{event_id}",
            step_type="error",
            title=f"{source} 执行失败",
            summary=self._safe_text(message, 220) or "执行失败，正在保留可用结果",
            status="failed",
            timestamp=timestamp,
            ref=ref,
            details={"error_type": source, "error_message": self._safe_text(message, 500)},
        )

    def _upsert(
        self,
        accumulator: dict[str, dict[str, Any]],
        *,
        step_id: str,
        step_type: str,
        title: str,
        summary: str,
        status: str,
        timestamp: datetime,
        ref: AssistantTraceSourceRef,
        tool_name: str = "",
        tool_type: str = "other",
        details: dict[str, Any] | None = None,
        parent_step_id: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
    ) -> None:
        """新增或合并同一 step 的状态更新。"""
        current = accumulator.setdefault(
            step_id,
            {
                "step_id": step_id,
                "type": step_type,
                "title": title,
                "summary": summary,
                "tool_name": tool_name,
                "tool_type": tool_type,
                "status": status,
                "timestamp": timestamp,
                "refs": [],
                "details": {},
                "parent_step_id": parent_step_id,
                "_started_at": started_at,
                "_ended_at": ended_at,
                "_duration_known": False,
            },
        )
        current["title"] = title or current["title"]
        current["summary"] = summary or current["summary"]
        if tool_name:
            current["tool_name"] = tool_name
        if tool_type and tool_type != "other":
            current["tool_type"] = tool_type
        current["status"] = status or current["status"]
        current["timestamp"] = timestamp
        current["parent_step_id"] = parent_step_id or current.get("parent_step_id")
        if ref.event_id and ref.event_id not in {item.event_id for item in current["refs"]}:
            current["refs"].append(ref)
        for key, value in (details or {}).items():
            if value is None:
                continue
            if isinstance(value, list) and isinstance(current["details"].get(key), list):
                merged = [*current["details"][key], *value]
                current["details"][key] = self._deduplicate(merged)
            elif value:
                current["details"][key] = value
        if started_at:
            current["_started_at"] = started_at
        if ended_at:
            current["_ended_at"] = ended_at
        start = current.get("_started_at")
        end = current.get("_ended_at")
        if start and end and end >= start:
            current["duration_ms"] = max(0, int((end - start).total_seconds() * 1000))
            current["_duration_known"] = True

    @staticmethod
    def _as_step(item: dict[str, Any]) -> AssistantTraceStep:
        """把内部累积状态转换成对外 Pydantic step。"""
        details = {key: value for key, value in item["details"].items() if not key.startswith("_")}
        return AssistantTraceStep(
            trace_id=str(item.get("trace_id") or ""),
            step_id=str(item["step_id"]),
            timestamp=item["timestamp"],
            type=str(item["type"]),
            title=str(item["title"]),
            summary=str(item["summary"]),
            tool_name=str(item.get("tool_name") or ""),
            tool_type=str(item.get("tool_type") or "other"),
            status=str(item.get("status") or "running"),
            duration_ms=int(item.get("duration_ms") or 0),
            details=AssistantTraceStepDetails(
                duration_known=bool(item.get("_duration_known")),
                source_event_refs=item.get("refs") or [],
                **details,
            ),
            parent_step_id=item.get("parent_step_id"),
        )

    @staticmethod
    def _derive_status(
        runs: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        steps: list[AssistantTraceStep],
        events: list[dict[str, Any]],
    ) -> AssistantTraceStatus:
        """根据真实 run/call/step/event 状态推导 Trace 状态。"""
        has_final = any(step.type == "final" and step.status == "success" for step in steps)
        active_runs = any(str(run.get("status") or "") in ACTIVE_RUN_STATUSES for run in runs)
        active_calls = any(str(call.get("phase") or "") in ACTIVE_TOOL_PHASES for call in calls)
        waiting_calls = any(str(call.get("phase") or "") in WAITING_TOOL_PHASES for call in calls)

        if has_final:
            return "completed"

        if calls:
            if waiting_calls and not active_runs and not active_calls:
                return "waiting_approval"
            if active_runs or active_calls:
                return "running"

            continuation_states = {
                str(call.get("continuation_state") or "")
                for call in calls
            }
            if "dead_letter" in continuation_states or "failed" in continuation_states:
                return "failed"
            if any(
                str(call.get("continuation_state") or "") == "pending"
                and call.get("continuation_next_retry_at") is not None
                for call in calls
            ):
                return "recovering"
            if "pending" in continuation_states or "scheduled" in continuation_states:
                return "running"

            terminal_calls = [
                call
                for call in calls
                if str(call.get("phase") or "") in TERMINAL_TOOL_PHASES
            ]
            if not terminal_calls:
                return "planning"

            phases = {str(call.get("phase") or "") for call in terminal_calls}
            if phases <= {"canceled"}:
                return "canceled"
            if any(
                str(call.get("continuation_state") or "") == "skipped"
                for call in terminal_calls
            ):
                return "failed" if "failed" in phases else "completed"
            if any(
                str(call.get("continuation_state") or "") == "completed"
                for call in terminal_calls
            ):
                return "running"

            terminal_event_ids = {
                str(event.get("call_id") or "")
                for event in events
                if str(event.get("type") or "") in {"tool.result", "tool.failed", "tool.canceled"}
            }
            if terminal_event_ids:
                return "running"
            return "failed" if "failed" in phases else "completed"

        statuses = {str(run.get("status") or "") for run in runs}
        if active_runs:
            return "running"
        if "failed" in statuses:
            return "failed"
        if "canceled" in statuses:
            return "canceled"
        if "completed" in statuses:
            return "completed"
        return "planning"

    @staticmethod
    def _build_summary(
        steps: list[AssistantTraceStep],
        calls: list[dict[str, Any]],
        events: list[dict[str, Any]],
        status: AssistantTraceStatus,
        warnings: list[str],
    ) -> AssistantTraceSummary:
        """统计真实 Trace 步骤与整轮 wall-clock 耗时。"""
        def count(step_type: str, tool_type: str | None = None) -> int:
            return sum(
                1
                for step in steps
                if step.type == step_type and (tool_type is None or step.tool_type == tool_type)
            )

        timestamps = [item.timestamp for item in steps]
        first = min(timestamps) if timestamps else None
        last = max(timestamps) if timestamps else None
        terminal = status in TERMINAL_RUN_STATUSES
        known = terminal and first is not None and last is not None
        return AssistantTraceSummary(
            total_steps=len(steps),
            commands=count("command"),
            control_changes=count("control"),
            tool_calls=count("tool_call", "algorithm"),
            llm_calls=count("tool_call", "llm"),
            retrievals=count("tool_call", "retrieval"),
            approvals=count("approval"),
            file_reads=count("read"),
            file_writes=count("write"),
            file_edits=count("edit"),
            artifacts=sum(len(item.get("artifact_refs") or []) for item in calls),
            exports=count("export"),
            feedback=count("feedback"),
            compactions=sum(1 for step in steps if step.type == "context" and "context.compacted" in step.details.event_types),
            errors=count("error"),
            recoveries=sum(1 for step in steps if step.type == "error" and step.details.retry_scheduled),
            replay_warnings=len(warnings),
            duration_ms=int((last - first).total_seconds() * 1000) if known and first is not None and last is not None else 0,
            duration_known=known,
        )

    @staticmethod
    def _trace_run(run: dict[str, Any]) -> AssistantTraceRun:
        """转换 AssistantRun 摘要。"""
        context = ((run.get("request_snapshot") or {}).get("context") or {})
        request_kind = "final_answer" if context.get("tool_call_ids") else (
            "tool_proposal" if context.get("selected_tool_ids") else "final_answer"
        )
        return AssistantTraceRun(
            run_id=str(run.get("run_id") or ""),
            request_kind=request_kind,
            status=str(run.get("status") or "queued"),
            started_at=AssistantTraceProjectionService._parse_datetime(run.get("started_at")),
            finished_at=AssistantTraceProjectionService._parse_datetime(run.get("finished_at")),
        )

    @staticmethod
    def _trace_tool_call(call: dict[str, Any]) -> AssistantTraceToolCall:
        """转换算法工具调用摘要。"""
        return AssistantTraceToolCall(
            call_id=str(call.get("call_id") or ""),
            algorithm_id=str(call.get("algorithm_id") or call.get("tool_id") or ""),
            tool_name=str(call.get("tool_name") or call.get("tool_id") or ""),
            phase=str(call.get("phase") or "requested"),
            run_id=call.get("run_id"),
        )

    @staticmethod
    def _trace_command(command: dict[str, Any]) -> AssistantTraceCommand:
        """转换 Slash Command 摘要。"""
        return AssistantTraceCommand(
            command_id=str(command.get("command_id") or ""),
            name=str(command.get("name") or ""),
            status=str(command.get("status") or "running"),
            run_id=command.get("run_id"),
            call_id=command.get("call_id"),
        )

    @staticmethod
    def _source_ref(event: dict[str, Any]) -> AssistantTraceSourceRef:
        """构造真实事件引用。"""
        return AssistantTraceSourceRef(
            stream="embedded_event" if str(event.get("event_id") or "").startswith("embedded:") else "assistant_event",
            event_id=str(event.get("event_id") or ""),
            run_id=str(event.get("run_id") or ""),
            call_id=str(event.get("call_id") or ""),
            seq=int(event.get("seq") or 0),
            chat_seq=int(event.get("chat_seq") or 0),
        )

    @staticmethod
    def _event_details(
        event: dict[str, Any],
        *,
        command_id: object = None,
        command_name: object = None,
        result_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造控制面事件的安全白名单详情。"""
        event_type = str(event.get("type") or "")
        return {
            "event_type": event_type,
            "event_types": [event_type],
            "command_id": str(command_id) if command_id else None,
            "command_name": str(command_name) if command_name else None,
            "chat_seq": int(event.get("chat_seq") or 0),
            "result_summary": result_summary or {},
        }

    @staticmethod
    def _control_title(event_type: str, data: dict[str, Any]) -> str:
        """把控制面事件映射为用户可读标题。"""
        return {
            "plan.mode.changed": "Plan Mode 已更新",
            "goal.changed": "会话目标已更新",
            "todo.changed": "会话 Todo 已更新",
            "permission.mode.changed": "权限模式已更新",
            "session.reset": "控制状态已重置",
            "session.clear": "已切换新会话",
        }.get(event_type, "会话控制事件")

    @classmethod
    def _control_summary(cls, event_type: str, data: dict[str, Any]) -> str:
        """生成控制面事件的简短摘要。"""
        if event_type == "plan.mode.changed":
            return "Plan Mode 已启用" if bool(data.get("active")) else "Plan Mode 已退出"
        if event_type == "goal.changed":
            action = str(data.get("action") or "set")
            return "长期目标已设置" if action == "set" else "长期目标已清除"
        if event_type == "permission.mode.changed":
            return f"{data.get('before') or 'unknown'} → {data.get('after') or 'unknown'}"
        if event_type == "session.reset":
            return "Plan、权限、目标与 Todo 已恢复默认值，审计历史保留"
        if event_type == "session.clear":
            return f"新会话 {data.get('new_chat_id') or ''}".rstrip()
        return cls._safe_text(data.get("message"), 160) or "控制状态已记录"

    @staticmethod
    def _status_verb(status: str) -> str:
        """把导出状态转换为简短动词。"""
        return {"completed": "完成", "failed": "失败", "started": "开始"}.get(status, "更新")

    @staticmethod
    def _safe_sections(sections: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """保留上下文 section 的安全统计字段。"""
        allowed = {"name", "source", "digest", "token_estimate", "included", "omitted_reason"}
        return [{key: item.get(key) for key in allowed if item.get(key) is not None} for item in sections]

    @staticmethod
    def _safe_artifacts(artifacts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """保留 artifact 的公开标识与名称。"""
        allowed = {"artifact_id", "id", "name", "filename", "content_type", "size_bytes"}
        return [{key: item.get(key) for key in allowed if item.get(key) is not None} for item in artifacts]

    @staticmethod
    def _safe_map(value: dict[str, Any]) -> dict[str, Any]:
        """限制结果摘要大小并移除敏感赋值。"""
        if not value:
            return {}
        safe = SENSITIVE_ASSIGNMENT.sub(r"\1=[REDACTED]", str(value))
        return {"message": safe[:1000], "truncated": len(safe) > 1000}

    @staticmethod
    def _safe_text(value: object, limit: int) -> str:
        """生成脱敏、限长的自然语言摘要。"""
        text = SENSITIVE_ASSIGNMENT.sub(r"\1=[REDACTED]", str(value or "")).replace("\n", " ").strip()
        return text[:limit] + ("…" if len(text) > limit else "")

    @staticmethod
    def _deduplicate(values: list[Any]) -> list[Any]:
        """按 JSON 表示去重并保持顺序。"""
        seen: set[str] = set()
        result: list[Any] = []
        for value in values:
            key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    @staticmethod
    def _event_time(event: dict[str, Any]) -> datetime | None:
        """解析统一事件时间。"""
        return AssistantTraceProjectionService._parse_datetime(event.get("at"))

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        """兼容 datetime 与 ISO 字符串。"""
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    @staticmethod
    def _event_sort_text(event: dict[str, Any]) -> str:
        """生成稳定排序键。"""
        parsed = AssistantTraceProjectionService._event_time(event)
        return parsed.isoformat() if parsed else str(event.get("at") or "")

    @staticmethod
    def _min_datetime(values: list[datetime]) -> datetime | None:
        """返回最小时间。"""
        return min(values) if values else None

    @staticmethod
    def _max_datetime(values: list[datetime]) -> datetime | None:
        """返回最大时间。"""
        return max(values) if values else None


assistant_trace_service = AssistantTraceProjectionService()
