"""按 evaluation_id 抓取 LUI 录制事实。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from evaluation.lui.schemas import (
    FixtureMessage,
    FixtureRetrieval,
    FixtureRetrievalItem,
    FixtureRun,
    FixtureToolCall,
    ObservedFacts,
)


def _parse_datetime(value: Any) -> datetime | None:
    """解析文档时间字段。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _duration_ms(started: Any, finished: Any) -> int | None:
    """计算起止时间差。"""
    start = _parse_datetime(started)
    end = _parse_datetime(finished)
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds() * 1000)


def _usage_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """读取 usage 事件的 token 字段。"""
    data = event.get("data") if isinstance(event.get("data"), dict) else event
    if str(data.get("type") or event.get("type") or "") != "llm.usage.recorded":
        return None
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else data
    if usage.get("total_tokens") is None and usage.get("prompt_tokens") is None:
        return None
    return dict(usage)


def _retrievals_from_events(events: list[dict[str, Any]]) -> list[FixtureRetrieval]:
    """从 retrieval.result 事件构建观测检索。"""
    retrievals: list[FixtureRetrieval] = []
    for event in events:
        data = event.get("data") if isinstance(event.get("data"), dict) else event
        if str(data.get("type") or "") != "retrieval.result":
            continue
        results = [
            FixtureRetrievalItem(
                id=str(item.get("id") or ""),
                rank=int(item.get("rank") or index + 1),
                score=item.get("score"),
                snippet=str(item.get("snippet") or ""),
                used_in_answer=item.get("used_in_answer"),
            )
            for index, item in enumerate(data.get("results") or [])
            if item.get("id")
        ]
        retrievals.append(
            FixtureRetrieval(
                source=str(data.get("source") or "knowledge"),
                status=str(data.get("status") or "searched"),
                results=results,
            )
        )
    return retrievals


def _fixture_run(run: dict[str, Any], events: list[dict[str, Any]]) -> FixtureRun:
    """把 run 文档投影为 FixtureRun。"""
    usage_events = [
        usage
        for usage in (_usage_from_event(event) for event in events)
        if usage is not None
    ]
    return FixtureRun(
        run_id=str(run.get("run_id") or ""),
        status=str(run.get("status") or "failed"),
        stage=run.get("stage"),
        error=run.get("error"),
        duration_ms=run.get("duration_ms"),
        first_token_ms=run.get("first_token_ms"),
        queue_wait_ms=run.get("queue_wait_ms"),
        prompt_tokens=run.get("prompt_tokens"),
        completion_tokens=run.get("completion_tokens"),
        total_tokens=run.get("total_tokens"),
        provider_id=run.get("provider_id"),
        model_id=run.get("model_id"),
        route=run.get("route") or {},
        usage_events=usage_events,
    )


def _fixture_tool_call(call: dict[str, Any]) -> FixtureToolCall:
    """把工具调用文档投影为 FixtureToolCall。"""
    return FixtureToolCall(
        call_id=str(call.get("call_id") or ""),
        tool_id=str(call.get("tool_id") or ""),
        function_name=call.get("function_name"),
        raw_arguments=call.get("raw_arguments"),
        arguments=call.get("arguments") or {},
        missing_fields=call.get("missing_fields") or [],
        arguments_parse_error=call.get("arguments_parse_error"),
        phase=str(call.get("phase") or ""),
        error=call.get("error"),
        duration_ms=_duration_ms(call.get("started_at"), call.get("finished_at")),
        proposal_usage=call.get("proposal_usage"),
    )


def capture_facts_by_evaluation(evaluation_id: str) -> dict[str, ObservedFacts]:
    """按评测 ID 抓取任务级原始事实。

    Args:
        evaluation_id: 写入 run 请求上下文的评测批次 ID。

    Returns:
        task_id 到 ObservedFacts 的映射；同一任务多次运行时取最新 run。
    """
    from app.infra.research_engine_repositories import (
        AssistantEventRepository,
        AssistantMessageRepository,
        AssistantRunRepository,
        AssistantToolCallRepository,
    )

    runs = sorted(
        AssistantRunRepository.find_by_evaluation_id(evaluation_id),
        key=lambda item: str(item.get("created_at") or ""),
    )
    grouped: dict[str, dict[str, Any]] = {}
    for run in runs:
        context = ((run.get("request_snapshot") or {}).get("context") or {})
        task_id = str(context.get("task_id") or "")
        if not task_id:
            continue
        # 按 created_at 升序遍历，后写入覆盖旧值，保留每个任务最新 run。
        grouped[task_id] = run

    facts: dict[str, ObservedFacts] = {}
    for task_id, run in grouped.items():
        run_ids = {
            str(run.get("run_id") or ""),
            str(run.get("trace_id") or ""),
        }
        trace_id = str(run.get("trace_id") or run.get("run_id") or "")
        calls = AssistantToolCallRepository.list_for_trace(trace_id, run_ids)
        events: list[dict[str, Any]] = []
        for run_id in sorted(item for item in run_ids if item):
            events.extend(AssistantEventRepository.list_for_run(run_id))
        events.sort(key=lambda item: int(item.get("seq") or 0))
        message_doc = None
        if run.get("assistant_message_id"):
            message_doc = AssistantMessageRepository.find_one(
                {"message_id": run.get("assistant_message_id")}
            )
        message = (
            FixtureMessage(
                content=str((message_doc or {}).get("content") or ""),
                references=(message_doc or {}).get("references") or [],
                answer_mode=(message_doc or {}).get("answer_mode"),
                answer_scope=(message_doc or {}).get("answer_scope"),
                retrieval_status=(message_doc or {}).get("retrieval_status"),
            )
            if message_doc
            else None
        )
        confirmations = sum(1 for call in calls if call.get("confirmed_at"))
        param_completions = sum(
            1 for call in calls if str(call.get("phase") or "") == "awaiting_input"
        )
        permission_blocked = any(
            "permission" in str(event.get("type") or event.get("data", {}).get("type", "")).lower()
            and any(
                word in str(event.get("type") or event.get("data", {}).get("type", "")).lower()
                for word in ("denied", "blocked")
            )
            for event in events
        )
        dead_letter = any(call.get("continuation_dead_letter_reason") for call in calls)
        user_canceled = str(run.get("status") or "") == "canceled" or any(
            call.get("canceled_at") for call in calls
        )
        facts[task_id] = ObservedFacts(
            task_id=task_id,
            trace_id=trace_id or None,
            captured_at=datetime.utcnow().isoformat(),
            run=_fixture_run(run, events),
            tool_calls=[_fixture_tool_call(call) for call in calls],
            retrievals=_retrievals_from_events(events),
            message=message,
            escalation={
                "confirmations": confirmations,
                "param_completions": param_completions,
                "permission_blocked": permission_blocked,
                "awaiting_input_terminal": param_completions > 0,
                "dead_letter": dead_letter,
                "user_canceled": user_canceled,
                "needed_retry": False,
            },
        )
    return facts
