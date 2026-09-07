"""LUI 录制事实评测的环境口径测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.lui.runner import load_dataset
from evaluation.lui.schemas import DATASET_VERSION


DATASET_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "lui" / "dataset"
RECORDED_KNOWLEDGE_BASE_IDS = frozenset(
    {
        "e698c2e9-3ca6-4380-a4c0-dd349a9e9cb3",
        "cd049d65-2bcc-49ce-b51f-deb4070d0759",
        "f4022d41-a2e6-42df-9ceb-a92b232f04ad",
        "e8fedc4e-7708-44c1-b159-30bb1e67ad3d",
        "80795841-63ea-489b-847d-37712b508e55",
    }
)
RECORDED_TOOL_IDS = frozenset(
    {
        "algorithm:electrolyte_formulation_predictor",
        "algorithm:pi_synthesis_mock",
        "algorithm:polymer_tg_knn_upload_test",
        "algorithm:polymer_tg_knn_upload_test_manual",
        "algorithm:polymer_tg_knn_upload_test_ui",
    }
)


class LuiRecordedEnvironmentTest(unittest.TestCase):
    def test_dataset_version_is_incremented_for_real_environment(self) -> None:
        """切换真实录制环境时必须递增数据集版本。"""
        self.assertEqual(DATASET_VERSION, "2026.09.01")

    def test_all_tasks_only_reference_recorded_environment(self) -> None:
        """full 录制任务不得引用不可调用的内置适配器或假想知识库。"""
        tasks = load_dataset(DATASET_DIR)
        for task in tasks:
            with self.subTest(task=task.id):
                tool_ids = set(task.context.selected_tool_ids)
                tool_ids.update(call.tool_id for call in task.expected.tool_calls)
                if task.fixture is not None:
                    tool_ids.update(call.tool_id for call in task.fixture.tool_calls)
                if tool_ids:
                    self.assertLessEqual(tool_ids, RECORDED_TOOL_IDS)

                knowledge_ids = set(task.context.knowledge_base_ids)
                self.assertLessEqual(knowledge_ids, RECORDED_KNOWLEDGE_BASE_IDS)

    def test_tool_tasks_expect_controlled_confirmation(self) -> None:
        """active 垂类工具默认强制确认，Golden 应把受控确认纳入期望。"""
        for task in load_dataset(DATASET_DIR):
            if task.expected.task_success and task.expected.tool_calls:
                with self.subTest(task=task.id):
                    self.assertEqual(task.expected.escalation.level, "confirmation")

    def test_real_environment_tools_are_covered(self) -> None:
        """工具题应覆盖当前 5 个已激活垂类模型。"""
        used_tool_ids: set[str] = set()
        for task in load_dataset(DATASET_DIR):
            used_tool_ids.update(task.context.selected_tool_ids)
            used_tool_ids.update(call.tool_id for call in task.expected.tool_calls)
        self.assertEqual(used_tool_ids, RECORDED_TOOL_IDS)


if __name__ == "__main__":
    unittest.main()
