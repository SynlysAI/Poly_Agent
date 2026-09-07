"""LUI 生产采样指标聚合。

面向无 Ground Truth 的生产 run/tool/event 只读采样，输出 M6 延迟、
M7 成本、M8 人工兜底候选与链路侧 M2 候选。所有投影均做匿名化：
不包含用户 ID、chat/message 内容、raw_arguments 或完整时间戳
（时间仅保留日期桶）。
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime
from typing import Any

from evaluation.lui.metrics import percentile


TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}
PERMISSION_ERROR_MARKERS = ("permission", "权限", "forbidden")


def _number(value: Any) -> int | None:
    """读取非负整数；缺失或非法时返回 None。"""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _date_bucket(value: Any) -> str | None:
    """把时间戳投影为日期桶，去除精确时间。"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value or "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] or None


def _short_hash(value: str) -> str:
    """生成 8 位短哈希，便于人工标注对照且不暴露原始 ID。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _duration_ms(started: Any, finished: Any) -> int | None:
    """计算起止时间差（毫秒）。"""
    parsed: list[datetime | None] = []
    for value in (started, finished):
        if isinstance(value, datetime):
            parsed.append(value)
            continue
        if isinstance(value, str) and value:
            try:
                parsed.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
            except ValueError:
                parsed.append(None)
        else:
            parsed.append(None)
    start, end = parsed[0], parsed[1]
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds() * 1000)


def _error_code(call: dict[str, Any]) -> str | None:
    """提取工具错误码；不携带错误详情文本。"""
    error = call.get("error")
    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        return str(code) if code else None
    return None


def _is_permission_error(call: dict[str, Any]) -> bool:
    """判断失败调用是否疑似权限阻断。"""
    error = call.get("error")
    if isinstance(error, dict):
        text = " ".join(
            str(error.get(key) or "") for key in ("code", "type", "message")
        ).lower()
    else:
        text = str(error or "").lower()
    return any(marker in text for marker in PERMISSION_ERROR_MARKERS)


def anonymize_run(run: dict[str, Any]) -> dict[str, Any]:
    """把 run 文档投影为匿名采样记录。

    Args:
        run: assistant run 原始文档。

    Returns:
        仅含状态、时长、用量、路由与日期桶的匿名记录。
    """
    route = run.get("route") or {}
    usage = {
        "prompt_tokens": _number(run.get("prompt_tokens")),
        "completion_tokens": _number(run.get("completion_tokens")),
        "total_tokens": _number(run.get("total_tokens")),
    }
    return {
        "run_key": _short_hash(str(run.get("run_id") or "")),
        "status": str(run.get("status") or ""),
        "stage": run.get("stage"),
        "continuation_state": run.get("continuation_state"),
        "duration_ms": _number(run.get("duration_ms")),
        "first_token_ms": _number(run.get("first_token_ms")),
        "queue_wait_ms": _number(run.get("queue_wait_ms")),
        "usage": usage,
        "provider_id": run.get("provider_id"),
        "model_id": run.get("model_id"),
        "capabilities": list(route.get("capabilities") or []),
        "selected_tool_count": len(
            ((run.get("request_snapshot") or {}).get("context") or {}).get(
                "selected_tool_ids"
            )
            or []
        ),
        "date": _date_bucket(run.get("created_at")),
    }


def anonymize_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    """把 tool call 文档投影为匿名采样记录。

    Args:
        call: assistant tool call 原始文档。

    Returns:
        仅含工具、阶段、时长与用量摘要的匿名记录；不含参数内容。
    """
    proposal_usage = call.get("proposal_usage") or {}
    return {
        "call_key": _short_hash(str(call.get("call_id") or "")),
        "run_key": _short_hash(str(call.get("assistant_run_id") or "")),
        "tool_id": str(call.get("tool_id") or ""),
        "function_name": call.get("function_name"),
        "phase": str(call.get("phase") or ""),
        "duration_ms": _duration_ms(call.get("started_at"), call.get("finished_at")),
        "missing_field_count": len(call.get("missing_fields") or []),
        "arguments_parse_error": bool(call.get("arguments_parse_error")),
        "proposal_total_tokens": _number(proposal_usage.get("total_tokens")),
        "error_code": _error_code(call),
    }


def summarize_production_sample(
    runs: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """聚合无 Ground Truth 的生产运行指标。

    Args:
        runs: run 原始文档（仅读取，不修改）。
        tool_calls: tool call 原始文档。
        events: 可选事件文档，用于 dead letter 计数。

    Returns:
        含 M6/M7/M8 与链路侧 M2 候选的匿名化汇总。
    """
    events = events or []
    completed_runs = [run for run in runs if run.get("status") == "completed"]
    failed_runs = [run for run in runs if run.get("status") == "failed"]
    canceled_runs = [run for run in runs if run.get("status") == "canceled"]
    completed_calls = [call for call in tool_calls if call.get("phase") == "completed"]
    failed_calls = [call for call in tool_calls if call.get("phase") == "failed"]

    run_durations = [
        value
        for run in completed_runs
        if (value := _number(run.get("duration_ms"))) is not None
    ]
    first_tokens = [
        value
        for run in completed_runs
        if (value := _number(run.get("first_token_ms"))) is not None
    ]
    tool_durations = [
        value
        for call in completed_calls
        if (value := _duration_ms(call.get("started_at"), call.get("finished_at")))
        is not None
    ]

    usage_runs = [
        run
        for run in runs
        if _number(run.get("total_tokens")) is not None
        or _number(run.get("prompt_tokens")) is not None
    ]
    total_tokens = sum(
        _number(run.get("total_tokens"))
        or (_number(run.get("prompt_tokens")) or 0)
        + (_number(run.get("completion_tokens")) or 0)
        for run in usage_runs
    )
    proposal_tokens = sum(
        value
        for call in completed_calls
        if (value := _number((call.get("proposal_usage") or {}).get("total_tokens")))
        is not None
    )

    permission_blocked = [call for call in failed_calls if _is_permission_error(call)]
    dead_letter_runs = [
        run for run in runs if run.get("continuation_state") == "dead_letter"
    ]
    dead_letter_events = [
        event for event in events if event.get("type") == "tool.continuation.dead_letter"
    ]
    validation_failed = [
        call
        for call in tool_calls
        if bool(call.get("arguments_parse_error")) or bool(call.get("missing_fields"))
    ]
    selected_tool_runs = [
        run
        for run in runs
        if ((run.get("request_snapshot") or {}).get("context") or {}).get(
            "selected_tool_ids"
        )
    ]
    call_run_ids = {
        str(call.get("assistant_run_id"))
        for call in tool_calls
        if call.get("assistant_run_id")
    }
    runs_missing_proposal = [
        run
        for run in selected_tool_runs
        if str(run.get("run_id")) not in call_run_ids
    ]

    terminal_runs = [run for run in runs if run.get("status") in TERMINAL_RUN_STATUSES]
    return {
        "sample": {
            "runs": len(runs),
            "tool_calls": len(tool_calls),
            "events": len(events),
            "terminal_runs": len(terminal_runs),
            "anonymized": True,
        },
        "m6_latency": {
            "run_e2e_ms_p50": percentile(run_durations, 0.5),
            "run_e2e_ms_p95": percentile(run_durations, 0.95),
            "first_token_ms_p50": percentile(first_tokens, 0.5),
            "first_token_ms_p95": percentile(first_tokens, 0.95),
            "tool_ms_p50": percentile(tool_durations, 0.5),
            "tool_ms_p95": percentile(tool_durations, 0.95),
            "completed_run_samples": len(run_durations),
            "failed_or_canceled_runs_excluded": len(failed_runs) + len(canceled_runs),
        },
        "m7_cost": {
            "total_tokens": total_tokens,
            "runs_with_usage": len(usage_runs),
            "tokens_per_run": (
                round(total_tokens / len(usage_runs), 2) if usage_runs else None
            ),
            "proposal_tokens": proposal_tokens,
            "proposal_token_ratio": (
                round(proposal_tokens / total_tokens, 6)
                if total_tokens and proposal_tokens
                else None
            ),
            "runs_without_usage": len(runs) - len(usage_runs),
        },
        "m8_escalation_candidates": {
            "failed_terminal_runs": len(failed_runs),
            "user_canceled_runs": len(canceled_runs),
            "permission_blocked_calls": len(permission_blocked),
            "failed_tool_calls": len(failed_calls),
            "continuation_dead_letter": len(dead_letter_runs) + len(dead_letter_events),
            "note": "候选口径：需人工标注确认后再计入正式 M8",
        },
        "m2_link_side_candidates": {
            "validation_failed_calls": len(validation_failed),
            "selected_tool_runs_missing_proposal": len(runs_missing_proposal),
            "note": "链路侧候选：无 Golden 期望，不构成任务级 M2 判定",
        },
    }


def build_label_sample(
    runs: list[dict[str, Any]],
    *,
    size: int,
    seed: int = 20260828,
) -> list[dict[str, Any]]:
    """抽取匿名化 run 样本供人工标注。

    Args:
        runs: run 原始文档。
        size: 抽样数量；超过样本量时返回全部。
        seed: 随机种子，固定后可复现。

    Returns:
        匿名化 run 投影列表。
    """
    if size <= 0:
        return []
    rng = random.Random(seed)
    candidates = list(runs)
    rng.shuffle(candidates)
    return [anonymize_run(run) for run in candidates[:size]]
