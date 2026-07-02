"""Optimization service unit coverage."""

from __future__ import annotations

from app.infra.computation_repositories import AuditEventRepository
from app.schemas.optimization import CampaignCreateRequest
from app.schemas.optimization import CandidateImportRequest
from app.schemas.optimization import ObservationCreateRequest
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

    def test_create_observation_from_completed_computation(self) -> None:
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

        data = self.service.create_observation_from_computation(
            submitted.run_id,
            actor_user_id="tester",
            request_id="req-observation",
        )

        self.assertIn("gain_factor", data.observation.values)
        self.assertEqual(data.observation.source_run_id, submitted.run_id)

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
        self.assertEqual(len(detail.observations), 1)
        self.assertEqual(detail.observations[0].source_run_id, submitted.run_id)
        self.assertEqual(len(detail.suggestions), 2)
        self.assertIn("automation.observation_created", event_types)
        self.assertIn("automation.suggestion_triggered", event_types)
