from __future__ import annotations

from scripts.restore_polymer_mongo_scope import (
    assert_no_alloy_values,
    inspect,
    is_metal_handoff,
    is_metal_problem_spec,
    is_metal_registry_entry,
)


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, *_args, **_kwargs):
        return list(self.rows)


class _Database:
    def __init__(self, collections):
        self.collections = collections

    def __getitem__(self, name):
        return self.collections[name]

    def list_collection_names(self):
        return list(self.collections)


def test_metal_predicates_select_only_owned_records():
    assert is_metal_registry_entry({"algorithm_id": "lpbf_porosity_predictor"})
    assert is_metal_registry_entry({"algorithm_id": "am_alloy_property_predictor"})
    assert not is_metal_registry_entry({"algorithm_id": "local_xtb_adapter"})

    assert is_metal_problem_spec({"material_family": "nickel_superalloy"})
    assert not is_metal_problem_spec({"material_family": "fluoropolymer"})

    assert is_metal_handoff({"material_scope": ["titanium_alloy"]})
    assert is_metal_handoff({"algorithm_id": "lpbf_process_parameter_predictor"})
    assert not is_metal_handoff({"algorithm_id": "polymer_descriptor_mock", "material_scope": ["universal"]})


def test_inspect_selects_metal_owned_documents_without_touching_polymer_rows():
    database = _Database(
        {
            "algorithm_registry_entries": _Collection([
                {"algorithm_id": "lpbf_porosity_predictor"},
                {"algorithm_id": "local_xtb_adapter"},
            ]),
            "research_problem_specs": _Collection([
                {"problem_spec_id": "metal", "material_family": "nickel_superalloy"},
                {"problem_spec_id": "polymer", "material_family": "fluoropolymer"},
            ]),
            "algorithm_handoffs": _Collection([
                {"handoff_id": "lpbf", "algorithm_id": "lpbf_porosity_predictor"},
                {"handoff_id": "poly", "algorithm_id": "local_xtb_adapter", "material_scope": ["universal"]},
            ]),
        }
    )
    selected = inspect(database)
    assert [row["algorithm_id"] for row in selected["algorithm_registry_entries"]] == ["lpbf_porosity_predictor"]
    assert [row["problem_spec_id"] for row in selected["research_problem_specs"]] == ["metal"]
    assert [row["handoff_id"] for row in selected["algorithm_handoffs"]] == ["lpbf"]


def test_assert_no_alloy_values_scans_all_collections():
    database = _Database(
        {
            "computation_runs": _Collection([{"run_id": "r1", "material": "titanium_alloy"}]),
        }
    )
    try:
        assert_no_alloy_values(database)
    except RuntimeError as exc:
        assert "computation_runs" in str(exc)
    else:
        raise AssertionError("alloy value was not detected")
