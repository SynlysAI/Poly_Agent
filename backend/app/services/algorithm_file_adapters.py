"""Generic file adapters for uploaded algorithm assets."""

from __future__ import annotations

import csv
import json
import math
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.schemas.research_engine import AlgorithmAssetSpec


SUPPORTED_DATA_KINDS = {"table", "series", "image", "json", "text", "binary"}
SUPPORTED_PARSERS = {"auto", "table.v1", "series_xy.v1", "json.v1", "text.v1", "binary.v1"}
TEXT_EXTENSIONS = {".txt", ".dat", ".csv", ".md", ".log"}
TABLE_EXTENSIONS = {".csv", ".xlsx"}
SERIES_EXTENSIONS = {".txt", ".dat", ".csv", ".xlsx"}
JSON_EXTENSIONS = {".json"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class ParsedInputAsset:
    """Platform-normalized representation of an uploaded algorithm file."""

    key: str
    data_kind: str
    parser: str
    payload: dict[str, Any]
    artifact_type: str
    mime_type: str = "application/json"
    warnings: list[str] = field(default_factory=list)


class AlgorithmFileAdapterRegistry:
    """Resolve and run generic file parsers for algorithm input assets."""

    def parse(self, *, spec: AlgorithmAssetSpec, path: Path, filename: str | None = None, mime_type: str | None = None) -> ParsedInputAsset | None:
        self.validate_supported(spec=spec, filename=filename or path.name, mime_type=mime_type)
        parser = self._resolve_parser(spec=spec, path=path)
        if parser == "binary.v1":
            return None
        if parser == "json.v1":
            return self._parse_json(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        if parser == "text.v1":
            return self._parse_text(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        if parser == "table.v1":
            return self._parse_table(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        if parser == "series_xy.v1":
            return self._parse_series_xy(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        raise self.unsupported_error(spec=spec, filename=filename or path.name, mime_type=mime_type, suffix=path.suffix.lower())

    def validate_supported(self, *, spec: AlgorithmAssetSpec, filename: str, mime_type: str | None = None) -> None:
        suffix = Path(filename).suffix.lower()
        parser = (spec.parser or "auto").strip() or "auto"
        if parser not in SUPPORTED_PARSERS:
            raise self.unsupported_error(spec=spec, filename=filename, mime_type=mime_type, suffix=suffix)
        if parser == "auto":
            data_kind = (spec.data_kind or "").strip()
            if data_kind and data_kind not in SUPPORTED_DATA_KINDS:
                raise self.unsupported_error(spec=spec, filename=filename, mime_type=mime_type, suffix=suffix)
        if spec.extensions and suffix not in {item.lower() for item in spec.extensions}:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "UNSUPPORTED_INPUT_ASSET_TYPE",
                    "message": f"输入文件 {spec.key} 扩展名不受支持",
                    "details": {
                        "asset_key": spec.key,
                        "filename": filename,
                        "extension": suffix,
                        "supported_extensions": spec.extensions,
                    },
                },
            )
        if spec.mime_types and mime_type and mime_type not in set(spec.mime_types):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "UNSUPPORTED_INPUT_ASSET_TYPE",
                    "message": f"输入文件 {spec.key} MIME 类型不受支持",
                    "details": {
                        "asset_key": spec.key,
                        "filename": filename,
                        "mime_type": mime_type,
                        "supported_mime_types": spec.mime_types,
                    },
                },
            )
        resolved_parser = self._resolve_parser_for_name(spec=spec, filename=filename)
        supported_extensions = self._supported_extensions_for_parser(resolved_parser)
        if supported_extensions and suffix not in supported_extensions:
            raise self.unsupported_error(spec=spec, filename=filename, mime_type=mime_type, suffix=suffix)

    def supported_extensions_for(self, spec: AlgorithmAssetSpec) -> list[str]:
        if spec.extensions:
            return sorted({item.lower() for item in spec.extensions})
        parser = (spec.parser or "auto").strip() or "auto"
        data_kind = (spec.data_kind or "").strip()
        if parser == "table.v1" or data_kind == "table":
            return sorted(TABLE_EXTENSIONS)
        if parser == "series_xy.v1" or data_kind == "series":
            return sorted(SERIES_EXTENSIONS)
        if parser == "json.v1" or data_kind == "json":
            return sorted(JSON_EXTENSIONS)
        if parser == "text.v1" or data_kind == "text":
            return sorted(TEXT_EXTENSIONS)
        if data_kind == "image":
            return sorted(IMAGE_EXTENSIONS)
        return []

    def _resolve_parser_for_name(self, *, spec: AlgorithmAssetSpec, filename: str) -> str:
        parser = (spec.parser or "auto").strip() or "auto"
        if parser != "auto":
            return parser
        suffix = Path(filename).suffix.lower()
        data_kind = (spec.data_kind or "").strip()
        if data_kind == "table":
            return "table.v1"
        if data_kind == "series":
            return "series_xy.v1"
        if data_kind == "json" or suffix in JSON_EXTENSIONS:
            return "json.v1"
        if data_kind == "text":
            return "text.v1"
        if data_kind in {"binary", "image"}:
            return "binary.v1"
        if suffix in TABLE_EXTENSIONS:
            return "table.v1"
        if suffix in TEXT_EXTENSIONS:
            return "text.v1"
        return "binary.v1"

    @staticmethod
    def _supported_extensions_for_parser(parser: str) -> set[str]:
        if parser == "table.v1":
            return TABLE_EXTENSIONS
        if parser == "series_xy.v1":
            return SERIES_EXTENSIONS
        if parser == "json.v1":
            return JSON_EXTENSIONS
        if parser == "text.v1":
            return TEXT_EXTENSIONS
        return set()

    def unsupported_error(
        self,
        *,
        spec: AlgorithmAssetSpec,
        filename: str,
        mime_type: str | None,
        suffix: str,
    ) -> HTTPException:
        return HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_INPUT_ASSET_TYPE",
                "message": f"输入文件 {spec.key} 当前不支持该文件类型",
                "details": {
                    "asset_key": spec.key,
                    "filename": filename,
                    "extension": suffix,
                    "mime_type": mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    "parser": spec.parser or "auto",
                    "data_kind": spec.data_kind,
                    "supported_extensions": self.supported_extensions_for(spec),
                    "supported_parsers": sorted(SUPPORTED_PARSERS),
                },
            },
        )

    def _resolve_parser(self, *, spec: AlgorithmAssetSpec, path: Path) -> str:
        parser = (spec.parser or "auto").strip() or "auto"
        suffix = path.suffix.lower()
        if parser != "auto":
            if parser not in SUPPORTED_PARSERS:
                raise self.unsupported_error(spec=spec, filename=path.name, mime_type=None, suffix=suffix)
            return parser
        data_kind = (spec.data_kind or "").strip()
        if data_kind == "table":
            return "table.v1"
        if data_kind == "series":
            return "series_xy.v1"
        if data_kind == "json" or suffix in JSON_EXTENSIONS:
            return "json.v1"
        if data_kind == "text":
            return "text.v1"
        if data_kind in {"binary", "image"}:
            return "binary.v1"
        if suffix in TABLE_EXTENSIONS:
            return "table.v1"
        if suffix in TEXT_EXTENSIONS:
            return "text.v1"
        return "binary.v1"

    def _base_payload(self, *, spec: AlgorithmAssetSpec, path: Path, parser: str, filename: str | None, mime_type: str | None) -> dict[str, Any]:
        return {
            "schema_version": "polyagent_parsed_input.v1",
            "asset_key": spec.key,
            "data_kind": spec.data_kind,
            "parser": parser,
            "source": {
                "filename": filename or path.name,
                "extension": path.suffix.lower(),
                "mime_type": mime_type or mimetypes.guess_type(filename or path.name)[0],
                "size_bytes": path.stat().st_size,
            },
            "metadata": {},
            "warnings": [],
        }

    def _parse_json(self, *, spec: AlgorithmAssetSpec, path: Path, parser: str, filename: str | None, mime_type: str | None) -> ParsedInputAsset:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"code": "INPUT_ASSET_PARSE_FAILED", "message": f"输入文件 {spec.key} 不是合法 JSON", "details": {"asset_key": spec.key, "error": str(exc)}}) from exc
        payload = self._base_payload(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        payload.update({"data_kind": "json", "data": data})
        return ParsedInputAsset(spec.key, "json", parser, payload, "parsed_input_json")

    def _parse_text(self, *, spec: AlgorithmAssetSpec, path: Path, parser: str, filename: str | None, mime_type: str | None) -> ParsedInputAsset:
        text = path.read_text(encoding="utf-8", errors="replace")
        payload = self._base_payload(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        payload.update({"data_kind": "text", "data": {"text": text}})
        return ParsedInputAsset(spec.key, "text", parser, payload, "parsed_input_json")

    def _parse_table(self, *, spec: AlgorithmAssetSpec, path: Path, parser: str, filename: str | None, mime_type: str | None) -> ParsedInputAsset:
        frame = self._read_frame(path)
        payload = self._base_payload(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        rows = self._frame_rows(frame)
        payload.update({
            "data_kind": "table",
            "data": {"columns": [str(col) for col in frame.columns], "rows": rows},
            "metadata": {"row_count": len(rows), "column_count": len(frame.columns)},
        })
        return ParsedInputAsset(spec.key, "table", parser, payload, "table_json")

    def _parse_series_xy(self, *, spec: AlgorithmAssetSpec, path: Path, parser: str, filename: str | None, mime_type: str | None) -> ParsedInputAsset:
        points = self._read_xy_points(path)
        if not points:
            raise HTTPException(status_code=422, detail={"code": "INPUT_ASSET_PARSE_FAILED", "message": f"输入文件 {spec.key} 未解析到 x-y 数据", "details": {"asset_key": spec.key, "filename": filename or path.name}})
        payload = self._base_payload(spec=spec, path=path, parser=parser, filename=filename, mime_type=mime_type)
        payload.update({
            "data_kind": "series",
            "data": {"series_type": "xy", "points": points},
            "metadata": {"point_count": len(points), "x_min": points[0]["x"], "x_max": points[-1]["x"]},
        })
        return ParsedInputAsset(spec.key, "series", parser, payload, "series_json")

    def _read_frame(self, path: Path):
        import pandas as pd

        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            return pd.read_excel(path, engine="openpyxl")
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".txt", ".dat"}:
            return pd.read_csv(path, sep=r"[\s,;]+", engine="python")
        raise self.unsupported_error(
            spec=AlgorithmAssetSpec(key="file", data_kind="table", parser="table.v1"),
            filename=path.name,
            mime_type=None,
            suffix=suffix,
        )

    def _read_xy_points(self, path: Path) -> list[dict[str, float]]:
        suffix = path.suffix.lower()
        if suffix == ".xlsx":
            frame = self._read_frame(path)
            records = frame.iloc[:, :2].values.tolist()
        else:
            records = []
            with path.open("r", encoding="utf-8", errors="replace", newline="") as fp:
                for row in csv.reader(fp):
                    if len(row) == 1:
                        row = row[0].replace(",", " ").replace(";", " ").split()
                    records.append(row[:2])
        points: list[dict[str, float]] = []
        for row in records:
            if len(row) < 2:
                continue
            try:
                x = float(row[0])
                y = float(row[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append({"x": x, "y": y})
        return points

    @staticmethod
    def _frame_rows(frame) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for raw in frame.to_dict(orient="records"):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                if value is None:
                    row[str(key)] = None
                elif isinstance(value, float) and math.isnan(value):
                    row[str(key)] = None
                elif hasattr(value, "item"):
                    row[str(key)] = value.item()
                else:
                    row[str(key)] = value
            rows.append(row)
        return rows
