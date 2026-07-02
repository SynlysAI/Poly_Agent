"""Computation adapter registry."""

from __future__ import annotations

from fastapi import HTTPException

from app.computation_adapters.base import ComputationAdapter
from app.computation_adapters.local_structure import LocalStructureAdapter
from app.computation_adapters.local_xtb import LocalXtbAdapter
from app.computation_adapters.mock import MockComputationAdapter
from app.computation_adapters.orca_chemos_laser import OrcaChemosLaserAdapter


def get_adapter(workflow_type: str, engine: str) -> ComputationAdapter:
    """Resolve workflow/engine to a computation adapter."""
    if workflow_type in {"MOCK_XTB_ONLY", "MOCK_LASER"} and engine == "MOCK":
        return MockComputationAdapter()
    if workflow_type == "LOCAL_STRUCTURE" and engine in {"LOCAL", "RDKit", "OPENBABEL"}:
        return LocalStructureAdapter()
    if workflow_type == "LOCAL_XTB" and engine == "XTB":
        return LocalXtbAdapter()
    if workflow_type == "ORCA_CHEMOS_LASER" and engine == "ORCA":
        return OrcaChemosLaserAdapter()
    raise HTTPException(
        status_code=400,
        detail=f"不支持的计算 workflow/engine 组合：{workflow_type}/{engine}",
    )


def supported_workflow_engine_pairs() -> set[tuple[str, str]]:
    """Return supported workflow/engine pairs for validation and diagnostics."""
    return {
        ("MOCK_XTB_ONLY", "MOCK"),
        ("MOCK_LASER", "MOCK"),
        ("LOCAL_STRUCTURE", "LOCAL"),
        ("LOCAL_STRUCTURE", "RDKit"),
        ("LOCAL_STRUCTURE", "OPENBABEL"),
        ("LOCAL_XTB", "XTB"),
        ("ORCA_CHEMOS_LASER", "ORCA"),
    }
