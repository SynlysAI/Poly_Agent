"""ResearchEngine repository 单元测试。

覆盖 ResearchProblemSpecRepository、AlgorithmRegistryRepository、
AlgorithmRunRepository、ResearchRunRepository 的 CRUD 和查询操作。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

from app.infra.research_engine_repositories import (
    AlgorithmRegistryRepository,
    AlgorithmRunRepository,
    ResearchProblemSpecRepository,
    ResearchRunRepository,
)

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


# =============================================================================
# 辅助函数
# =============================================================================


def _now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(timezone.utc)


def _problem_spec_doc(**overrides) -> dict:
    """构建 ProblemSpec 文档。"""
    now = _now()
    doc = {
        "problem_spec_id": "ps_test_001",
        "name": "测试任务",
        "material_family": "fluoropolymer",
        "problem_type": "formulation_process_optimization",
        "execution_mode": "hybrid",
        "variables": [],
        "objectives": [
            {"name": "dielectric_constant", "direction": "maximize", "unit": "dimensionless"},
        ],
        "constraints": [],
        "measurements": [],
        "campaign_id": None,
        "description": None,
        "schema_version": "0.2",
        "created_by": "tester",
        "owner_id": None,
        "project_id": "proj_001",
        "status": "draft",
        "frozen_version": 0,
        "created_at": now,
        "updated_at": now,
    }
    doc.update(overrides)
    return doc


def _algorithm_entry_doc(**overrides) -> dict:
    """构建 AlgorithmRegistry 条目文档。"""
    doc = {
        "algorithm_id": "test_adapter",
        "name": "测试算法",
        "type": "simulator",
        "material_scope": ["fluoropolymer", "universal"],
        "task_scope": ["COMPUTE_PREDICT"],
        "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"], "constraints": {}},
        "output_schema": {"fields": {"energy": "float"}, "required": ["energy"], "constraints": {}},
        "call_method": "SDK",
        "trigger_modes": ["human", "autoresearch"],
        "runtime_dependency": "Python",
        "version": "1.0.0",
        "validation_metric": {},
        "owner": "team",
        "status": "active",
        "description": "测试用算法",
    }
    doc.update(overrides)
    return doc


def _algorithm_run_doc(**overrides) -> dict:
    """构建 AlgorithmRun 文档。"""
    now = _now()
    doc = {
        "run_id": "ar_test_001",
        "algorithm_id": "test_adapter",
        "trigger_source": "human",
        "trigger_context_id": None,
        "problem_spec_id": "ps_test_001",
        "problem_spec_version": None,
        "campaign_id": None,
        "research_run_id": None,
        "stage_run_id": None,
        "linked_computation_run_id": None,
        "linked_suggestion_id": None,
        "linked_observation_id": None,
        "input_snapshot": {},
        "output_summary": {},
        "artifact_refs": [],
        "status": "completed",
        "error": None,
        "created_by": "tester",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
    doc.update(overrides)
    return doc


def _research_run_doc(**overrides) -> dict:
    """构建 ResearchRun 文档。"""
    now = _now()
    doc = {
        "run_id": "rr_test_001",
        "project_id": "proj_001",
        "problem_spec_id": "ps_test_001",
        "campaign_id": None,
        "profile_id": "fluoropolymer",
        "status": "draft",
        "current_stage": None,
        "stage_runs": [],
        "linked_algorithm_runs": [],
        "linked_experiment_runs": [],
        "checkpoint": {},
        "summary": {},
        "max_iterations": 5,
        "batch_size": 10,
        "created_by": "tester",
        "owner_id": None,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "finished_at": None,
    }
    doc.update(overrides)
    return doc


# =============================================================================
# ResearchProblemSpecRepository 测试
# =============================================================================


class ProblemSpecRepositoryTest(ComputationTestCase):
    """覆盖 ProblemSpec 仓储的 CRUD 操作。"""

    def test_save_and_find_one(self) -> None:
        """保存后可通过 find_one 查询。"""
        doc = _problem_spec_doc()
        ResearchProblemSpecRepository.save("problem_spec_id", doc)
        found = ResearchProblemSpecRepository.find_one({"problem_spec_id": "ps_test_001"})
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "测试任务")
        self.assertEqual(found["material_family"], "fluoropolymer")

    def test_list_all_with_pagination(self) -> None:
        """分页查询正确。"""
        for i in range(5):
            doc = _problem_spec_doc(problem_spec_id=f"ps_{i:03d}", name=f"任务{i}")
            ResearchProblemSpecRepository.save("problem_spec_id", doc)

        items, total = ResearchProblemSpecRepository.list_all({}, page=1, page_size=3)
        self.assertEqual(len(items), 3)
        self.assertEqual(total, 5)

    def test_list_by_project_id(self) -> None:
        """按 project_id 过滤。"""
        doc_a = _problem_spec_doc(problem_spec_id="ps_a", project_id="proj_A", name="项目A任务")
        doc_b = _problem_spec_doc(problem_spec_id="ps_b", project_id="proj_B", name="项目B任务")
        ResearchProblemSpecRepository.save("problem_spec_id", doc_a)
        ResearchProblemSpecRepository.save("problem_spec_id", doc_b)

        items, total = ResearchProblemSpecRepository.list_problem_specs(project_id="proj_A")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["problem_spec_id"], "ps_a")

    def test_list_by_campaign_id(self) -> None:
        """按 campaign_id 过滤。"""
        doc = _problem_spec_doc(problem_spec_id="ps_camp", campaign_id="camp_001")
        ResearchProblemSpecRepository.save("problem_spec_id", doc)

        items, total = ResearchProblemSpecRepository.list_problem_specs(campaign_id="camp_001")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["campaign_id"], "camp_001")

    def test_list_by_created_by(self) -> None:
        """按创建者过滤。"""
        doc_a = _problem_spec_doc(problem_spec_id="ps_user_a", created_by="user_a")
        doc_b = _problem_spec_doc(problem_spec_id="ps_user_b", created_by="user_b")
        ResearchProblemSpecRepository.save("problem_spec_id", doc_a)
        ResearchProblemSpecRepository.save("problem_spec_id", doc_b)

        items, total = ResearchProblemSpecRepository.list_problem_specs(created_by="user_a")
        self.assertEqual(total, 1)

    def test_list_by_status(self) -> None:
        """按状态过滤。"""
        doc_draft = _problem_spec_doc(problem_spec_id="ps_draft", status="draft")
        doc_frozen = _problem_spec_doc(problem_spec_id="ps_frozen", status="frozen")
        ResearchProblemSpecRepository.save("problem_spec_id", doc_draft)
        ResearchProblemSpecRepository.save("problem_spec_id", doc_frozen)

        items, _ = ResearchProblemSpecRepository.list_problem_specs(status="frozen")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["problem_spec_id"], "ps_frozen")

    def test_list_by_material_family(self) -> None:
        """按材料体系过滤。"""
        doc = _problem_spec_doc(problem_spec_id="ps_fluoro", material_family="fluoropolymer")
        ResearchProblemSpecRepository.save("problem_spec_id", doc)
        items, _ = ResearchProblemSpecRepository.list_problem_specs(material_family="fluoropolymer")
        self.assertGreaterEqual(len(items), 1)

    def test_update_fields(self) -> None:
        """更新字段成功。"""
        doc = _problem_spec_doc()
        ResearchProblemSpecRepository.save("problem_spec_id", doc)

        updated = ResearchProblemSpecRepository.update_fields(
            "ps_test_001",
            {"status": "frozen", "frozen_version": 1},
        )
        self.assertTrue(updated)

        found = ResearchProblemSpecRepository.find_one({"problem_spec_id": "ps_test_001"})
        self.assertEqual(found["status"], "frozen")
        self.assertEqual(found["frozen_version"], 1)

    def test_find_by_campaign(self) -> None:
        """按 campaign 查询关联 ProblemSpec。"""
        doc = _problem_spec_doc(problem_spec_id="ps_camp_lookup", campaign_id="camp_lookup")
        ResearchProblemSpecRepository.save("problem_spec_id", doc)
        items = ResearchProblemSpecRepository.find_by_campaign("camp_lookup")
        self.assertEqual(len(items), 1)

    def test_save_is_upsert(self) -> None:
        """重复保存为 upsert 操作。"""
        doc = _problem_spec_doc(name="原始名称")
        ResearchProblemSpecRepository.save("problem_spec_id", doc)
        doc_v2 = _problem_spec_doc(name="更新名称")
        ResearchProblemSpecRepository.save("problem_spec_id", doc_v2)
        found = ResearchProblemSpecRepository.find_one({"problem_spec_id": "ps_test_001"})
        self.assertEqual(found["name"], "更新名称")


# =============================================================================
# AlgorithmRegistryRepository 测试
# =============================================================================


class AlgorithmRegistryRepositoryTest(ComputationTestCase):
    """覆盖算法能力清单仓储的查询和种子写入。"""

    def test_save_and_find_one(self) -> None:
        """保存算法条目后可查询。"""
        doc = _algorithm_entry_doc()
        AlgorithmRegistryRepository.save("algorithm_id", doc)
        found = AlgorithmRegistryRepository.find_one({"algorithm_id": "test_adapter"})
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "测试算法")

    def test_list_by_type(self) -> None:
        """按算法类型过滤。"""
        doc_sim = _algorithm_entry_doc(algorithm_id="sim_001", type="simulator")
        doc_pred = _algorithm_entry_doc(algorithm_id="pred_001", type="predictor")
        AlgorithmRegistryRepository.save("algorithm_id", doc_sim)
        AlgorithmRegistryRepository.save("algorithm_id", doc_pred)

        items, total = AlgorithmRegistryRepository.list_algorithms(algorithm_type="simulator")
        self.assertGreaterEqual(total, 1)
        for item in items:
            self.assertEqual(item["type"], "simulator")

    def test_list_by_status(self) -> None:
        """按状态过滤。"""
        doc = _algorithm_entry_doc(algorithm_id="active_001", status="active")
        AlgorithmRegistryRepository.save("algorithm_id", doc)
        items, _ = AlgorithmRegistryRepository.list_algorithms(status="active")
        self.assertGreaterEqual(len(items), 1)

    def test_seed_defaults_is_idempotent(self) -> None:
        """种子写入幂等：重复写入不产生重复条目。"""
        entries = [
            _algorithm_entry_doc(algorithm_id="seed_001", name="种子算法1"),
            _algorithm_entry_doc(algorithm_id="seed_002", name="种子算法2"),
        ]
        count1 = AlgorithmRegistryRepository.seed_defaults(entries)
        self.assertEqual(count1, 2)

        # 重复写入应跳过
        count2 = AlgorithmRegistryRepository.seed_defaults(entries)
        self.assertEqual(count2, 0)

        # 总数不变
        items, total = AlgorithmRegistryRepository.list_algorithms(page_size=100)
        self.assertGreaterEqual(total, 2)

    def test_update_fields(self) -> None:
        """更新算法条目字段。"""
        doc = _algorithm_entry_doc()
        AlgorithmRegistryRepository.save("algorithm_id", doc)
        AlgorithmRegistryRepository.update_fields("test_adapter", {"status": "frozen"})
        found = AlgorithmRegistryRepository.find_one({"algorithm_id": "test_adapter"})
        self.assertEqual(found["status"], "frozen")

    def test_list_all_with_pagination(self) -> None:
        """分页查询正确。"""
        for i in range(5):
            doc = _algorithm_entry_doc(algorithm_id=f"algo_{i:03d}", name=f"算法{i}")
            AlgorithmRegistryRepository.save("algorithm_id", doc)

        items, total = AlgorithmRegistryRepository.list_algorithms(page=1, page_size=3)
        self.assertEqual(len(items), 3)
        self.assertEqual(total, 5)


# =============================================================================
# AlgorithmRunRepository 测试
# =============================================================================


class AlgorithmRunRepositoryTest(ComputationTestCase):
    """覆盖 AlgorithmRun 仓储的 CRUD 和过滤查询。"""

    def test_save_and_find_one(self) -> None:
        """保存运行记录后可查询。"""
        doc = _algorithm_run_doc()
        AlgorithmRunRepository.save("run_id", doc)
        found = AlgorithmRunRepository.find_one({"run_id": "ar_test_001"})
        self.assertIsNotNone(found)
        self.assertEqual(found["algorithm_id"], "test_adapter")
        self.assertEqual(found["trigger_source"], "human")

    def test_list_by_problem_spec_id(self) -> None:
        """按 ProblemSpec ID 过滤。"""
        doc_a = _algorithm_run_doc(run_id="ar_a", problem_spec_id="ps_A")
        doc_b = _algorithm_run_doc(run_id="ar_b", problem_spec_id="ps_B")
        AlgorithmRunRepository.save("run_id", doc_a)
        AlgorithmRunRepository.save("run_id", doc_b)

        items, total = AlgorithmRunRepository.list_runs(problem_spec_id="ps_A")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["run_id"], "ar_a")

    def test_list_by_trigger_source(self) -> None:
        """按触发来源过滤。"""
        doc_human = _algorithm_run_doc(run_id="ar_human", trigger_source="human")
        doc_auto = _algorithm_run_doc(run_id="ar_auto", trigger_source="autoresearch")
        AlgorithmRunRepository.save("run_id", doc_human)
        AlgorithmRunRepository.save("run_id", doc_auto)

        items, _ = AlgorithmRunRepository.list_runs(trigger_source="autoresearch")
        self.assertGreaterEqual(len(items), 1)
        for item in items:
            self.assertEqual(item["trigger_source"], "autoresearch")

    def test_list_by_status(self) -> None:
        """按运行状态过滤。"""
        doc = _algorithm_run_doc(run_id="ar_completed", status="completed")
        AlgorithmRunRepository.save("run_id", doc)
        items, _ = AlgorithmRunRepository.list_runs(status="completed")
        self.assertGreaterEqual(len(items), 1)

    def test_list_by_algorithm_id(self) -> None:
        """按算法 ID 过滤。"""
        doc = _algorithm_run_doc(run_id="ar_algo", algorithm_id="local_xtb_adapter")
        AlgorithmRunRepository.save("run_id", doc)
        items, _ = AlgorithmRunRepository.list_runs(algorithm_id="local_xtb_adapter")
        self.assertGreaterEqual(len(items), 1)

    def test_list_by_campaign_id(self) -> None:
        """按 Campaign ID 过滤。"""
        doc = _algorithm_run_doc(run_id="ar_camp", campaign_id="camp_001")
        AlgorithmRunRepository.save("run_id", doc)
        items, _ = AlgorithmRunRepository.list_runs(campaign_id="camp_001")
        self.assertGreaterEqual(len(items), 1)

    def test_list_by_research_run_id(self) -> None:
        """按 ResearchRun ID 过滤。"""
        doc = _algorithm_run_doc(run_id="ar_rr", research_run_id="rr_001")
        AlgorithmRunRepository.save("run_id", doc)
        items, _ = AlgorithmRunRepository.list_runs(research_run_id="rr_001")
        self.assertGreaterEqual(len(items), 1)

    def test_update_fields(self) -> None:
        """更新运行记录字段。"""
        doc = _algorithm_run_doc()
        AlgorithmRunRepository.save("run_id", doc)
        AlgorithmRunRepository.update_fields(
            "ar_test_001",
            {"status": "failed", "error": {"message": "计算超时"}},
        )
        found = AlgorithmRunRepository.find_one({"run_id": "ar_test_001"})
        self.assertEqual(found["status"], "failed")
        self.assertEqual(found["error"]["message"], "计算超时")

    def test_list_by_research_run_aggregation(self) -> None:
        """聚合查询 ResearchRun 关联的所有 AlgorithmRun。"""
        for i in range(3):
            doc = _algorithm_run_doc(
                run_id=f"ar_rr_agg_{i}",
                research_run_id="rr_agg_001",
            )
            AlgorithmRunRepository.save("run_id", doc)
        items = AlgorithmRunRepository.list_by_research_run("rr_agg_001")
        self.assertEqual(len(items), 3)

    def test_cross_references_preserved(self) -> None:
        """交叉引用字段（computation、suggestion、observation）正确保存和读取。"""
        doc = _algorithm_run_doc(
            run_id="ar_cross_ref",
            linked_computation_run_id="comp_001",
            linked_suggestion_id="sug_001",
            linked_observation_id="obs_001",
        )
        AlgorithmRunRepository.save("run_id", doc)
        found = AlgorithmRunRepository.find_one({"run_id": "ar_cross_ref"})
        self.assertEqual(found["linked_computation_run_id"], "comp_001")
        self.assertEqual(found["linked_suggestion_id"], "sug_001")
        self.assertEqual(found["linked_observation_id"], "obs_001")


# =============================================================================
# ResearchRunRepository 测试
# =============================================================================


class ResearchRunRepositoryTest(ComputationTestCase):
    """覆盖 ResearchRun 仓储的 CRUD 和过滤查询。"""

    def test_save_and_find_one(self) -> None:
        """保存运行记录后可查询。"""
        doc = _research_run_doc()
        ResearchRunRepository.save("run_id", doc)
        found = ResearchRunRepository.find_one({"run_id": "rr_test_001"})
        self.assertIsNotNone(found)
        self.assertEqual(found["problem_spec_id"], "ps_test_001")
        self.assertEqual(found["status"], "draft")

    def test_list_by_problem_spec_id(self) -> None:
        """按 ProblemSpec ID 过滤。"""
        doc_a = _research_run_doc(run_id="rr_a", problem_spec_id="ps_A")
        doc_b = _research_run_doc(run_id="rr_b", problem_spec_id="ps_B")
        ResearchRunRepository.save("run_id", doc_a)
        ResearchRunRepository.save("run_id", doc_b)

        items, total = ResearchRunRepository.list_runs(problem_spec_id="ps_A")
        self.assertEqual(total, 1)
        self.assertEqual(items[0]["run_id"], "rr_a")

    def test_list_by_status(self) -> None:
        """按状态过滤。"""
        doc_running = _research_run_doc(run_id="rr_running", status="running")
        ResearchRunRepository.save("run_id", doc_running)
        items, _ = ResearchRunRepository.list_runs(status="running")
        self.assertGreaterEqual(len(items), 1)

    def test_list_by_campaign_id(self) -> None:
        """按 Campaign ID 过滤。"""
        doc = _research_run_doc(run_id="rr_camp", campaign_id="camp_001")
        ResearchRunRepository.save("run_id", doc)
        items, _ = ResearchRunRepository.list_runs(campaign_id="camp_001")
        self.assertGreaterEqual(len(items), 1)

    def test_list_by_created_by(self) -> None:
        """按创建者过滤。"""
        doc = _research_run_doc(run_id="rr_creator", created_by="expert_A")
        ResearchRunRepository.save("run_id", doc)
        items, _ = ResearchRunRepository.list_runs(created_by="expert_A")
        self.assertGreaterEqual(len(items), 1)

    def test_list_by_project_id(self) -> None:
        """按项目 ID 过滤。"""
        doc = _research_run_doc(run_id="rr_proj", project_id="proj_special")
        ResearchRunRepository.save("run_id", doc)
        items, _ = ResearchRunRepository.list_runs(project_id="proj_special")
        self.assertGreaterEqual(len(items), 1)

    def test_update_fields(self) -> None:
        """更新 ResearchRun 字段。"""
        doc = _research_run_doc()
        ResearchRunRepository.save("run_id", doc)
        ResearchRunRepository.update_fields(
            "rr_test_001",
            {"status": "running", "current_stage": "KNOWLEDGE_RETRIEVAL"},
        )
        found = ResearchRunRepository.find_one({"run_id": "rr_test_001"})
        self.assertEqual(found["status"], "running")
        self.assertEqual(found["current_stage"], "KNOWLEDGE_RETRIEVAL")

    def test_update_stage_runs(self) -> None:
        """更新内嵌 stage_runs 列表。"""
        doc = _research_run_doc()
        ResearchRunRepository.save("run_id", doc)

        stage_run = {
            "stage_run_id": "sr_001",
            "research_run_id": "rr_test_001",
            "stage_key": "PROBLEM_SPEC",
            "status": "completed",
            "gate": None,
            "input_snapshot": {},
            "output_summary": {"validated": True},
            "error": None,
            "decisions": [],
            "linked_algorithm_runs": [],
            "linked_experiment_runs": [],
            "artifact_ids": [],
            "checkpoint_data": {},
            "started_at": None,
            "finished_at": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        ResearchRunRepository.update_fields(
            "rr_test_001",
            {"stage_runs": [stage_run], "current_stage": "PROBLEM_SPEC"},
        )
        found = ResearchRunRepository.find_one({"run_id": "rr_test_001"})
        self.assertEqual(len(found["stage_runs"]), 1)
        self.assertEqual(found["stage_runs"][0]["stage_key"], "PROBLEM_SPEC")

    def test_list_by_problem_spec_aggregation(self) -> None:
        """聚合查询 ProblemSpec 关联的所有 ResearchRun。"""
        for i in range(3):
            doc = _research_run_doc(
                run_id=f"rr_ps_agg_{i}",
                problem_spec_id="ps_agg_001",
            )
            ResearchRunRepository.save("run_id", doc)
        items = ResearchRunRepository.list_by_problem_spec("ps_agg_001")
        self.assertEqual(len(items), 3)

    def test_list_all_with_pagination(self) -> None:
        """分页查询正确。"""
        for i in range(5):
            doc = _research_run_doc(run_id=f"rr_{i:03d}", problem_spec_id=f"ps_{i:03d}")
            ResearchRunRepository.save("run_id", doc)

        items, total = ResearchRunRepository.list_all({}, page=1, page_size=3)
        self.assertEqual(len(items), 3)
        self.assertEqual(total, 5)


# =============================================================================
# 跨仓储关联测试
# =============================================================================


class CrossRepositoryTest(ComputationTestCase):
    """验证不同仓储之间的关联字段可正确交叉查询。"""

    def test_problem_spec_to_algorithm_run_link(self) -> None:
        """ProblemSpec -> AlgorithmRun 关联查询。"""
        ps_doc = _problem_spec_doc(problem_spec_id="ps_cross_001")
        ResearchProblemSpecRepository.save("problem_spec_id", ps_doc)

        ar_doc = _algorithm_run_doc(run_id="ar_cross_001", problem_spec_id="ps_cross_001")
        AlgorithmRunRepository.save("run_id", ar_doc)

        items, _ = AlgorithmRunRepository.list_runs(problem_spec_id="ps_cross_001")
        self.assertEqual(len(items), 1)

    def test_problem_spec_to_research_run_link(self) -> None:
        """ProblemSpec -> ResearchRun 关联查询。"""
        ps_doc = _problem_spec_doc(problem_spec_id="ps_cross_002")
        ResearchProblemSpecRepository.save("problem_spec_id", ps_doc)

        rr_doc = _research_run_doc(run_id="rr_cross_002", problem_spec_id="ps_cross_002")
        ResearchRunRepository.save("run_id", rr_doc)

        items = ResearchRunRepository.list_by_problem_spec("ps_cross_002")
        self.assertEqual(len(items), 1)

    def test_campaign_cross_reference(self) -> None:
        """同一 campaign 下可关联 ProblemSpec、AlgorithmRun、ResearchRun。"""
        campaign_id = "camp_cross_001"

        ps_doc = _problem_spec_doc(problem_spec_id="ps_camp_cross", campaign_id=campaign_id)
        ResearchProblemSpecRepository.save("problem_spec_id", ps_doc)

        ar_doc = _algorithm_run_doc(run_id="ar_camp_cross", campaign_id=campaign_id)
        AlgorithmRunRepository.save("run_id", ar_doc)

        rr_doc = _research_run_doc(run_id="rr_camp_cross", campaign_id=campaign_id)
        ResearchRunRepository.save("run_id", rr_doc)

        ps_items = ResearchProblemSpecRepository.find_by_campaign(campaign_id)
        self.assertEqual(len(ps_items), 1)

        ar_items, _ = AlgorithmRunRepository.list_runs(campaign_id=campaign_id)
        self.assertEqual(len(ar_items), 1)

        rr_items, _ = ResearchRunRepository.list_runs(campaign_id=campaign_id)
        self.assertEqual(len(rr_items), 1)
