"""ResearchEngine Plan-first 计划纯逻辑模块。

从编排器拆分的执行计划生成、依赖解析与核验纯函数：
不访问数据库、不写审计，所有输入通过参数显式传入，便于独立测试与复用。
"""

from __future__ import annotations

from datetime import datetime

from app.infra.computation_repositories import utc_now
from app.schemas.research_engine import (
    PlanDependency,
    PlanStep,
    StageExecutionPlan,
)

# 可追溯到 ProblemSpec 的计划输入字段白名单。
PROBLEM_SPEC_PLAN_FIELDS = {
    "problem_spec_id",
    "problem_spec_snapshot",
    "material_family",
    "target_properties",
    "variables",
    "objectives",
    "smiles",
}


def stage_requires_plan(stage_run: dict) -> bool:
    """判断当前阶段契约是否要求生成执行计划。

    Args:
        stage_run: StageRun 文档。

    Returns:
        契约要求生成计划时返回 True。
    """
    gate = stage_run.get("gate") or {}
    policy = gate.get("plan_policy") or {}
    return bool(policy.get("require_plan", False))


def stage_blocks_plan_drift(stage_run: dict) -> bool:
    """判断计划与实际执行漂移时是否阻断审批。

    Args:
        stage_run: StageRun 文档。

    Returns:
        契约要求漂移阻断时返回 True。
    """
    gate = stage_run.get("gate") or {}
    policy = gate.get("plan_policy") or {}
    return bool(policy.get("block_on_drift", False))


def plan_step_kind(algorithm_id: str | None) -> str:
    """把算法 ID 映射为受限计划步骤类型。

    Args:
        algorithm_id: 阶段将要调用的受管算法 ID。

    Returns:
        计划步骤类型（knowledge/computation/manual_review）。
    """
    if algorithm_id == "weknora_adapter":
        return "knowledge"
    if algorithm_id in {
        "polymer_descriptor_mock",
        "computation_submit_adapter",
        "mobo_alchemist_adapter",
        "mobo_mock",
    }:
        return "computation"
    return "manual_review"


def plan_safety_note(stage_key: str, algorithm_id: str | None) -> str:
    """生成供 Gate 审查的步骤安全提示。

    Args:
        stage_key: 阶段标识。
        algorithm_id: 阶段将要调用的受管算法 ID。

    Returns:
        供人工审查的安全提示文案。
    """
    if stage_key == "EXPERIMENT_EXECUTION":
        return "实验下发仍受既有确认机制约束；本阶段不得绕过审批直接提交外部任务。"
    if algorithm_id is None:
        return "本步骤只做人工审查或平台内状态更新，不调用外部工具。"
    return f"仅允许调用受管算法 '{algorithm_id}'，输入输出均写入审计追踪。"


def planned_input_fields(
    stage_run: dict,
    algorithm_input: dict | None,
) -> list[str]:
    """计算当前阶段计划需要显式声明的输入字段。

    Args:
        stage_run: StageRun 文档。
        algorithm_input: 算法实际输入快照；为 None 表示无算法调用的纯审查阶段。

    Returns:
        去重后的输入字段列表。
    """
    if algorithm_input is None:
        gate = stage_run.get("gate") or {}
        return list(dict.fromkeys(gate.get("required_inputs") or []))
    return list(dict.fromkeys(algorithm_input))


def find_upstream_output(doc: dict, stage_run: dict, field: str) -> dict | None:
    """从当前阶段之前查找声明产出该字段的上游 StageRun。

    Args:
        doc: ResearchRun 文档。
        stage_run: 当前 StageRun 文档。
        field: 输入字段名。

    Returns:
        命中的上游 StageRun；未命中返回 None。
    """
    stage_runs = doc.get("stage_runs", [])
    current_index = next(
        (
            index
            for index, item in enumerate(stage_runs)
            if item.get("stage_run_id") == stage_run.get("stage_run_id")
        ),
        len(stage_runs),
    )
    for item in reversed(stage_runs[:current_index]):
        if item.get("status") not in {"completed", "skipped"}:
            continue
        gate = item.get("gate") or {}
        if field in (gate.get("expected_outputs") or []):
            return item
    return None


def build_plan_dependency(doc: dict, stage_run: dict, field: str) -> PlanDependency:
    """把一个输入字段解析为可追溯的计划依赖。

    优先追溯到上游阶段输出，其次追溯到 ProblemSpec 字段，
    其余字段显式声明为人工输入，不做静默猜测。

    Args:
        doc: ResearchRun 文档。
        stage_run: 当前 StageRun 文档。
        field: 输入字段名。

    Returns:
        计划依赖声明。
    """
    upstream = find_upstream_output(doc, stage_run, field)
    if upstream:
        return PlanDependency(
            field=field,
            source_kind="stage_output",
            source_ref=upstream["stage_run_id"],
            source_path=field,
            required=True,
        )
    if field in PROBLEM_SPEC_PLAN_FIELDS:
        return PlanDependency(
            field=field,
            source_kind="problem_spec",
            source_ref=doc.get("problem_spec_id"),
            source_path=field,
            required=True,
        )
    return PlanDependency(field=field, source_kind="manual", required=True)


def build_stage_execution_plan(
    *,
    doc: dict,
    stage_run: dict,
    algorithm_id: str | None,
    input_fields: list[str],
    plan_id: str,
    generated_at: datetime,
) -> StageExecutionPlan:
    """基于阶段契约和实际上下文构造规则式执行计划。

    只负责构造计划对象，不落库、不写审计；
    持久化与审计由编排器在返回后执行。

    Args:
        doc: ResearchRun 文档。
        stage_run: 当前 StageRun 文档。
        algorithm_id: 阶段将要调用的受管算法 ID。
        input_fields: 计划需要显式声明的输入字段列表。
        plan_id: 新计划 ID。
        generated_at: 计划生成时间。

    Returns:
        待持久化的 draft 状态执行计划。
    """
    stage_key = stage_run["stage_key"]
    gate = stage_run.get("gate") or {}
    artifact_policy = gate.get("artifact_policy") or {}
    dependencies = [
        build_plan_dependency(doc, stage_run, field)
        for field in input_fields
    ]
    return StageExecutionPlan(
        plan_id=plan_id,
        research_run_id=doc["run_id"],
        stage_key=stage_key,
        stage_run_id=stage_run["stage_run_id"],
        steps=[
            PlanStep(
                step_key=f"{stage_key.lower()}:primary",
                kind=plan_step_kind(algorithm_id),
                tool_ref=algorithm_id,
                inputs=dependencies,
                expected_artifacts=list(
                    artifact_policy.get("required_artifacts") or []
                ),
                triggers_dispatch=False,
                safety_note=plan_safety_note(stage_key, algorithm_id),
            )
        ],
        data_sensitivity="internal",
        generated_at=generated_at,
        generated_by="rule",
        review_status="draft",
    )


def verify_stage_plan(
    stage_run: dict,
    output: dict,
    *,
    actual_tool: str | None,
) -> dict:
    """核验实际工具、输入字段与计划是否一致。

    Args:
        stage_run: 当前 StageRun 文档。
        output: 实际阶段输出。
        actual_tool: 实际调用的受管算法 ID（无算法调用时为 None）。

    Returns:
        包含工具、输入和制品覆盖情况的核验结果。
    """
    plan = stage_run.get("plan") or {}
    steps = plan.get("steps") or []
    primary_step = steps[0] if steps else {}
    planned_tool = primary_step.get("tool_ref")
    planned_inputs = [
        item["field"]
        for item in (primary_step.get("inputs") or [])
        if item.get("required", True)
    ]
    actual_inputs = list((stage_run.get("input_snapshot") or {}).keys())
    manual_review = planned_tool is None and actual_tool is None
    missing_inputs = (
        []
        if manual_review
        else [field for field in planned_inputs if field not in actual_inputs]
    )
    expected_artifacts = list(primary_step.get("expected_artifacts") or [])
    output_keys = set(output or {})
    tool_matched = planned_tool == actual_tool
    inputs_matched = not missing_inputs
    checked_at = utc_now()
    return {
        "status": "matched" if tool_matched and inputs_matched else "mismatched",
        "plan_id": plan.get("plan_id"),
        "planned_tool_ref": planned_tool,
        "actual_tool_ref": actual_tool,
        "planned_input_fields": planned_inputs,
        "actual_input_fields": actual_inputs,
        "missing_input_fields": missing_inputs,
        "input_check": (
            "not_applicable_manual_review"
            if manual_review
            else "algorithm_input_snapshot"
        ),
        "expected_artifacts": expected_artifacts,
        "generated_artifacts": [
            item for item in expected_artifacts if item in output_keys
        ],
        "artifacts_complete": all(
            item in output_keys for item in expected_artifacts
        ),
        "checked_at": checked_at.isoformat()
        if isinstance(checked_at, datetime)
        else str(checked_at),
    }


def prepare_gate_plan_review(
    stage_run: dict,
    *,
    decision: str,
    actual_tool: str | None,
) -> dict:
    """构造写入 StageGateDecision 的计划审查与核验结果。

    优先复用阶段已保存的核验结果，缺失时基于 output_summary 现场核验；
    并把人工决策回写到计划 review_status，保持原审批留痕语义。

    Args:
        stage_run: 当前 StageRun 文档。
        decision: 人工决策类型（approved/rejected）。
        actual_tool: 实际调用的受管算法 ID（无算法调用时为 None）。

    Returns:
        写入 StageGateDecision 的计划审查结果。
    """
    plan = stage_run.get("plan")
    if not plan:
        return {
            "status": "plan_missing",
            "decision": decision,
        }
    verification = (
        stage_run.get("checkpoint_data", {}).get("plan_verification")
        or verify_stage_plan(
            stage_run,
            stage_run.get("output_summary") or {},
            actual_tool=actual_tool,
        )
    )
    plan["review_status"] = decision
    return {
        **verification,
        "decision": decision,
        "review_status": decision,
        "status": (
            "rejected" if decision == "rejected" else verification.get("status")
        ),
    }
