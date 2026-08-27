"""通用实验下发配置、目标契约与规则执行结果。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import UtcDatetimeJsonModel
from app.schemas.execution_security import ExecutionAccessRecord


JsonValueType = Literal["string", "number", "integer", "boolean", "object", "array", "any"]
ProfileStatus = Literal["draft", "published", "archived"]
ProfileVisibility = Literal["private", "public"]


def _json_pointer(value: str, *, field_name: str = "path") -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("/"):
        raise ValueError(f"{field_name} 必须使用 JSON Pointer")
    return normalized


class DispatchSourceField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None = Field(default=None, max_length=160)
    value_type: JsonValueType = "any"
    required: bool = True
    unit: str | None = Field(default=None, max_length=40)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _json_pointer(value)


class DispatchSourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    example_algorithm_id: str | None = Field(default=None, max_length=80)
    allowed_trigger_sources: list[str] = Field(default_factory=list)
    required_fields: list[DispatchSourceField] = Field(default_factory=list)


class BoundaryLimit(BaseModel):
    """单个数值字段的边界限制。"""

    model_config = ConfigDict(extra="forbid")

    min: float | None = Field(default=None)
    max: float | None = Field(default=None)
    min_inclusive: bool = True
    max_inclusive: bool = True
    message: str | None = Field(default=None, max_length=500)


class FieldSecurityPolicy(BaseModel):
    """单个 target 字段的配置级安全策略。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    write_allowed: bool = True
    boundary: BoundaryLimit | None = None
    allowed_values: list[Any] | None = None
    violation_policy: Literal["error", "warn"] = "error"
    audit_level: Literal["default", "verbose"] = "default"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _json_pointer(value)

    @model_validator(mode="after")
    def validate_boundary(self):
        """校验数值边界的单调性。"""
        if self.boundary and self.boundary.min is not None and self.boundary.max is not None:
            if self.boundary.min > self.boundary.max:
                raise ValueError("字段边界 minimum 不能大于 maximum")
        return self


class TargetSecurityPolicy(BaseModel):
    """一个实验下发 target 的整体安全策略。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment_dispatch_target_security.v1"] = (
        "experiment_dispatch_target_security.v1"
    )
    target_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    field_policies: list[FieldSecurityPolicy] = Field(default_factory=list, max_length=500)
    default_write_allowed: bool = True

    @model_validator(mode="after")
    def validate_unique_paths(self):
        """确保每个字段路径只有一条安全策略。"""
        paths = [item.path for item in self.field_policies]
        if len(paths) != len(set(paths)):
            raise ValueError("target 安全策略存在重复字段路径")
        return self


class DispatchTargetField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None = Field(default=None, max_length=160)
    value_type: JsonValueType = "any"
    required: bool = False
    unit: str | None = Field(default=None, max_length=40)
    default_value: Any = None
    allow_override: bool = False
    order: int = Field(default=0, ge=0)
    security: FieldSecurityPolicy | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _json_pointer(value)

    @model_validator(mode="after")
    def validate_field_security(self):
        """确保字段内联安全策略只作用于当前字段。"""
        if self.security and self.security.path != self.path:
            raise ValueError("字段安全策略 path 必须与 target 字段 path 一致")
        return self


class DispatchTargetDefinition(UtcDatetimeJsonModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment_dispatch_target.v1"] = "experiment_dispatch_target.v1"
    target_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    service_key: str | None = Field(default=None, max_length=100)
    method: str = Field(default="POST", max_length=12)
    path: str | None = Field(default=None, max_length=500)
    fields: list[DispatchTargetField] = Field(default_factory=list)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    security_policy: TargetSecurityPolicy | None = None
    system_managed: bool = True
    created_at: datetime | None = None

    @model_validator(mode="after")
    def validate_target_identity(self):
        """确保安全策略归属当前 target 与版本。"""
        if self.security_policy and (
            self.security_policy.target_id != self.target_id
            or self.security_policy.version != self.version
        ):
            raise ValueError("target 安全策略的 target_id/version 与契约不一致")
        return self


class DispatchValueSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["path", "constant", "coalesce", "manual", "target"]
    path: str | None = None
    paths: list[str] = Field(default_factory=list, max_length=20)
    value: Any = None
    key: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_source(self):
        if self.kind in {"path", "target"}:
            if not self.path:
                raise ValueError(f"{self.kind} 数据源缺少 path")
            self.path = _json_pointer(self.path)
        if self.kind == "coalesce":
            if not self.paths:
                raise ValueError("coalesce 数据源至少需要一个路径")
            self.paths = [_json_pointer(item) for item in self.paths]
        if self.kind == "manual" and not self.key:
            raise ValueError("manual 数据源缺少 key")
        return self


class DispatchTransform(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["cast", "scale", "lookup", "concat", "array_item", "default"]
    value_type: JsonValueType | None = None
    scale: float = 1
    offset: float = 0
    lookup: dict[str, Any] = Field(default_factory=dict)
    default_value: Any = None
    prefix: str = ""
    suffix: str = ""
    index: int = 0

    @model_validator(mode="after")
    def validate_operation(self):
        if self.operation == "cast" and not self.value_type:
            raise ValueError("cast 转换必须指定 value_type")
        if self.operation == "lookup" and not self.lookup:
            raise ValueError("lookup 转换不能为空")
        return self


class DispatchMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: str
    label: str | None = Field(default=None, max_length=160)
    source: DispatchValueSource
    transforms: list[DispatchTransform] = Field(default_factory=list, max_length=20)
    default_value: Any = None
    required: bool = False
    allow_override: bool = False
    error_policy: Literal["block", "warn", "omit"] = "block"

    @field_validator("target_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _json_pointer(value, field_name="target_path")


class DispatchCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    operator: Literal["exists", "equals", "notEquals", "in", "between", "gt", "gte", "lt", "lte"]
    value: Any = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _json_pointer(value)

    @model_validator(mode="after")
    def validate_value(self):
        if self.operator == "between" and (not isinstance(self.value, list) or len(self.value) != 2):
            raise ValueError("between 条件必须提供两个边界值")
        if self.operator == "in" and not isinstance(self.value, list):
            raise ValueError("in 条件必须提供数组")
        return self


class DispatchConditionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "any"] = "all"
    items: list[DispatchCondition] = Field(min_length=1, max_length=50)


class DispatchBranchAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["set", "warn", "block"]
    target_path: str | None = None
    source: DispatchValueSource | None = None
    transforms: list[DispatchTransform] = Field(default_factory=list, max_length=20)
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_action(self):
        if self.kind == "set":
            if not self.target_path or not self.source:
                raise ValueError("set 动作必须提供 target_path 和 source")
            self.target_path = _json_pointer(self.target_path, field_name="target_path")
        elif not self.message:
            raise ValueError(f"{self.kind} 动作必须提供 message")
        return self


class DispatchBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=100, ge=0)
    conditions: DispatchConditionGroup
    actions: list[DispatchBranchAction] = Field(min_length=1, max_length=50)
    stop_on_match: bool = False


class ExperimentDispatchProfile(UtcDatetimeJsonModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment_dispatch_profile.v1"] = "experiment_dispatch_profile.v1"
    profile_id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=10000)
    status: ProfileStatus = "draft"
    visibility: ProfileVisibility = "private"
    owner_id: str = Field(min_length=1, max_length=100)
    source_contract: DispatchSourceContract = Field(default_factory=DispatchSourceContract)
    target_id: str = Field(min_length=1, max_length=100)
    target_version: str = Field(min_length=1, max_length=40)
    target_fields: list[DispatchTargetField] = Field(default_factory=list, max_length=500)
    mappings: list[DispatchMapping] = Field(default_factory=list, max_length=500)
    branches: list[DispatchBranch] = Field(default_factory=list, max_length=500)
    display_fields: list[str] = Field(default_factory=list)
    source_info: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(min_length=1, max_length=100)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    published_at: datetime | None = None

    @model_validator(mode="after")
    def validate_unique_rules(self):
        mapping_paths = [item.target_path for item in self.mappings]
        if len(mapping_paths) != len(set(mapping_paths)):
            raise ValueError("同一目标字段不能配置多条基础映射")
        rule_ids = [item.rule_id for item in self.branches]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("条件分支 rule_id 不能重复")
        return self


class DispatchMappingTrace(BaseModel):
    target_path: str
    source: str | None = None
    value: Any = None
    transforms: list[str] = Field(default_factory=list)
    overridden: bool = False
    rule_id: str | None = None


class DispatchSecurityEvent(BaseModel):
    """实验下发安全策略命中事件。"""

    event_type: Literal["write_denied", "boundary_exceeded", "value_not_allowed"]
    path: str
    severity: Literal["error", "warning"]
    message: str
    policy_version: str
    audit_level: Literal["default", "verbose"] = "default"


class DispatchEvaluationResult(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    trace: list[DispatchMappingTrace] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    security_events: list[DispatchSecurityEvent] = Field(default_factory=list)
    is_valid: bool = False


class ExperimentDispatchProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = Field(default=None, max_length=100)
    version: str = Field(default="0.1.0", min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=10000)
    visibility: ProfileVisibility = "private"
    source_contract: DispatchSourceContract = Field(default_factory=DispatchSourceContract)
    target_id: str = Field(min_length=1, max_length=100)
    target_version: str = Field(min_length=1, max_length=40)
    target_fields: list[DispatchTargetField] = Field(default_factory=list, max_length=500)
    mappings: list[DispatchMapping] = Field(default_factory=list, max_length=500)
    branches: list[DispatchBranch] = Field(default_factory=list, max_length=500)
    display_fields: list[str] = Field(default_factory=list)
    source_info: dict[str, Any] = Field(default_factory=dict)


class ExperimentDispatchProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=10000)
    source_contract: DispatchSourceContract = Field(default_factory=DispatchSourceContract)
    target_id: str = Field(min_length=1, max_length=100)
    target_version: str = Field(min_length=1, max_length=40)
    target_fields: list[DispatchTargetField] = Field(default_factory=list, max_length=500)
    mappings: list[DispatchMapping] = Field(default_factory=list, max_length=500)
    branches: list[DispatchBranch] = Field(default_factory=list, max_length=500)
    display_fields: list[str] = Field(default_factory=list)
    source_info: dict[str, Any] = Field(default_factory=dict)


class ExperimentDispatchProfileCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=40)


class ExperimentDispatchProfileVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: ProfileVisibility


class ExperimentDispatchProfileListData(BaseModel):
    items: list[ExperimentDispatchProfile]
    page: int
    page_size: int
    total: int


class DispatchTargetListData(BaseModel):
    items: list[DispatchTargetDefinition]
    total: int


class ExperimentDispatchProfileEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=120)
    profile_id: str = Field(min_length=1, max_length=100)
    profile_version: str | None = Field(default=None, max_length=40)
    manual_values: dict[str, Any] = Field(default_factory=dict)


class ExperimentDispatchProfileSaveRequest(ExperimentDispatchProfileEvaluationRequest):
    preview_digest: str = Field(min_length=64, max_length=64)
    experiment_name: str | None = Field(default=None, max_length=200)
    experiment_notes: str | None = Field(default=None, max_length=10000)


class ExperimentDispatchProfileEvaluation(BaseModel):
    run_id: str
    algorithm_id: str
    profile_id: str
    profile_version: str
    target_id: str
    target_version: str
    result: DispatchEvaluationResult
    execution_access: ExecutionAccessRecord = Field(default_factory=ExecutionAccessRecord)
    preview_digest: str


class ExperimentDispatchCandidate(UtcDatetimeJsonModel):
    run_id: str
    algorithm_id: str
    algorithm_name: str
    algorithm_type: str | None = None
    algorithm_family: str | None = None
    trigger_source: str | None = None
    source_kind: str | None = None
    algorithm_version_id: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class ExperimentDispatchCandidateListData(BaseModel):
    items: list[ExperimentDispatchCandidate]
    page: int
    page_size: int
    total: int
