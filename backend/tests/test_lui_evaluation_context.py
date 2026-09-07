"""LUI 评测上下文透传与录制事实抓取测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.infra.research_engine_repositories import (
    AssistantMessageRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant import AssistantChatRequest
from app.services.assistant_context_assembler import ContextAssembly
from app.services.assistant_run_service import AssistantRunService
from app.services.assistant_service import AssistantService
from evaluation.lui.capture import capture_facts_by_evaluation


EVALUATION_ID = "lui-eval-context-test"
TASK_ID = "LUI-TS-0001"


def _assembly() -> ContextAssembly:
    """构建最小上下文装配结果。"""
    return ContextAssembly(
        request_kind="assistant",
        sections=(),
        digest="digest-test",
        token_estimate=10,
        native_tool_schema_token_estimate=0,
        budget_token_estimate=10,
        chars_per_token=4,
        rendered="",
    )


class LuiEvaluationContextTest(ComputationTestCase):
    def test_tool_source_context_persists_evaluation_fields(self) -> None:
        """工具提案来源快照应保留评测三字段，供续答 run 透传。"""
        request = AssistantChatRequest(
            messages=[{"role": "user", "content": "预测介电常数"}],
            context={
                "evaluation_id": EVALUATION_ID,
                "task_id": TASK_ID,
                "evaluation_version": "2026.08.28",
            },
        )
        snapshot = AssistantService()._tool_source_context(
            request=request,
            llm_route={"provider_id": "deepseek", "model_id": "deepseek-chat"},
            assembly=_assembly(),
            selected_tool_ids=["algorithm:demo"],
        )
        self.assertEqual(snapshot["evaluation_id"], EVALUATION_ID)
        self.assertEqual(snapshot["task_id"], TASK_ID)
        self.assertEqual(snapshot["evaluation_version"], "2026.08.28")

    def test_tool_source_context_omits_missing_evaluation_fields(self) -> None:
        """非评测请求不应写入空的评测字段，保持旧快照兼容。"""
        request = AssistantChatRequest(
            messages=[{"role": "user", "content": "普通问题"}],
            context={"mode": "qa"},
        )
        snapshot = AssistantService()._tool_source_context(
            request=request,
            llm_route={},
            assembly=_assembly(),
            selected_tool_ids=[],
        )
        self.assertNotIn("evaluation_id", snapshot)
        self.assertNotIn("task_id", snapshot)
        self.assertNotIn("evaluation_version", snapshot)

    def test_continuation_context_propagates_evaluation_fields(self) -> None:
        """续答 run 上下文应从工具来源快照透传评测三字段。"""
        context = AssistantRunService._continuation_context(
            {"call_id": "atc_eval", "chat_id": "chat_eval", "tool_id": "algorithm:demo"},
            {
                "mode": "qa",
                "evaluation_id": EVALUATION_ID,
                "task_id": TASK_ID,
                "evaluation_version": "2026.08.28",
            },
            "message_eval",
        )
        self.assertEqual(context["evaluation_id"], EVALUATION_ID)
        self.assertEqual(context["task_id"], TASK_ID)
        self.assertEqual(context["evaluation_version"], "2026.08.28")

    def test_continuation_context_without_evaluation_fields_stays_compatible(self) -> None:
        """旧工具快照没有评测字段时，续答上下文不应新增空键。"""
        context = AssistantRunService._continuation_context(
            {"call_id": "atc_legacy", "chat_id": "chat_legacy", "tool_id": "algorithm:demo"},
            {"mode": "qa"},
            "message_legacy",
        )
        self.assertNotIn("evaluation_id", context)
        self.assertNotIn("task_id", context)
        self.assertNotIn("evaluation_version", context)

    def test_capture_prefers_latest_run_and_final_message(self) -> None:
        """同一任务多 run 时应抓取最新续答 run 与最终回答。"""
        base_time = datetime(2026, 9, 1, 12, 0, 0)
        proposal_run_id = "asrun_eval_proposal"
        continuation_run_id = "asrun_eval_continuation"
        message_id = "msg_eval_final"
        common_snapshot = {
            "content": "预测介电常数",
            "messages": [],
            "context": {
                "evaluation_id": EVALUATION_ID,
                "task_id": TASK_ID,
                "evaluation_version": "2026.08.28",
            },
        }
        self.assertTrue(
            AssistantRunRepository.create_active(
                {
                    "run_id": proposal_run_id,
                    "trace_id": proposal_run_id,
                    "chat_id": "chat_eval",
                    "created_by": "eval-user",
                    "user_message_id": "message_eval_user",
                    "status": "completed",
                    "active": False,
                    "stage": "completed",
                    "event_seq": 0,
                    "events": [],
                    "created_at": base_time,
                    "updated_at": base_time,
                    "request_snapshot": common_snapshot,
                }
            )[0]
        )
        self.assertTrue(
            AssistantRunRepository.create_active(
                {
                    "run_id": continuation_run_id,
                    "trace_id": proposal_run_id,
                    "chat_id": "chat_eval",
                    "created_by": "eval-user",
                    "user_message_id": "message_eval_user",
                    "status": "completed",
                    "active": False,
                    "stage": "completed",
                    "event_seq": 0,
                    "events": [],
                    "assistant_message_id": message_id,
                    "created_at": base_time + timedelta(seconds=5),
                    "updated_at": base_time + timedelta(seconds=5),
                    "request_snapshot": common_snapshot,
                }
            )[0]
        )
        AssistantToolCallRepository.save(
            "call_id",
            {
                "call_id": "atc_eval_capture",
                "trace_id": proposal_run_id,
                "assistant_run_id": proposal_run_id,
                "chat_id": "chat_eval",
                "created_by": "eval-user",
                "tool_id": "algorithm:demo",
                "algorithm_id": "demo",
                "tool_name": "Demo",
                "phase": "completed",
                "arguments": {"smiles": "C=C(F)F"},
                "confirmed_at": base_time + timedelta(seconds=2),
                "created_at": base_time,
                "updated_at": base_time,
            },
        )
        AssistantMessageRepository.save(
            "message_id",
            {
                "message_id": message_id,
                "chat_id": "chat_eval",
                "created_by": "eval-user",
                "role": "assistant",
                "content": "已根据工具结果完成最终回答。",
                "references": [],
                "created_at": base_time + timedelta(seconds=5),
                "updated_at": base_time + timedelta(seconds=5),
            },
        )

        facts = capture_facts_by_evaluation(EVALUATION_ID)[TASK_ID]

        self.assertEqual(facts.run.run_id, continuation_run_id)
        self.assertEqual(facts.message.content, "已根据工具结果完成最终回答。")
        self.assertEqual(facts.tool_calls[0].call_id, "atc_eval_capture")
