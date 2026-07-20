"""来源、引用与机构标注数据契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AttributionRole = Literal[
    "framework_reference",
    "method_reference",
    "implementation_source",
    "dependency",
    "developer",
]
"""来源角色。"""

AttributionVisibility = Literal["prominent", "detail"]
"""来源标注展示级别。"""


class AttributionItem(BaseModel):
    """单条来源、引用或开发者标注。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    role: AttributionRole
    organization: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    url: str | None = Field(default=None, max_length=600)
    citation_text: str | None = Field(default=None, max_length=1000)
    license: str | None = Field(default=None, max_length=120)
    logo_asset: str | None = Field(default=None, max_length=300)
    logo_alt: str | None = Field(default=None, max_length=160)
    visibility: AttributionVisibility = "detail"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化来源名称。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("来源名称不能为空")
        return normalized

    @field_validator("organization", "description", "url", "citation_text", "license", "logo_asset", "logo_alt")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """规范化可选文本字段。"""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ModuleAttribution(BaseModel):
    """系统模块来源标注。"""

    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    page_path: str | None = Field(default=None, max_length=160)
    summary: str = Field(min_length=1, max_length=600)
    implementation_boundary: str | None = Field(default=None, max_length=800)
    attributions: list[AttributionItem] = Field(default_factory=list)


class ModuleAttributionListData(BaseModel):
    """系统模块来源标注列表。"""

    items: list[ModuleAttribution]
    total: int
