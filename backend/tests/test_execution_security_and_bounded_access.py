"""ALS P1 统一安全层与受限执行回归测试。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.computation_adapters.base import (  # noqa: E402
    AdapterContext,
    validate_adapter_access,
)
from app.core.config import settings  # noqa: E402
from app.infra.demo_store import demo_store  # noqa: E402
from app.infra.experiment_dispatch_profile_repositories import (  # noqa: E402
    ExperimentDispatchProfileRepository,
    ExperimentDispatchTargetRepository,
)
from app.infra.research_engine_repositories import AlgorithmRunRepository  # noqa: E402
from app.schemas.computation import ComputationRun  # noqa: E402
from app.schemas.execution_security import (  # noqa: E402
    ExecutionAccessError,
    validate_execution_access,
)
from app.schemas.experiment_dispatch_profile import (  # noqa: E402
    BoundaryLimit,
    DispatchMapping,
    DispatchTargetDefinition,
    DispatchTargetField,
    FieldSecurityPolicy,
    TargetSecurityPolicy,
    DispatchValueSource,
    ExperimentDispatchProfile,
    ExperimentDispatchProfileEvaluationRequest,
    ExperimentDispatchProfileSaveRequest,
)
from app.services.computation_service import ComputationService  # noqa: E402
from app.services.experiment_dispatch_profile_engine import (  # noqa: E402
    ExperimentDispatchProfileEngine,
)
from app.services.experiment_dispatch_profile_service import (  # noqa: E402
    ExperimentDispatchProfileService,
)


def _run() -> ComputationRun:
    """构造不落库的最小计算运行上下文。"""
    now = datetime(2026, 8, 27, 12, 0, 0)
    return ComputationRun(
        run_id="compute-access-test",
        workflow_type="LOCAL_XTB",
        engine="XTB",
        status="running",
        molecule={"smiles": "CCO"},
        parameters={},
        resources={},
        created_by="tester",
        created_at=now,
        updated_at=now,
    )


def _target(policy: TargetSecurityPolicy | None = None) -> DispatchTargetDefinition:
    """构造带可选安全策略的通用 JSON target。"""
    return DispatchTargetDefinition(
        target_id="generic_json",
        version="1.0.0",
        name="Generic JSON",
        fields=[
            DispatchTargetField(path="/temperature", value_type="number", required=True),
            DispatchTargetField(path="/mode", value_type="string", required=True),
            DispatchTargetField(path="/debug_token", value_type="string", required=False),
        ],
        security_policy=policy,
    )


def _profile() -> ExperimentDispatchProfile:
    """构造覆盖安全策略字段的声明式下发 profile。"""
    return ExperimentDispatchProfile(
        profile_id="security_test",
        version="1.0.0",
        name="Security test",
        status="published",
        visibility="private",
        owner_id="owner-a",
        target_id="generic_json",
        target_version="1.0.0",
        mappings=[
            DispatchMapping(
                target_path="/temperature",
                source=DispatchValueSource(kind="path", path="/output/temperature"),
                required=True,
            ),
            DispatchMapping(
                target_path="/mode",
                source=DispatchValueSource(kind="constant", value="fast"),
                required=True,
            ),
            DispatchMapping(
                target_path="/debug_token",
                source=DispatchValueSource(kind="constant", value="secret"),
            ),
        ],
        created_by="demo_user",
    )


class BoundedExecutionSecurityTest(TestCase):
    def setUp(self) -> None:
        self.engine = ExperimentDispatchProfileEngine()

    def test_boundary_enum_and_write_block_are_rejected(self) -> None:
        policy = TargetSecurityPolicy(
            target_id="generic_json",
            version="1.0.0",
            field_policies=[
                FieldSecurityPolicy(
                    path="/temperature",
                    boundary=BoundaryLimit(min=20, max=30),
                ),
                FieldSecurityPolicy(path="/mode", allowed_values=["safe"]),
                FieldSecurityPolicy(path="/debug_token", write_allowed=False),
            ],
        )

        result = self.engine.evaluate(
            _profile(),
            _target(policy),
            input_snapshot={},
            output_summary={"temperature": 40},
            run_metadata={},
            manual_values={},
        )

        self.assertFalse(result.is_valid)
        self.assertIn("目标字段 /temperature 超出配置边界", result.errors[0])
        self.assertIn("目标字段 /mode 不在枚举白名单内", result.errors)
        self.assertIn("目标字段 /debug_token 被安全策略禁止写入", result.errors)
        self.assertEqual(
            {item.event_type for item in result.security_events},
            {"boundary_exceeded", "value_not_allowed", "write_denied"},
        )

    def test_warn_policy_allows_value_but_keeps_trace(self) -> None:
        policy = TargetSecurityPolicy(
            target_id="generic_json",
            version="1.0.0",
            default_write_allowed=True,
            field_policies=[
                FieldSecurityPolicy(
                    path="/temperature",
                    boundary=BoundaryLimit(min=20, max=30),
                    violation_policy="warn",
                ),
            ],
        )

        result = self.engine.evaluate(
            _profile(),
            _target(policy),
            input_snapshot={},
            output_summary={"temperature": 40},
            run_metadata={},
            manual_values={},
        )

        self.assertTrue(result.is_valid)
        self.assertIn("目标字段 /temperature 超出配置边界", result.warnings)
        self.assertEqual(result.security_events[0].severity, "warning")

    def test_default_write_deny_acts_as_field_whitelist(self) -> None:
        policy = TargetSecurityPolicy(
            target_id="generic_json",
            version="1.0.0",
            default_write_allowed=False,
            field_policies=[
                FieldSecurityPolicy(path="/temperature"),
                FieldSecurityPolicy(path="/mode"),
            ],
        )

        result = self.engine.evaluate(
            _profile(),
            _target(policy),
            input_snapshot={},
            output_summary={"temperature": 25},
            run_metadata={},
            manual_values={},
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, ["目标字段 /debug_token 被安全策略禁止写入"])
        self.assertEqual(result.security_events[0].event_type, "write_denied")

    def test_adapter_read_only_rejects_write_and_external_dispatch(self) -> None:
        now = datetime(2026, 8, 27, 12, 0, 0)
        context = AdapterContext(
            run=_run(),
            worker_id="worker-test",
            workdir=Path("/tmp/poly-agent-access-test"),
            started_at=now,
            timeout_seconds=60,
            access_mode="read_only",
        )

        with self.assertRaises(ExecutionAccessError):
            validate_adapter_access(context, artifact_write_count=1)
        with self.assertRaises(ExecutionAccessError):
            validate_adapter_access(context, external_dispatch_count=1)
        with self.assertRaises(ExecutionAccessError):
            validate_execution_access("privileged")
        validate_adapter_access(context)


class DispatchExecutionAccessServiceTest(TestCase):
    def setUp(self) -> None:
        self.original_require_mongodb = settings.require_mongodb
        self.original_demo_store_path = demo_store.path
        settings.require_mongodb = False
        demo_store.path = Path(self.id().replace(".", "_") + ".json").resolve()
        self.mongo_unavailable = patch(
            "app.infra.computation_repositories._mongo_unavailable",
            True,
        )
        self.mongo_unavailable.start()
        self.service = ExperimentDispatchProfileService(seed_enabled=False)
        ExperimentDispatchTargetRepository.save(
            "target_key",
            {
                **_target().model_dump(mode="python"),
                "target_key": "generic_json@1.0.0",
            },
        )
        AlgorithmRunRepository.save(
            "run_id",
            {
                "run_id": "arun-access-test",
                "algorithm_id": "example_predictor",
                "algorithm_version_id": "aiv_1",
                "trigger_source": "human_workflow",
                "status": "completed",
                "created_by": "owner-a",
                "input_snapshot": {},
                "output_summary": {"temperature": 25},
                "created_at": None,
                "finished_at": None,
            },
        )
        ExperimentDispatchProfileRepository.save(
            "profile_key",
            {
                **_profile().model_dump(mode="python"),
                "profile_key": "security_test@1.0.0",
            },
        )

    def tearDown(self) -> None:
        self.mongo_unavailable.stop()
        settings.require_mongodb = self.original_require_mongodb
        demo_store.path.unlink(missing_ok=True)
        demo_store.path = self.original_demo_store_path

    def evaluation_request(self) -> ExperimentDispatchProfileEvaluationRequest:
        return ExperimentDispatchProfileEvaluationRequest(
            run_id="arun-access-test",
            profile_id="security_test",
            profile_version="1.0.0",
        )

    def test_preview_is_read_only_and_save_is_confirmed_writable(self) -> None:
        request = self.evaluation_request()
        evaluation = self.service.evaluate(
            request,
            actor_user_id="owner-a",
            is_admin=False,
        )
        self.assertEqual(evaluation.execution_access.access_mode, "read_only")
        self.assertEqual(evaluation.execution_access.operations, ["query"])

        with patch.object(ComputationService, "register_owner_artifacts", return_value=[]) as register_mock, patch(
            "app.services.experiment_dispatch_profile_service.speclabos_dispatch_service.dispatch",
            return_value={
                "dispatch_id": "external-dispatch-1",
                "status": "received",
                "received_at": "2026-08-27T12:00:00Z",
            },
        ):
            saved = self.service.save_dispatch(
                ExperimentDispatchProfileSaveRequest(
                    **request.model_dump(),
                    preview_digest=evaluation.preview_digest,
                ),
                actor_user_id="owner-a",
                is_admin=False,
            )

        self.assertEqual(saved.status, "accepted")
        self.assertEqual(saved.execution_access.access_mode, "writable")
        self.assertEqual(
            saved.execution_access.operations,
            ["persist", "artifact_write", "external_dispatch"],
        )
        self.assertEqual(saved.execution_access.confirmed_preview_digest, evaluation.preview_digest)
        self.assertEqual(register_mock.call_count, 1)
        self.assertEqual(register_mock.call_args.kwargs["owner_type"], "experiment_dispatch")

    def test_security_violation_is_audited(self) -> None:
        target = _target(
            TargetSecurityPolicy(
                target_id="generic_json",
                version="1.0.0",
                field_policies=[
                    FieldSecurityPolicy(path="/temperature", boundary=BoundaryLimit(min=20, max=24)),
                ],
            )
        )
        ExperimentDispatchTargetRepository.save(
            "target_key",
            {**target.model_dump(mode="python"), "target_key": "generic_json@1.0.0"},
        )
        with patch("app.services.experiment_dispatch_profile_service.AuditEventRepository.append") as audit_mock:
            evaluation = self.service.evaluate(
                self.evaluation_request(),
                actor_user_id="owner-a",
                is_admin=False,
            )

        self.assertFalse(evaluation.result.is_valid)
        self.assertEqual(audit_mock.call_count, 1)
        audit_event = audit_mock.call_args.args[0]
        self.assertEqual(audit_event["event_type"], "experiment_dispatch.security_blocked")
        self.assertEqual(audit_event["metadata"]["event_type"], "boundary_exceeded")

    def test_security_warning_is_audited_without_blocking_preview(self) -> None:
        target = _target(
            TargetSecurityPolicy(
                target_id="generic_json",
                version="1.0.0",
                field_policies=[
                    FieldSecurityPolicy(
                        path="/temperature",
                        boundary=BoundaryLimit(min=20, max=24),
                        violation_policy="warn",
                    )
                ],
            )
        )
        ExperimentDispatchTargetRepository.save(
            "target_key",
            {**target.model_dump(mode="python"), "target_key": "generic_json@1.0.0"},
        )
        with patch("app.services.experiment_dispatch_profile_service.AuditEventRepository.append") as audit_mock:
            evaluation = self.service.evaluate(
                self.evaluation_request(),
                actor_user_id="owner-a",
                is_admin=False,
            )

        self.assertTrue(evaluation.result.is_valid)
        self.assertEqual(audit_mock.call_count, 1)
        self.assertEqual(audit_mock.call_args.args[0]["event_type"], "experiment_dispatch.security_warning")
