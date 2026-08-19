"""LUI 调用质量指标聚合服务。"""

from __future__ import annotations

import copy
from collections import defaultdict
from datetime import datetime
import math
import time
from typing import Any

from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantEventRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.infra.assistant_command_repositories import (
    AssistantCommandRunRepository,
    AssistantFeedbackRepository,
)
from app.services.assistant_command_service import CATALOG_LATENCY_SAMPLES


EXECUTING_TOOL_PHASES = {"queued", "running", "completed", "failed"}
TERMINAL_TOOL_PHASES = {"completed", "failed"}
QUALITY_CACHE_TTL_SECONDS = 60
_QUALITY_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _ratio(numerator: int, denominator: int) -> float | None:
    """返回百分比小数；分母为 0 时返回 None。"""
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _display_rate(value: float | None) -> str:
    """将小数格式化为百分比文本。"""
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _metric(
    key: str,
    label: str,
    value: float | None,
    numerator: int,
    denominator: int,
    *,
    target: str,
) -> dict[str, Any]:
    """构建指标字典。"""
    return {
        "key": key,
        "label": label,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "display": _display_rate(value),
        "target": target,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    """计算有序百分位数；空样本返回 None。

    Args:
        values: 数值样本。
        percentile: 0-1 之间的百分位。

    Returns:
        对应百分位数；无样本时为 None。
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _has_tool_calling(route: dict[str, Any] | None) -> bool:
    """判断 route 是否声明工具调用能力。"""
    capabilities = (route or {}).get("capabilities") or []
    return "tool_calling" in capabilities


def _selected_tool_ids(run: dict[str, Any]) -> list[str]:
    """读取 run 请求快照中的 selected_tool_ids。"""
    context = ((run.get("request_snapshot") or {}).get("context")) or {}
    return [str(item) for item in (context.get("selected_tool_ids") or []) if item]


def _context_token_distribution(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 context section 聚合 token estimate 与省略次数。"""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for run in runs:
        manifests = run.get("request_manifests") or {}
        for manifest in manifests.values():
            sections = ((manifest or {}).get("context") or {}).get("sections") or []
            for section in sections:
                name = str(section.get("name") or "unknown")
                source = str(section.get("source") or "unknown")
                key = (name, source)
                if key not in grouped:
                    grouped[key] = {
                        "name": name,
                        "source": source,
                        "count": 0,
                        "token_total": 0,
                        "token_max": 0,
                        "omitted_count": 0,
                    }
                row = grouped[key]
                row["count"] += 1
                tokens = int(section.get("token_estimate") or 0)
                row["token_total"] += tokens
                row["token_max"] = max(int(row["token_max"]), tokens)
                if not bool(section.get("included", True)):
                    row["omitted_count"] += 1
    rows = list(grouped.values())
    rows.sort(key=lambda item: (-int(item["token_total"]), item["name"], item["source"]))
    for row in rows:
        row["token_avg"] = round(int(row["token_total"]) / int(row["count"]), 2) if row["count"] else 0
    return rows


def _event_replay_errors(events: list[dict[str, Any]]) -> int:
    """统计统一事件流中的 seq 空洞与重复。"""
    grouped: dict[str, list[int]] = defaultdict(list)
    for event in events:
        run_id = str(event.get("run_id") or "")
        call_id = str(event.get("call_id") or "")
        if not run_id and not call_id:
            continue
        grouped[f"{run_id}::{call_id}"].append(int(event.get("seq") or 0))

    errors = 0
    for seqs in grouped.values():
        seen: set[int] = set()
        last_seq = 0
        for seq in sorted(seqs):
            if seq <= 0 or seq in seen:
                errors += 1
                continue
            if seq != last_seq + 1:
                errors += 1
            seen.add(seq)
            last_seq = seq
    return errors


def _parse_time(value: str | datetime | None) -> datetime | None:
    """把查询时间转换为可比较的 datetime。"""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _value_time(value: Any) -> datetime | None:
    """读取文档或事件中可比较的时间字段。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _within_window(document: dict[str, Any], since: datetime | None, until: datetime | None) -> bool:
    """判断文档是否落在指定时间窗口内。"""
    if not since and not until:
        return True
    candidate = _value_time(
        document.get("at")
        or document.get("created_at")
        or document.get("updated_at")
    )
    if candidate is None:
        return False
    if since and candidate < since:
        return False
    if until and candidate > until:
        return False
    return True


def build_quality_metrics(
    *,
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    use_cache: bool = False,
) -> dict[str, Any]:
    """从 assistant run、tool call 与事件日志聚合 LUI 调用质量指标。

    Args:
        since: 统计起始时间，包含边界。
        until: 统计结束时间，包含边界。
        use_cache: 是否使用短 TTL 聚合缓存。

    Returns:
        含窗口、缓存状态与指标的汇总结果。
    """
    since_value = _parse_time(since)
    until_value = _parse_time(until)
    cache_key = (
        since_value.isoformat() if since_value else "",
        until_value.isoformat() if until_value else "",
    )
    now_monotonic = time.monotonic()
    if use_cache and cache_key in _QUALITY_CACHE:
        cached_at, cached_value = _QUALITY_CACHE[cache_key]
        if now_monotonic - cached_at < QUALITY_CACHE_TTL_SECONDS:
            result = copy.deepcopy(cached_value)
            result["cache_hit"] = True
            return result

    runs, _ = AssistantRunRepository.list_all(page=1, page_size=10_000)
    calls, _ = AssistantToolCallRepository.list_all(page=1, page_size=10_000)
    events, _ = AssistantEventRepository.list_all(
        page=1,
        page_size=10_000,
        sort_field="seq",
        reverse=False,
    )
    runs = [run for run in runs if _within_window(run, since_value, until_value)]
    calls = [call for call in calls if _within_window(call, since_value, until_value)]
    events = [event for event in events if _within_window(event, since_value, until_value)]

    resolved_runs = [
        run for run in runs
        if bool((run.get("route") or {}).get("provider_id"))
        and bool((run.get("route") or {}).get("model_id"))
    ]
    mismatch_runs = []
    for run in resolved_runs:
        route = run.get("route") or {}
        requested_provider = str(route.get("requested_provider_id") or "").strip()
        requested_model = str(route.get("requested_model_id") or "").strip()
        if not requested_provider and not requested_model:
            continue
        if (
            requested_provider != str(route.get("provider_id") or "")
            or requested_model != str(route.get("model_id") or "")
        ):
            mismatch_runs.append(run)

    route_calls = [
        call for call in calls
        if bool((call.get("proposal_route") or {}).get("provider_id"))
        or bool((call.get("proposal_route") or {}).get("model_id"))
    ]
    tool_capable_calls = [
        call for call in route_calls
        if _has_tool_calling(call.get("proposal_route"))
    ]

    selected_tool_runs = [run for run in runs if _selected_tool_ids(run)]
    call_run_ids = {str(call.get("assistant_run_id")) for call in calls if call.get("assistant_run_id")}
    runs_with_proposal = [
        run for run in selected_tool_runs
        if run.get("run_id") in call_run_ids
    ]

    validation_failed_calls = [
        call for call in calls
        if bool(call.get("arguments_parse_error")) or bool(call.get("missing_fields"))
    ]
    unsupported_fallback_events = [
        event for event in events if event.get("type") == "route.fallback"
    ]
    confirmed_calls = [call for call in calls if call.get("phase") in EXECUTING_TOOL_PHASES]
    terminal_tool_calls = [call for call in calls if call.get("phase") in TERMINAL_TOOL_PHASES]
    failed_tool_calls = [call for call in terminal_tool_calls if call.get("phase") == "failed"]
    continuation_tool_calls = [
        call for call in terminal_tool_calls if call.get("continuation_state") is not None
    ]
    continuation_succeeded_calls = [
        call for call in continuation_tool_calls if call.get("continuation_state") == "completed"
    ]

    commands, _ = AssistantCommandRunRepository.list_all(
        page=1,
        page_size=10_000,
        sort_field="created_at",
        reverse=False,
    )
    commands = [command for command in commands if _within_window(command, since_value, until_value)]
    feedbacks, _ = AssistantFeedbackRepository.list_all(
        page=1,
        page_size=10_000,
        sort_field="created_at",
        reverse=False,
    )
    feedbacks = [feedback for feedback in feedbacks if _within_window(feedback, since_value, until_value)]
    chats, _ = AssistantChatRepository.list_all(page=1, page_size=10_000)

    successful_commands = [command for command in commands if command.get("status") == "success"]
    unknown_commands = [command for command in commands if command.get("name") == "unknown"]
    dynamic_tool_commands = [
        command for command in commands
        if command.get("source_kind") == "tool" or str(command.get("tool_id") or "").startswith("algorithm:")
    ]
    dynamic_tool_conversions = [command for command in dynamic_tool_commands if command.get("call_id")]
    export_commands = [command for command in commands if command.get("name") == "export"]
    successful_exports = [command for command in export_commands if command.get("status") == "success"]
    feedback_command_chats = {
        str(command.get("chat_id") or "") for command in commands if command.get("name") == "feedback"
    }
    permission_decisions = [event for event in events if event.get("type") == "permission.decision"]
    denied_decisions = [
        event for event in permission_decisions if str((event.get("data") or {}).get("decision")) == "denied"
    ]
    plan_mode_blocks = [
        event for event in denied_decisions
        if str((event.get("data") or {}).get("reason")) == "plan_mode_blocked"
    ]
    compactions = [chat.get("compaction") for chat in chats if chat.get("compaction")]
    compact_original_tokens = sum(int((item or {}).get("original_token_estimate") or 0) for item in compactions)
    compact_current_tokens = sum(int((item or {}).get("token_estimate") or 0) for item in compactions)
    compact_reduction = max(0, compact_original_tokens - compact_current_tokens)
    catalog_values = [
        value
        for sampled_at, value, _success in CATALOG_LATENCY_SAMPLES
        if (since_value is None or sampled_at >= since_value)
        and (until_value is None or sampled_at <= until_value)
    ]
    catalog_latency = _percentile(catalog_values, 0.95)

    context_distribution = _context_token_distribution(runs)
    context_tokens = sum(int(row["token_total"]) for row in context_distribution)

    result = {
        "totals": {
            "runs": len(runs),
            "tool_calls": len(calls),
            "events": len(events),
            "commands": len(commands),
            "feedback": len(feedbacks),
        },
        "window": {
            "since": since_value.isoformat() if since_value else None,
            "until": until_value.isoformat() if until_value else None,
        },
        "cache_hit": False,
        "metrics": [
            {
                "key": "command_catalog_latency",
                "label": "command catalog latency",
                "value": catalog_latency,
                "numerator": len(catalog_values),
                "denominator": len(catalog_values),
                "display": f"{catalog_latency:.2f} ms" if catalog_latency is not None else "—",
                "target": "热缓存 P95 < 100ms",
            },
            _metric(
                "command_execute_success_rate",
                "command execute success rate",
                _ratio(len(successful_commands), len(commands)),
                len(successful_commands),
                len(commands),
                target="接近 100%",
            ),
            _metric(
                "unknown_command_rate",
                "unknown command rate",
                _ratio(len(unknown_commands), len(commands)),
                len(unknown_commands),
                len(commands),
                target="持续下降",
            ),
            _metric(
                "permission_blocked_rate",
                "permission blocked rate",
                _ratio(len(denied_decisions), len(permission_decisions)),
                len(denied_decisions),
                len(permission_decisions),
                target="阻断均带明确 reason",
            ),
            _metric(
                "plan_mode_block_rate",
                "plan mode block rate",
                _ratio(len(plan_mode_blocks), len(denied_decisions)),
                len(plan_mode_blocks),
                len(denied_decisions),
                target="Plan Mode 阻断可审计",
            ),
            _metric(
                "dynamic_tool_command_conversion",
                "dynamic tool command conversion",
                _ratio(len(dynamic_tool_conversions), len(dynamic_tool_commands)),
                len(dynamic_tool_conversions),
                len(dynamic_tool_commands),
                target="提升",
            ),
            _metric(
                "compact_token_reduction",
                "compact token reduction",
                _ratio(compact_reduction, compact_original_tokens),
                compact_reduction,
                compact_original_tokens,
                target="长会话可观测下降",
            ),
            _metric(
                "export_success_rate",
                "export success rate",
                _ratio(len(successful_exports), len(export_commands)),
                len(successful_exports),
                len(export_commands),
                target="接近 100%",
            ),
            _metric(
                "feedback_submission_rate",
                "feedback submission rate",
                _ratio(len(feedbacks), len(feedback_command_chats)),
                len(feedbacks),
                len(feedback_command_chats),
                target="提升",
            ),
            _metric(
                "route_resolved_rate",
                "route resolved rate",
                _ratio(len(resolved_runs), len(runs)),
                len(resolved_runs),
                len(runs),
                target="接近 100%",
            ),
            _metric(
                "requested_vs_resolved_mismatch",
                "requested vs resolved mismatch",
                _ratio(len(mismatch_runs), len(resolved_runs)),
                len(mismatch_runs),
                len(resolved_runs),
                target="可解释、可审计",
            ),
            _metric(
                "tool_capable_model_usage",
                "tool-capable model usage",
                _ratio(len(tool_capable_calls), len(route_calls)),
                len(tool_capable_calls),
                len(route_calls),
                target="提升",
            ),
            _metric(
                "tool_proposal_rate",
                "tool proposal rate",
                _ratio(len(runs_with_proposal), len(selected_tool_runs)),
                len(runs_with_proposal),
                len(selected_tool_runs),
                target="提升",
            ),
            _metric(
                "tool_proposal_validation_failure",
                "tool proposal validation failure",
                _ratio(len(validation_failed_calls), len(route_calls)),
                len(validation_failed_calls),
                len(route_calls),
                target="下降",
            ),
            _metric(
                "unsupported_model_fallback",
                "unsupported model fallback",
                _ratio(
                    len(unsupported_fallback_events),
                    len(selected_tool_runs) or len(resolved_runs),
                ),
                len(unsupported_fallback_events),
                len(selected_tool_runs) or len(resolved_runs),
                target="下降且明确展示",
            ),
            _metric(
                "confirmation_conversion",
                "confirmation conversion",
                _ratio(len(confirmed_calls), len(calls)),
                len(confirmed_calls),
                len(calls),
                target="提升",
            ),
            _metric(
                "tool_run_failure",
                "tool run failure",
                _ratio(len(failed_tool_calls), len(terminal_tool_calls)),
                len(failed_tool_calls),
                len(terminal_tool_calls),
                target="下降",
            ),
            _metric(
                "continuation_success",
                "continuation success",
                _ratio(len(continuation_succeeded_calls), len(continuation_tool_calls)),
                len(continuation_succeeded_calls),
                len(continuation_tool_calls),
                target="接近 100%",
            ),
        ],
        "context_token_distribution": {
            "total_tokens": context_tokens,
            "sections": context_distribution,
        },
        "event_replay_errors": _event_replay_errors(events),
    }
    _QUALITY_CACHE[cache_key] = (now_monotonic, copy.deepcopy(result))
    return result
