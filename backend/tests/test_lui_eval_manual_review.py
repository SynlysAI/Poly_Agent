"""LUI 评测人工抽检工具测试。"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from evaluation.lui.manual_review import (
    build_review_sheet,
    load_review_sheet,
    sample_review_items,
    summarize_review,
    validate_review_sheet_alignment,
    validate_sheet_completed,
)
from evaluation.lui.runner import load_dataset, run_evaluation


DATASET_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "lui" / "dataset"


class LuiManualReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """一次性执行 fixture 快速评测供抽检断言使用。"""
        cls.tasks = load_dataset(DATASET_DIR)
        cls.report, cls.evaluations = run_evaluation(DATASET_DIR, mode="smoke")

    def test_sample_meets_ratio_and_covers_categories(self) -> None:
        """抽样应不低于 20%，且样本覆盖该指标全部适用分桶。"""
        pairs = sample_review_items(self.tasks, self.evaluations)
        for metric in ("m4", "m5"):
            applicable = [
                item
                for item in self.evaluations
                if item.outcomes[metric].applicable
            ]
            sampled = [task_id for task_id, key in pairs if key == metric]
            expected = max(2, math.ceil(len(applicable) * 0.2))
            self.assertGreaterEqual(len(sampled), expected)
            sampled_categories = {
                item.category
                for item in self.evaluations
                if item.task_id in sampled
            }
            applicable_categories = {item.category for item in applicable}
            self.assertEqual(sampled_categories, applicable_categories)

    def test_sample_rejects_low_ratio(self) -> None:
        """抽检比例低于 20% 应拒绝。"""
        with self.assertRaises(ValueError):
            sample_review_items(self.tasks, self.evaluations, ratio=0.1)

    def test_build_sheet_contains_review_inputs(self) -> None:
        """抽检表应包含提示词、期望、回答与机器判定。"""
        sheet = build_review_sheet(
            self.tasks,
            self.evaluations,
            evaluation_id="lui-review-test",
            dataset_version="test",
        )
        self.assertGreater(len(sheet.items), 0)
        for item in sheet.items:
            self.assertIn(item.metric, ("m4", "m5"))
            self.assertTrue(item.prompt)
            self.assertTrue(item.answer)
            self.assertIsNotNone(item.machine_passed)

    def test_summary_computes_disagreement_rate(self) -> None:
        """汇总应计算不一致率并区分原因归类。"""
        sheet = build_review_sheet(
            self.tasks,
            self.evaluations,
            evaluation_id="lui-review-test",
            dataset_version="test",
        )
        for item in sheet.items:
            item.agree = True
        sheet.items[0].agree = False
        sheet.items[0].reason_category = "judge_false_positive"
        summary = summarize_review(sheet)
        metric = summary["metrics"][sheet.items[0].metric]
        self.assertEqual(metric["disagreements"], 1)
        self.assertGreater(metric["disagreement_rate"], 0)
        self.assertEqual(metric["reasons"]["判定器误判"], 1)

    def test_validate_sheet_completed_rejects_missing_fields(self) -> None:
        """未填写结论或缺失原因归类的抽检表应校验失败。"""
        sheet = build_review_sheet(
            self.tasks,
            self.evaluations,
            evaluation_id="lui-review-test",
            dataset_version="test",
        )
        with self.assertRaises(ValueError):
            validate_sheet_completed(sheet)
        for item in sheet.items:
            item.agree = False
        with self.assertRaises(ValueError):
            validate_sheet_completed(sheet)

    def test_alignment_validation_rejects_stale_review_sheet(self) -> None:
        """非当前评测批次或数据集版本的抽检表不得并入报告。"""
        sheet = build_review_sheet(
            self.tasks,
            self.evaluations,
            evaluation_id="old-evaluation",
            dataset_version=self.report["dataset_version"],
        )
        with self.assertRaisesRegex(ValueError, "evaluation_id"):
            validate_review_sheet_alignment(
                sheet,
                evaluation_id=self.report["evaluation_id"],
                dataset_version=self.report["dataset_version"],
            )
        sheet.evaluation_id = self.report["evaluation_id"]
        sheet.dataset_version = "old-dataset"
        with self.assertRaisesRegex(ValueError, "dataset_version"):
            validate_review_sheet_alignment(
                sheet,
                evaluation_id=self.report["evaluation_id"],
                dataset_version=self.report["dataset_version"],
            )

    def test_completed_baseline_review_record_is_valid(self) -> None:
        """入库的抽检记录应可解析、完整且不一致率为 0。"""
        record_path = (
            DATASET_DIR.parent / "baselines" / "manual-review-2026.08.28.json"
        )
        sheet = load_review_sheet(record_path)
        validate_sheet_completed(sheet)
        validate_review_sheet_alignment(
            sheet,
            evaluation_id=sheet.evaluation_id,
            dataset_version=sheet.dataset_version,
        )
        summary = summarize_review(sheet)
        for metric in ("m4", "m5"):
            row = summary["metrics"][metric]
            self.assertGreaterEqual(row["sampled"], 2)
            self.assertEqual(row["disagreements"], 0)
            self.assertTrue(row["within_limit"])
