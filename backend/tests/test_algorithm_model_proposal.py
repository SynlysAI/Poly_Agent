"""算法版本模型提案解析辅助函数测试。"""

from __future__ import annotations

import unittest

from app.services.algorithm_model_proposal import (
    CONFIGURED_MODEL_PROPOSAL_SOURCE,
    CONTRACT_MODEL_PROPOSAL_SOURCE,
    NOT_CONFIGURED_SOURCE,
    resolve_model_proposal,
)


class AlgorithmModelProposalTest(unittest.TestCase):
    """覆盖显式参数模板来源边界。"""

    def test_top_level_model_proposal_has_priority(self) -> None:
        """版本顶层显式模板优先于契约内模板。"""
        proposal, source = resolve_model_proposal(
            {
                "model_proposal": {"smiles": "CCC"},
                "contract": {"model_proposal": {"smiles": "CCO"}},
            }
        )
        self.assertEqual(source, CONFIGURED_MODEL_PROPOSAL_SOURCE)
        self.assertEqual(proposal, {"smiles": "CCC"})

    def test_contract_model_proposal_is_explicit_source(self) -> None:
        """契约内显式 model_proposal 可以作为回填来源。"""
        proposal, source = resolve_model_proposal(
            {
                "contract": {"model_proposal": {"smiles": "CCC"}},
            }
        )
        self.assertEqual(source, CONTRACT_MODEL_PROPOSAL_SOURCE)
        self.assertEqual(proposal, {"smiles": "CCC"})

    def test_sample_input_and_schema_do_not_derive_proposal(self) -> None:
        """sample_input 与 schema 都不能自动生成参数模板。"""
        proposal, source = resolve_model_proposal(
            {
                "contract": {"sample_input": {"smiles": "C=C(F)F"}},
                "input_schema": {
                    "fields": {"smiles": "string", "temperature": "number"},
                    "field_types": {"temperature": "number"},
                    "required": ["smiles"],
                }
            }
        )
        self.assertEqual(source, NOT_CONFIGURED_SOURCE)
        self.assertIsNone(proposal)

if __name__ == "__main__":
    unittest.main()
