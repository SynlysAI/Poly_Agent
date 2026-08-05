"""通用实验下发配置规则执行器测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.experiment_dispatch_profile import (  # noqa: E402
    DispatchBranch,
    DispatchBranchAction,
    DispatchCondition,
    DispatchConditionGroup,
    DispatchMapping,
    DispatchSourceContract,
    DispatchSourceField,
    DispatchTargetDefinition,
    DispatchTargetField,
    DispatchTransform,
    DispatchValueSource,
    ExperimentDispatchProfile,
)
from app.services.experiment_dispatch_profile_engine import (  # noqa: E402
    ExperimentDispatchProfileEngine,
)


def _target(*fields: DispatchTargetField) -> DispatchTargetDefinition:
    return DispatchTargetDefinition(
        target_id="generic_json",
        version="1.0.0",
        name="Generic JSON",
        fields=list(fields),
        response_schema={"status": "string"},
    )


def _profile(
    *,
    mappings: list[DispatchMapping],
    branches: list[DispatchBranch] | None = None,
    required_fields: list[DispatchSourceField] | None = None,
) -> ExperimentDispatchProfile:
    return ExperimentDispatchProfile(
        profile_id="edp_test",
        version="1.0.0",
        name="Test profile",
        status="published",
        visibility="private",
        owner_id="demo_user",
        source_contract=DispatchSourceContract(required_fields=required_fields or []),
        target_id="generic_json",
        target_version="1.0.0",
        mappings=mappings,
        branches=branches or [],
        created_by="demo_user",
    )


class ExperimentDispatchProfileEngineTest(TestCase):
    def setUp(self) -> None:
        self.engine = ExperimentDispatchProfileEngine()

    def test_maps_fallback_cast_scale_lookup_and_manual_override(self) -> None:
        target = _target(
            DispatchTargetField(path="/sample", label="Sample", value_type="string", required=True),
            DispatchTargetField(path="/temperature", label="Temperature", value_type="number", required=True),
            DispatchTargetField(path="/resource", label="Resource", value_type="string", required=True),
        )
        profile = _profile(
            required_fields=[DispatchSourceField(path="/output/score", value_type="number", required=True)],
            mappings=[
                DispatchMapping(
                    target_path="/sample",
                    source=DispatchValueSource(kind="coalesce", paths=["/output/sample", "/input/sample"]),
                ),
                DispatchMapping(
                    target_path="/temperature",
                    source=DispatchValueSource(kind="path", path="/output/temperature_text"),
                    transforms=[
                        DispatchTransform(operation="cast", value_type="number"),
                        DispatchTransform(operation="scale", scale=2, offset=1),
                    ],
                    allow_override=True,
                ),
                DispatchMapping(
                    target_path="/resource",
                    source=DispatchValueSource(kind="path", path="/output/process"),
                    transforms=[
                        DispatchTransform(
                            operation="lookup",
                            lookup={"A": "recipes/a.task", "B": "recipes/b.task"},
                        )
                    ],
                ),
            ],
        )

        result = self.engine.evaluate(
            profile,
            target,
            input_snapshot={"sample": "input sample"},
            output_summary={"score": 4, "temperature_text": "12.5", "process": "A"},
            run_metadata={"run_id": "run-1"},
            manual_values={"/temperature": 30},
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.payload, {"sample": "input sample", "temperature": 30, "resource": "recipes/a.task"})
        self.assertTrue(next(item for item in result.trace if item.target_path == "/temperature").overridden)

    def test_applies_ordered_condition_branch_and_warning(self) -> None:
        target = _target(
            DispatchTargetField(path="/route", label="Route", value_type="string", required=True),
            DispatchTargetField(path="/volume", label="Volume", value_type="number", required=False),
        )
        profile = _profile(
            mappings=[
                DispatchMapping(
                    target_path="/route",
                    source=DispatchValueSource(kind="constant", value="default"),
                )
            ],
            branches=[
                DispatchBranch(
                    rule_id="high-score",
                    name="High score route",
                    priority=10,
                    conditions=DispatchConditionGroup(
                        mode="all",
                        items=[DispatchCondition(path="/output/score", operator="between", value=[80, 100])],
                    ),
                    actions=[
                        DispatchBranchAction(
                            kind="set",
                            target_path="/route",
                            source=DispatchValueSource(kind="constant", value="high"),
                        ),
                        DispatchBranchAction(
                            kind="set",
                            target_path="/volume",
                            source=DispatchValueSource(kind="constant", value=60),
                        ),
                        DispatchBranchAction(kind="warn", message="Review high-score route"),
                    ],
                    stop_on_match=True,
                )
            ],
        )

        result = self.engine.evaluate(
            profile,
            target,
            input_snapshot={},
            output_summary={"score": 88},
            run_metadata={},
            manual_values={},
        )

        self.assertEqual(result.payload["route"], "high")
        self.assertEqual(result.payload["volume"], 60)
        self.assertEqual(result.matched_rules, ["high-score"])
        self.assertEqual(result.warnings, ["Review high-score route"])

    def test_block_action_and_missing_required_target_make_result_invalid(self) -> None:
        target = _target(DispatchTargetField(path="/required", value_type="string", required=True))
        profile = _profile(
            mappings=[],
            branches=[
                DispatchBranch(
                    rule_id="unsupported",
                    name="Unsupported",
                    priority=1,
                    conditions=DispatchConditionGroup(
                        items=[DispatchCondition(path="/output/status", operator="equals", value="unsupported")]
                    ),
                    actions=[DispatchBranchAction(kind="block", message="Output is outside the configured scope")],
                )
            ],
        )

        result = self.engine.evaluate(
            profile,
            target,
            input_snapshot={},
            output_summary={"status": "unsupported"},
            run_metadata={},
            manual_values={},
        )

        self.assertFalse(result.is_valid)
        self.assertIn("Output is outside the configured scope", result.errors)
        self.assertTrue(any("required" in message for message in result.errors))

    def test_same_engine_supports_unrelated_domain_profiles(self) -> None:
        target = _target(DispatchTargetField(path="/value", value_type="number", required=True))
        synthesis = _profile(
            mappings=[
                DispatchMapping(
                    target_path="/value",
                    source=DispatchValueSource(kind="path", path="/output/process/temperature"),
                )
            ]
        )
        formulation = _profile(
            mappings=[
                DispatchMapping(
                    target_path="/value",
                    source=DispatchValueSource(kind="path", path="/output/formulation/concentration"),
                )
            ]
        )

        first = self.engine.evaluate(synthesis, target, {}, {"process": {"temperature": 25}}, {}, {})
        second = self.engine.evaluate(formulation, target, {}, {"formulation": {"concentration": 1.2}}, {}, {})

        self.assertEqual(first.payload["value"], 25)
        self.assertEqual(second.payload["value"], 1.2)


if __name__ == "__main__":
    import unittest

    unittest.main()
