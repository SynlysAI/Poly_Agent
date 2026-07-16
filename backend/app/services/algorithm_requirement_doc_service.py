"""需求文档模板下载与解析服务。"""

from __future__ import annotations

import re
import io
import zipfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import yaml
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.research_engine import (
    AlgorithmHandoffCreate,
    AlgorithmIOSchema,
    AlgorithmRequirementDocumentParseResult,
)


DOCX_TEMPLATE_FILENAME = "PolyAgent_模型数据集成需求收集_填写模板.docx"
DOCX_TEMPLATE_PATH = Path("refer") / "AlgoRequirement" / DOCX_TEMPLATE_FILENAME
MARKDOWN_TEMPLATE_FILENAME = "polyagent-algorithm-requirement-template.md"
ALLOWED_EXTENSIONS = {".docx", ".md"}
WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


class AlgorithmRequirementDocService:
    """把需求文档模板转成可执行的接入草案。"""

    def download_template(self) -> tuple[str, bytes]:
        template_path = settings.project_root / DOCX_TEMPLATE_PATH
        if template_path.exists():
            return DOCX_TEMPLATE_FILENAME, template_path.read_bytes()
        return MARKDOWN_TEMPLATE_FILENAME, self.template_markdown().encode("utf-8")

    def parse_document(self, *, filename: str, content: bytes) -> AlgorithmRequirementDocumentParseResult:
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=422, detail="仅支持 .docx / .md 需求文档")

        text, docx_metadata = self._read_document_content(filename=filename, content=content, suffix=suffix)
        if not text:
            raise HTTPException(status_code=422, detail="需求文档不能为空")

        front_matter, body = self._split_front_matter(text)
        metadata = self._safe_load_yaml(front_matter) if front_matter else {}
        if metadata and not isinstance(metadata, dict):
            raise HTTPException(status_code=422, detail="需求文档模板顶部必须是 YAML 对象")

        metadata = {**(metadata or {}), **docx_metadata}
        title = self._extract_title(body) or self._string_value(metadata.get("name"))
        algorithm_id = self._string_value(metadata.get("algorithm_id")) or self._slugify(title)
        draft = self._build_draft(metadata, body, algorithm_id=algorithm_id, title=title)
        missing_fields = self._missing_fields(metadata, draft)
        warnings = self._warnings(metadata, draft, body)

        return AlgorithmRequirementDocumentParseResult(
            source_filename=filename,
            template_version=self._string_value(metadata.get("template_version")) or "0.1",
            ok=True,
            draft=draft,
            missing_fields=missing_fields,
            warnings=warnings,
            summary={
                "title": title or draft.name,
                "body_lines": len([line for line in body.splitlines() if line.strip()]),
                "detected_example_id": draft.example_id,
            },
        )

    def template_markdown(self) -> str:
        return (
            "---\n"
            "template_version: \"0.1\"\n"
            "algorithm_id: vertical_tg_predictor\n"
            "name: Polymer Tg Predictor\n"
            "version: 0.1.0\n"
            "example_id: generic_python_predictor\n"
            "owner_name: \n"
            "owner_contact: \n"
            "description: >\n"
            "  这里填写模型解决的问题、输入是什么、输出是什么。\n"
            "material_scope:\n"
            "  - universal\n"
            "requirements_hint:\n"
            "  - scikit-learn\n"
            "input_schema:\n"
            "  fields:\n"
            "    smiles: string\n"
            "  required:\n"
            "    - smiles\n"
            "output_schema:\n"
            "  fields:\n"
            "    prediction: object\n"
            "  required:\n"
            "    - prediction\n"
            "sample_input:\n"
            "  smiles: C=C(F)F\n"
            "---\n\n"
            "# Poly Agent 需求文档\n\n"
            "## 1. 目标\n"
            "请用最少文字描述这个算法要解决什么问题。\n\n"
            "## 2. 输入输出\n"
            "建议直接在 YAML front matter 中维护 input_schema / output_schema / sample_input。\n\n"
            "## 3. 依赖和说明\n"
            "如果有特殊依赖、资源限制或上线前注意事项，请写在这里。\n"
        )

    def _read_document_content(self, *, filename: str, content: bytes, suffix: str) -> tuple[str, dict[str, Any]]:
        if suffix == ".docx":
            return self._docx_to_text_and_metadata(filename=filename, content=content)
        return content.decode("utf-8", errors="replace").strip(), {}

    def _docx_to_text_and_metadata(self, *, filename: str, content: bytes) -> tuple[str, dict[str, Any]]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                root = ET.fromstring(zf.read("word/document.xml"))
        except (KeyError, ET.ParseError, zipfile.BadZipFile) as error:
            raise HTTPException(status_code=422, detail=f"无法解析 docx 需求文档: {error}") from error

        paragraphs = self._docx_paragraphs(root)
        tables = self._docx_tables(root)
        metadata = self._metadata_from_docx_tables(tables)
        metadata.update(self._metadata_from_docx_json_examples(paragraphs))
        return "\n".join(paragraphs).strip() or filename, metadata

    def _docx_paragraphs(self, root: ET.Element) -> list[str]:
        paragraphs: list[str] = []
        for paragraph in root.findall(".//w:p", WORD_NAMESPACE):
            text = self._docx_text(paragraph)
            if text:
                paragraphs.extend(line for line in text.splitlines() if line.strip())
        return paragraphs

    def _docx_tables(self, root: ET.Element) -> list[list[list[str]]]:
        tables: list[list[list[str]]] = []
        for table in root.findall(".//w:tbl", WORD_NAMESPACE):
            rows: list[list[str]] = []
            for table_row in table.findall("./w:tr", WORD_NAMESPACE):
                rows.append([self._docx_text(cell) for cell in table_row.findall("./w:tc", WORD_NAMESPACE)])
            tables.append(rows)
        return tables

    def _docx_text(self, element: ET.Element) -> str:
        parts: list[str] = []
        for node in element.iter():
            if node.tag == f"{{{WORD_NAMESPACE['w']}}}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{{{WORD_NAMESPACE['w']}}}br":
                parts.append("\n")
        return "".join(parts).strip()

    def _metadata_from_docx_tables(self, tables: list[list[list[str]]]) -> dict[str, Any]:
        values: dict[str, str] = {}
        for rows in tables:
            if not rows or len(rows[0]) < 2 or rows[0][0] != "字段":
                continue
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                key = row[0].strip()
                value = row[1].strip()
                if key and self._is_filled_docx_value(value):
                    values[key] = value

        metadata: dict[str, Any] = {}
        algorithm_name = values.get("算法名称 / 代号")
        if algorithm_name:
            name, algorithm_id = self._split_docx_name_and_id(algorithm_name)
            if name:
                metadata["name"] = name
            if algorithm_id:
                metadata["algorithm_id"] = algorithm_id
        owner = values.get("负责人")
        if owner:
            metadata["owner_name"] = owner.split("/")[0].strip() or owner
            contact = self._extract_email(owner)
            if contact:
                metadata["owner_contact"] = contact
        if values.get("算法功能介绍"):
            metadata["description"] = values["算法功能介绍"]
        if values.get("适用体系"):
            metadata["material_scope"] = self._normalize_material_scope(values["适用体系"])
        if values.get("依赖（附 requirements.txt）"):
            metadata["requirements_hint"] = self._normalize_requirements_hint(values["依赖（附 requirements.txt）"])
        if values.get("服务地址") or values.get("接口路径 + 方法"):
            metadata["example_id"] = "http_service_adapter"
        return metadata

    def _metadata_from_docx_json_examples(self, paragraphs: list[str]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        input_example = self._extract_json_after_label(paragraphs, "输入 JSON 示例")
        output_example = self._extract_json_after_label(paragraphs, "输出 JSON 示例")
        if input_example:
            metadata["sample_input"] = input_example
            metadata["input_schema"] = self._schema_from_mapping(input_example)
        if output_example:
            metadata["output_schema"] = self._schema_from_mapping(output_example)
        return metadata

    @staticmethod
    def _is_filled_docx_value(value: str) -> bool:
        stripped = value.strip()
        return bool(stripped) and stripped not in {"(示例)", "示例", "待定"}

    def _split_docx_name_and_id(self, value: str) -> tuple[str | None, str | None]:
        parts = [part.strip() for part in re.split(r"[/／\n]", value) if part.strip()]
        if not parts:
            return None, None
        if len(parts) == 1:
            return parts[0], self._slugify(parts[0])
        return parts[0], self._slugify(parts[-1])

    @staticmethod
    def _extract_email(value: str) -> str | None:
        match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
        return match.group(0) if match else None

    def _normalize_material_scope(self, value: str) -> list[str]:
        normalized = self._normalize_string_list(value)
        if not normalized:
            return ["universal"]
        scope_map = {
            "通用": "universal",
            "氟基": "fluoropolymer",
            "含氟": "fluoropolymer",
            "碳基": "carbon_polymer",
            "硅基": "silicon_polymer",
            "无机": "inorganic",
        }
        mapped: list[str] = []
        for item in normalized:
            match = next((value for keyword, value in scope_map.items() if keyword in item), item)
            if match not in mapped:
                mapped.append(match)
        return mapped or ["universal"]

    def _normalize_requirements_hint(self, value: str) -> list[str]:
        cleaned = value.replace("pip install -r requirements.txt", "")
        items = self._normalize_string_list(cleaned)
        return [item for item in items if item and item.lower() not in {"requirements.txt", "无"}]

    def _extract_json_after_label(self, paragraphs: list[str], label: str) -> dict[str, Any] | None:
        try:
            start = next(index for index, line in enumerate(paragraphs) if label in line)
        except StopIteration:
            return None
        buffer: list[str] = []
        collecting = False
        depth = 0
        for line in paragraphs[start + 1:]:
            stripped = line.strip()
            if not collecting and "{" not in stripped:
                if re.match(r"^\d+(\.\d+)*\s+|^第.+部分", stripped):
                    break
                continue
            collecting = True
            buffer.append(stripped)
            depth += stripped.count("{") - stripped.count("}")
            if collecting and depth <= 0 and "}" in stripped:
                break
        if not buffer:
            return None
        try:
            parsed = yaml.safe_load("\n".join(buffer))
        except yaml.YAMLError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _schema_from_mapping(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "fields": {str(key): self._schema_type(item) for key, item in value.items()},
            "required": [str(key) for key in value.keys()],
        }

    def _schema_type(self, value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and not isinstance(value, bool):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, list):
            return "list"
        if isinstance(value, dict):
            return "object"
        return "string"

    def _build_draft(
        self,
        metadata: dict[str, Any],
        body: str,
        *,
        algorithm_id: str,
        title: str | None,
    ) -> AlgorithmHandoffCreate:
        name = self._string_value(metadata.get("name")) or title or algorithm_id.replace("_", " ").title()
        version = self._string_value(metadata.get("version")) or "0.1.0"
        example_id = self._infer_example_id(metadata, body)
        material_scope = self._normalize_string_list(metadata.get("material_scope")) or ["universal"]
        requirements_hint = self._normalize_string_list(metadata.get("requirements_hint"))
        input_schema = self._normalize_schema(metadata.get("input_schema"), default_fields={"smiles": "string"})
        output_schema = self._normalize_schema(metadata.get("output_schema"), default_fields={"prediction": "object"})
        sample_input = self._normalize_mapping(metadata.get("sample_input"), default_value={"smiles": "C=C(F)F"})

        return AlgorithmHandoffCreate(
            algorithm_id=algorithm_id,
            name=name,
            version=version,
            example_id=example_id,
            owner_name=self._string_value(metadata.get("owner_name")),
            owner_contact=self._string_value(metadata.get("owner_contact")),
            description=self._string_value(metadata.get("description")) or self._extract_section(body, "目标"),
            material_scope=material_scope,
            input_schema=input_schema,
            output_schema=output_schema,
            sample_input=sample_input,
            requirements_hint=requirements_hint,
        )

    def _missing_fields(self, metadata: dict[str, Any], draft: AlgorithmHandoffCreate) -> list[str]:
        missing: list[str] = []
        for key in ("owner_name", "owner_contact"):
            if not self._string_value(metadata.get(key)):
                missing.append(key)
        if not draft.description:
            missing.append("description")
        if not draft.requirements_hint:
            missing.append("requirements_hint")
        return missing

    def _warnings(self, metadata: dict[str, Any], draft: AlgorithmHandoffCreate, body: str) -> list[str]:
        warnings: list[str] = []
        if not self._string_value(metadata.get("algorithm_id")):
            warnings.append("未填写 algorithm_id，已根据标题自动生成")
        if draft.example_id == "generic_python_predictor" and "smiles" not in draft.input_schema.fields:
            warnings.append("未识别到明显模板，已使用通用接入模板")
        if not self._extract_section(body, "依赖和说明"):
            warnings.append("文档正文较短，建议补充依赖和上线约束")
        return warnings

    def _infer_example_id(self, metadata: dict[str, Any], body: str) -> str:
        raw_example_id = self._string_value(metadata.get("example_id"))
        if raw_example_id:
            allowed = {
                "batch_formulation_predictor",
                "smiles_property_predictor",
                "file_based_predictor",
                "http_service_adapter",
                "generic_python_predictor",
            }
            if raw_example_id in allowed:
                return raw_example_id

        sample_input = self._normalize_mapping(metadata.get("sample_input"), default_value={})
        input_schema = self._normalize_schema(metadata.get("input_schema"), default_fields={})
        field_names = set(input_schema.fields.keys()) | set(sample_input.keys())
        if "formulations" in field_names:
            return "batch_formulation_predictor"
        if "smiles" in field_names:
            return "smiles_property_predictor"
        if {"file_ref", "file_path", "path"} & field_names:
            return "file_based_predictor"
        if {"payload", "request", "request_body"} & field_names or "http" in body.lower():
            return "http_service_adapter"
        return "generic_python_predictor"

    @staticmethod
    def _split_front_matter(text: str) -> tuple[str | None, str]:
        match = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", text, flags=re.S)
        if not match:
            return None, text
        return match.group(1), match.group(2)

    @staticmethod
    def _safe_load_yaml(value: str) -> Any:
        return yaml.safe_load(value)

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return str(value)

    def _normalize_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,，\n]", value) if item.strip()]
        if isinstance(value, list):
            items: list[str] = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        items.append(stripped)
                else:
                    items.append(str(item))
            return items
        return [str(value)]

    def _normalize_schema(self, value: Any, *, default_fields: dict[str, str]) -> AlgorithmIOSchema:
        schema = value if isinstance(value, dict) else {}
        fields = schema.get("fields") if isinstance(schema, dict) else None
        if not isinstance(fields, dict) or not fields:
            fields = dict(default_fields)
        required = schema.get("required") if isinstance(schema, dict) else None
        if not isinstance(required, list) or not required:
            required = list(fields.keys())[:1] if fields else []
        constraints = schema.get("constraints") if isinstance(schema, dict) and isinstance(schema.get("constraints"), dict) else {}
        field_defaults = schema.get("field_defaults") if isinstance(schema, dict) and isinstance(schema.get("field_defaults"), dict) else {}
        ui_hints = schema.get("ui_hints") if isinstance(schema, dict) and isinstance(schema.get("ui_hints"), dict) else {}
        field_options = schema.get("field_options") if isinstance(schema, dict) and isinstance(schema.get("field_options"), dict) else {}
        return AlgorithmIOSchema(
            fields={str(key): str(value) for key, value in fields.items()},
            required=[str(item) for item in required],
            constraints=constraints,
            field_defaults=field_defaults,
            ui_hints=ui_hints,
            field_options={
                str(key): [str(item) for item in (items if isinstance(items, list) else [items])]
                for key, items in field_options.items()
            },
        )

    @staticmethod
    def _normalize_mapping(value: Any, *, default_value: dict[str, Any]) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        return dict(default_value)

    @staticmethod
    def _extract_title(body: str) -> str | None:
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip() or None
        return None

    @staticmethod
    def _extract_section(body: str, heading: str) -> str | None:
        pattern = re.compile(rf"^##\s*{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)", re.M)
        match = pattern.search(body)
        if not match:
            return None
        content = match.group(1).strip()
        return content or None

    @staticmethod
    def _slugify(value: str | None) -> str:
        text = (value or "algorithm").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "_", text)
        slug = slug.strip("_")
        return slug or "algorithm"
