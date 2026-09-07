"""LUI 动态计算预算数据契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AssistantBudgetMode = Literal["disabled", "shadow", "enabled"]
AssistantQueryComplexity = Literal["simple", "complex"]
AssistantRiskLevel = Literal["low", "medium", "high"]
AssistantEvidenceNeed = Literal["entry_fact", "grounded_answer", "multi_source_synthesis"]
AssistantUserConstraint = Literal[
    "balanced",
    "low_latency",
    "low_cost",
    "high_quality",
    "high_explainability",
]
AssistantClassificationCategory = Literal["simple", "complex", "high_risk"]
AssistantModelTier = Literal["simple", "complex", "high_risk"]
AssistantModelPurpose = Literal["qa", "deep"]
AssistantRetrievalTier = Literal["vector", "hybrid_reranker", "hybrid_reranker_web"]
AssistantExecutionTier = Literal["one_shot", "planning", "planning_verification_human"]


class ClassificationPolicy(BaseModel):
    """确定性查询分类策略。"""

    model_config = ConfigDict(extra="forbid")

    simple_keywords: tuple[str, ...]
    complex_keywords: tuple[str, ...]
    high_risk_keywords: tuple[str, ...]
    explainability_keywords: tuple[str, ...]
    minimum_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    uncertain_fallback: AssistantClassificationCategory = "complex"


class BudgetPolicy(BaseModel):
    """模型、检索与执行档位映射策略。"""

    model_config = ConfigDict(extra="forbid")

    default_mode: AssistantBudgetMode = "shadow"
    model_purposes: dict[AssistantModelTier, AssistantModelPurpose]
    retrieval_tiers: dict[AssistantClassificationCategory, AssistantRetrievalTier]
    execution_tiers: dict[AssistantClassificationCategory, AssistantExecutionTier]
    allow_deep_simple_downgrade: bool = True


class ExecutionPolicy(BaseModel):
    """执行分级与不可绕过的安全底线。"""

    model_config = ConfigDict(extra="forbid")

    one_shot_max_model_calls: int = Field(default=1, ge=1)
    planning_max_model_calls: int = Field(default=3, ge=1)
    human_risk_levels: tuple[AssistantRiskLevel, ...] = ("high",)
    verification_required: tuple[AssistantClassificationCategory, ...] = ("high_risk",)
    preserve_session_control: bool = True


class AssistantPreset(BaseModel):
    """一个科研助手 Preset 的存储兼容契约。"""

    model_config = ConfigDict(extra="forbid")

    preset_id: Literal["research_qa", "research_deep"]
    mode: Literal["qa", "deep"]
    route_purpose: AssistantModelPurpose
    display_name: str
    classification_policy: ClassificationPolicy
    budget_policy: BudgetPolicy
    execution_policy: ExecutionPolicy


class ClassificationInput(BaseModel):
    """分类器允许使用的最小、可审计输入摘要。"""

    model_config = ConfigDict(extra="forbid")

    query_digest: str
    query_complexity: AssistantQueryComplexity = "complex"
    risk_level: AssistantRiskLevel = "low"
    evidence_need: AssistantEvidenceNeed = "grounded_answer"
    explainability_required: bool = False
    user_constraint: AssistantUserConstraint = "balanced"
    prior_evidence_conflict: bool = False
    selected_tool_count: int = Field(default=0, ge=0)
    plan_mode: bool = False
    permission_mode: str = "workspace_write"
    signals: tuple[str, ...] = Field(default_factory=tuple)


class ClassificationResult(ClassificationInput):
    """确定性分类结果。"""

    category: AssistantClassificationCategory = "complex"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    fallback_reason: str | None = None


class BudgetCostEstimate(BaseModel):
    """预算决策期的成本估算；真实 token 由 LLM usage 事件补充。"""

    model_config = ConfigDict(extra="forbid")

    estimated_model_calls: int = Field(default=1, ge=0)
    estimated_retrieval_calls: int = Field(default=0, ge=0)
    estimated_web_fetch_pages: int = Field(default=0, ge=0)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class AssistantBudgetDecision(BaseModel):
    """一次请求的动态计算预算决策快照。"""

    model_config = ConfigDict(extra="forbid")

    preset_id: str
    compatibility_mode: str
    release_mode: AssistantBudgetMode
    rollout_eligible: bool = False
    classification: ClassificationResult
    recommended_model_tier: AssistantModelTier
    recommended_model_purpose: AssistantModelPurpose
    recommended_retrieval_tier: AssistantRetrievalTier
    recommended_execution_tier: AssistantExecutionTier
    effective_model_tier: AssistantModelTier
    effective_model_purpose: AssistantModelPurpose
    effective_retrieval_tier: AssistantRetrievalTier
    effective_execution_tier: AssistantExecutionTier
    user_overrides: tuple[str, ...] = Field(default_factory=tuple)
    safety_guards: tuple[str, ...] = Field(default_factory=tuple)
    fallback_reason: str | None = None
    decision_duration_ms: int = Field(default=0, ge=0)
    cost: BudgetCostEstimate = Field(default_factory=BudgetCostEstimate)
