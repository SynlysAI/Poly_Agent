"""LUI Golden Set schema 测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from evaluation.lui.runner import load_dataset
from evaluation.lui.schemas import GoldenTask


DATASET_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "lui" / "dataset"


class LuiEvalSchemasTest(unittest.TestCase):
    def test_dataset_loads_with_balanced_buckets(self) -> None:
        """数据集应加载 80 条任务且 8 个分桶均衡。"""
        tasks = load_dataset(DATASET_DIR)
        categories: dict[str, int] = {}
        for task in tasks:
            categories[task.category] = categories.get(task.category, 0) + 1
        self.assertEqual(len(tasks), 80)
        self.assertEqual(len(categories), 8)
        self.assertEqual(set(categories.values()), {10})
        self.assertGreater(sum(1 for task in tasks if task.fixture), 30)

    def test_tool_task_requires_tool_capability(self) -> None:
        """工具任务缺少 tool_calling 声明应校验失败。"""
        with self.assertRaises(ValueError):
            GoldenTask.model_validate(
                {
                    "id": "LUI-XX-0001",
                    "category": "tool_argument",
                    "messages": [{"role": "user", "content": "预测"}],
                    "expected": {
                        "tool_calls": [{"tool_id": "algorithm:weknora_adapter"}]
                    },
                }
            )

    def test_tolerance_requires_non_negative_value(self) -> None:
        """absolute 容忍缺少非负 value 应校验失败。"""
        with self.assertRaises(ValueError):
            GoldenTask.model_validate(
                {
                    "id": "LUI-XX-0002",
                    "category": "tool_argument",
                    "requires_model_capability": "tool_calling",
                    "messages": [{"role": "user", "content": "推荐"}],
                    "expected": {
                        "tool_calls": [
                            {
                                "tool_id": "algorithm:mobo_alchemist_adapter",
                                "arguments": {"batch_size": 5},
                                "argument_tolerance": {
                                    "batch_size": {"kind": "absolute", "value": -1}
                                },
                            }
                        ]
                    },
                }
            )

    def test_refusal_bucket_requires_answer(self) -> None:
        """拒绝分桶缺少期望回答应校验失败。"""
        with self.assertRaises(ValueError):
            GoldenTask.model_validate(
                {
                    "id": "LUI-XX-0003",
                    "category": "refusal_boundary",
                    "messages": [{"role": "user", "content": "危险请求"}],
                    "expected": {"task_success": True},
                }
            )

    def test_duplicate_task_ids_rejected(self) -> None:
        """重复任务 ID 应在数据集加载时失败。"""
        task = {
            "id": "LUI-XX-0004",
            "category": "project_fact",
            "messages": [{"role": "user", "content": "项目名"}],
            "expected": {"task_success": True},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dup.yaml"
            path.write_text(yaml.safe_dump([task, task]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_dataset(temp_dir)


if __name__ == "__main__":
    unittest.main()
