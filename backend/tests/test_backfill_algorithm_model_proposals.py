"""算法参数模板回填脚本测试。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "backfill_algorithm_model_proposals.py"


def load_script_module():
    """加载历史回填脚本用于隔离测试。

    Returns:
        可替换仓库依赖的脚本模块。
    """
    spec = importlib.util.spec_from_file_location("backfill_algorithm_model_proposals_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BackfillAlgorithmModelProposalsTest(unittest.TestCase):
    """覆盖 sample_input 与显式参数模板的回填边界。"""

    def test_apply_does_not_backfill_sample_input(self) -> None:
        """没有显式 model_proposal 时不得把 sample_input 写入版本。"""
        module = load_script_module()
        version = {
            "version_id": "ver-sample",
            "contract": {"sample_input": {"smiles": "C=C(F)F"}},
        }
        updated: list[str] = []

        class FakeVersionRepository:
            @staticmethod
            def find_one(_query):
                return version

            @staticmethod
            def update_fields(version_id, _fields):
                updated.append(version_id)
                return True

        class FakeRegistryRepository:
            @staticmethod
            def list_algorithms(**_kwargs):
                return ([{"algorithm_id": "demo", "active_version_id": "ver-sample"}], 1)

        with patch.object(module, "AlgorithmRegistryRepository", FakeRegistryRepository), patch.object(
            module,
            "AlgorithmVersionRepository",
            FakeVersionRepository,
        ), patch.object(sys, "argv", ["backfill", "--apply"]):
            module.main()

        self.assertEqual(updated, [])

    def test_apply_backfills_explicit_model_proposal(self) -> None:
        """显式配置的 model_proposal 仍可作为管理端模板回填。"""
        module = load_script_module()
        version = {
            "version_id": "ver-explicit",
            "contract": {"model_proposal": {"smiles": "CCC"}},
        }
        updated: list[str] = []

        class FakeVersionRepository:
            @staticmethod
            def find_one(_query):
                return version

            @staticmethod
            def update_fields(version_id, _fields):
                updated.append(version_id)
                return True

        class FakeRegistryRepository:
            @staticmethod
            def list_algorithms(**_kwargs):
                return ([{"algorithm_id": "demo", "active_version_id": "ver-explicit"}], 1)

        with patch.object(module, "AlgorithmRegistryRepository", FakeRegistryRepository), patch.object(
            module,
            "AlgorithmVersionRepository",
            FakeVersionRepository,
        ), patch.object(sys, "argv", ["backfill", "--apply"]):
            module.main()

        self.assertEqual(updated, ["ver-explicit"])


if __name__ == "__main__":
    unittest.main()
