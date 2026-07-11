"""Report context service tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_context_service import ReportContextService


class _TraceabilityPayload:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str = "python") -> dict:
        return self.payload


class _ObjectPayload:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        for key, value in payload.items():
            setattr(self, key, value)

    def model_dump(self, *, mode: str = "python") -> dict:
        return self.payload


class _FakeResearchEngineService:
    def __init__(self) -> None:
        self.algorithm_called_with = None
        self.research_called_with = None

    def get_algorithm_run_traceability(self, run_id: str, *, actor_user_id=None, is_admin=False):
        self.algorithm_called_with = (run_id, actor_user_id, is_admin)
        return _TraceabilityPayload(
            {
                "algorithm_run": {
                    "run_id": run_id,
                    "status": "completed",
                    "input_snapshot": {
                        "api_key": "sk-test",
                        "input_path": "/home/user/private/input.json",
                        "notes": "short",
                    },
                    "output_summary": {"result": "ok"},
                    "artifact_refs": [{"artifact_id": "art_1", "path": "/tmp/raw.txt"}],
                },
                "linked_computation": {
                    "run_id": "comp_1",
                    "output_summary": {"secret_token": "token-value"},
                },
                "audit_events": [
                    {
                        "event_id": "audit_1",
                        "event_type": "algorithm_run.completed",
                        "after": {"password": "hidden"},
                    }
                ],
            }
        )

    def get_research_run_traceability(self, run_id: str, *, actor_user_id=None, is_admin=False):
        self.research_called_with = (run_id, actor_user_id, is_admin)
        return _TraceabilityPayload(
            {
                "research_run": {
                    "run_id": run_id,
                    "status": "completed",
                    "stage_runs": [
                        {
                            "stage_run_id": "stage_1",
                            "stage_key": "COMPUTE_PREDICT",
                            "output_summary": {"long_text": "x" * 120},
                        }
                    ],
                },
                "linked_algorithm_runs": [
                    {"run_id": "ar_1", "input_snapshot": {"token": "abc"}}
                ],
                "linked_computations": [],
                "linked_observations": [{"observation_id": "obs_1", "source_path": "/data/raw.csv"}],
                "audit_events": [],
            }
        )

    def get_workflow_run(self, run_id: str, *, actor_user_id=None, is_admin=False):
        return _ObjectPayload(
            {
                "workflow_run_id": run_id,
                "status": "completed",
                "step_runs": [{"algorithm_run_id": "ar_wf_1"}],
                "artifact_refs": [{"artifact_id": "wf_art", "storage_uri": "/tmp/workflow.json"}],
            }
        )

    def list_algorithm_runs(self, **kwargs):
        return SimpleNamespace(
            items=[
                _ObjectPayload(
                    {
                        "run_id": "ar_wf_1",
                        "workflow_run_id": kwargs["workflow_run_id"],
                        "output_summary": {"score": 1},
                    }
                )
            ]
        )

    def query_audit_events(self, **kwargs):
        return SimpleNamespace(
            items=[
                _ObjectPayload(
                    {
                        "event_id": "audit_wf_1",
                        "event_type": "workflow_run.completed",
                        "entity_type": kwargs["entity_type"],
                        "entity_id": kwargs["entity_id"],
                    }
                )
            ]
        )


class ReportContextServiceTest(unittest.TestCase):
    def test_algorithm_run_context_is_collected_and_redacted(self) -> None:
        fake_service = _FakeResearchEngineService()
        service = ReportContextService(research_engine_service=fake_service, max_string_length=80)

        context = service.collect_context(
            subject_type="algorithm_run",
            subject_id="ar_test_001",
            actor_user_id="tester",
            is_admin=True,
        )

        self.assertEqual(fake_service.algorithm_called_with, ("ar_test_001", "tester", True))
        self.assertEqual(context["subject"]["subject_type"], "algorithm_run")
        self.assertEqual(context["subject"]["subject_id"], "ar_test_001")
        self.assertEqual(context["algorithm_run"]["input_snapshot"]["api_key"], "[REDACTED]")
        self.assertEqual(context["linked_computation"]["output_summary"]["secret_token"], "[REDACTED]")
        self.assertEqual(context["audit_events"][0]["after"]["password"], "[REDACTED]")
        self.assertEqual(context["algorithm_run"]["input_snapshot"]["input_path"], "[REDACTED_PATH]")
        self.assertEqual(context["algorithm_run"]["artifact_refs"][0]["path"], "[REDACTED_PATH]")

    def test_research_run_context_is_collected_and_long_fields_are_truncated(self) -> None:
        fake_service = _FakeResearchEngineService()
        service = ReportContextService(research_engine_service=fake_service, max_string_length=40)

        context = service.collect_context(subject_type="research_run", subject_id="rr_test_001")

        self.assertEqual(fake_service.research_called_with, ("rr_test_001", None, False))
        self.assertEqual(context["subject"]["subject_type"], "research_run")
        self.assertEqual(context["research_run"]["run_id"], "rr_test_001")
        self.assertEqual(context["linked_algorithm_runs"][0]["input_snapshot"]["token"], "[REDACTED]")
        self.assertEqual(context["linked_observations"][0]["source_path"], "[REDACTED_PATH]")
        long_text = context["research_run"]["stage_runs"][0]["output_summary"]["long_text"]
        self.assertLessEqual(len(long_text), 80)
        self.assertTrue(context["truncation_notes"])

    def test_unknown_subject_type_rejected(self) -> None:
        service = ReportContextService(research_engine_service=_FakeResearchEngineService())

        with self.assertRaises(ValueError):
            service.collect_context(subject_type="unknown", subject_id="x")

    def test_workflow_run_context_is_collected(self) -> None:
        service = ReportContextService(research_engine_service=_FakeResearchEngineService())

        context = service.collect_context(subject_type="workflow_run", subject_id="wfr_test_001")

        self.assertEqual(context["subject"]["subject_type"], "workflow_run")
        self.assertEqual(context["workflow_run"]["workflow_run_id"], "wfr_test_001")
        self.assertEqual(context["linked_algorithm_runs"][0]["run_id"], "ar_wf_1")
        self.assertEqual(context["workflow_run"]["artifact_refs"][0]["storage_uri"], "[REDACTED_PATH]")

    def test_computation_run_context_is_collected(self) -> None:
        fake_service = SimpleNamespace(
            get_run=lambda run_id, **kwargs: _ObjectPayload(
                {
                    "run_id": run_id,
                    "status": "completed",
                    "result_summary": {"energy": -1.23},
                    "created_by": "tester",
                }
            ),
            list_artifacts=lambda run_id, **kwargs: [
                _ObjectPayload(
                    {
                        "artifact_id": "cart_1",
                        "run_id": run_id,
                        "storage_uri": "/tmp/private/result.xyz",
                    }
                )
            ],
            list_audit_events=lambda **kwargs: SimpleNamespace(
                items=[
                    _ObjectPayload(
                        {
                            "event_id": "audit_comp_1",
                            "event_type": "computation.completed",
                            "entity_type": kwargs["entity_type"],
                            "entity_id": kwargs["entity_id"],
                        }
                    )
                ]
            ),
        )
        service = ReportContextService(research_engine_service=_FakeResearchEngineService())

        with patch("app.services.computation_service.ComputationService", return_value=fake_service):
            context = service.collect_context(subject_type="computation_run", subject_id="comp_test_001")

        self.assertEqual(context["subject"]["subject_type"], "computation_run")
        self.assertEqual(context["computation_run"]["run_id"], "comp_test_001")
        self.assertEqual(context["artifacts"][0]["storage_uri"], "[REDACTED_PATH]")
