"""LUI Agent 评测的 Golden Set 与观测事实契约。

本模块只定义数据结构与纯校验，不依赖数据库和网络，便于离线回归。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


GoldenCategory = Literal[
    "project_fact",
    "knowledge_retrieval",
    "web_retrieval",
    "tool_selection",
    "tool_argument",
    "multi_turn",
    "refusal_boundary",
    "failure_recovery",
]

TaskMode = Literal["qa", "deep"]
ModelCapability = Literal["none", "tool_calling"]
EscalationLevel = Literal[
    "none",
    "confirmation",
    "param_completion",
    "permission_block",
    "takeover",
    "cancel",
]
AnswerType = Literal[
    "exact",
    "facts",
    "numeric",
    "keywords",
    "rubric",
    "refusal",
    "insufficient_info",
]
ToleranceKind = Literal[
    "exact",
    "absolute",
    "relative",
    "significant_figures",
    "ignore",
]

DATASET_VERSION = "2026.08.28"
DEFAULT_RECALL_KS = (1, 3, 5)


class GoldenContext(BaseModel):
    """评测任务的对话上下文输入。"""

    model_config = ConfigDict(extra="allow")

    selected_tool_ids: list[str] = Field(default_factory=list)
    use_web_search: bool | None = None
    use_knowledge_base: bool | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)
    permission_mode: Literal["workspace_write", "read_only"] | None = None
    preset_id: str | None = None
    mode: TaskMode | None = None


class ToleranceRule(BaseModel):
    """参数或数值的容忍规则。

    Args:
        kind: 判定方式；exact 为精确等价，absolute/relative 为误差容忍，
            significant_figures 按有效数字比较，ignore 表示该字段不参与判定。
        value: 容忍值或有效数字位数；ignore/exact 时可为空。
    """

    kind: ToleranceKind = "exact"
    value: float | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "ToleranceRule":
        """校验容忍规则必须携带所需数值。"""
        if self.kind in {"absolute", "relative", "significant_figures"}:
            if self.value is None or self.value < 0:
                raise ValueError(f"tolerance kind={self.kind} requires value >= 0")
        return self


class ExpectedToolCall(BaseModel):
    """Golden 期望的一次算法工具调用。"""

    tool_id: str
    function_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    argument_tolerance: dict[str, ToleranceRule] = Field(default_factory=dict)
    ignored_extra_fields: list[str] = Field(default_factory=list)
    forbid_extra_arguments: bool = False


class ExpectedRetrieval(BaseModel):
    """检索召回的期望证据集合。"""

    source: Literal["knowledge", "web", "any"] = "any"
    relevant_ids: list[str] = Field(min_length=1)
    ks: list[int] = Field(default_factory=lambda: list(DEFAULT_RECALL_KS))

    @field_validator("ks")
    @classmethod
    def validate_ks(cls, value: list[int]) -> list[int]:
        """校验 Recall@K 的 K 值为递增正整数。"""
        normalized = sorted(set(int(item) for item in value))
        if not normalized or any(item <= 0 for item in normalized):
            raise ValueError("ks must be positive integers")
        return normalized


class ExpectedAnswer(BaseModel):
    """最终回答的期望与判定输入。"""

    type: AnswerType
    value: str | None = None
    must_include: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    numeric_value: float | None = None
    numeric_tolerance: ToleranceRule | None = None
    rubric: list[str] = Field(default_factory=list)
    min_rubric_score: float = Field(default=0.7, ge=0.0, le=1.0)
    case_sensitive: bool = False

    @model_validator(mode="after")
    def validate_requirements(self) -> "ExpectedAnswer":
        """按回答类型校验必填字段。"""
        if self.type in {"exact", "facts"} and not (self.value or "").strip():
            raise ValueError(f"answer type={self.type} requires value")
        if self.type == "numeric" and self.numeric_value is None:
            raise ValueError("answer type=numeric requires numeric_value")
        if self.type == "rubric" and not (self.must_include or self.rubric):
            raise ValueError("answer type=rubric requires must_include or rubric")
        return self


class ExpectedHallucination(BaseModel):
    """幻觉检查的自动化输入与人工复核说明。"""

    forbidden_claims: list[str] = Field(default_factory=list)
    require_citations: bool = False
    checks: list[str] = Field(default_factory=list)


class ExpectedEscalation(BaseModel):
    """人工兜底期望。"""

    level: EscalationLevel = "none"
    reason: str | None = None


class GoldenExpected(BaseModel):
    """单条 Golden 任务的期望结果。"""

    task_success: bool = True
    tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    retrieval: ExpectedRetrieval | None = None
    answer: ExpectedAnswer | None = None
    hallucination: ExpectedHallucination = Field(default_factory=ExpectedHallucination)
    escalation: ExpectedEscalation = Field(default_factory=ExpectedEscalation)
    latency_budget_ms: int | None = Field(default=None, ge=0)
    token_budget: int | None = Field(default=None, ge=0)


class GoldenMessage(BaseModel):
    """评测任务中的一条消息。"""

    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1)


class FixtureRetrievalItem(BaseModel):
    """离线 fixture 中的一条检索结果。"""

    id: str
    rank: int = Field(ge=1)
    score: float | None = None
    snippet: str = ""
    used_in_answer: bool | None = None


class FixtureRetrieval(BaseModel):
    """离线 fixture 中一次检索的观测事实。"""

    source: Literal["knowledge", "web"]
    status: str = "searched"
    duration_ms: int | None = Field(default=None, ge=0)
    results: list[FixtureRetrievalItem] = Field(default_factory=list)


class FixtureToolCall(BaseModel):
    """离线 fixture 中一次工具调用的观测事实。"""

    call_id: str
    tool_id: str
    function_name: str | None = None
    raw_arguments: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    arguments_parse_error: str | None = None
    phase: str = "completed"
    error: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    proposal_usage: dict[str, Any] | None = None


class FixtureRun(BaseModel):
    """离线 fixture 中 assistant run 的观测事实。"""

    run_id: str
    status: Literal["queued", "running", "completed", "failed", "canceled"]
    stage: str | None = None
    error: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    first_token_ms: int | None = Field(default=None, ge=0)
    queue_wait_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    provider_id: str | None = None
    model_id: str | None = None
    route: dict[str, Any] = Field(default_factory=dict)
    usage_events: list[dict[str, Any]] = Field(default_factory=list)


class FixtureMessage(BaseModel):
    """离线 fixture 中最终 assistant 消息的观测事实。"""

    content: str = ""
    references: list[dict[str, Any]] = Field(default_factory=list)
    answer_mode: str | None = None
    answer_scope: str | None = None
    retrieval_status: str | None = None


class FixtureEscalation(BaseModel):
    """离线 fixture 中人工兜底信号的观测事实。"""

    confirmations: int = Field(default=0, ge=0)
    param_completions: int = Field(default=0, ge=0)
    permission_blocked: bool = False
    awaiting_input_terminal: bool = False
    dead_letter: bool = False
    user_canceled: bool = False
    needed_retry: bool = False


class TaskFixture(BaseModel):
    """单条任务的确定性观测事实，用于离线快速回归。"""

    run: FixtureRun
    tool_calls: list[FixtureToolCall] = Field(default_factory=list)
    retrievals: list[FixtureRetrieval] = Field(default_factory=list)
    message: FixtureMessage | None = None
    escalation: FixtureEscalation = Field(default_factory=FixtureEscalation)


class GoldenTask(BaseModel):
    """一条可版本化的 LUI 评测 Golden 任务。"""

    id: str = Field(pattern=r"^LUI-[A-Z0-9]+-\d{4}$")
    category: GoldenCategory
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    mode: TaskMode = "qa"
    requires_model_capability: ModelCapability = "none"
    messages: list[GoldenMessage] = Field(min_length=1)
    context: GoldenContext = Field(default_factory=GoldenContext)
    expected: GoldenExpected
    fixture: TaskFixture | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_task(self) -> "GoldenTask":
        """校验任务结构与能力声明一致。"""
        if not any(item.role == "user" for item in self.messages):
            raise ValueError("task requires at least one user message")
        if self.expected.tool_calls and self.requires_model_capability != "tool_calling":
            raise ValueError("tool tasks require tool_calling capability")
        if self.category in {"tool_selection", "tool_argument"} and not self.expected.tool_calls:
            raise ValueError(f"category={self.category} requires expected tool_calls")
        if (
            self.category in {"knowledge_retrieval", "web_retrieval"}
            and not self.expected.retrieval
            and not (
                self.expected.answer
                and self.expected.answer.type == "insufficient_info"
            )
        ):
            raise ValueError(f"category={self.category} requires expected retrieval")
        if self.category == "refusal_boundary" and not self.expected.answer:
            raise ValueError("category=refusal_boundary requires expected answer")
        if self.category == "failure_recovery" and not (
            self.expected.answer or self.expected.escalation.level != "none"
        ):
            raise ValueError(
                "category=failure_recovery requires expected answer or escalation"
            )
        return self


class ObservedFacts(TaskFixture):
    """评测器消费的任务级原始事实。

    与 TaskFixture 同构：离线模式直接来自 Golden 任务内嵌 fixture，
    录制模式来自 `evaluation_id` 关联的 run/tool/event/message 投影。
    """

    task_id: str
    trace_id: str | None = None
    captured_at: str | None = None


class MetricOutcome(BaseModel):
    """单项指标在单任务上的判定结果。"""

    key: str
    applicable: bool
    passed: bool | None = None
    score: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TaskEvaluation(BaseModel):
    """单任务的 M1–M8 判定汇总。"""

    task_id: str
    category: GoldenCategory
    mode: TaskMode
    outcomes: dict[str, MetricOutcome]

    @property
    def success(self) -> bool:
        """任务是否满足期望成功判定。"""
        outcome = self.outcomes.get("m1")
        return bool(outcome and outcome.applicable and outcome.passed)
