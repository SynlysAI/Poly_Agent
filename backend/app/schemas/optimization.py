"""优化 campaign 模块数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CampaignStatus = Literal["draft", "running", "paused", "completed", "failed", "archived"]
PlannerType = Literal["fallback", "tanimoto"]
ObjectiveDirection = Literal["max", "min"]
SuggestionStatus = Literal["suggested", "submitted", "evaluated", "rejected", "failed"]
ObservationSourceType = Literal["computation", "experiment", "manual", "imported"]
PlannerSuggestionConfidence = Literal["high", "low"]


class OptimizationObjective(BaseModel):
    """优化目标定义。"""

    name: str = Field(min_length=1, max_length=80)
    direction: ObjectiveDirection = "max"
    unit: str | None = Field(default=None, max_length=40)
    required: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化目标名。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("目标名称不能为空")
        return normalized


class CampaignCreateRequest(BaseModel):
    """创建 campaign 请求。"""

    name: str = Field(min_length=1, max_length=120)
    objectives: list[OptimizationObjective] = Field(min_length=1)
    planner_type: PlannerType = "fallback"
    planner_config: dict = Field(default_factory=lambda: {"batch_size": 1})

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化 campaign 名称。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Campaign 名称不能为空")
        return normalized


class CampaignStatusChangeRequest(BaseModel):
    """Campaign 状态变更请求。"""

    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        """规范化状态变更原因。"""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OptimizationCampaign(BaseModel):
    """优化 campaign 记录。"""

    campaign_id: str
    name: str
    status: CampaignStatus
    planner_type: PlannerType
    search_space: dict = Field(default_factory=dict)
    objectives: list[OptimizationObjective]
    planner_config: dict = Field(default_factory=dict)
    source: str | None = Field(default=None, max_length=80)
    linked_problem_spec_id: str | None = Field(default=None, max_length=80)
    created_by: str
    created_at: datetime
    updated_at: datetime

    @field_validator("status", mode="before")
    @classmethod
    def normalize_legacy_status(cls, value: str) -> str:
        """兼容早期 active 状态。"""
        if value == "active":
            return "running"
        return value


class CampaignListData(BaseModel):
    """campaign 分页响应。"""

    items: list[OptimizationCampaign]
    page: int
    page_size: int
    total: int


class CandidateImportItem(BaseModel):
    """候选分子导入项。"""

    candidate_key: str = Field(min_length=1, max_length=80)
    smiles: str = Field(min_length=1, max_length=512)
    parameters: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    @field_validator("candidate_key", "smiles")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """规范化必填文本。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("候选字段不能为空")
        return normalized


class CandidateImportRequest(BaseModel):
    """候选分子批量导入请求。"""

    candidates: list[CandidateImportItem] = Field(min_length=1, max_length=200)


class CandidateImportCsvRequest(BaseModel):
    """候选分子 CSV 导入请求。"""

    csv_text: str = Field(min_length=1)


class CandidateImportFailedRow(BaseModel):
    """候选导入失败行报告。"""

    row_number: int
    candidate_key: str | None = None
    smiles: str | None = None
    reason: str


class CandidateImportDuplicateRow(BaseModel):
    """候选导入重复行报告。"""

    row_number: int
    candidate_key: str
    reason: str


class OptimizationCandidate(BaseModel):
    """优化候选记录。"""

    candidate_id: str
    campaign_id: str
    candidate_key: str
    smiles: str
    parameters: dict = Field(default_factory=dict)
    descriptors: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime


class PlannerCandidate(BaseModel):
    """planner 输入候选契约。"""

    candidate_id: str
    candidate_key: str
    smiles: str
    parameters: dict = Field(default_factory=dict)
    descriptors: dict = Field(default_factory=dict)


class PlannerObservation(BaseModel):
    """planner 输入 observation 契约。"""

    observation_id: str
    candidate_id: str
    suggestion_id: str | None = None
    values: dict[str, float]
    uncertainty: dict = Field(default_factory=dict)
    source_type: ObservationSourceType
    source_run_id: str | None = None


class PlannerConstraints(BaseModel):
    """planner 约束 schema。"""

    model_config = ConfigDict(extra="forbid")

    allowed_candidate_ids: list[str] | None = None
    excluded_candidate_ids: list[str] = Field(default_factory=list)
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    require_descriptor: bool = False
    minimum_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    max_low_confidence_suggestions: int = Field(default=1, ge=0, le=20)

    @field_validator("allowed_candidate_ids", "excluded_candidate_ids")
    @classmethod
    def normalize_candidate_ids(cls, value: list[str] | None) -> list[str] | None:
        """去重并规范化 candidate id 列表。"""
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            candidate_id = str(item).strip()
            if not candidate_id or candidate_id in seen:
                continue
            seen.add(candidate_id)
            normalized.append(candidate_id)
        return normalized

    @field_validator("excluded_counts")
    @classmethod
    def validate_excluded_counts(cls, value: dict[str, int]) -> dict[str, int]:
        """校验排除计数。"""
        normalized: dict[str, int] = {}
        for key, count in value.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                raise ValueError("excluded_counts key 不能为空")
            if int(count) < 0:
                raise ValueError("excluded_counts 不能为负数")
            normalized[normalized_key] = int(count)
        return normalized


class PlannerRequest(BaseModel):
    """planner 标准输入。"""

    schema_version: str = "planner_request.v1"
    campaign_id: str
    planner_type: PlannerType
    batch_size: int = Field(ge=1, le=20)
    candidates: list[PlannerCandidate]
    observations: list[PlannerObservation]
    objectives: list[OptimizationObjective]
    constraints: PlannerConstraints = Field(default_factory=PlannerConstraints)


class PlannerSuggestionItem(BaseModel):
    """planner 标准输出中的单条推荐。"""

    candidate_id: str
    candidate_key: str
    score: float
    reason: str
    confidence: PlannerSuggestionConfidence = "high"
    metadata: dict = Field(default_factory=dict)


class PlannerSkippedItem(BaseModel):
    """planner 跳过候选说明。"""

    candidate_id: str | None = None
    candidate_key: str | None = None
    reason: str
    code: str
    metadata: dict = Field(default_factory=dict)


class PlannerResponse(BaseModel):
    """planner 标准输出。"""

    schema_version: str = "planner_response.v1"
    planner_type: PlannerType
    suggestions: list[PlannerSuggestionItem]
    skipped: list[PlannerSkippedItem] = Field(default_factory=list)
    iteration_metadata: dict = Field(default_factory=dict)


class CandidateImportData(BaseModel):
    """候选导入响应。"""

    imported_count: int
    updated_count: int = 0
    failed_rows: list[CandidateImportFailedRow] = Field(default_factory=list)
    duplicate_rows: list[CandidateImportDuplicateRow] = Field(default_factory=list)
    items: list[OptimizationCandidate]


class OptimizationSuggestion(BaseModel):
    """推荐记录。"""

    suggestion_id: str
    campaign_id: str
    candidate_id: str
    candidate_key: str
    smiles: str
    iteration_index: int
    status: SuggestionStatus
    planner_type: PlannerType
    planner_payload: dict = Field(default_factory=dict)
    submitted_run_id: str | None = None
    submitted_experiment_run_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SuggestionCreateRequest(BaseModel):
    """生成推荐请求。"""

    batch_size: int = Field(default=1, ge=1, le=20)


class SuggestionCreateData(BaseModel):
    """生成推荐响应。"""

    items: list[OptimizationSuggestion]


class SuggestionRejectRequest(BaseModel):
    """拒绝推荐请求。"""

    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """规范化原因。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason 不能为空")
        return normalized


class SuggestionFailureRequest(BaseModel):
    """标记推荐失败请求。"""

    reason: str = Field(min_length=1, max_length=1000)
    run_id: str | None = Field(default=None, max_length=80)
    error_code: str | None = Field(default=None, max_length=120)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """规范化原因。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason 不能为空")
        return normalized


class ObservationCreateRequest(BaseModel):
    """写入 observation 请求。"""

    candidate_id: str
    suggestion_id: str | None = None
    source_type: ObservationSourceType = "manual"
    source_run_id: str | None = None
    values: dict[str, float]
    uncertainty: dict = Field(default_factory=dict)
    raw_result_ref: str | None = None


class OptimizationObservation(BaseModel):
    """优化 observation 记录。"""

    observation_id: str
    campaign_id: str
    candidate_id: str
    suggestion_id: str | None = None
    source_type: ObservationSourceType
    source_run_id: str | None = None
    values: dict[str, float]
    uncertainty: dict = Field(default_factory=dict)
    raw_result_ref: str | None = None
    confirmed_by: str
    created_at: datetime


class SubmitSuggestionComputationData(BaseModel):
    """推荐转计算响应。"""

    suggestion_id: str
    run_id: str
    suggestion_status: SuggestionStatus


class CampaignDetailData(BaseModel):
    """campaign 详情响应。"""

    campaign: OptimizationCampaign
    candidates: list[OptimizationCandidate]
    suggestions: list[OptimizationSuggestion]
    observations: list[OptimizationObservation]


class CampaignHistoryEvent(BaseModel):
    """优化闭环历史事件。"""

    event_type: str
    occurred_at: datetime
    campaign_id: str
    candidate_id: str | None = None
    suggestion_id: str | None = None
    source_run_id: str | None = None
    summary: dict = Field(default_factory=dict)


class CampaignHistoryData(BaseModel):
    """优化闭环历史响应。"""

    items: list[CampaignHistoryEvent]


class CreateObservationFromComputationData(BaseModel):
    """从计算结果生成 observation 响应。"""

    observation: OptimizationObservation
