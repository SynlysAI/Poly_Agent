"""LUI 生产采样聚合测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation.lui.production import (
    anonymize_run,
    anonymize_tool_call,
    build_label_sample,
    summarize_production_sample,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "sample_lui_production_metrics.py"
)


def _load_script_module():
    """以独立模块加载采样脚本，便于测试其 IO 辅助函数。"""
    spec = importlib.util.spec_from_file_location("sample_lui_production_metrics", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(**overrides):
    """构建一条最小 run 文档。"""
    payload = {
        "run_id": "run-1",
        "status": "completed",
        "duration_ms": 8000,
        "first_token_ms": 1200,
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "provider_id": "p1",
        "model_id": "m1",
        "route": {"capabilities": ["tool_calling"]},
        "request_snapshot": {"context": {"selected_tool_ids": ["algorithm:x"]}},
        "created_at": "2026-08-28T10:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _call(**overrides):
    """构建一条最小 tool call 文档。"""
    payload = {
        "call_id": "call-1",
        "assistant_run_id": "run-1",
        "tool_id": "algorithm:x",
        "function_name": "predict",
        "phase": "completed",
        "raw_arguments": '{"secret": "user-content"}',
        "proposal_usage": {"total_tokens": 200},
        "started_at": "2026-08-28T10:00:01+00:00",
        "finished_at": "2026-08-28T10:00:03+00:00",
    }
    payload.update(overrides)
    return payload


class LuiProductionSamplingTest(unittest.TestCase):
    def test_summarizes_latency_cost_and_candidates(self) -> None:
        """聚合应输出 M6/M7/M8 候选与链路侧 M2 候选。"""
        runs = [
            _run(),
            _run(run_id="run-2", status="failed", duration_ms=None),
        ]
        calls = [
            _call(),
            _call(
                call_id="call-2",
                phase="failed",
                error={"code": "permission_denied"},
                proposal_usage=None,
            ),
            _call(
                call_id="call-3",
                arguments_parse_error="invalid json",
                missing_fields=["solvent"],
            ),
        ]
        summary = summarize_production_sample(runs, calls, [{"type": "tool.continuation.dead_letter"}])
        self.assertEqual(summary["sample"]["runs"], 2)
        self.assertEqual(summary["m6_latency"]["run_e2e_ms_p50"], 8000)
        self.assertEqual(summary["m6_latency"]["failed_or_canceled_runs_excluded"], 1)
        self.assertEqual(summary["m7_cost"]["total_tokens"], 3000)
        self.assertEqual(summary["m7_cost"]["proposal_tokens"], 400)
        self.assertEqual(summary["m8_escalation_candidates"]["failed_terminal_runs"], 1)
        self.assertEqual(summary["m8_escalation_candidates"]["permission_blocked_calls"], 1)
        self.assertEqual(summary["m8_escalation_candidates"]["continuation_dead_letter"], 1)
        self.assertEqual(summary["m2_link_side_candidates"]["validation_failed_calls"], 1)

    def test_anonymization_removes_identifiers_and_arguments(self) -> None:
        """匿名投影不得包含用户、chat、参数或精确时间。"""
        run = anonymize_run(
            _run(
                created_by="user-secret",
                chat_id="chat-secret",
                created_at="2026-08-28T10:11:12+00:00",
            )
        )
        self.assertNotIn("created_by", run)
        self.assertNotIn("chat_id", run)
        self.assertNotIn("created_at", run)
        self.assertEqual(run["date"], "2026-08-28")
        call = anonymize_tool_call(_call())
        self.assertNotIn("raw_arguments", call)
        self.assertNotIn("secret", json.dumps(call))

    def test_label_sample_is_deterministic_and_limited(self) -> None:
        """人工标注抽样应可复现且不超过样本量。"""
        runs = [_run(run_id=f"run-{index}") for index in range(10)]
        first = build_label_sample(runs, size=3)
        second = build_label_sample(runs, size=3)
        self.assertEqual(len(first), 3)
        self.assertEqual(
            [row["run_key"] for row in first],
            [row["run_key"] for row in second],
        )
        self.assertEqual(build_label_sample(runs, size=0), [])


class LuiProductionScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """加载脚本模块。"""
        cls.script = _load_script_module()

    def test_dry_run_without_source_exits_zero(self) -> None:
        """默认无数据源时为 dry-run，不连接任何存储。"""
        exit_code = self.script.main([])
        self.assertEqual(exit_code, 0)

    def test_loads_export_with_window_filter(self) -> None:
        """导出目录应按窗口过滤并限制条数。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "runs.ndjson").write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        _run(run_id="in-window"),
                        _run(run_id="too-early", created_at="2026-01-01T00:00:00+00:00"),
                    ]
                ),
                encoding="utf-8",
            )
            runs, calls, events = self.script.load_from_export(
                str(base),
                since=None,
                until=None,
                limit=1,
            )
            self.assertEqual(len(runs), 1)
            self.assertEqual(calls, [])
            self.assertEqual(events, [])

    def test_db_loader_does_not_let_latest_page_hide_historical_window(self) -> None:
        """数据库只读采样应跨页跳过窗口后的最新数据。"""

        class Repository:
            """按 created_at 倒序模拟仓储分页。"""

            def list_all(
                self,
                *,
                page: int,
                page_size: int,
                sort_field: str,
                reverse: bool,
            ):
                """返回一页模拟文档。"""
                rows = sorted(
                    [
                        _run(run_id="latest", created_at="2026-09-01T00:00:00+00:00"),
                        _run(run_id="in-window", created_at="2026-08-28T10:00:00+00:00"),
                        _run(run_id="too-early", created_at="2026-08-01T00:00:00+00:00"),
                    ],
                    key=lambda item: item[sort_field],
                    reverse=reverse,
                )
                start = (page - 1) * page_size
                return rows[start : start + page_size], len(rows)

        rows = self.script._load_window_from_repository(
            Repository(),
            since=self.script._parse_time("2026-08-14T00:00:00+00:00"),
            until=self.script._parse_time("2026-08-28T23:59:59+00:00"),
            limit=10,
        )

        self.assertEqual([row["run_id"] for row in rows], ["in-window"])


if __name__ == "__main__":
    unittest.main()
