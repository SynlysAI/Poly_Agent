"""实验下发配置持久化、权限和试运行测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.infra.demo_store import demo_store  # noqa: E402
from app.infra.experiment_dispatch_profile_repositories import (  # noqa: E402
    ExperimentDispatchProfileRepository,
    ExperimentDispatchTargetRepository,
)
from app.infra.research_engine_repositories import (  # noqa: E402
    AlgorithmRegistryRepository,
    AlgorithmRunRepository,
)
from app.schemas.experiment_dispatch_profile import (  # noqa: E402
    DispatchMapping,
    DispatchSourceContract,
    DispatchSourceField,
    DispatchTargetDefinition,
    DispatchTargetField,
    DispatchValueSource,
    ExperimentDispatchProfileCreateRequest,
    ExperimentDispatchProfileEvaluationRequest,
    ExperimentDispatchProfileSaveRequest,
    ExperimentDispatchProfileUpdateRequest,
)
from app.services.experiment_dispatch_profile_service import (  # noqa: E402
    ExperimentDispatchProfileService,
)


class ExperimentDispatchProfileServiceTest(TestCase):
    def setUp(self) -> None:
        self.original_require_mongodb = settings.require_mongodb
        self.original_demo_store_path = demo_store.path
        settings.require_mongodb = False
        demo_store.path = Path(self.id().replace(".", "_") + ".json").resolve()
        self.mongo_unavailable = patch("app.infra.computation_repositories._mongo_unavailable", True)
        self.mongo_unavailable.start()
        self.service = ExperimentDispatchProfileService(seed_enabled=False)
        ExperimentDispatchTargetRepository.save(
            "target_key",
            {
                **DispatchTargetDefinition(
                    target_id="generic_json",
                    version="1.0.0",
                    name="Generic JSON",
                    fields=[DispatchTargetField(path="/result", value_type="number", required=True)],
                ).model_dump(mode="python"),
                "target_key": "generic_json@1.0.0",
            },
        )
        AlgorithmRegistryRepository.save(
            "algorithm_id",
            {
                "algorithm_id": "example_predictor",
                "name": "Example predictor",
                "type": "predictor",
                "algorithm_family": "vertical_prediction",
                "output_schema": {"fields": {"prediction": "number"}},
                "created_at": None,
            },
        )
        AlgorithmRunRepository.save(
            "run_id",
            {
                "run_id": "arun_profile_test",
                "algorithm_id": "example_predictor",
                "algorithm_version_id": "aiv_1",
                "trigger_source": "human_workflow",
                "status": "completed",
                "created_by": "owner-a",
                "input_snapshot": {},
                "output_summary": {"prediction": 42},
                "created_at": None,
                "finished_at": None,
            },
        )

    def tearDown(self) -> None:
        self.mongo_unavailable.stop()
        settings.require_mongodb = self.original_require_mongodb
        demo_store.path.unlink(missing_ok=True)
        demo_store.path = self.original_demo_store_path

    @staticmethod
    def create_payload() -> ExperimentDispatchProfileCreateRequest:
        return ExperimentDispatchProfileCreateRequest(
            profile_id="result_mapping",
            version="1.0.0",
            name="Result mapping",
            source_contract=DispatchSourceContract(
                example_algorithm_id="example_predictor",
                required_fields=[DispatchSourceField(path="/output/prediction", value_type="number")],
            ),
            target_id="generic_json",
            target_version="1.0.0",
            mappings=[
                DispatchMapping(
                    target_path="/result",
                    source=DispatchValueSource(kind="path", path="/output/prediction"),
                    required=True,
                )
            ],
        )

    def test_private_profile_visibility_and_admin_access(self) -> None:
        created = self.service.create(self.create_payload(), actor_user_id="owner-a")
        self.assertEqual(created.status, "draft")
        self.assertEqual(self.service.list(actor_user_id="owner-a", is_admin=False, page=1, page_size=20).total, 1)
        self.assertEqual(self.service.list(actor_user_id="owner-b", is_admin=False, page=1, page_size=20).total, 0)
        self.assertEqual(self.service.list(actor_user_id="owner-b", is_admin=True, page=1, page_size=20).total, 1)

    def test_published_profile_is_immutable_and_can_be_cloned(self) -> None:
        self.service.create(self.create_payload(), actor_user_id="owner-a")
        published = self.service.publish("result_mapping", "1.0.0", actor_user_id="owner-a")
        self.assertEqual(published.status, "published")
        with self.assertRaises(HTTPException) as ctx:
            self.service.update(
                "result_mapping",
                "1.0.0",
                ExperimentDispatchProfileUpdateRequest(**self.create_payload().model_dump(exclude={"profile_id", "version", "visibility"})),
                actor_user_id="owner-a",
            )
        self.assertEqual(ctx.exception.status_code, 409)
        clone = self.service.clone_version("result_mapping", "1.0.0", "1.1.0", actor_user_id="owner-a")
        self.assertEqual(clone.status, "draft")
        self.assertEqual(clone.version, "1.1.0")

    def test_evaluate_returns_payload_and_stable_digest(self) -> None:
        self.service.create(self.create_payload(), actor_user_id="owner-a")
        self.service.publish("result_mapping", "1.0.0", actor_user_id="owner-a")
        request = ExperimentDispatchProfileEvaluationRequest(
            run_id="arun_profile_test",
            profile_id="result_mapping",
            profile_version="1.0.0",
        )
        first = self.service.evaluate(request, actor_user_id="owner-a", is_admin=False)
        second = self.service.evaluate(request, actor_user_id="owner-a", is_admin=False)
        self.assertTrue(first.result.is_valid)
        self.assertEqual(first.result.payload, {"result": 42})
        self.assertEqual(first.preview_digest, second.preview_digest)

    def test_candidates_filter_algorithm_metadata(self) -> None:
        data = self.service.list_candidates(
            actor_user_id="owner-a",
            is_admin=False,
            trigger_source="human_workflow",
            algorithm_type="predictor",
            algorithm_family="vertical_prediction",
            algorithm_id="example_predictor",
            profile_id=None,
            keyword="profile",
            page=1,
            page_size=20,
        )
        self.assertEqual(data.total, 1)
        self.assertEqual(data.items[0].algorithm_name, "Example predictor")

    def test_save_requires_current_valid_preview_digest(self) -> None:
        self.service.create(self.create_payload(), actor_user_id="owner-a")
        self.service.publish("result_mapping", "1.0.0", actor_user_id="owner-a")
        evaluation_request = ExperimentDispatchProfileEvaluationRequest(
            run_id="arun_profile_test",
            profile_id="result_mapping",
            profile_version="1.0.0",
        )
        evaluation = self.service.evaluate(evaluation_request, actor_user_id="owner-a", is_admin=False)
        with self.assertRaises(HTTPException) as ctx:
            self.service.save_dispatch(
                ExperimentDispatchProfileSaveRequest(
                    **evaluation_request.model_dump(),
                    preview_digest="0" * 64,
                ),
                actor_user_id="owner-a",
                is_admin=False,
            )
        self.assertEqual(ctx.exception.status_code, 409)

        saved = self.service.save_dispatch(
            ExperimentDispatchProfileSaveRequest(
                **evaluation_request.model_dump(),
                preview_digest=evaluation.preview_digest,
            ),
            actor_user_id="owner-a",
            is_admin=False,
        )
        self.assertEqual(saved.status, "prepared")
        self.assertEqual(saved.payload, {"result": 42})


if __name__ == "__main__":
    import unittest

    unittest.main()
