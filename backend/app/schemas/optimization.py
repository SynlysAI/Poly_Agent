"""优化 campaign 模块数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


CampaignStatus = Literal["draft", "running", "paused", "completed", "failed", "archived"]
PlannerType = Literal["fallback"]
ObjectiveDirection = Literal["max", "min"]
SuggestionStatus = Literal["suggested", "submitted", "evaluated", "rejected", "failed"]
ObservationSourceType = Literal["computation", "experiment", "manual", "imported"]


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


class OptimizationCampaign(BaseModel):
    """优化 campaign 记录。"""

    campaign_id: str
    name: str
    status: CampaignStatus
    planner_type: PlannerType
    search_space: dict = Field(default_factory=dict)
    objectives: list[OptimizationObjective]
    planner_config: dict = Field(default_factory=dict)
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


class CandidateImportData(BaseModel):
    """候选导入响应。"""

    imported_count: int
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
