"""Report skill orchestrator tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.report_providers.mock import MockReportProvider
from app.services.report_skill_orchestrator import ReportSkillOrchestrator


class ReportSkillOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_allowlist = list(settings.report_skill_allowlist)
        self.original_strict_mode = settings.report_skill_strict_mode

    def tearDown(self) -> None:
        settings.report_skill_allowlist = self.original_allowlist
        settings.report_skill_strict_mode = self.original_strict_mode

    def test_default_pipeline_builds_basic_nature_steps(self) -> None:
        plan = ReportSkillOrchestrator().build_plan(
            report_request={
                "skill_pipeline_id": "nature_research_report_zh",
                "scope": {
                    "include_citations": False,
                    "include_figures": False,
                    "include_literature_background": False,
                },
            },
            context={"subject": {"subject_type": "research_run", "subject_id": "rr_1"}},
        )

        self.assertEqual(plan["pipeline_id"], "nature_research_report_zh")
        self.assertEqual(
            [step["skill_id"] for step in plan["steps"]],
            ["context_summarizer", "nature-writing", "nature-polishing", "nature-data", "nature-reviewer"],
        )

    def test_default_pipeline_does_not_include_enhanced_steps_when_disabled(self) -> None:
        plan = ReportSkillOrchestrator().build_plan(
            report_request={"skill_pipeline_id": "nature_research_report_zh", "scope": {}},
            context={"subject": {"subject_type": "algorithm_run", "subject_id": "ar_1"}},
        )
        skill_ids = [step["skill_id"] for step in plan["steps"]]

        self.assertNotIn("nature-citation", skill_ids)
        self.assertNotIn("nature-figure", skill_ids)
        self.assertNotIn("nature-reader", skill_ids)

    def test_run_plan_returns_structured_report_and_skill_runs(self) -> None:
        orchestrator = ReportSkillOrchestrator()
        context = {
            "subject": {"subject_type": "algorithm_run", "subject_id": "ar_1"},
            "algorithm_run": {"run_id": "ar_1", "output_summary": {"score": 0.9}},
        }
        plan = orchestrator.build_plan(
            report_request={"skill_pipeline_id": "nature_research_report_zh", "scope": {}},
            context=context,
        )

        result = orchestrator.run_plan(plan, provider=MockReportProvider(), context=context)

        self.assertIn("structured_report", result)
        self.assertIn("skill_runs", result)
        self.assertEqual(result["structured_report"]["title"], "研发运行报告")
        self.assertEqual(len(result["skill_runs"]), 5)
        self.assertTrue(all(step["status"] == "completed" for step in result["skill_runs"]))
        self.assertTrue(all(step["input_artifact_id"] for step in result["skill_runs"]))
        self.assertTrue(all(step["output_artifact_id"] for step in result["skill_runs"]))
        self.assertIn("data_availability", result["structured_report"])
        self.assertIn("reviewer_qa", result["structured_report"])

    def test_enhanced_options_insert_optional_steps(self) -> None:
        plan = ReportSkillOrchestrator().build_plan(
            report_request={
                "skill_pipeline_id": "nature_research_report_zh",
                "scope": {
                    "include_citations": True,
                    "include_figures": True,
                    "include_literature_background": True,
                },
            },
            context={"subject": {"subject_type": "research_run", "subject_id": "rr_1"}},
        )
        skill_ids = [step["skill_id"] for step in plan["steps"]]

        self.assertEqual(plan["pipeline_id"], "nature_research_report_with_figures_zh")
        self.assertIn("nature-reader", skill_ids)
        self.assertIn("nature-academic-search", skill_ids)
        self.assertIn("nature-citation", skill_ids)
        self.assertIn("figure_data_extractor", skill_ids)
        self.assertIn("nature-figure", skill_ids)

    def test_enhanced_steps_return_productized_outputs(self) -> None:
        orchestrator = ReportSkillOrchestrator()
        context = {
            "subject": {"subject_type": "research_run", "subject_id": "rr_1"},
            "artifacts": [{"artifact_id": "art_1", "filename": "result.json"}],
        }
        plan = orchestrator.build_plan(
            report_request={
                "skill_pipeline_id": "nature_research_report_zh",
                "scope": {
                    "include_citations": True,
                    "include_figures": True,
                    "include_literature_background": True,
                },
            },
            context=context,
        )

        result = orchestrator.run_plan(plan, provider=MockReportProvider(), context=context)
        report = result["structured_report"]

        self.assertIn("literature_background", report)
        self.assertIn("academic_search", report)
        self.assertIn("citation_map", report)
        self.assertIn("figure_data", report)
        self.assertIn("figure_placeholders", report)
        self.assertNotIn("enhancements", report)
        self.assertFalse(any(step["warnings"] for step in result["skill_runs"]))

    def test_failure_analysis_pipeline_uses_failure_steps(self) -> None:
        plan = ReportSkillOrchestrator().build_plan(
            report_request={
                "skill_pipeline_id": "nature_research_report_zh",
                "scope": {"include_failure_analysis": True},
            },
            context={"subject": {"subject_type": "research_run", "subject_id": "rr_failed"}},
        )

        self.assertEqual(plan["pipeline_id"], "research_run_failure_analysis_zh")
        self.assertEqual(
            [step["skill_id"] for step in plan["steps"]],
            ["failure_context_summarizer", "nature-writing", "nature-reviewer", "nature-polishing"],
        )

    def test_strict_allowlist_rejects_disallowed_skill(self) -> None:
        settings.report_skill_strict_mode = True
        settings.report_skill_allowlist = ["nature-writing", "nature-polishing", "nature-data", "nature-reviewer"]

        with self.assertRaises(HTTPException):
            ReportSkillOrchestrator().build_plan(
                report_request={
                    "skill_pipeline_id": "nature_research_report_zh",
                    "scope": {"include_citations": True},
                },
                context={"subject": {"subject_type": "research_run", "subject_id": "rr_1"}},
            )
