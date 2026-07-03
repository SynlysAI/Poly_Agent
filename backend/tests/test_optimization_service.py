"""Optimization service unit coverage."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.infra.computation_repositories import AuditEventRepository
from app.schemas.optimization import CampaignCreateRequest
from app.schemas.optimization import CampaignStatusChangeRequest
from app.schemas.optimization import CandidateImportRequest
from app.schemas.optimization import CandidateImportCsvRequest
from app.schemas.optimization import ObservationCreateRequest
from app.schemas.optimization import SuggestionFailureRequest
from app.schemas.optimization import SuggestionRejectRequest
from app.schemas.optimization import SuggestionCreateRequest
from app.services.optimization_service import OptimizationService
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class OptimizationServiceTest(ComputationTestCase):
    """Cover import/generate/submit/observation service behavior."""

    def setUp(self) -> None:
        super().setUp()
        self.service = OptimizationService()

    def _create_campaign_with_candidate(self) -> tuple[str, str]:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(name="svc-campaign", objectives=[{"name": "gain_factor", "direction": "max"}]),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        imported = self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(candidates=[{"candidate_key": "CAND-001", "smiles": "CCO"}]),
            actor_user_id="tester",
            request_id="req-import",
        )
        return campaign.campaign_id, imported.items[0].candidate_id

    def test_import_candidates_updates_campaign_search_space(self) -> None:
        campaign_id, candidate_id = self._create_campaign_with_candidate()
        detail = self.service.get_detail(campaign_id)

        self.assertEqual(detail.campaign.search_space["candidate_count"], 1)
        self.assertEqual(detail.candidates[0].candidate_id, candidate_id)

    def test_campaign_access_is_scoped_to_owner(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(name="owned-campaign", objectives=[{"name": "gain_factor", "direction": "max"}]),
            actor_user_id="user-a",
            request_id="req-campaign",
        )

        visible = self.service.list_campaigns(page=1, page_size=20, actor_user_id="user-a", is_admin=False)
        hidden = self.service.list_campaigns(page=1, page_size=20, actor_user_id="user-b", is_admin=False)
        admin = self.service.list_campaigns(page=1, page_size=20, actor_user_id="admin", is_admin=True)

        self.assertEqual(visible.total, 1)
        self.assertEqual(hidden.total, 0)
        self.assertEqual(admin.total, 1)
        with self.assertRaises(HTTPException) as caught:
            self.service.get_detail(campaign.campaign_id, actor_user_id="user-b", is_admin=False)
        self.assertEqual(caught.exception.status_code, 403)

    def test_import_candidates_reports_duplicates_and_updates(self) -> None:
        campaign_id, _ = self._create_campaign_with_candidate()

        report = self.service.import_candidates(
            campaign_id,
            CandidateImportRequest(
                candidates=[
                    {"candidate_key": "CAND-001", "smiles": "CCN"},
                    {"candidate_key": "CAND-002", "smiles": "CCC"},
                    {"candidate_key": "CAND-002", "smiles": "CCCC"},
                ]
            ),
            actor_user_id="tester",
            request_id="req-import-report",
        )
        detail = self.service.get_detail(campaign_id)

        self.assertEqual(report.imported_count, 1)
        self.assertEqual(report.updated_count, 1)
        self.assertEqual(len(report.duplicate_rows), 1)
        self.assertEqual(report.failed_rows, [])
        self.assertEqual(detail.campaign.search_space["candidate_count"], 2)

    def test_import_candidates_from_csv_keeps_row_failures_in_report(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(name="csv-campaign", objectives=[{"name": "gain_factor", "direction": "max"}]),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        csv_text = "candidate_key,smiles\nCAND-001,CCO\nEMPTY,\nCAND-001,CCC\nCAND-002,CCN\n"

        report = self.service.import_candidates_csv(
            campaign.campaign_id,
            CandidateImportCsvRequest(csv_text=csv_text),
            actor_user_id="tester",
            request_id="req-csv",
        )

        self.assertEqual(report.imported_count, 2)
        self.assertEqual(report.updated_count, 0)
        self.assertEqual(len(report.failed_rows), 1)
        self.assertEqual(len(report.duplicate_rows), 1)
        self.assertEqual(len(report.items), 2)

    def test_import_candidates_from_unparseable_csv_returns_400(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(name="bad-csv-campaign", objectives=[{"name": "gain_factor", "direction": "max"}]),
            actor_user_id="tester",
            request_id="req-campaign",
        )

        with self.assertRaises(HTTPException) as caught:
            self.service.import_candidates_csv(
                campaign.campaign_id,
                CandidateImportCsvRequest(csv_text="candidate_key\nCAND-001\n"),
                actor_user_id="tester",
                request_id="req-csv-bad",
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_generate_suggestions_uses_first_unevaluated_candidate(self) -> None:
        campaign_id, candidate_id = self._create_campaign_with_candidate()

        suggestion = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        self.assertEqual(suggestion.candidate_id, candidate_id)
        self.assertEqual(suggestion.status, "suggested")
        self.assertEqual(suggestion.planner_payload["request"]["campaign_id"], campaign_id)
        self.assertIn("candidates", suggestion.planner_payload["request"])
        self.assertIn("observations", suggestion.planner_payload["request"])
        self.assertIn("objectives", suggestion.planner_payload["request"])
        self.assertIn("constraints", suggestion.planner_payload["request"])
        self.assertIn("suggestions", suggestion.planner_payload["response"])
        self.assertIn("iteration_metadata", suggestion.planner_payload["response"])
        self.assertEqual(suggestion.planner_payload["snapshot_schema_version"], "suggestion_planner_snapshot.v1")
        self.assertEqual(suggestion.planner_payload["request_schema_version"], "planner_request.v1")
        self.assertEqual(suggestion.planner_payload["response_schema_version"], "planner_response.v1")

    def test_campaign_lifecycle_blocks_new_suggestion_and_computation(self) -> None:
        campaign_id, _ = self._create_campaign_with_candidate()
        suggestion = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        paused = self.service.change_campaign_status(
            campaign_id,
            "paused",
            CampaignStatusChangeRequest(reason="operator pause"),
            actor_user_id="tester",
            request_id="req-pause",
        )
        self.assertEqual(paused.status, "paused")

        with self.assertRaises(HTTPException) as generate_caught:
            self.service.generate_suggestions(
                campaign_id,
                SuggestionCreateRequest(batch_size=1),
                actor_user_id="tester",
                request_id="req-suggestion-paused",
            )
        self.assertEqual(generate_caught.exception.status_code, 400)

        with self.assertRaises(HTTPException) as submit_caught:
            self.service.submit_suggestion_computation(
                suggestion.suggestion_id,
                actor_user_id="tester",
                request_id="req-submit-paused",
            )
        self.assertEqual(submit_caught.exception.status_code, 400)

        resumed = self.service.change_campaign_status(
            campaign_id,
            "running",
            CampaignStatusChangeRequest(reason="resume loop"),
            actor_user_id="tester",
            request_id="req-resume",
        )
        self.assertEqual(resumed.status, "running")
        submitted = self.service.submit_suggestion_computation(
            suggestion.suggestion_id,
            actor_user_id="tester",
            request_id="req-submit",
        )
        self.assertEqual(submitted.suggestion_status, "submitted")

        completed = self.service.change_campaign_status(
            campaign_id,
            "completed",
            CampaignStatusChangeRequest(reason="done"),
            actor_user_id="tester",
            request_id="req-complete",
        )
        self.assertEqual(completed.status, "completed")
        history_types = [item.event_type for item in self.service.get_history(campaign_id).items]
        self.assertIn("campaign.status_changed", history_types)

        with self.assertRaises(HTTPException):
            self.service.generate_suggestions(
                campaign_id,
                SuggestionCreateRequest(batch_size=1),
                actor_user_id="tester",
                request_id="req-suggestion-completed",
            )

    def test_archived_campaign_cannot_resume_or_import(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(name="archive-campaign", objectives=[{"name": "gain_factor", "direction": "max"}]),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        archived = self.service.change_campaign_status(
            campaign.campaign_id,
            "archived",
            CampaignStatusChangeRequest(reason="not needed"),
            actor_user_id="tester",
            request_id="req-archive",
        )
        self.assertEqual(archived.status, "archived")

        with self.assertRaises(HTTPException) as resume_caught:
            self.service.change_campaign_status(
                campaign.campaign_id,
                "running",
                CampaignStatusChangeRequest(reason="resume"),
                actor_user_id="tester",
                request_id="req-resume",
            )
        self.assertEqual(resume_caught.exception.status_code, 400)

        with self.assertRaises(HTTPException) as import_caught:
            self.service.import_candidates(
                campaign.campaign_id,
                CandidateImportRequest(candidates=[{"candidate_key": "CAND-001", "smiles": "CCO"}]),
                actor_user_id="tester",
                request_id="req-import",
            )
        self.assertEqual(import_caught.exception.status_code, 400)

    def test_submit_suggestion_creates_linked_computation(self) -> None:
        campaign_id, _ = self._create_campaign_with_candidate()
        suggestion = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        submitted = self.service.submit_suggestion_computation(
            suggestion.suggestion_id,
            actor_user_id="tester",
            request_id="req-submit",
        )
        detail = self.service.computation_service.get_run(submitted.run_id)

        self.assertEqual(submitted.suggestion_status, "submitted")
        self.assertEqual(detail.campaign_id, campaign_id)
        self.assertEqual(detail.suggestion_id, suggestion.suggestion_id)
        self.assertEqual(detail.workflow_type, "LOCAL_XTB")
        self.assertEqual(detail.engine, "XTB")

    def test_submit_suggestion_uses_orca_campaign_preset(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(
                name="orca-preset",
                objectives=[{"name": "gain_factor", "direction": "max"}],
                planner_config={
                    "batch_size": 1,
                    "computation_preset": {
                        "preset_key": "orca",
                        "resources": {"num_cores": 6, "memory_mb": 8192, "max_wallclock_seconds": 3600},
                    },
                },
            ),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(candidates=[{"candidate_key": "CAND-ORCA", "smiles": "CCO"}]),
            actor_user_id="tester",
            request_id="req-import",
        )
        suggestion = self.service.generate_suggestions(
            campaign.campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        submitted = self.service.submit_suggestion_computation(
            suggestion.suggestion_id,
            actor_user_id="tester",
            request_id="req-submit",
        )
        detail = self.service.computation_service.get_run(submitted.run_id)

        self.assertEqual(detail.workflow_type, "ORCA_CHEMOS_LASER")
        self.assertEqual(detail.engine, "ORCA")
        self.assertEqual(detail.source, "optimization_suggestion:orca")
        self.assertEqual(detail.resources.num_cores, 6)
        self.assertEqual(detail.resources.memory_mb, 8192)

    def test_create_campaign_rejects_unknown_computation_preset(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.service.create_campaign(
                CampaignCreateRequest(
                    name="bad-preset",
                    objectives=[{"name": "gain_factor", "direction": "max"}],
                    planner_config={"batch_size": 1, "computation_preset": "shell:orca input.inp"},
                ),
                actor_user_id="tester",
                request_id="req-bad-preset",
            )
        self.assertEqual(caught.exception.status_code, 400)

        with self.assertRaises(HTTPException) as shell_caught:
            self.service.create_campaign(
                CampaignCreateRequest(
                    name="bad-preset-command",
                    objectives=[{"name": "gain_factor", "direction": "max"}],
                    planner_config={
                        "batch_size": 1,
                        "computation_preset": {
                            "preset_key": "orca",
                            "shell_command": "orca input.inp",
                        },
                    },
                ),
                actor_user_id="tester",
                request_id="req-bad-preset-command",
            )
        self.assertEqual(shell_caught.exception.status_code, 400)

    def test_create_campaign_rejects_invalid_planner_constraints(self) -> None:
        invalid_configs = [
            {"constraints": {"minimum_similarity": 2.0}},
            {"constraints": {"unknown": True}},
        ]
        for planner_config in invalid_configs:
            with self.assertRaises(HTTPException) as caught:
                self.service.create_campaign(
                    CampaignCreateRequest(
                        name="bad-constraints",
                        objectives=[{"name": "gain_factor", "direction": "max"}],
                        planner_config=planner_config,
                    ),
                    actor_user_id="tester",
                    request_id="req-bad-constraints",
                )
            self.assertEqual(caught.exception.status_code, 400)

    def test_submit_suggestion_rejects_unsafe_preset_method_override(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(
                name="bad-method-preset",
                objectives=[{"name": "gain_factor", "direction": "max"}],
                planner_config={
                    "batch_size": 1,
                    "computation_preset": {"preset_key": "orca", "method": "/tmp/run_orca.sh"},
                },
            ),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(candidates=[{"candidate_key": "CAND-ORCA", "smiles": "CCO"}]),
            actor_user_id="tester",
            request_id="req-import",
        )
        suggestion = self.service.generate_suggestions(
            campaign.campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        with self.assertRaises(HTTPException) as caught:
            self.service.submit_suggestion_computation(
                suggestion.suggestion_id,
                actor_user_id="tester",
                request_id="req-submit",
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_reject_and_failed_suggestions_cannot_be_submitted(self) -> None:
        campaign_id, _ = self._create_campaign_with_candidate()
        suggestion = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        rejected = self.service.reject_suggestion(
            suggestion.suggestion_id,
            SuggestionRejectRequest(reason="low confidence"),
            actor_user_id="tester",
            request_id="req-reject",
        )
        history = self.service.get_history(campaign_id).items

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.planner_payload["rejection"]["reason"], "low confidence")
        self.assertIn("suggestion.rejected", [item.event_type for item in history])
        with self.assertRaises(HTTPException) as rejected_submit:
            self.service.submit_suggestion_computation(
                suggestion.suggestion_id,
                actor_user_id="tester",
                request_id="req-submit",
            )
        self.assertEqual(rejected_submit.exception.status_code, 400)

        second = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion-2",
        ).items[0]
        failed = self.service.mark_suggestion_failed(
            second.suggestion_id,
            SuggestionFailureRequest(reason="worker failed", run_id="run_failed_1", error_code="XTB_FAILED"),
            actor_user_id="tester",
            request_id="req-failed",
        )
        self.assertEqual(failed.status, "failed")
        with self.assertRaises(HTTPException):
            self.service.submit_suggestion_computation(
                second.suggestion_id,
                actor_user_id="tester",
                request_id="req-submit-2",
            )

    def test_create_manual_observation_marks_suggestion_evaluated(self) -> None:
        campaign_id, candidate_id = self._create_campaign_with_candidate()
        suggestion = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        observation = self.service.create_observation(
            campaign_id,
            ObservationCreateRequest(
                candidate_id=candidate_id,
                suggestion_id=suggestion.suggestion_id,
                source_type="manual",
                values={"gain_factor": 1.2},
            ),
            actor_user_id="tester",
            request_id="req-observation",
        )
        detail = self.service.get_detail(campaign_id)

        self.assertEqual(observation.values["gain_factor"], 1.2)
        self.assertEqual(detail.suggestions[0].status, "evaluated")

    def test_create_observation_validates_objective_schema(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(
                name="schema-campaign",
                objectives=[
                    {"name": "gain_factor", "direction": "max", "required": True},
                    {"name": "lifetime", "direction": "max", "required": False},
                ],
            ),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        imported = self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(candidates=[{"candidate_key": "CAND-001", "smiles": "CCO"}]),
            actor_user_id="tester",
            request_id="req-import",
        )
        candidate_id = imported.items[0].candidate_id

        optional_missing = self.service.create_observation(
            campaign.campaign_id,
            ObservationCreateRequest(candidate_id=candidate_id, values={"gain_factor": 1.0}),
            actor_user_id="tester",
            request_id="req-ok",
        )
        self.assertEqual(optional_missing.values["gain_factor"], 1.0)

        cases = [
            ObservationCreateRequest(candidate_id=candidate_id, values={"unknown": 1.0, "gain_factor": 1.0}),
            ObservationCreateRequest(candidate_id=candidate_id, values={"lifetime": 1.0}),
            ObservationCreateRequest(candidate_id=candidate_id, values={"gain_factor": float("nan")}),
            ObservationCreateRequest(candidate_id=candidate_id, values={"gain_factor": float("inf")}),
        ]
        for payload in cases:
            with self.assertRaises(HTTPException) as caught:
                self.service.create_observation(
                    campaign.campaign_id,
                    payload,
                    actor_user_id="tester",
                    request_id="req-invalid",
                )
            self.assertEqual(caught.exception.status_code, 400)

    def test_create_observation_from_non_laser_computation_is_rejected(self) -> None:
        campaign_id, _ = self._create_campaign_with_candidate()
        suggestion = self.service.generate_suggestions(
            campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]
        submitted = self.service.submit_suggestion_computation(
            suggestion.suggestion_id,
            actor_user_id="tester",
            request_id="req-submit",
        )
        ComputationWorker(worker_id="worker-test").acquire_and_run_one()

        with self.assertRaises(HTTPException) as caught:
            self.service.create_observation_from_computation(
                submitted.run_id,
                actor_user_id="tester",
                request_id="req-observation",
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_import_candidates_records_descriptor_schema_metadata(self) -> None:
        campaign_id, _ = self._create_campaign_with_candidate()
        detail = self.service.get_detail(campaign_id)
        descriptors = detail.candidates[0].descriptors

        self.assertEqual(descriptors["schema_version"], "candidate_descriptor.v1")
        self.assertIn(descriptors["status"], {"available", "not_available", "failed"})
        self.assertIn("parameters", descriptors)
        self.assertIn("generated_at", descriptors)

    def test_tanimoto_planner_scores_candidates_from_best_observation(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(
                name="tanimoto-campaign",
                objectives=[{"name": "gain_factor", "direction": "max"}],
                planner_type="tanimoto",
            ),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        imported = self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(
                candidates=[
                    {"candidate_key": "BEST", "smiles": "CCO"},
                    {"candidate_key": "SIMILAR", "smiles": "CCCO"},
                    {"candidate_key": "OTHER", "smiles": "c1ccccc1"},
                ]
            ),
            actor_user_id="tester",
            request_id="req-import",
        )
        best_candidate_id = imported.items[0].candidate_id
        self.service.create_observation(
            campaign.campaign_id,
            ObservationCreateRequest(
                candidate_id=best_candidate_id,
                source_type="manual",
                values={"gain_factor": 2.0},
            ),
            actor_user_id="tester",
            request_id="req-observation",
        )

        suggestion = self.service.generate_suggestions(
            campaign.campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        self.assertEqual(suggestion.planner_type, "tanimoto")
        self.assertEqual(suggestion.candidate_key, "SIMILAR")
        response_suggestion = suggestion.planner_payload["response"]["suggestions"][0]
        self.assertGreater(response_suggestion["score"], 0)
        self.assertIn("Tanimoto", response_suggestion["reason"])

    def test_tanimoto_planner_marks_low_confidence_and_snapshots_skips(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(
                name="low-confidence-campaign",
                objectives=[{"name": "gain_factor", "direction": "max"}],
                planner_type="tanimoto",
                planner_config={
                    "constraints": {
                        "minimum_similarity": 0.99,
                        "max_low_confidence_suggestions": 1,
                    }
                },
            ),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        imported = self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(
                candidates=[
                    {"candidate_key": "BEST", "smiles": "CCO"},
                    {"candidate_key": "LOW", "smiles": "c1ccccc1"},
                ]
            ),
            actor_user_id="tester",
            request_id="req-import",
        )
        self.service.create_observation(
            campaign.campaign_id,
            ObservationCreateRequest(
                candidate_id=imported.items[0].candidate_id,
                source_type="manual",
                values={"gain_factor": 3.0},
            ),
            actor_user_id="tester",
            request_id="req-observation",
        )

        suggestion = self.service.generate_suggestions(
            campaign.campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]

        response_item = suggestion.planner_payload["response"]["suggestions"][0]
        self.assertEqual(response_item["confidence"], "low")
        self.assertIn("below minimum", response_item["reason"])
        self.assertIn("skipped", suggestion.planner_payload["response"])

    def test_worker_auto_creates_observation_and_next_suggestion_when_enabled(self) -> None:
        campaign = self.service.create_campaign(
            CampaignCreateRequest(
                name="auto-campaign",
                objectives=[{"name": "gain_factor", "direction": "max"}],
                planner_config={
                    "batch_size": 1,
                    "automation": {
                        "auto_create_observation": True,
                        "auto_generate_suggestion": True,
                        "suggestion_batch_size": 1,
                        "observation_mapping": {"gain_factor": "laser_metrics.gain_factor"},
                    },
                },
            ),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        self.service.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(
                candidates=[
                    {"candidate_key": "CAND-001", "smiles": "CCO"},
                    {"candidate_key": "CAND-002", "smiles": "CCCO"},
                ]
            ),
            actor_user_id="tester",
            request_id="req-import",
        )
        first = self.service.generate_suggestions(
            campaign.campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]
        submitted = self.service.submit_suggestion_computation(
            first.suggestion_id,
            actor_user_id="tester",
            request_id="req-submit",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_detail(campaign.campaign_id)
        events, _ = AuditEventRepository.list_events(
            entity_type=None,
            entity_id=None,
            event_type=None,
            page=1,
            page_size=100,
        )
        event_types = {item["event_type"] for item in events}

        self.assertEqual(result.run_id, submitted.run_id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(len(detail.observations), 0)
        self.assertEqual(len(detail.suggestions), 1)
        self.assertNotIn("automation.observation_created", event_types)
        self.assertNotIn("automation.suggestion_triggered", event_types)
