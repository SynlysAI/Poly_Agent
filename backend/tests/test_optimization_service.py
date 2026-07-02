"""Optimization service unit coverage."""

from __future__ import annotations

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
