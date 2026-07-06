"""ResearchEngine 高分子材料 AI 研发平台数据契约。

本模块定义 ResearchEngine P0 所需的核心领域模型、枚举和基础校验。
遵循现有 computation.py/optimization.py 的 Pydantic 模式：
ConfigDict(extra="forbid")、field_validator 装饰器、Literal 类型、中文错误消息。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# 枚举与 Literal 类型
# =============================================================================

ExecutionMode = Literal["manual", "autoresearch", "hybrid"]
"""执行模式：manual=纯人工触发，autoresearch=纯自动编排，hybrid=双通道并行。"""

TriggerSource = Literal["human", "autoresearch", "system"]
"""触发来源：human=人工通道，autoresearch=AutoResearch 编排，system=系统内部触发。"""

ResearchRunStatus = Literal[
    "draft", "running", "paused", "blocked_approval", "completed", "failed", "archived"
]
"""ResearchRun 主运行状态。"""

ResearchStageStatus = Literal[
    "pending", "running", "blocked_approval", "completed", "failed"
]
"""ResearchStageRun 阶段运行状态。"""

ResearchStageKey = Literal[
    "PROBLEM_SPEC",
    "KNOWLEDGE_RETRIEVAL",
    "STRUCTURE_FEATURE",
    "COMPUTE_PREDICT",
    "RECOMMENDATION_ASK",
    "HUMAN_REVIEW",
    "EXPERIMENT_EXECUTION",
    "RESULT_TELL",
    "MODEL_UPDATE",
    "ARCHIVE_LEARNING",
]
"""材料版 AutoResearch 阶段标识。"""

AlgorithmType = Literal["retriever", "predictor", "simulator", "optimizer"]
"""算法能力类型。"""

AlgorithmStatus = Literal[
    "active", "pending_encapsulation", "in_development", "frozen", "decommissioned"
]
"""算法能力登记状态。"""

MaterialScope = Literal[
    "fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"
]
"""适用材料体系范围。"""

GateDecision = Literal["approved", "rejected", "modified"]
"""人工审批决策类型。"""

AlgorithmRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
"""AlgorithmRun 运行状态。"""

ProblemType = Literal[
    "formulation_process_optimization",
    "structure_property_prediction",
    "material_discovery",
    "reaction_condition_optimization",
]
"""材料研发问题类型。"""

VariableType = Literal["continuous", "categorical", "discrete", "composition"]
"""问题变量类型。"""

VariableRole = Literal["structure", "process", "formulation", "measurement"]
"""变量在研发问题中的角色。"""

ConstraintType = Literal["hard", "soft"]
"""约束类型。"""

ObjectiveDirection = Literal["maximize", "minimize"]
"""优化目标方向。"""


# =============================================================================
# 状态转移规则常量
# =============================================================================

# ResearchRun 合法状态转移表
RESEARCH_RUN_TRANSITIONS: dict[ResearchRunStatus, set[ResearchRunStatus]] = {
    "draft": {"running"},
    "running": {"blocked_approval", "paused", "completed", "failed"},
    "blocked_approval": {"running", "failed", "paused"},
    "paused": {"running"},
    "completed": {"archived"},
    "failed": set(),
    "archived": set(),
}

# ResearchStageRun 合法状态转移表
RESEARCH_STAGE_TRANSITIONS: dict[ResearchStageStatus, set[ResearchStageStatus]] = {
    "pending": {"running"},
    "running": {"completed", "failed", "blocked_approval"},
    "blocked_approval": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


# =============================================================================
# ProblemSpec 相关模型
# =============================================================================


class ProblemSpecVariable(BaseModel):
    """问题规格中的变量定义。

    表达材料研发任务中的自变量，包括结构变量、工艺变量、配方变量和测量变量。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    type: VariableType = "continuous"
    role: VariableRole = "structure"
    unit: str | None = Field(default=None, max_length=40)
    bounds: list[float] | None = Field(default=None, min_length=2, max_length=2)
    categories: list[str] | None = Field(default=None)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化变量名。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("变量名称不能为空")
        return normalized

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: list[float] | None) -> list[float] | None:
        """校验变量边界。"""
        if value is None:
            return None
        if len(value) != 2:
            raise ValueError("变量边界必须包含两个元素 [min, max]")
        if value[0] >= value[1]:
            raise ValueError("变量边界最小值必须小于最大值")
        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: list[str] | None) -> list[str] | None:
        """校验分类变量候选项。"""
        if value is None:
            return None
        if len(value) < 2:
            raise ValueError("分类变量至少需要两个候选项")
        return value


class ProblemSpecObjective(BaseModel):
    """问题规格中的优化目标定义。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    direction: ObjectiveDirection = "maximize"
    unit: str | None = Field(default=None, max_length=40)
    weight: float = Field(default=1.0, ge=0.0, le=10.0)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化目标名。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("目标名称不能为空")
        return normalized


class ProblemSpecConstraint(BaseModel):
    """问题规格中的约束条件定义。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    type: ConstraintType = "hard"
    expression: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化约束名。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("约束名称不能为空")
        return normalized


class ProblemSpecMeasurement(BaseModel):
    """问题规格中的测量条件定义。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    condition: str | None = Field(default=None, max_length=200)
    method: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化测量项名。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("测量项名称不能为空")
        return normalized


class ProblemSpecCreate(BaseModel):
    """创建 ProblemSpec 请求。

    支持 execution_mode、变量/目标/约束定义，是材料研发任务的核心入口。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    material_family: MaterialScope = "fluoropolymer"
    problem_type: ProblemType = "formulation_process_optimization"
    execution_mode: ExecutionMode = "hybrid"
    variables: list[ProblemSpecVariable] = Field(default_factory=list)
    objectives: list[ProblemSpecObjective] = Field(default_factory=list, min_length=1)
    constraints: list[ProblemSpecConstraint] = Field(default_factory=list)
    measurements: list[ProblemSpecMeasurement] = Field(default_factory=list)
    campaign_id: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化 ProblemSpec 名称。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("ProblemSpec 名称不能为空")
        return normalized


class ProblemSpec(ProblemSpecCreate):
    """ProblemSpec 完整记录。

    在创建请求基础上增加系统字段：ID、版本、时间戳、创建者等。
    """

    problem_spec_id: str
    schema_version: str = "0.2"
    created_by: str
    owner_id: str | None = None
    project_id: str | None = None
    status: str = "draft"
    frozen_version: int = 0
    created_at: datetime
    updated_at: datetime


class ProblemSpecListData(BaseModel):
    """ProblemSpec 分页响应。"""

    items: list[ProblemSpec]
    page: int
    page_size: int
    total: int


# =============================================================================
# AlgorithmRegistry 相关模型
# =============================================================================


class AlgorithmIOSchema(BaseModel):
    """算法输入/输出 schema 描述。

    用于描述算法对输入输出的字段、类型、单位、约束要求。
    """

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, str] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    constraints: dict[str, dict] = Field(default_factory=dict)


class AlgorithmRegistryEntry(BaseModel):
    """算法能力登记条目。

    每个算法进入平台前至少登记以下字段，形成统一的算法能力清单。
    """

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    type: AlgorithmType = "predictor"
    material_scope: list[MaterialScope] = Field(default_factory=lambda: ["universal"])
    task_scope: list[ResearchStageKey] = Field(default_factory=list)
    input_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    output_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    call_method: str = Field(default="REST", max_length=40)
    trigger_modes: list[TriggerSource] = Field(default_factory=lambda: ["human"])
    runtime_dependency: str | None = Field(default=None, max_length=200)
    version: str = Field(default="1.0.0", max_length=40)
    validation_metric: dict = Field(default_factory=dict)
    owner: str | None = Field(default=None, max_length=80)
    status: AlgorithmStatus = "active"
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("algorithm_id")
    @classmethod
    def normalize_algorithm_id(cls, value: str) -> str:
        """规范化算法 ID。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("算法 ID 不能为空")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """规范化算法名称。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("算法名称不能为空")
        return normalized


class AlgorithmRegistryListData(BaseModel):
    """AlgorithmRegistry 分页响应。"""

    items: list[AlgorithmRegistryEntry]
    page: int
    page_size: int
    total: int


# =============================================================================
# AlgorithmRun 相关模型
# =============================================================================


class AlgorithmRunCreate(BaseModel):
    """创建算法运行请求。"""

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(min_length=1, max_length=80)
    trigger_source: TriggerSource = "human"
    trigger_context_id: str | None = Field(default=None, max_length=80)
    problem_spec_id: str | None = Field(default=None, max_length=80)
    campaign_id: str | None = Field(default=None, max_length=80)
    research_run_id: str | None = Field(default=None, max_length=80)
    stage_run_id: str | None = Field(default=None, max_length=80)
    input_snapshot: dict = Field(default_factory=dict)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("algorithm_id")
    @classmethod
    def normalize_algorithm_id(cls, value: str) -> str:
        """规范化算法 ID。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("算法 ID 不能为空")
        return normalized


class AlgorithmRun(BaseModel):
    """算法运行记录。

    统一表达人工通道和 AutoResearch 通道的算法调用产物。
    与 ComputationRun 是不同的抽象层级：
    - AlgorithmRun 是算法能力调用的通用记录
    - ComputationRun 是具体计算工作流的执行记录
    """

    run_id: str
    algorithm_id: str
    trigger_source: TriggerSource
    trigger_context_id: str | None = None
    problem_spec_id: str | None = None
    problem_spec_version: str | None = None
    campaign_id: str | None = None
    research_run_id: str | None = None
    stage_run_id: str | None = None
    linked_computation_run_id: str | None = None
    linked_suggestion_id: str | None = None
    linked_observation_id: str | None = None
    input_snapshot: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    artifact_refs: list[dict] = Field(default_factory=list)
    status: AlgorithmRunStatus = "queued"
    error: dict | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AlgorithmRunListData(BaseModel):
    """AlgorithmRun 分页响应。"""

    items: list[AlgorithmRun]
    page: int
    page_size: int
    total: int


# =============================================================================
# ResearchRun / ResearchStageRun / StageGate 相关模型
# =============================================================================


class StageGate(BaseModel):
    """阶段门禁定义。

    表达每个 ResearchStage 的输入输出契约、审批策略、重试策略和回滚目标。
    """

    model_config = ConfigDict(extra="forbid")

    stage_key: ResearchStageKey
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    definition_of_done: str = Field(default="", max_length=500)
    gate_policy: dict = Field(default_factory=dict)
    retry_policy: dict = Field(default_factory=dict)
    rollback_target: ResearchStageKey | None = None
    artifact_policy: dict = Field(default_factory=dict)


class StageGateDecision(BaseModel):
    """人工审批决策记录。"""

    model_config = ConfigDict(extra="forbid")

    stage_key: ResearchStageKey
    decision: GateDecision
    actor_user_id: str
    reason: str = Field(min_length=1, max_length=1000)
    modified_candidates: list[dict] = Field(default_factory=list)
    decided_at: datetime

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """规范化审批原因。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("审批原因不能为空")
        return normalized


class ResearchStageRun(BaseModel):
    """单个 AutoResearch 阶段运行记录。"""

    stage_run_id: str
    research_run_id: str
    stage_key: ResearchStageKey
    status: ResearchStageStatus = "pending"
    gate: StageGate | None = None
    input_snapshot: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    error: dict | None = None
    decisions: list[StageGateDecision] = Field(default_factory=list)
    linked_algorithm_runs: list[str] = Field(default_factory=list)
    linked_experiment_runs: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    checkpoint_data: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ResearchRunCreate(BaseModel):
    """创建 ResearchRun 请求。"""

    model_config = ConfigDict(extra="forbid")

    problem_spec_id: str = Field(min_length=1, max_length=80)
    campaign_id: str | None = Field(default=None, max_length=80)
    profile_id: str = Field(default="fluoropolymer", max_length=80)
    max_iterations: int = Field(default=5, ge=1, le=100)
    batch_size: int = Field(default=10, ge=1, le=100)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("problem_spec_id")
    @classmethod
    def normalize_problem_spec_id(cls, value: str) -> str:
        """规范化 ProblemSpec ID。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("ProblemSpec ID 不能为空")
        return normalized


class ResearchRun(BaseModel):
    """AutoResearch 主运行记录。

    表达一次完整的 AutoResearch 自动编排运行，
    包含阶段序列、当前阶段、关联算法运行和实验运行。
    """

    run_id: str
    project_id: str | None = None
    problem_spec_id: str
    campaign_id: str | None = None
    profile_id: str = "fluoropolymer"
    status: ResearchRunStatus = "draft"
    current_stage: ResearchStageKey | None = None
    stage_runs: list[ResearchStageRun] = Field(default_factory=list)
    linked_algorithm_runs: list[str] = Field(default_factory=list)
    linked_experiment_runs: list[str] = Field(default_factory=list)
    checkpoint: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)
    max_iterations: int = 5
    batch_size: int = 10
    created_by: str
    owner_id: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ResearchRunListData(BaseModel):
    """ResearchRun 分页响应。"""

    items: list[ResearchRun]
    page: int
    page_size: int
    total: int


# =============================================================================
# 状态变更请求模型
# =============================================================================


class ResearchRunStatusChangeRequest(BaseModel):
    """ResearchRun 状态变更请求。"""

    model_config = ConfigDict(extra="forbid")

    target_status: ResearchRunStatus
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """规范化状态变更原因。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("状态变更原因不能为空")
        return normalized


class StageApprovalRequest(BaseModel):
    """阶段审批请求。"""

    model_config = ConfigDict(extra="forbid")

    stage_key: ResearchStageKey
    decision: GateDecision
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """规范化审批原因。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("审批原因不能为空")
        return normalized


# =============================================================================
# Traceability 追溯模型
# =============================================================================


class AuditEventItem(BaseModel):
    """审计事件轻量条目。

    用于追溯查询中返回的关键审计事件，不暴露内部敏感路径。
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor_user_id: str
    actor_role: str | None = None
    reason: str | None = None
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    created_at: datetime


class EntityAuditListData(BaseModel):
    """按实体聚合的审计事件列表。"""

    items: list[AuditEventItem]
    page: int
    page_size: int
    total: int


class LinkedComputationRef(BaseModel):
    """追溯链中引用的计算任务摘要。"""

    run_id: str
    workflow_type: str | None = None
    engine: str | None = None
    status: str | None = None
    input_snapshot: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    artifact_refs: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None


class AlgorithmRunTraceability(BaseModel):
    """AlgorithmRun 完整追溯链。

    聚合算法运行的自有 artifact、关联计算任务产物和审计事件。
    """

    algorithm_run: AlgorithmRun
    linked_computation: LinkedComputationRef | None = None
    audit_events: list[AuditEventItem] = Field(default_factory=list)


class ResearchRunTraceability(BaseModel):
    """ResearchRun 完整追溯链。

    聚合 AutoResearch 运行的阶段时间线、关联算法运行、计算任务、观测和审计事件。
    """

    research_run: ResearchRun
    linked_algorithm_runs: list[AlgorithmRun] = Field(default_factory=list)
    linked_computations: list[LinkedComputationRef] = Field(default_factory=list)
    linked_observations: list[dict] = Field(default_factory=list)
    audit_events: list[AuditEventItem] = Field(default_factory=list)


class StageRunTraceability(BaseModel):
    """StageRun 完整追溯链。

    聚合单个阶段的输入输出、关联算法运行和审计事件。
    """

    stage_run: ResearchStageRun
    linked_algorithm_runs: list[AlgorithmRun] = Field(default_factory=list)
    linked_computations: list[LinkedComputationRef] = Field(default_factory=list)
    audit_events: list[AuditEventItem] = Field(default_factory=list)


# =============================================================================
# 状态转移校验工具函数
# =============================================================================


def validate_research_run_transition(
    current_status: ResearchRunStatus,
    target_status: ResearchRunStatus,
) -> bool:
    """校验 ResearchRun 状态转移是否合法。

    Args:
        current_status: 当前状态。
        target_status: 目标状态。

    Returns:
        转移是否合法。
    """
    allowed = RESEARCH_RUN_TRANSITIONS.get(current_status, set())
    return target_status in allowed


def validate_stage_transition(
    current_status: ResearchStageStatus,
    target_status: ResearchStageStatus,
) -> bool:
    """校验 ResearchStageRun 状态转移是否合法。

    Args:
        current_status: 当前状态。
        target_status: 目标状态。

    Returns:
        转移是否合法。
    """
    allowed = RESEARCH_STAGE_TRANSITIONS.get(current_status, set())
    return target_status in allowed
