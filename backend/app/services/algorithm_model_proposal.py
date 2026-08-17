"""算法版本显式参数模板解析。"""

from __future__ import annotations

from typing import Any


CONFIGURED_MODEL_PROPOSAL_SOURCE = "configured_model_proposal"
CONTRACT_MODEL_PROPOSAL_SOURCE = "contract_model_proposal"
NOT_CONFIGURED_SOURCE = "not_configured"


def resolve_model_proposal(version_doc: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """解析显式版本级参数模板，不从 sample_input 或 schema 自动派生。

    Args:
        version_doc: 算法版本文档。

    Returns:
        (参数模板, 来源)；未显式配置时参数模板为 None。
    """
    configured = version_doc.get("model_proposal")
    if isinstance(configured, dict) and configured:
        return configured, CONFIGURED_MODEL_PROPOSAL_SOURCE

    contract = version_doc.get("contract") or {}
    contract_proposal = contract.get("model_proposal")
    if isinstance(contract_proposal, dict) and contract_proposal:
        return contract_proposal, CONTRACT_MODEL_PROPOSAL_SOURCE

    return None, NOT_CONFIGURED_SOURCE
