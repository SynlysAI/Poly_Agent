"""ALchemist 实验设计与优化 — Pydantic 数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ============================================================
# Session 管理
# ============================================================

class CreateSessionRequest(BaseModel):
    """创建 Session 请求。"""
    name: str | None = Field(None, description="Session 名称")
    description: str | None = Field(None, description="Session 描述")
    tags: list[str] | None = Field(None, description="标签列表")


class SessionListItem(BaseModel):
    """Session 列表项。"""
    session_id: str
    name: str | None = None
    description: str | None = None
    variable_count: int = 0
    experiment_count: int = 0
    model_trained: bool = False
    model_backend: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class SessionDetail(BaseModel):
    """Session 详情。"""
    session_id: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = []
    created_by: str
    status: str = "active"
    variables: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    staged_experiments: list[dict[str, Any]] = []
    audit_log: list[dict[str, Any]] = []
    model_trained: bool = False
    model_backend: str | None = None
    model_kernel: str | None = None
    variable_count: int = 0
    experiment_count: int = 0
    created_at: datetime
    updated_at: datetime


class SessionCreateResponse(BaseModel):
    """创建 Session 响应。"""
    session_id: str
    created_at: datetime


class SessionListData(BaseModel):
    """Session 分页列表。"""
    items: list[SessionListItem]
    page: int
    page_size: int
    total: int


# ============================================================
# 变量管理
# ============================================================

class AddRealVariableRequest(BaseModel):
    """添加实值变量。"""
    name: str
    type: Literal["real"] = "real"
    min: float
    max: float
    unit: str | None = None
    description: str | None = None


class AddIntegerVariableRequest(BaseModel):
    """添加整数变量。"""
    name: str
    type: Literal["integer"] = "integer"
    min: int
    max: int
    unit: str | None = None
    description: str | None = None


class AddCategoricalVariableRequest(BaseModel):
    """添加分类变量。"""
    name: str
    type: Literal["categorical"] = "categorical"
    categories: list[str]
    unit: str | None = None
    description: str | None = None


class AddDiscreteVariableRequest(BaseModel):
    """添加离散数值变量。"""
    name: str
    type: Literal["discrete"] = "discrete"
    allowed_values: list[float] = Field(min_length=2)
    unit: str | None = None
    description: str | None = None


class VariableResponse(BaseModel):
    """变量操作响应。"""
    message: str = "操作成功"
    variable: dict[str, Any]


class VariablesListResponse(BaseModel):
    """变量列表响应。"""
    variables: list[dict[str, Any]]
    n_variables: int


# ============================================================
# 实验数据
# ============================================================

class AddExperimentRequest(BaseModel):
    """添加单个实验。"""
    inputs: dict[str, float | int | str]
    output: float | None = None
    noise: float | None = None
    iteration: int | None = None
    reason: str | None = None


class AddExperimentsBatchRequest(BaseModel):
    """批量添加实验。"""
    experiments: list[AddExperimentRequest]


class ExperimentResponse(BaseModel):
    """实验操作响应。"""
    message: str = "操作成功"
    n_experiments: int
    model_trained: bool = False
    training_metrics: dict[str, Any] | None = None


class ExperimentsListResponse(BaseModel):
    """实验列表响应。"""
    experiments: list[dict[str, Any]]
    n_experiments: int


class ExperimentsSummaryResponse(BaseModel):
    """实验统计摘要。"""
    n_experiments: int
    has_data: bool
    has_noise: bool | None = None
    target_stats: dict[str, float] | None = None
    feature_names: list[str] | None = None


# ============================================================
# 实验设计 (DoE)
# ============================================================

class InitialDesignRequest(BaseModel):
    """初始实验设计请求。"""
    method: Literal[
        "random", "lhs", "sobol", "halton", "hammersly",
        "full_factorial", "fractional_factorial", "ccd", "box_behnken",
        "plackett_burman", "gsd"
    ] = "lhs"
    n_points: int | None = Field(None, ge=1, le=1000)
    random_seed: int | None = None
    lhs_criterion: str = "maximin"
    n_levels: int = Field(default=2, ge=2, le=5)
    n_center: int = Field(default=1, ge=0, le=10)
    generators: str | None = None
    ccd_alpha: Literal["orthogonal", "rotatable"] = "orthogonal"
    ccd_face: Literal["circumscribed", "inscribed", "faced"] = "circumscribed"
    gsd_reduction: int = Field(default=2, ge=2, le=10)


class InitialDesignResponse(BaseModel):
    """初始设计响应。"""
    points: list[dict[str, Any]]
    method: str
    n_points: int
    design_info: dict[str, Any] | None = None


# ============================================================
# 最优设计 (OED)
# ============================================================

class OptimalDesignInfoRequest(BaseModel):
    """最优设计预览请求。"""
    model_type: Literal["linear", "interaction", "quadratic"] | None = None
    effects: list[str] | None = None


class OptimalDesignInfoResponse(BaseModel):
    """最优设计预览响应。"""
    model_terms: list[str]
    p_columns: int
    n_points_minimum: int
    n_points_recommended: int


class OptimalDesignRequest(BaseModel):
    """最优设计生成请求。"""
    model_type: Literal["linear", "interaction", "quadratic"] | None = None
    effects: list[str] | None = None
    n_points: int | None = Field(None, ge=1, le=10000)
    p_multiplier: float | None = Field(None, ge=1.0, le=10.0)
    criterion: Literal["D", "A", "I"] = "D"
    algorithm: Literal["sequential", "simple_exchange", "fedorov", "modified_fedorov", "detmax"] = "fedorov"
    n_levels: int = Field(default=5, ge=2, le=20)
    max_iter: int = Field(default=200, ge=10, le=10000)
    random_seed: int | None = None


class OptimalDesignResponse(BaseModel):
    """最优设计响应。"""
    points: list[dict[str, Any]]
    n_points: int
    design_info: dict[str, Any]


# ============================================================
# 暂存实验
# ============================================================

class StageExperimentsBatchRequest(BaseModel):
    """批量暂存实验。"""
    experiments: list[dict[str, float | int | str]]
    reason: str | None = None


class StagedExperimentsListResponse(BaseModel):
    """暂存实验列表。"""
    experiments: list[dict[str, Any]]
    n_staged: int
    reason: str | None = None


# ============================================================
# GP 建模
# ============================================================

class TrainModelRequest(BaseModel):
    """训练模型请求。"""
    backend: Literal["sklearn", "botorch"] = "sklearn"
    kernel: str = "Matern"
    kernel_params: dict[str, Any] | None = None
    input_transform: str | None = None
    output_transform: str | None = None
    calibration_enabled: bool = False


class TrainModelResponse(BaseModel):
    """训练模型响应。"""
    success: bool
    backend: str
    kernel: str
    hyperparameters: dict[str, Any]
    metrics: dict[str, float]
    message: str = "模型训练成功"


class ModelInfoResponse(BaseModel):
    """模型信息响应。"""
    backend: str | None = None
    kernel: str | None = None
    hyperparameters: dict[str, Any] | None = None
    metrics: dict[str, float] | None = None
    is_trained: bool


# ============================================================
# 采集优化
# ============================================================

class AcquisitionRequest(BaseModel):
    """建议下一个实验点请求。"""
    strategy: str = "EI"
    goal: Literal["maximize", "minimize"] = "maximize"
    n_suggestions: int = Field(default=1, ge=1, le=10)
    xi: float | None = 0.01
    kappa: float | None = 2.0


class AcquisitionResponse(BaseModel):
    """采集建议响应。"""
    suggestions: list[dict[str, Any]]
    n_suggestions: int


class FindOptimumRequest(BaseModel):
    """寻找最优点请求。"""
    goal: Literal["maximize", "minimize"] = "maximize"


class FindOptimumResponse(BaseModel):
    """寻找最优点响应。"""
    optimum: dict[str, Any]
    predicted_value: float
    predicted_std: float | None = None
    goal: str


# ============================================================
# 可视化
# ============================================================

class ContourDataRequest(BaseModel):
    """等值线图请求。"""
    x_var: str
    y_var: str
    fixed_values: dict[str, Any] = Field(default_factory=dict)
    grid_resolution: int = Field(default=50, ge=10, le=200)
    include_experiments: bool = True
    include_suggestions: bool = False


# ============================================================
# LLM 辅助
# ============================================================

class LLMProviderConfig(BaseModel):
    """LLM 提供商配置。"""
    provider: Literal["openai", "ollama"] = "openai"
    model: str = ""
    api_key: str | None = None
    base_url: str | None = None


class EdisonConfig(BaseModel):
    """Edison 文献搜索配置。"""
    api_key: str | None = None
    job_type: Literal["literature", "literature_high", "precedent"] = "literature"
    timeout_secs: int | None = Field(None, ge=60, le=3600)
    force_refresh: bool = False


class SuggestEffectsRequest(BaseModel):
    """LLM 效应建议请求。"""
    structuring_provider: LLMProviderConfig
    edison_config: EdisonConfig | None = None
    system_context: str = ""


# ============================================================
# 审计日志
# ============================================================

class UpdateMetadataRequest(BaseModel):
    """更新 Session 元数据。"""
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class SessionMetadataResponse(BaseModel):
    """Session 元数据响应。"""
    session_id: str
    name: str
    created_at: str
    last_modified: str
    description: str
    tags: list[str]
