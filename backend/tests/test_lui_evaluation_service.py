"""LUI 评测基线服务与 API 测试。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.services.lui_evaluation_service import (
    list_baseline_modes,
    load_baseline_summary,
)


class LuiEvaluationServiceTest(unittest.TestCase):
    def test_lists_modes_and_ignores_non_baseline_files(self) -> None:
        """只识别 smoke/full 前缀的受控基线文件。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "smoke-2026.08.28.json").write_text("{}", encoding="utf-8")
            (base / "full-2026.08.28.json").write_text("{}", encoding="utf-8")
            (base / "manual-review-2026.08.28.json").write_text("{}", encoding="utf-8")
            self.assertEqual(list_baseline_modes(base), ["full", "smoke"])

    def test_loads_latest_baseline_summary(self) -> None:
        """应读取指定模式最新基线并投影页面字段。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            payload = {
                "evaluation_id": "lui-eval-smoke-test",
                "dataset_version": "2026.08.28",
                "mode": "smoke",
                "generated_at": "2026-08-28T00:00:00+00:00",
                "summary": {"evaluated_tasks": 37, "task_success_rate": 1.0},
                "metrics": {"m1": {"label": "任务成功率", "pass_rate": 1.0}},
                "by_category": {},
                "by_mode": {},
                "metadata": {"facts_source": "fixture", "manual_review": {"metrics": {}}},
            }
            (base / "smoke-2026.08.27.json").write_text("{}", encoding="utf-8")
            (base / "smoke-2026.08.28.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            summary = load_baseline_summary("smoke", base)
            self.assertTrue(summary["available"])
            self.assertEqual(summary["evaluation_id"], "lui-eval-smoke-test")
            self.assertEqual(summary["source_file"], "smoke-2026.08.28.json")
            self.assertEqual(summary["facts_source"], "fixture")
            self.assertEqual(summary["manual_review"], {"metrics": {}})

    def test_missing_baseline_returns_available_false(self) -> None:
        """无基线时返回 available=False 与可用模式。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            (base / "smoke-2026.08.28.json").write_text("{}", encoding="utf-8")
            summary = load_baseline_summary("full", base)
            self.assertFalse(summary["available"])
            self.assertEqual(summary["available_modes"], ["smoke"])

    def test_rejects_unknown_mode(self) -> None:
        """非法模式应拒绝，防止路径拼接。"""
        with self.assertRaises(ValueError):
            load_baseline_summary("../secrets", "/tmp")


class LuiEvaluationApiTest(ComputationTestCase):
    def test_summary_endpoint_requires_admin_and_returns_payload(self) -> None:
        """评测基线接口应在关闭鉴权的测试环境返回基线投影。"""
        response = self.client.get("/api/v1/assistant/lui-evaluation/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("available", payload)
        self.assertIn(payload["mode"], ("smoke", "full"))
