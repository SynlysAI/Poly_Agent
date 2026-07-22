"""Generic uploaded-algorithm file adapter tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.research_engine import AlgorithmAssetSpec
from app.services.algorithm_file_adapters import AlgorithmFileAdapterRegistry


def test_table_adapter_parses_xlsx(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["name", "value"])
    sheet.append(["sample-a", 1.25])
    path = tmp_path / "table.xlsx"
    workbook.save(path)

    parsed = AlgorithmFileAdapterRegistry().parse(
        spec=AlgorithmAssetSpec(key="table_file", data_kind="table", parser="table.v1"),
        path=path,
        filename="table.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert parsed is not None
    assert parsed.artifact_type == "table_json"
    assert parsed.payload["data_kind"] == "table"
    assert parsed.payload["data"]["columns"] == ["name", "value"]
    assert parsed.payload["data"]["rows"][0]["value"] == 1.25


def test_series_adapter_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "series.pdf"
    path.write_bytes(b"%PDF-1.4")

    with pytest.raises(Exception) as exc_info:
        AlgorithmFileAdapterRegistry().parse(
            spec=AlgorithmAssetSpec(key="series_file", data_kind="series", parser="series_xy.v1"),
            path=path,
            filename="series.pdf",
            mime_type="application/pdf",
        )

    error = exc_info.value
    assert getattr(error, "status_code", None) == 422
    assert error.detail["code"] == "UNSUPPORTED_INPUT_ASSET_TYPE"
