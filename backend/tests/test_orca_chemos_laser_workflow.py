"""ORCA/ChemOS laser workflow coverage."""

from __future__ import annotations

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.computation import ComputationCreateRequest
from app.services.computation_service import ComputationService
from app.services.optimization_service import OptimizationService
from app.schemas.optimization import CampaignCreateRequest
from app.schemas.optimization import CandidateImportRequest
from app.schemas.optimization import SuggestionCreateRequest
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class OrcaChemosLaserWorkflowTest(ComputationTestCase):
    """Validate controlled workflow behavior and parser artifacts."""

    def setUp(self) -> None:
        super().setUp()
        self.original_orca_mode = settings.orca_chemos_execution_mode
        self.original_orca_license = settings.orca_license_available
        self.original_hpc_queue = settings.hpc_queue_available
        self.original_hpc_queue_name = settings.hpc_queue_name
        self.original_external_executor = getattr(settings, "orca_chemos_external_executor", "fake")
        self.original_fake_outcome = getattr(settings, "orca_chemos_fake_external_outcome", "success")
        self.service = ComputationService()

    def tearDown(self) -> None:
        settings.orca_chemos_execution_mode = self.original_orca_mode
        settings.orca_license_available = self.original_orca_license
        settings.hpc_queue_available = self.original_hpc_queue
        settings.hpc_queue_name = self.original_hpc_queue_name
        settings.orca_chemos_external_executor = self.original_external_executor
        settings.orca_chemos_fake_external_outcome = self.original_fake_outcome
        super().tearDown()

    def test_orca_chemos_request_rejects_shell_command_and_local_path_parameters(self) -> None:
        with self.assertRaises(ValidationError):
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "/tmp/run_orca.sh"},
            )

        with self.assertRaises(ValidationError):
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP", "shell_command": "orca input.inp"},
            )

    def test_orca_chemos_fixture_generates_parser_artifacts_and_summary(self) -> None:
        settings.orca_chemos_execution_mode = "fixture"
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCOC1=CC=CC=C1", "name": "laser-test"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP", "solvent": "TOLUENE"},
            ),
            actor_user_id="tester",
            request_id="req-orca-fixture",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        spectrum_artifact = next(item for item in artifacts if item.artifact_type == "spectrum_json")

        self.assertEqual(result.status, "completed")
        self.assertEqual(
            [step.step_key for step in detail.steps],
            [
                "CHEMOS_PREPARE_STRUCTURE",
                "CHEMOS_XTB_CREST",
                "CHEMOS_ORCA",
                "CHEMOS_SPECTRA_PARSE",
                "CHEMOS_GAIN_PARSE",
            ],
        )
        self.assertEqual(detail.result_summary["schema_version"], "chemos_laser_result.v1")
        self.assertIn("gain_factor", detail.result_summary["laser_metrics"])
        self.assertEqual(spectrum_artifact.parser_version, "1.0.0")
        self.assertEqual(spectrum_artifact.metadata["output_schema"], "chemos_spectrum.v1")
        self.assertIn("input_checksums", spectrum_artifact.metadata)

        spectrum = self.service.get_artifact_spectrum(spectrum_artifact.artifact_id)
        self.assertEqual(spectrum.spectrum["schema_version"], "chemos_spectrum.v1")
        self.assertGreater(len(spectrum.spectrum["spectrum"]["points"]), 3)

    def test_orca_chemos_unconfigured_failure_is_explicit(self) -> None:
        settings.orca_chemos_execution_mode = "disabled"
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
            ),
            actor_user_id="tester",
            request_id="req-orca-disabled",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "ORCA_WORKFLOW_NOT_CONFIGURED")
        self.assertIn("ORCA/ChemOS workflow 未配置", detail.error["message"])
        self.assertEqual(detail.steps[0].status, "failed")

    def test_orca_chemos_gain_factor_maps_to_observation(self) -> None:
        settings.orca_chemos_execution_mode = "fixture"
        optimization = OptimizationService()
        campaign = optimization.create_campaign(
            CampaignCreateRequest(name="orca-campaign", objectives=[{"name": "gain_factor", "direction": "max"}]),
            actor_user_id="tester",
            request_id="req-campaign",
        )
        optimization.import_candidates(
            campaign.campaign_id,
            CandidateImportRequest(candidates=[{"candidate_key": "CAND-ORCA", "smiles": "CCO"}]),
            actor_user_id="tester",
            request_id="req-import",
        )
        suggestion = optimization.generate_suggestions(
            campaign.campaign_id,
            SuggestionCreateRequest(batch_size=1),
            actor_user_id="tester",
            request_id="req-suggestion",
        ).items[0]
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": suggestion.smiles, "name": suggestion.candidate_key},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
                campaign_id=campaign.campaign_id,
                suggestion_id=suggestion.suggestion_id,
            ),
            actor_user_id="tester",
            request_id="req-orca-submit",
        )
        ComputationWorker(worker_id="worker-test").acquire_and_run_one()

        observation = optimization.create_observation_from_computation(
            created.run_id,
            actor_user_id="tester",
            request_id="req-observation",
        ).observation

        self.assertIn("gain_factor", observation.values)
        self.assertEqual(observation.source_run_id, created.run_id)

    def test_orca_chemos_external_fake_executor_success_records_refs_and_parser_outputs(self) -> None:
        settings.orca_chemos_execution_mode = "external"
        settings.orca_license_available = True
        settings.hpc_queue_available = True
        settings.hpc_queue_name = "gpu-debug"
        settings.orca_chemos_external_executor = "fake"
        settings.orca_chemos_fake_external_outcome = "success"
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCOC1=CC=CC=C1", "name": "external-success"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP", "solvent": "TOLUENE"},
            ),
            actor_user_id="tester",
            request_id="req-orca-external-success",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        names = {artifact.name for artifact in artifacts}

        self.assertEqual(result.status, "completed")
        self.assertEqual(detail.external_refs["orca_chemos_job_id"], f"fake-orca-{created.run_id}")
        self.assertEqual(detail.external_refs["queue"], "gpu-debug")
        self.assertIsNotNone(detail.external_refs["submitted_at"])
        self.assertIsNotNone(detail.external_refs["polled_at"])
        self.assertEqual(detail.external_refs["executor"], "fake")
        self.assertIn("job_spec.json", names)
        self.assertIn("spectra.raw.csv", names)
        self.assertIn("gain.raw.json", names)
        self.assertEqual(detail.result_summary["schema_version"], "chemos_laser_result.v1")

    def test_orca_chemos_external_fake_executor_failure_keeps_error_artifact(self) -> None:
        settings.orca_chemos_execution_mode = "external"
        settings.orca_license_available = True
        settings.hpc_queue_available = True
        settings.orca_chemos_external_executor = "fake"
        settings.orca_chemos_fake_external_outcome = "failed"
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
            ),
            actor_user_id="tester",
            request_id="req-orca-external-fail",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)
        artifact_types = {artifact.artifact_type for artifact in self.service.list_artifacts(created.run_id)}

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "ORCA_EXTERNAL_JOB_FAILED")
        self.assertEqual(detail.external_refs["orca_chemos_job_id"], f"fake-orca-{created.run_id}")
        self.assertIn("error_json", artifact_types)

    def test_orca_chemos_external_fake_executor_timeout_is_retryable(self) -> None:
        settings.orca_chemos_execution_mode = "external"
        settings.orca_license_available = True
        settings.hpc_queue_available = True
        settings.orca_chemos_external_executor = "fake"
        settings.orca_chemos_fake_external_outcome = "timeout"
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
            ),
            actor_user_id="tester",
            request_id="req-orca-external-timeout",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "ORCA_EXTERNAL_JOB_TIMEOUT")
        self.assertTrue(detail.error["retryable"])

    def test_orca_chemos_external_missing_queue_keeps_failed_error_artifact(self) -> None:
        settings.orca_chemos_execution_mode = "external"
        settings.orca_license_available = True
        settings.hpc_queue_available = False
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
            ),
            actor_user_id="tester",
            request_id="req-orca-external-no-queue",
        )

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)
        artifact_types = {artifact.artifact_type for artifact in self.service.list_artifacts(created.run_id)}

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "HPC_QUEUE_UNAVAILABLE")
        self.assertIn("error_json", artifact_types)

    def test_orca_chemos_external_fake_executor_cancel_keeps_run_cancelled(self) -> None:
        settings.orca_chemos_execution_mode = "external"
        settings.orca_license_available = True
        settings.hpc_queue_available = True
        settings.orca_chemos_external_executor = "fake"
        settings.orca_chemos_fake_external_outcome = "success"
        created = self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
            ),
            actor_user_id="tester",
            request_id="req-orca-external-cancel",
        )
        original_poll = __import__(
            "app.computation_adapters.orca_chemos_laser",
            fromlist=["FakeOrcaChemosExternalExecutor"],
        ).FakeOrcaChemosExternalExecutor.poll

        def cancelling_poll(executor, job_id):
            self.service.cancel_run(
                created.run_id,
                actor_user_id="tester",
                request_id="req-orca-external-cancel",
            )
            return original_poll(executor, job_id)

        import app.computation_adapters.orca_chemos_laser as adapter_module

        adapter_module.FakeOrcaChemosExternalExecutor.poll = cancelling_poll
        try:
            result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        finally:
            adapter_module.FakeOrcaChemosExternalExecutor.poll = original_poll
        detail = self.service.get_run(created.run_id)

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(detail.status, "cancelled")
        self.assertEqual(detail.error["error_code"], "USER_CANCELLED")
        self.assertEqual(detail.external_refs["external_cancelled"], True)
