"""算法版本模型提案解析辅助函数测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.algorithm_model_proposal import (
    PACKAGE_SAMPLE_SOURCE,
    CONTRACT_SAMPLE_SOURCE,
    SCHEMA_FALLBACK_SOURCE,
    build_model_proposal_from_schema,
    resolve_model_proposal,
)


class AlgorithmModelProposalTest(unittest.TestCase):
    """覆盖提案来源优先级和 schema 兜底生成。"""

    def test_package_sample_input_has_priority(self) -> None:
        """算法包内 tests/sample_input.json 存在时应优先使用。"""
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "package"
            (package_path / "tests").mkdir(parents=True)
            (package_path / "tests" / "sample_input.json").write_text(
                json.dumps({"smiles": "CCO"}),
                encoding="utf-8",
            )
            proposal, source = resolve_model_proposal(
                {
                    "package_path": str(package_path),
                    "contract": {"sample_input": {"smiles": "WRONG"}},
                    "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                }
            )
        self.assertEqual(source, PACKAGE_SAMPLE_SOURCE)
        self.assertEqual(proposal, {"smiles": "CCO"})

    def test_contract_sample_input_is_fallback_when_package_missing(self) -> None:
        """没有算法包样例时使用 contract.sample_input。"""
        proposal, source = resolve_model_proposal(
            {
                "contract": {"sample_input": {"smiles": "CCC"}},
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
            }
        )
        self.assertEqual(source, CONTRACT_SAMPLE_SOURCE)
        self.assertEqual(proposal, {"smiles": "CCC"})

    def test_schema_fallback_generates_declared_fields(self) -> None:
        """两个样例来源都缺失时按 input_schema 生成兜底提案。"""
        proposal, source = resolve_model_proposal(
            {
                "input_schema": {
                    "fields": {"smiles": "string", "temperature": "number"},
                    "field_types": {"temperature": "number"},
                    "required": ["smiles"],
                }
            }
        )
        self.assertEqual(source, SCHEMA_FALLBACK_SOURCE)
        self.assertEqual(set(proposal), {"smiles", "temperature"})
        self.assertEqual(proposal["smiles"], "string")
        self.assertEqual(proposal["temperature"], 0.0)

    def test_schema_fallback_respects_defaults_and_options(self) -> None:
        """field_defaults 优先，其次 field_options 第一项。"""
        proposal = build_model_proposal_from_schema(
            {
                "fields": {"mode": "string", "solvent": "string"},
                "field_defaults": {"mode": "fast"},
                "field_options": {"solvent": ["WATER", "DMSO"]},
                "required": ["mode", "solvent"],
            }
        )
        self.assertEqual(proposal["mode"], "fast")
        self.assertEqual(proposal["solvent"], "WATER")


if __name__ == "__main__":
    unittest.main()
