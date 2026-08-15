"""LUI 调用质量指标聚合服务。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.infra.research_engine_repositories import (
    AssistantEventRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)


EXECUTING_TOOL_PHASES = {"queued", "running", "completed", "failed"}
TERMINAL_TOOL_PHASES = {"completed", "failed"}


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


def build_quality_metrics() -> dict[str, Any]:
    """从 assistant run、tool call 与事件日志聚合 LUI 调用质量指标。"""
    runs, _ = AssistantRunRepository.list_all(page=1, page_size=10_000)
    calls, _ = AssistantToolCallRepository.list_all(page=1, page_size=10_000)
    events, _ = AssistantEventRepository.list_all(
        page=1,
        page_size=10_000,
        sort_field="seq",
        reverse=False,
    )

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

    context_distribution = _context_token_distribution(runs)
    context_tokens = sum(int(row["token_total"]) for row in context_distribution)

    return {
        "totals": {
            "runs": len(runs),
            "tool_calls": len(calls),
            "events": len(events),
        },
        "metrics": [
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
                _ratio(len(validation_failed_calls), len(calls)),
                len(validation_failed_calls),
                len(calls),
                target="下降",
            ),
            _metric(
                "unsupported_model_fallback",
                "unsupported model fallback",
                _ratio(len(unsupported_fallback_events), len(resolved_runs)),
                len(unsupported_fallback_events),
                len(resolved_runs),
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
