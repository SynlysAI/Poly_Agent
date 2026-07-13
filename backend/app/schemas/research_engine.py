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

ExecutionDecisionMode = Literal["manual_workbench", "autoresearch"]
"""执行决策模式：manual_workbench=人工算法工作台，autoresearch=自动编排。"""

TriggerSource = Literal["human_workflow", "autoresearch", "system"]
"""触发来源：human_workflow=人工 Workflow，autoresearch=AutoResearch 编排，system=系统内部触发。"""

ProblemSpecDecisionStatus = Literal["pending_execution_decision", "decision_made"]
"""ProblemSpec 执行决策状态。"""

WorkflowRunStatus = Literal["draft", "queued", "running", "completed", "failed", "cancelled"]
"""WorkflowRun 运行状态。"""

WorkflowStepRunStatus = Literal["pending", "running", "completed", "failed", "skipped"]
"""WorkflowStepRun 运行状态。"""

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

AlgorithmFamily = Literal[
    "computation",
    "wetlab_optimization",
    "vertical_prediction",
    "knowledge",
    "structure",
]
"""面向产品入口的算法族。"""

AlgorithmStatus = Literal[
    "active", "pending_encapsulation", "in_development", "frozen", "decommissioned"
]
"""算法能力登记状态。"""

AlgorithmIntegrationKind = Literal["real", "builtin", "simulated", "pending"]
"""算法接入形态，用于区分真实能力、内置能力、模拟演示和待接入能力。"""

MaterialScope = Literal[
    "fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"
]
"""适用材料体系范围。"""

GateDecision = Literal["approved", "rejected", "modified"]
"""人工审批决策类型。"""

AlgorithmRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
"""AlgorithmRun 运行状态。"""

AlgorithmPackageStatus = Literal[
    "uploaded",
    "validating",
    "validated",
    "validation_failed",
    "building",
    "build_failed",
    "built",
    "deploying",
    "deployed_staging",
    "active",
    "frozen",
    "decommissioned",
]
"""用户上传算法包/版本生命周期状态。"""

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

    支持 allowed_execution_modes、变量/目标/约束定义，是材料研发任务的核心入口。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    material_family: MaterialScope = "fluoropolymer"
    problem_type: ProblemType = "formulation_process_optimization"
    allowed_execution_modes: list[ExecutionDecisionMode] = Field(
        default_factory=lambda: ["manual_workbench", "autoresearch"],
        min_length=1,
    )
    decision_status: ProblemSpecDecisionStatus = "pending_execution_decision"
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

    @field_validator("allowed_execution_modes")
    @classmethod
    def validate_allowed_execution_modes(
        cls, value: list[ExecutionDecisionMode]
    ) -> list[ExecutionDecisionMode]:
        """校验可用执行模式。"""
        unique_modes = list(dict.fromkeys(value))
        if not unique_modes:
            raise ValueError("至少需要一个可用执行模式")
        return unique_modes


class ProblemSpec(ProblemSpecCreate):
    """ProblemSpec 完整记录。

    在创建请求基础上增加系统字段：ID、版本、时间戳、创建者等。
    """

    problem_spec_id: str
    schema_version: str = "0.4"
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
# ExecutionDecision / ManualWorkflow 相关模型
# =============================================================================


class ExecutionDecisionCreate(BaseModel):
    """创建执行决策请求。"""

    model_config = ConfigDict(extra="forbid")

    mode: ExecutionDecisionMode
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        """规范化选择原因。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("执行模式选择原因不能为空")
        return normalized


class ExecutionDecision(BaseModel):
    """执行模式选择记录。"""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    problem_spec_id: str
    problem_spec_version: str
    mode: ExecutionDecisionMode
    reason: str
    status: str = "active"
    initial_context_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class ExecutionDecisionListData(BaseModel):
    """ExecutionDecision 分页响应。"""

    items: list[ExecutionDecision]
    page: int
    page_size: int
    total: int


class WorkflowInputBinding(BaseModel):
    """Workflow 节点输入绑定。"""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=80)
    path: str | None = Field(default=None, max_length=300)
    value: object | None = None
    step_id: str | None = Field(default=None, max_length=80)


class ManualWorkflowStep(BaseModel):
    """人工 Workflow 定义中的算法节点。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=80)
    algorithm_id: str = Field(min_length=1, max_length=80)
    input_bindings: dict[str, WorkflowInputBinding] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    output_alias: str | None = Field(default=None, max_length=80)


class ManualAlgorithmWorkflowCreate(BaseModel):
    """创建人工算法 Workflow 请求。"""

    model_config = ConfigDict(extra="forbid")

    problem_spec_id: str = Field(min_length=1, max_length=80)
    execution_decision_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    steps: list[ManualWorkflowStep] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=1000)


class ManualAlgorithmWorkflow(ManualAlgorithmWorkflowCreate):
    """人工算法 Workflow 定义。"""

    workflow_id: str
    status: str = "active"
    validation_status: str = "validated"
    created_by: str
    owner_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ManualAlgorithmWorkflowListData(BaseModel):
    """ManualAlgorithmWorkflow 分页响应。"""

    items: list[ManualAlgorithmWorkflow]
    page: int
    page_size: int
    total: int


class WorkflowStepRun(BaseModel):
    """Workflow 中单个步骤运行记录。"""

    step_run_id: str
    workflow_run_id: str
    step_id: str
    algorithm_id: str
    status: WorkflowStepRunStatus = "pending"
    input_snapshot: dict = Field(default_factory=dict)
    output_summary: dict = Field(default_factory=dict)
    algorithm_run_id: str | None = None
    error: dict | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowRun(BaseModel):
    """人工 Workflow 运行记录。"""

    workflow_run_id: str
    workflow_id: str
    problem_spec_id: str
    execution_decision_id: str
    status: WorkflowRunStatus = "queued"
    step_runs: list[WorkflowStepRun] = Field(default_factory=list)
    input_snapshot: dict = Field(default_factory=dict)
    artifact_refs: list[dict] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowRunListData(BaseModel):
    """WorkflowRun 分页响应。"""

    items: list[WorkflowRun]
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
    field_defaults: dict[str, object] = Field(default_factory=dict)
    ui_hints: dict[str, dict] = Field(default_factory=dict)
    field_options: dict[str, list[str]] = Field(default_factory=dict)
    """字段可选值列表，key 为字段名，value 为该字段允许的值列表。

    若字段在 field_options 中有定义，前端应渲染为下拉选择而非自由文本输入。
    包含值时后端 validate_input 会进行白名单校验。
    """


class AlgorithmRegistryEntry(BaseModel):
    """算法能力登记条目。

    每个算法进入平台前至少登记以下字段，形成统一的算法能力清单。
    """

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    type: AlgorithmType = "predictor"
    algorithm_family: AlgorithmFamily | None = None
    material_scope: list[MaterialScope] = Field(default_factory=lambda: ["universal"])
    task_scope: list[ResearchStageKey] = Field(default_factory=list)
    input_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    output_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    call_method: str = Field(default="REST", max_length=40)
    trigger_modes: list[TriggerSource] = Field(default_factory=lambda: ["human_workflow"])
    runtime_dependency: str | None = Field(default=None, max_length=200)
    version: str = Field(default="1.0.0", max_length=40)
    validation_metric: dict = Field(default_factory=dict)
    owner: str | None = Field(default=None, max_length=80)
    status: AlgorithmStatus = "active"
    description: str | None = Field(default=None, max_length=1000)
    active_version_id: str | None = Field(default=None, max_length=120)
    source: str = Field(default="builtin", max_length=40)
    deployment_status: str | None = Field(default=None, max_length=40)
    integration_kind: AlgorithmIntegrationKind = "builtin"
    capability_group: str | None = Field(default=None, max_length=80)

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


class AlgorithmPackageCreate(BaseModel):
    """网页打包助手提交的算法元信息。"""

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    algorithm_family: AlgorithmFamily = "vertical_prediction"
    type: AlgorithmType = "predictor"
    material_scope: list[MaterialScope] = Field(default_factory=lambda: ["universal"], min_length=1)
    task_scope: list[ResearchStageKey] = Field(default_factory=lambda: ["COMPUTE_PREDICT"])
    trigger_modes: list[TriggerSource] = Field(default_factory=lambda: ["human_workflow", "autoresearch"])
    entrypoint: str = Field(default="src.handler:predict", max_length=200)
    loader: str | None = Field(default=None, max_length=200)
    input_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    output_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    runtime: dict = Field(default_factory=dict)
    sample_input: dict = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("algorithm_id")
    @classmethod
    def normalize_package_algorithm_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("算法 ID 不能为空")
        return normalized


class AlgorithmPackage(BaseModel):
    """用户上传算法包记录。"""

    model_config = ConfigDict(extra="forbid")

    package_id: str
    algorithm_id: str | None = None
    version: str | None = None
    version_id: str | None = None
    status: AlgorithmPackageStatus = "uploaded"
    package_sha256: str
    filename: str
    storage_uri: str
    size_bytes: int
    validation_errors: list[dict] = Field(default_factory=list)
    validation_logs: list[str] = Field(default_factory=list)
    build_logs: list[str] = Field(default_factory=list)
    deployment_logs: list[str] = Field(default_factory=list)
    image_digest: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class AlgorithmVersion(BaseModel):
    """不可变算法版本记录。"""

    model_config = ConfigDict(extra="forbid")

    version_id: str
    package_id: str
    algorithm_id: str
    name: str
    version: str
    package_sha256: str
    image_digest: str | None = None
    status: AlgorithmPackageStatus = "validated"
    runtime: dict = Field(default_factory=dict)
    input_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    output_schema: AlgorithmIOSchema = Field(default_factory=AlgorithmIOSchema)
    entrypoint: str
    loader: str | None = None
    package_path: str
    deployment: dict = Field(default_factory=dict)
    contract: dict = Field(default_factory=dict)
    created_by: str
    created_at: datetime
    updated_at: datetime


class AlgorithmPackageListData(BaseModel):
    """算法包分页响应。"""

    items: list[AlgorithmPackage]
    page: int
    page_size: int
    total: int


class AlgorithmVersionListData(BaseModel):
    """算法版本分页响应。"""

    items: list[AlgorithmVersion]
    page: int
    page_size: int
    total: int


class ResearchEngineExampleSummary(BaseModel):
    """ResearchEngine 示例流程摘要。"""

    model_config = ConfigDict(extra="forbid")

    example_id: str
    title: str
    description: str
    mode: ExecutionDecisionMode
    tags: list[str] = Field(default_factory=list)


class ResearchEngineExampleListData(BaseModel):
    """ResearchEngine 示例流程列表。"""

    items: list[ResearchEngineExampleSummary]


class ResearchEngineExampleInstantiateResult(BaseModel):
    """ResearchEngine 示例实例化结果。"""

    model_config = ConfigDict(extra="forbid")

    example_id: str
    problem_spec: ProblemSpec
    execution_decision: ExecutionDecision
    manual_workflow: ManualAlgorithmWorkflow | None = None
    workflow_run: WorkflowRun | None = None
    research_run: ResearchRun | None = None
    navigation: dict = Field(default_factory=dict)
    message: str


# =============================================================================
# AlgorithmRun 相关模型
# =============================================================================


class AlgorithmRunCreate(BaseModel):
    """创建算法运行请求。"""

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(min_length=1, max_length=80)
    trigger_source: TriggerSource = "human_workflow"
    trigger_context_id: str | None = Field(default=None, max_length=80)
    problem_spec_id: str | None = Field(default=None, max_length=80)
    campaign_id: str | None = Field(default=None, max_length=80)
    workflow_run_id: str | None = Field(default=None, max_length=80)
    workflow_step_run_id: str | None = Field(default=None, max_length=80)
    research_run_id: str | None = Field(default=None, max_length=80)
    stage_run_id: str | None = Field(default=None, max_length=80)
    input_snapshot: dict = Field(default_factory=dict)
    algorithm_version_id: str | None = Field(default=None, max_length=120)
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
    workflow_run_id: str | None = None
    workflow_step_run_id: str | None = None
    research_run_id: str | None = None
    stage_run_id: str | None = None
    algorithm_version_id: str | None = None
    package_sha256: str | None = None
    image_digest: str | None = None
    runtime_snapshot: dict = Field(default_factory=dict)
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
    execution_decision_id: str = Field(min_length=1, max_length=80)
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
    execution_decision_id: str | None = None
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


class ResearchEngineReadinessItem(BaseModel):
    """AutoResearch 启动前集成可用性条目。"""

    model_config = ConfigDict(extra="forbid")

    service: str
    label: str
    status: Literal["ready", "warning", "unavailable"]
    required: bool = False
    blocking: bool = False
    demo_fallback: bool = False
    message: str
    details: dict = Field(default_factory=dict)


class ResearchEngineReadinessData(BaseModel):
    """AutoResearch 启动前集成可用性摘要。"""

    model_config = ConfigDict(extra="forbid")

    ready: bool
    can_start: bool
    checked_at: datetime
    items: list[ResearchEngineReadinessItem]


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


class ArchiveRequest(BaseModel):
    """软删除/归档请求。"""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="用户归档", max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        return normalized or "用户归档"


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
