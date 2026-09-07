"""ALS P2 自然语言下发参数解析回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.infra.computation_repositories import AuditEventRepository  # noqa: E402
from app.infra.demo_store import demo_store  # noqa: E402
from app.infra.experiment_dispatch_profile_repositories import (  # noqa: E402
    ExperimentDispatchTargetRepository,
)
from app.infra.research_engine_repositories import AlgorithmRunRepository  # noqa: E402
from app.schemas.experiment_dispatch_profile import (  # noqa: E402
    BoundaryLimit,
    DispatchMapping,
    DispatchTargetDefinition,
    DispatchTargetField,
    DispatchValueSource,
    ExperimentDispatchNLParseRequest,
    ExperimentDispatchProfile,
    ExperimentDispatchProfileCreateRequest,
    ExperimentDispatchProfileEvaluationRequest,
    ExperimentDispatchProfileSaveRequest,
    FieldSecurityPolicy,
    TargetSecurityPolicy,
)
from app.services.experiment_dispatch_nl_parser import (  # noqa: E402
    NLDispatchParser,
)
from app.services.experiment_dispatch_profile_service import (  # noqa: E402
    ExperimentDispatchProfileService,
)


def _field(path: str, label: str, value_type: str, unit: str | None = None) -> DispatchTargetField:
    return DispatchTargetField(
        path=path,
        label=label,
        value_type=value_type,
        unit=unit,
        allow_override=True,
    )


def _profile(profile_id: str, *, reaction_time: bool = True) -> ExperimentDispatchProfile:
    fields = [
        _field("/experiment_name", "实验名称", "string"),
        _field("/temperature", "反应温度", "number", "degC"),
        _field("/experiment_content", "实验说明", "string"),
    ]
    if reaction_time:
        fields.append(_field("/reaction_time", "反应时间", "number", "h"))
    mappings = [
        DispatchMapping(
            target_path="/experiment_name",
            source=DispatchValueSource(kind="manual", key="experiment_name"),
            allow_override=True,
        ),
        DispatchMapping(
            target_path="/temperature",
            source=DispatchValueSource(kind="manual", key="temperature"),
            allow_override=True,
            required=True,
        ),
        DispatchMapping(
            target_path="/experiment_content",
            source=DispatchValueSource(kind="manual", key="experiment_content"),
            allow_override=True,
        ),
    ]
    if reaction_time:
        mappings.append(
            DispatchMapping(
                target_path="/reaction_time",
                source=DispatchValueSource(kind="manual", key="reaction_time"),
                allow_override=True,
            )
        )
    return ExperimentDispatchProfile(
        profile_id=profile_id,
        version="1.0.0",
        name="PI 合成实验下发" if reaction_time else "通用实验下发",
        status="published",
        visibility="public",
        owner_id="system",
        target_id="generic_json",
        target_version="1.0.0",
        target_fields=fields,
        mappings=mappings,
        created_by="system",
    )


def _target() -> DispatchTargetDefinition:
    return DispatchTargetDefinition(
        target_id="generic_json",
        version="1.0.0",
        name="Generic JSON",
        fields=[
            _field("/experiment_name", "实验名称", "string"),
            _field("/temperature", "反应温度", "number", "degC"),
            _field("/experiment_content", "实验说明", "string"),
            _field("/reaction_time", "反应时间", "number", "h"),
        ],
        security_policy=TargetSecurityPolicy(
            target_id="generic_json",
            version="1.0.0",
            field_policies=[
                FieldSecurityPolicy(
                    path="/temperature",
                    boundary=BoundaryLimit(min=20, max=250),
                )
            ],
        ),
    )


def _create_payload() -> ExperimentDispatchProfileCreateRequest:
    profile = _profile("pi")
    return ExperimentDispatchProfileCreateRequest(
        profile_id=profile.profile_id,
        version=profile.version,
        name=profile.name,
        target_id=profile.target_id,
        target_version=profile.target_version,
        target_fields=profile.target_fields,
        mappings=profile.mappings,
    )


class NLDispatchParserTest(TestCase):
    def setUp(self) -> None:
        self.parser = NLDispatchParser()

    def test_parses_fields_normalizes_units_and_keeps_unresolved(self) -> None:
        result = self.parser.parse(
            "实验名称：PI高温实验；反应温度 80℃，反应时间 120 分钟，"
            "实验说明：氮气保护；压力 5 MPa",
            [_profile("pi"), _profile("generic", reaction_time=False)],
            {"generic_json@1.0.0": _target()},
        )

        self.assertEqual(result.profile_id, "pi")
        self.assertEqual(
            result.manual_values,
            {
                "/experiment_name": "PI高温实验",
                "/temperature": 80.0,
                "/reaction_time": 2.0,
                "/experiment_content": "氮气保护",
            },
        )
        self.assertTrue(result.intents[1].resolved)
        self.assertEqual(result.intents[1].unit, "degC")
        self.assertEqual(result.unresolved[0].description, "压力 5 MPa")
        self.assertGreater(result.profile_candidates[0].score, result.profile_candidates[1].score)

    def test_single_profile_recommendation_does_not_guess_non_override_field(self) -> None:
        result = self.parser.parse(
            "实验名称为耐高温PI；debug token=secret",
            [_profile("pi")],
            {"generic_json@1.0.0": _target()},
        )

        self.assertEqual(result.profile_id, "pi")
        self.assertEqual(result.manual_values, {"/experiment_name": "耐高温PI"})
        self.assertEqual(result.unresolved[0].description, "debug token=secret")
        self.assertNotIn("/debug_token", result.manual_values)


class NLDispatchServiceIntegrationTest(TestCase):
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
            {**_target().model_dump(mode="python"), "target_key": "generic_json@1.0.0"},
        )
        AlgorithmRunRepository.save(
            "run_id",
            {
                "run_id": "run-nl",
                "algorithm_id": "algorithm-nl",
                "trigger_source": "human_workflow",
                "status": "completed",
                "created_by": "owner-a",
                "input_snapshot": {},
                "output_summary": {},
            },
        )
        self.profile = self.service.create(_create_payload(), actor_user_id="owner-a")
        self.service.publish("pi", "1.0.0", actor_user_id="owner-a")

    def tearDown(self) -> None:
        self.mongo_unavailable.stop()
        settings.require_mongodb = self.original_require_mongodb
        demo_store.path.unlink(missing_ok=True)
        demo_store.path = self.original_demo_store_path

    def test_parse_evaluate_and_audit_full_chain(self) -> None:
        parsed = self.service.parse_natural_language(
            ExperimentDispatchNLParseRequest(
                run_id="run-nl",
                natural_language="实验名称：PI高温实验；反应温度 80℃；压力 5 MPa",
            ),
            actor_user_id="owner-a",
            is_admin=False,
        )
        forged_parse = parsed.model_copy(update={
            "unresolved": [],
            "manual_values": {"/experiment_name": "伪造解析结果"},
        })
        evaluation = self.service.evaluate(
            ExperimentDispatchProfileEvaluationRequest(
                run_id="run-nl",
                profile_id=parsed.profile_id,
                profile_version=parsed.profile_version,
                manual_values={},
                natural_language=parsed.raw_text,
                nl_parse=forged_parse,
            ),
            actor_user_id="owner-a",
            is_admin=False,
        )

        self.assertEqual(evaluation.nl_parse.manual_values["/experiment_name"], "PI高温实验")
        self.assertEqual(evaluation.result.payload["experiment_name"], "PI高温实验")
        events, _ = AuditEventRepository.list_events(
            entity_type="experiment_dispatch_profile",
            entity_id="pi@1.0.0",
            event_type="experiment_dispatch.nl_parsed",
            page=1,
            page_size=10,
        )
        self.assertEqual(events[0]["metadata"]["raw_text"], parsed.raw_text)
        final_events, _ = AuditEventRepository.list_events(
            entity_type="experiment_dispatch_target",
            entity_id="generic_json@1.0.0",
            event_type="experiment_dispatch.nl_evaluated",
            page=1,
            page_size=10,
        )
        self.assertEqual(final_events[0]["metadata"]["payload"]["experiment_name"], "PI高温实验")

        with patch(
            "app.services.experiment_dispatch_profile_service.speclabos_dispatch_service.dispatch",
            return_value={
                "dispatch_id": "speclabos_dispatch_nl",
                "status": "received",
                "received_at": "2026-08-27T12:00:00Z",
            },
        ):
            saved = self.service.save_dispatch(
                ExperimentDispatchProfileSaveRequest(
                    run_id="run-nl",
                    profile_id="pi",
                    profile_version="1.0.0",
                    manual_values={},
                    natural_language=parsed.raw_text,
                    nl_parse=evaluation.nl_parse,
                    preview_digest=evaluation.preview_digest,
                ),
                actor_user_id="owner-a",
                is_admin=False,
            )
        self.assertEqual(saved.status, "accepted")
        self.assertEqual(saved.payload["experiment_name"], "PI高温实验")

    def test_parsed_manual_values_are_still_blocked_by_security_policy(self) -> None:
        evaluation = self.service.evaluate(
            ExperimentDispatchProfileEvaluationRequest(
                run_id="run-nl",
                profile_id="pi",
                profile_version="1.0.0",
                manual_values={},
                natural_language="反应温度 300℃",
            ),
            actor_user_id="owner-a",
            is_admin=False,
        )

        self.assertFalse(evaluation.result.is_valid)
        self.assertIn("目标字段 /temperature 超出配置边界", evaluation.result.errors)
        self.assertEqual(evaluation.result.payload["temperature"], 300)


if __name__ == "__main__":
    import unittest

    unittest.main()
