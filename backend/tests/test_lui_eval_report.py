"""LUI 评测报告测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.lui.report import build_report, render_markdown, save_baseline, write_report
from evaluation.lui.runner import run_evaluation


DATASET_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "lui" / "dataset"


class LuiEvalReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """一次性执行 fixture 快速评测供报告断言使用。"""
        cls.report, cls.evaluations = run_evaluation(DATASET_DIR, mode="smoke")

    def test_report_summary_and_metric_rows(self) -> None:
        """报告应包含汇总、八项指标与分桶/模式拆解。"""
        summary = self.report["summary"]
        self.assertEqual(summary["evaluated_tasks"], len(self.evaluations))
        self.assertGreater(summary["evaluated_tasks"], 30)
        self.assertIn("task_success_rate", summary)
        self.assertEqual(set(self.report["metrics"]), {"m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"})
        self.assertEqual(len(self.report["by_category"]), 8)
        self.assertIn("qa", self.report["by_mode"])
        self.assertIn("deep", self.report["by_mode"])

    def test_markdown_renders_metric_tables(self) -> None:
        """Markdown 应包含指标表与分桶表。"""
        markdown = render_markdown(self.report)
        self.assertIn("# LUI Agent 评测报告", markdown)
        self.assertIn("任务成功率（m1）", markdown)
        self.assertIn("幻觉率（m5）", markdown)
        self.assertIn("| 分桶 | 任务数 | 成功 | 成功率 |", markdown)
        self.assertIn("fixture", self.report["metadata"]["facts_source"])

    def test_write_report_outputs_json_markdown_and_cases(self) -> None:
        """报告输出应包含 JSON、Markdown 与失败样例。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = write_report(self.report, self.evaluations, temp_dir)
            payload = json.loads(Path(paths["report_json"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["evaluation_id"], self.report["evaluation_id"])
            self.assertEqual(len(payload["tasks"]), len(self.evaluations))
            self.assertTrue(Path(paths["report_markdown"]).exists())
            if self.report["failures"]:
                expected_case = Path(temp_dir) / "cases" / f"{self.report['failures'][0]['task_id']}.md"
                self.assertTrue(expected_case.exists())

    def test_baseline_keeps_machine_fields_only(self) -> None:
        """基线应保留汇总指标但不含逐任务明细。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            baseline_path = save_baseline(self.report, Path(temp_dir) / "baseline.json")
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            self.assertIn("metrics", baseline)
            self.assertIn("by_category", baseline)
            self.assertNotIn("tasks", baseline)
            self.assertNotIn("failures", baseline)


if __name__ == "__main__":
    unittest.main()
