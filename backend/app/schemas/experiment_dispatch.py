"""通用实验方案转发契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UtcDatetimeJsonModel


JsonValueType = Literal["string", "number", "integer", "boolean", "object", "array", "any"]
DispatchStatus = Literal["preview", "prepared", "sent", "accepted", "failed"]


class ExperimentTemplateParameterBinding(BaseModel):
    """模板参数从运行快照到实验参数的映射。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=160)
    source_paths: list[str] = Field(min_length=1, max_length=20)
    value_type: JsonValueType = "any"
    required: bool = False
    default_value: Any = None

    @field_validator("name", "source_paths")
    @classmethod
    def validate_text(cls, value):
        if isinstance(value, list):
            normalized = [str(item).strip() for item in value]
            if any(not item.startswith("/") for item in normalized):
                raise ValueError("source_paths 必须使用 JSON Pointer")
            return normalized
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("参数名称不能为空")
        return normalized


class ExperimentTemplateVariant(BaseModel):
    """评分选择器的一个执行变体。"""

    model_config = ConfigDict(extra="forbid")

    variant_id: str = Field(min_length=1, max_length=100)
    min_score: float = Field(ge=0)
    max_score: float = Field(ge=0)
    instruction_set_path: str = Field(min_length=1, max_length=500)
    hardware_graph_path: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_score")
    @classmethod
    def validate_range(cls, value: float, info):
        minimum = info.data.get("min_score")
        if minimum is not None and value < minimum:
            raise ValueError("max_score 不能小于 min_score")
        return value


class ExperimentTemplateSelector(BaseModel):
    """通用数值区间选择器。"""

    model_config = ConfigDict(extra="forbid")

    override_key: str = Field(min_length=1, max_length=100)
    value_paths: list[str] = Field(min_length=1, max_length=20)
    variants: list[ExperimentTemplateVariant] = Field(min_length=1, max_length=100)

    @field_validator("value_paths")
    @classmethod
    def validate_paths(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value]
        if any(not item.startswith("/") for item in normalized):
            raise ValueError("value_paths 必须使用 JSON Pointer")
        return normalized


class ExperimentTemplateDefinition(BaseModel):
    """仓库内版本化实验模板定义。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment_template.v1"] = "experiment_template.v1"
    template_id: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parameter_bindings: list[ExperimentTemplateParameterBinding] = Field(default_factory=list)
    selector: ExperimentTemplateSelector


class ExperimentTemplateListData(BaseModel):
    items: list[ExperimentTemplateDefinition]
    total: int


class ExperimentDispatchBuildRequest(BaseModel):
    """生成实验方案预览或持久化记录的请求。"""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=100)
    template_version: str | None = Field(default=None, max_length=40)
    experiment_name: str | None = Field(default=None, max_length=200)
    experiment_notes: str | None = Field(default=None, max_length=10000)
    selection_inputs: dict[str, Any] = Field(default_factory=dict)
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)
    variant_id: str | None = Field(default=None, max_length=100)

    @field_validator("template_id", "template_version", "experiment_name", "experiment_notes", "variant_id")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class ExperimentDispatchSource(BaseModel):
    run_id: str
    algorithm_id: str
    algorithm_version_id: str | None = None


class ExperimentDispatchTemplateRef(BaseModel):
    template_id: str
    template_version: str
    variant_id: str


class ExperimentDispatchProfileRef(BaseModel):
    profile_id: str
    profile_version: str


class ExperimentDispatchTargetRef(BaseModel):
    target_id: str
    target_version: str


class ExperimentDispatchSelection(BaseModel):
    score: float | None = None
    source_path: str | None = None
    reason: str | None = None


class ExperimentDispatchProvenance(BaseModel):
    parameter_bindings: list[dict[str, Any]] = Field(default_factory=list)
    source_run_snapshot: dict[str, Any] = Field(default_factory=dict)
    template_snapshot: dict[str, Any] = Field(default_factory=dict)
    profile_snapshot: dict[str, Any] = Field(default_factory=dict)
    target_snapshot: dict[str, Any] = Field(default_factory=dict)


class ExperimentDispatchExternalReceipt(BaseModel):
    """SpecLabOS 接收回执。"""

    dispatch_id: str
    status: str
    received_at: str


class ExperimentDispatchManifest(UtcDatetimeJsonModel):
    """可审计的实验方案转发清单。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment_dispatch.v1"] = "experiment_dispatch.v1"
    dispatch_id: str
    status: DispatchStatus
    source: ExperimentDispatchSource
    template: ExperimentDispatchTemplateRef | None = None
    profile: ExperimentDispatchProfileRef | None = None
    target: ExperimentDispatchTargetRef | None = None
    experiment_name: str
    experiment_notes: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution_inputs: dict[str, Any] = Field(default_factory=dict)
    selection: ExperimentDispatchSelection | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    mapping_trace: list[dict[str, Any]] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    preview_digest: str | None = None
    external_receipt: ExperimentDispatchExternalReceipt | None = None
    dispatch_error: str | None = None
    provenance: ExperimentDispatchProvenance
    created_by: str
    created_at: datetime


class ExperimentDispatchListItem(UtcDatetimeJsonModel):
    dispatch_id: str
    status: DispatchStatus
    run_id: str
    algorithm_id: str
    template_id: str = ""
    template_version: str = ""
    variant_id: str = ""
    profile_id: str | None = None
    profile_version: str | None = None
    target_id: str | None = None
    experiment_name: str
    parameter_count: int
    external_receipt: ExperimentDispatchExternalReceipt | None = None
    dispatch_error: str | None = None
    created_by: str
    created_at: datetime


class ExperimentDispatchListData(BaseModel):
    items: list[ExperimentDispatchListItem]
    page: int
    page_size: int
    total: int
