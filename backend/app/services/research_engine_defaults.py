"""ResearchEngine 领域默认值和阶段常量。

固化材料版 AutoResearch 阶段序列、默认 stage contract、
默认算法能力清单条目，供后续 orchestrator 和 API 复用。
参考现有 ComputationStep 模式设计 ResearchStageRun。
"""

from __future__ import annotations

from app.schemas.attribution import AttributionItem
from app.schemas.research_engine import (
    AlgorithmIOSchema,
    AlgorithmRegistryEntry,
    AlgorithmStatus,
    AlgorithmType,
    MaterialScope,
    ResearchStageKey,
    StageGate,
    TriggerSource,
)


def source_item(
    name: str,
    role: str,
    organization: str | None,
    description: str,
    url: str | None = None,
    visibility: str = "detail",
) -> AttributionItem:
    """构建默认算法来源标注。"""
    return AttributionItem(
        name=name,
        role=role,
        organization=organization,
        description=description,
        url=url,
        logo_alt=organization or name,
        visibility=visibility,
    )


POLYAGENT_DEVELOPER = source_item(
    "PolyAgent",
    "implementation_source",
    "PolyAgent",
    "平台内置或适配算法条目，由 PolyAgent 注册表维护。",
    visibility="prominent",
)

CHEMOS_ATTRIBUTION = source_item(
    "ChemOS 2.0",
    "framework_reference",
    "University of Toronto / Aspuru-Guzik Group",
    "ResearchEngine 与计算编排参考其自驱实验室任务编排思想；PolyAgent 为本项目适配实现。",
    "https://github.com/malcolmsimgithub/ChemOS2.0",
    "prominent",
)

ALCHEMIST_ATTRIBUTION = source_item(
    "ALchemist",
    "framework_reference",
    "NatLabRockies / NREL / NLR",
    "主动学习、实验设计、GP 建模与采集优化工具包。",
    "https://github.com/NatLabRockies/ALchemist",
    "prominent",
)

# =============================================================================
# 默认阶段序列（材料版 AutoResearch 10 阶段）
# =============================================================================

DEFAULT_STAGE_SEQUENCE: list[ResearchStageKey] = [
    "PROBLEM_SPEC",
    "KNOWLEDGE_RETRIEVAL",
    "STRUCTURE_FEATURE",
    "COMPUTE_PREDICT",
    "RECOMMENDATION_ASK",
    "HUMAN_REVIEW",
    "EXPERIMENT_EXECUTION",
    "RESULT_TELL",
    "MODEL_UPDATE",
    "ARCHIVE_LEARNING",
]

# P0 默认需要人工审批的阶段
P0_GATE_STAGES: set[ResearchStageKey] = {
    "PROBLEM_SPEC",
    "RECOMMENDATION_ASK",
    "EXPERIMENT_EXECUTION",
}

# =============================================================================
# 默认 StageContract（每个阶段的输入输出契约）
# =============================================================================

DEFAULT_STAGE_CONTRACTS: dict[ResearchStageKey, StageGate] = {
    "PROBLEM_SPEC": StageGate(
        stage_key="PROBLEM_SPEC",
        required_inputs=["problem_spec_id"],
        expected_outputs=["problem_spec_snapshot", "validated_spec"],
        definition_of_done="ProblemSpec 已校验、冻结版本号已递增",
        gate_policy={
            "require_approval": True,
            "timeout_hours": 72,
            "allowed_operations": ["approve", "reject", "modify"],
        },
        retry_policy={"max_retries": 3, "retryable_errors": ["validation_error"]},
        rollback_target=None,
        artifact_policy={
            "required_artifacts": ["problem_spec_snapshot"],
            "optional_artifacts": ["spec_diff"],
        },
    ),
    "KNOWLEDGE_RETRIEVAL": StageGate(
        stage_key="KNOWLEDGE_RETRIEVAL",
        required_inputs=["problem_spec_snapshot", "material_family"],
        expected_outputs=[
            "answer",
            "hits",
            "citations",
            "graph_context",
            "knowledge_cards",
            "candidate_sources",
            "literature_summary",
        ],
        definition_of_done="知识增强检索完成，答案、证据、引用和图谱上下文已生成",
        gate_policy={
            "require_approval": False,
        },
        retry_policy={"max_retries": 2, "retryable_errors": ["search_timeout", "parse_error"]},
        rollback_target="PROBLEM_SPEC",
        artifact_policy={
            "required_artifacts": ["answer", "hits"],
            "optional_artifacts": ["citations", "graph_context", "knowledge_cards", "literature_summary", "raw_search_results"],
        },
    ),
    "STRUCTURE_FEATURE": StageGate(
        stage_key="STRUCTURE_FEATURE",
        required_inputs=["candidate_sources", "problem_spec_snapshot"],
        expected_outputs=["structure_features", "descriptors", "molecular_graphs"],
        definition_of_done="结构表示和描述符已生成，覆盖所有候选分子",
        gate_policy={
            "require_approval": False,
        },
        retry_policy={"max_retries": 2, "retryable_errors": ["parse_error", "descriptor_error"]},
        rollback_target="KNOWLEDGE_RETRIEVAL",
        artifact_policy={
            "required_artifacts": ["structure_features", "descriptors"],
            "optional_artifacts": ["molecular_graphs", "xyz_files"],
        },
    ),
    "COMPUTE_PREDICT": StageGate(
        stage_key="COMPUTE_PREDICT",
        required_inputs=["structure_features", "problem_spec_snapshot"],
        expected_outputs=["prediction_results", "computation_results"],
        definition_of_done="计算和性质预测已完成，结果已汇总",
        gate_policy={
            "require_approval": False,
        },
        retry_policy={"max_retries": 3, "retryable_errors": ["computation_timeout", "convergence_error"]},
        rollback_target="STRUCTURE_FEATURE",
        artifact_policy={
            "required_artifacts": ["prediction_results", "computation_summary"],
            "optional_artifacts": ["raw_computation_outputs", "energy_data"],
        },
    ),
    "RECOMMENDATION_ASK": StageGate(
        stage_key="RECOMMENDATION_ASK",
        required_inputs=["prediction_results", "problem_spec_snapshot", "historical_observations"],
        expected_outputs=["top_k_candidates", "pareto_solutions", "recommendation_reasons"],
        definition_of_done="Top-K 候选已生成，推荐理由和风险评估已完成",
        gate_policy={
            "require_approval": True,
            "timeout_hours": 72,
            "allowed_operations": ["approve", "reject", "modify"],
        },
        retry_policy={"max_retries": 3, "retryable_errors": ["optimization_error", "infeasible_constraints"]},
        rollback_target="COMPUTE_PREDICT",
        artifact_policy={
            "required_artifacts": ["top_k_candidates", "recommendation_reasons"],
            "optional_artifacts": ["pareto_plot", "uncertainty_analysis"],
        },
    ),
    "HUMAN_REVIEW": StageGate(
        stage_key="HUMAN_REVIEW",
        required_inputs=["top_k_candidates", "recommendation_reasons"],
        expected_outputs=["review_decisions", "approved_candidates", "rejected_candidates"],
        definition_of_done="人工审核完成，所有候选已有批准/拒绝/修改决策",
        gate_policy={
            "require_approval": True,
            "timeout_hours": 168,
            "allowed_operations": ["approve", "reject", "modify"],
        },
        retry_policy={"max_retries": 0},
        rollback_target="RECOMMENDATION_ASK",
        artifact_policy={
            "required_artifacts": ["review_decisions"],
            "optional_artifacts": ["expert_comments", "modified_candidates"],
        },
    ),
    "EXPERIMENT_EXECUTION": StageGate(
        stage_key="EXPERIMENT_EXECUTION",
        required_inputs=["approved_candidates", "problem_spec_snapshot"],
        expected_outputs=["experiment_runs", "computation_runs"],
        definition_of_done="所有批准的候选已提交计算或实验任务",
        gate_policy={
            "require_approval": True,
            "timeout_hours": 72,
            "allowed_operations": ["approve", "reject"],
        },
        retry_policy={"max_retries": 2, "retryable_errors": ["submit_error", "queue_full"]},
        rollback_target="HUMAN_REVIEW",
        artifact_policy={
            "required_artifacts": ["experiment_runs", "computation_runs"],
            "optional_artifacts": ["submission_logs"],
        },
    ),
    "RESULT_TELL": StageGate(
        stage_key="RESULT_TELL",
        required_inputs=["experiment_runs", "computation_runs"],
        expected_outputs=["observations", "result_summary", "failure_analysis"],
        definition_of_done="所有实验结果已回填，Observation 已生成",
        gate_policy={
            "require_approval": False,
        },
        retry_policy={"max_retries": 2, "retryable_errors": ["parse_error", "missing_result"]},
        rollback_target="EXPERIMENT_EXECUTION",
        artifact_policy={
            "required_artifacts": ["observations", "result_summary"],
            "optional_artifacts": ["raw_data_files", "failure_analysis"],
        },
    ),
    "MODEL_UPDATE": StageGate(
        stage_key="MODEL_UPDATE",
        required_inputs=["observations", "historical_data", "model_state"],
        expected_outputs=["model_update_record", "updated_dataset", "evaluation_metrics"],
        definition_of_done="模型或数据集已更新，评估指标已记录",
        gate_policy={
            "require_approval": True,
            "timeout_hours": 72,
            "allowed_operations": ["approve", "reject"],
        },
        retry_policy={"max_retries": 2, "retryable_errors": ["training_error", "data_insufficient"]},
        rollback_target="RESULT_TELL",
        artifact_policy={
            "required_artifacts": ["model_update_record", "evaluation_metrics"],
            "optional_artifacts": ["model_checkpoint", "dataset_snapshot"],
        },
    ),
    "ARCHIVE_LEARNING": StageGate(
        stage_key="ARCHIVE_LEARNING",
        required_inputs=["model_update_record", "all_stage_outputs", "research_run_summary"],
        expected_outputs=["archive_bundle", "lessons_learned", "failure_catalog"],
        definition_of_done="本轮经验已归档，失败原因和可复用 lesson 已记录",
        gate_policy={
            "require_approval": False,
        },
        retry_policy={"max_retries": 1, "retryable_errors": ["archive_error"]},
        rollback_target=None,
        artifact_policy={
            "required_artifacts": ["archive_bundle", "lessons_learned"],
            "optional_artifacts": ["failure_catalog", "replay_bundle"],
        },
    ),
}


# =============================================================================
# 默认算法能力清单条目
# =============================================================================

def build_default_algorithm_registry() -> list[AlgorithmRegistryEntry]:
    """构建 P0 默认算法能力清单（计算 Workflow 适配器）。

    包含三条已有计算 Workflow 对应的算法条目：
    - local_structure_adapter: 三维结构生成
    - local_xtb_adapter: xTB 半经验计算
    - orca_compute_engine_laser_adapter: ORCA DFT 精加工

    Returns:
        计算适配器算法能力条目列表。
    """
    return [
        AlgorithmRegistryEntry(
            algorithm_id="local_structure_adapter",
            name="三维结构生成",
            type="simulator",
            algorithm_family="structure",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "universal"],
            task_scope=["STRUCTURE_FEATURE"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "smiles": "string - SMILES 表达式（必填）",
                    "name": "string - 分子名称（可选）",
                },
                required=["smiles"],
                field_defaults={"name": "research-engine-molecule"},
                ui_hints={
                    "smiles": {"widget": "text", "placeholder": "CCO"},
                    "name": {"widget": "text"},
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "structure.xyz": "string - 原子坐标文件",
                    "structure.sdf": "string - 含键级信息的结构文件",
                    "structure.json": "object - 结构化数据",
                },
                required=["structure.xyz", "structure.json"],
            ),
            call_method="SDK",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="Python RDKit 或系统 OpenBabel",
            version="1.0.0",
            validation_metric={"coordinate_accuracy": "validated"},
            owner="computation_team",
            status="active",
            description="基于 RDKit/OpenBabel 的三维分子结构生成，支持 SMILES 到 3D 坐标转换",
            developer_attribution=POLYAGENT_DEVELOPER,
            framework_attributions=[CHEMOS_ATTRIBUTION],
            method_attributions=[
                source_item(
                    "RDKit",
                    "dependency",
                    "RDKit project",
                    "用于 SMILES 解析、三维构象生成和结构文件输出。",
                    "https://www.rdkit.org/",
                    "prominent",
                ),
                source_item(
                    "OpenBabel",
                    "dependency",
                    "Open Babel project",
                    "作为可选结构生成和化学文件转换后端。",
                    "https://openbabel.org/",
                    "prominent",
                ),
            ],
            implementation_notes="PolyAgent 负责任务契约、worker 编排、artifact 和审计；结构处理能力依赖 RDKit/OpenBabel。",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="local_xtb_adapter",
            name="xTB 半经验计算",
            type="simulator",
            algorithm_family="computation",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "universal"],
            task_scope=["COMPUTE_PREDICT"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "smiles": "string - SMILES 表达式（必填）",
                    "charge": "int - 电荷（默认 0，范围 -5~5）",
                    "multiplicity": "int - 自旋多重度（默认 1，范围 1~6）",
                    "method": "string - GFN2-xTB / GFN1-xTB / GFN0-xTB",
                    "solvent": "string - 可选，WATER / ACETONITRILE / TOLUENE 等",
                },
                required=["smiles"],
                constraints={
                    "charge": {"min": -5, "max": 5},
                    "multiplicity": {"min": 1, "max": 6},
                },
                field_defaults={
                    "charge": 0,
                    "multiplicity": 1,
                    "method": "GFN2-xTB",
                    "solvent": "",
                },
                ui_hints={
                    "smiles": {"widget": "text", "placeholder": "CCO"},
                    "method": {"widget": "select"},
                    "solvent": {"widget": "select"},
                    "charge": {"widget": "number"},
                    "multiplicity": {"widget": "number"},
                },
                field_options={
                    "method": ["GFN2-xTB", "GFN1-xTB", "GFN0-xTB"],
                    "solvent": ["", "WATER", "ACETONITRILE", "TOLUENE", "ETHANOL", "METHANOL", "DCM", "THF"],
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "energy_hartree": "float - 总能量（Hartree）",
                    "normal_termination": "bool - 是否正常终止",
                    "xtb_version": "string - xTB 版本号",
                    "runtime_seconds": "float - 运行耗时",
                },
                required=["energy_hartree", "normal_termination"],
            ),
            call_method="SDK",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="系统 xTB + CREST 可执行文件",
            version="1.0.0",
            validation_metric={"energy_mae": "validated"},
            owner="computation_team",
            status="active",
            description="基于 CREST 构象搜索 + xTB 半经验方法的能量计算，支持 GFN2-xTB/GFN1-xTB/GFN0-xTB",
            developer_attribution=POLYAGENT_DEVELOPER,
            framework_attributions=[CHEMOS_ATTRIBUTION],
            method_attributions=[
                source_item(
                    "xTB / CREST",
                    "dependency",
                    "Grimme Lab",
                    "用于半经验量子化学计算与构象搜索。",
                    "https://xtb-docs.readthedocs.io/",
                    "prominent",
                ),
            ],
            implementation_notes="PolyAgent 封装执行、日志、artifact、错误归一和 campaign 回填；量化计算能力来自本地 xTB/CREST。",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="orca_compute_engine_laser_adapter",
            name="ORCA DFT 精加工计算",
            type="simulator",
            algorithm_family="computation",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "universal"],
            task_scope=["COMPUTE_PREDICT"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "smiles": "string - SMILES 表达式（必填）",
                    "charge": "int - 电荷（默认 0）",
                    "multiplicity": "int - 自旋多重度（默认 1）",
                    "method": "string - ORCA_B3LYP_DEF2_SVP / ORCA_PBE0_DEF2_SVP",
                },
                required=["smiles"],
                constraints={
                    "charge": {"min": -5, "max": 5},
                    "multiplicity": {"min": 1, "max": 6},
                },
                field_defaults={
                    "charge": 0,
                    "multiplicity": 1,
                    "method": "ORCA_B3LYP_DEF2_SVP",
                },
                ui_hints={
                    "smiles": {"widget": "text", "placeholder": "CCO"},
                    "method": {"widget": "select"},
                    "charge": {"widget": "number"},
                    "multiplicity": {"widget": "number"},
                },
                field_options={
                    "method": ["ORCA_B3LYP_DEF2_SVP", "ORCA_PBE0_DEF2_SVP"],
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "energy_hartree": "float - FINAL SINGLE POINT ENERGY（Hartree）",
                    "normal_termination": "bool - 是否正常终止",
                },
                required=["energy_hartree", "normal_termination"],
            ),
            call_method="SDK",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="系统 ORCA + xTB + CREST 可执行文件，ORCA license 可用",
            version="1.0.0",
            validation_metric={"energy_accuracy": "DFT-validated"},
            owner="computation_team",
            status="active",
            description="CREST 构象搜索 + xTB 预优化 + ORCA DFT 精加工，提供高精度单点能计算",
            developer_attribution=POLYAGENT_DEVELOPER,
            framework_attributions=[CHEMOS_ATTRIBUTION],
            method_attributions=[
                source_item(
                    "ORCA",
                    "dependency",
                    "ORCA quantum chemistry program",
                    "用于可选 DFT 精加工计算，需本地 license 与执行环境。",
                    "https://orcaforum.kofo.mpg.de/",
                    "prominent",
                ),
                source_item(
                    "xTB / CREST",
                    "dependency",
                    "Grimme Lab",
                    "用于构象搜索和预优化。",
                    "https://xtb-docs.readthedocs.io/",
                ),
            ],
            implementation_notes="PolyAgent 负责任务编排与结果解析；ORCA、xTB 和 CREST 由本地计算环境提供。",
        ),
    ]


# =============================================================================
# Production/Adapter 算法能力清单条目
# =============================================================================


def build_adapter_algorithm_registry() -> list[AlgorithmRegistryEntry]:
    """构建 ResearchEngine 真实适配器能力清单。

    适配器不伪装成内置模型：未配置外部服务或本地索引时返回明确配置状态。

    Returns:
        真实适配器算法能力条目列表。
    """
    return [
        AlgorithmRegistryEntry(
            algorithm_id="weknora_adapter",
            name="WeKnora 知识增强检索",
            type="retriever",
            algorithm_family="knowledge",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["KNOWLEDGE_RETRIEVAL"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "system_id": "string - 知识库体系 ID；由 /knowledge-bases/systems 动态加载",
                    "query": "string - RAG 检索问题或关键词（必填）",
                    "material_family": "string - 材料体系",
                    "target_properties": "list[string] - 目标性质列表",
                    "mode": "string - hybrid/local/global/naive/mix",
                    "top_k": "int - 返回条数（默认 5）",
                    "include_graph_context": "bool - 是否返回图谱上下文",
                },
                required=["query"],
                constraints={"top_k": {"min": 1, "max": 20}},
                field_defaults={
                    "material_family": "fluoropolymer",
                    "target_properties": [],
                    "mode": "hybrid",
                    "top_k": 5,
                    "include_graph_context": True,
                },
                ui_hints={
                    "system_id": {"widget": "select"},
                    "query": {"widget": "textarea", "placeholder": "氟基高分子 介电常数 热稳定性"},
                    "material_family": {"widget": "select"},
                    "target_properties": {"widget": "multiselect"},
                    "mode": {"widget": "select"},
                    "top_k": {"widget": "number"},
                    "include_graph_context": {"widget": "checkbox"},
                },
                field_options={
                    "material_family": ["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
                    "target_properties": ["dielectric_constant", "thermal_stability", "tensile_strength", "conductivity", "elastic_modulus", "hydrophobicity", "glass_transition_temperature"],
                    "mode": ["hybrid", "local", "global", "naive", "mix"],
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "configured": "bool - 是否已配置 WeKnora 知识库服务",
                    "hits": "list[object] - 命中文献片段/知识卡片",
                    "citations": "list[object] - 引用来源",
                    "graph_context": "object - 查询相关图谱上下文",
                    "answer": "string - 基于命中的回答",
                    "message": "string - 配置或检索状态",
                },
                required=["configured", "hits", "answer"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="PolyAgent KnowledgeService；WEKNORA_BASE_URL 指向 WeKnora API 服务",
            version="1.1.0",
            validation_metric={"retrieval": "knowledge_service_contract"},
            owner="research_engine_team",
            status="active",
            description="通过 PolyAgent 知识库服务查询 WeKnora；未配置时明确返回服务不可用。",
            developer_attribution=POLYAGENT_DEVELOPER,
            method_attributions=[
                source_item(
                    "WeKnora",
                    "implementation_source",
                    "Tencent",
                    "提供知识库管理、检索、会话问答和引用证据能力。",
                    "https://github.com/Tencent/WeKnora",
                    visibility="prominent",
                ),
            ],
            implementation_notes="PolyAgent 保留本地契约和审计边界，知识库检索与问答由 WeKnora 提供。",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="knowledge_graph_adapter",
            name="知识图谱子图检索",
            type="retriever",
            algorithm_family="knowledge",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["KNOWLEDGE_RETRIEVAL"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "system_id": "string - 知识库体系 ID；由 /knowledge-bases/systems 动态加载",
                    "query": "string - 子图检索关键词（可选）",
                    "limit": "int - 最大节点数（默认 30）",
                },
                required=[],
                constraints={"limit": {"min": 1, "max": 100}},
                field_defaults={"query": "", "limit": 30},
                ui_hints={
                    "system_id": {"widget": "select"},
                    "query": {"widget": "text", "placeholder": "fluoropolymer dielectric"},
                    "limit": {"widget": "number"},
                },
                field_options={},
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "nodes": "list[object] - 图谱节点",
                    "edges": "list[object] - 图谱关系",
                    "stats": "object - entity/relation/document 统计",
                    "configured": "bool - 图谱服务是否可用",
                    "message": "string - 检索状态",
                },
                required=["nodes", "edges", "stats"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="PolyAgent KnowledgeService graph API；基于 WeKnora 检索结果合成子图，可选 WeKnora Neo4j 增强",
            version="1.0.0",
            validation_metric={"graph_contract": "nodes_edges_stats"},
            owner="research_engine_team",
            status="active",
            description="返回指定知识库体系的查询相关检索子图；配置 Neo4j 后补充实体和关系，供人工 Workflow 和 AutoResearch 证据追溯使用。",
            developer_attribution=POLYAGENT_DEVELOPER,
            method_attributions=[
                source_item(
                    "WeKnora",
                    "implementation_source",
                    "Tencent",
                    "提供知识库检索结果和可选 Neo4j 图谱数据，PolyAgent 将命中文档、片段、实体和关系组织为可视子图。",
                    "https://github.com/Tencent/WeKnora",
                    visibility="prominent",
                ),
            ],
            implementation_notes="PolyAgent 先用 WeKnora 检索命中合成 Paper/Chunk 子图；配置 WEKNORA_NEO4J_* 后按命中 chunk 扩展实体关系，失败自动回退。",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="vertical_predictor_adapter",
            name="垂类性质预测服务",
            type="predictor",
            algorithm_family="vertical_prediction",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["COMPUTE_PREDICT"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "smiles": "string - 单体或重复单元 SMILES（必填）",
                    "target_properties": "list[string] - 目标性质列表（必填）",
                    "material_family": "string - 材料体系",
                    "model_id": "string - 垂类模型 ID（可选）",
                    "features": "dict - 附加特征（可选）",
                },
                required=["smiles", "target_properties"],
                field_defaults={"material_family": "fluoropolymer", "target_properties": ["dielectric_constant"]},
                ui_hints={
                    "smiles": {"widget": "text", "placeholder": "C=C(F)F"},
                    "target_properties": {"widget": "multiselect"},
                    "material_family": {"widget": "select"},
                    "model_id": {"widget": "text"},
                },
                field_options={
                    "material_family": ["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
                    "target_properties": ["dielectric_constant", "thermal_stability", "tensile_strength", "conductivity", "elastic_modulus", "hydrophobicity", "glass_transition_temperature"],
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "predictions": "dict - 预测值",
                    "uncertainty": "dict - 不确定性",
                    "model_id": "string - 实际使用模型",
                    "configured": "bool - 是否已配置模型服务",
                },
                required=["predictions", "configured"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="VERTICAL_PREDICTOR_URL 环境变量指向的模型服务",
            version="1.0.0",
            validation_metric={"service_contract": "configured_at_runtime"},
            owner="model_platform_team",
            status="active",
            description="垂类性质预测服务调用契约；未配置模型服务时返回可操作错误。",
            developer_attribution=source_item(
                "垂类模型服务开发者",
                "developer",
                "模型平台或算法提供方",
                "具体模型开发者来源由接入服务或上传算法包提供；缺失时页面显示文字来源牌。",
                visibility="prominent",
            ),
            method_attributions=[
                source_item(
                    "Vertical Predictor Service",
                    "implementation_source",
                    "PolyAgent / 外部模型服务",
                    "通过 VERTICAL_PREDICTOR_URL 接入垂类性质预测模型服务。",
                    visibility="prominent",
                ),
            ],
            implementation_notes="该条目是模型服务调用契约，具体算法开发者以服务返回或上传包 metadata 为准。",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="mobo_alchemist_adapter",
            name="Alchemist BO/MOBO 优化推荐",
            type="optimizer",
            algorithm_family="wetlab_optimization",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["RECOMMENDATION_ASK"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "problem_spec_id": "string - ProblemSpec ID（可自动填充）",
                    "variables": "list[object] - 搜索变量，兼容 ProblemSpec variables",
                    "objectives": "list[object] - 优化目标定义（必填）",
                    "historical_observations": "list[object] - 历史观测数据",
                    "batch_size": "int - 推荐批次大小（默认 5）",
                    "session_name": "string - Alchemist session 名称",
                },
                required=["objectives"],
                constraints={"batch_size": {"min": 1, "max": 100}},
                field_defaults={"batch_size": 5, "historical_observations": []},
                ui_hints={
                    "problem_spec_id": {"widget": "hidden", "auto_fill": "problem_spec_id"},
                    "variables": {"widget": "json"},
                    "objectives": {"widget": "json"},
                    "historical_observations": {"widget": "json"},
                    "batch_size": {"widget": "number"},
                    "session_name": {"widget": "text"},
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "session_id": "string - Alchemist session ID",
                    "top_k_candidates": "list[object] - 推荐候选",
                    "acquisition_values": "list[float] - 采集函数值",
                    "model_status": "dict - 模型训练状态",
                },
                required=["session_id", "top_k_candidates"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="ALCHEMIST_BACKEND_URL",
            version="1.0.0",
            validation_metric={"recommendation_backend": "alchemist"},
            owner="optimization_team",
            status="active",
            description="调用 Alchemist session/variable/experiment/model/acquisition API 生成 BO/MOBO 推荐。",
            developer_attribution=POLYAGENT_DEVELOPER,
            framework_attributions=[ALCHEMIST_ATTRIBUTION, CHEMOS_ATTRIBUTION],
            method_attributions=[ALCHEMIST_ATTRIBUTION],
            implementation_notes="PolyAgent 负责 AlgorithmRun 契约和 Alchemist API 适配；优化方法来源标注为 ALchemist。",
        ),
    ]


# =============================================================================
# Mock/Preset 算法能力清单条目（演示算法）
# =============================================================================


def build_mock_algorithm_registry() -> list[AlgorithmRegistryEntry]:
    """构建 P0 Mock/Preset 算法能力清单。

    Mock 条目仅用于演示，前端默认隐藏。

    Returns:
        Mock 算法能力条目列表。
    """
    demo_ui_hint = {"_algorithm": {"is_demo": True, "hidden_by_default": True}}
    return [
        AlgorithmRegistryEntry(
            algorithm_id="literature_mock",
            name="文献检索",
            type="retriever",
            algorithm_family="knowledge",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["KNOWLEDGE_RETRIEVAL"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "keywords": "string - 检索关键词（必填）",
                    "material_family": "string - 材料体系",
                    "target_properties": "list[string] - 目标性质列表",
                    "max_results": "int - 最大返回结果数（默认 20）",
                },
                required=["keywords"],
                constraints={"max_results": {"min": 1, "max": 100}},
                field_defaults={"material_family": "fluoropolymer", "target_properties": [], "max_results": 20},
                ui_hints={
                    "keywords": {"widget": "textarea"},
                    "material_family": {"widget": "select"},
                    "target_properties": {"widget": "multiselect"},
                    "max_results": {"widget": "number"},
                    **demo_ui_hint,
                },
                field_options={
                    "material_family": ["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
                    "target_properties": ["dielectric_constant", "thermal_stability", "tensile_strength", "conductivity", "elastic_modulus", "hydrophobicity", "glass_transition_temperature"],
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "knowledge_cards": "list[object] - 知识卡片列表",
                    "candidate_sources": "list[object] - 候选来源",
                    "literature_summary": "string - 文献摘要",
                    "total_results": "int - 检索结果总数",
                },
                required=["knowledge_cards", "literature_summary"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="无特殊依赖",
            version="1.0.0",
            validation_metric={"recall": "mock"},
            owner="research_engine_team",
            status="active",
            description="演示算法：面向材料体系和目标性质的文献检索 mock，返回模拟知识卡片和候选来源",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="polymer_descriptor_mock",
            name="聚合物描述符生成",
            type="predictor",
            algorithm_family="structure",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["STRUCTURE_FEATURE"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "smiles": "string - 单体 SMILES 表达式（必填）",
                    "polymer_type": "string - 聚合物类型（homopolymer/copolymer）",
                    "composition": "dict - 共聚物组成配比（可选）",
                },
                required=["smiles"],
                field_defaults={"polymer_type": "homopolymer"},
                ui_hints={
                    "smiles": {"widget": "text", "placeholder": "C=C(F)F"},
                    "polymer_type": {"widget": "select"},
                    "composition": {"widget": "json"},
                    **demo_ui_hint,
                },
                field_options={"polymer_type": ["homopolymer", "copolymer"]},
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "descriptors": "object - 描述符字典（MW、logP、TPSA、rotatable_bonds 等）",
                    "molecular_weight": "float - 分子量",
                    "logp": "float - 脂水分配系数",
                    "tpsa": "float - 拓扑极性表面积",
                    "rotatable_bonds": "int - 可旋转键数",
                    "h_bond_donors": "int - 氢键供体数",
                    "h_bond_acceptors": "int - 氢键受体数",
                },
                required=["descriptors", "molecular_weight"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="Python RDKit",
            version="1.0.0",
            validation_metric={"descriptor_accuracy": "mock"},
            owner="research_engine_team",
            status="active",
            description="演示算法：基于单体 SMILES 生成聚合物描述符，支持均聚物和共聚物体系",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="property_predictor_mock",
            name="性质预测",
            type="predictor",
            algorithm_family="vertical_prediction",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["COMPUTE_PREDICT"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "smiles": "string - 单体 SMILES 表达式（必填）",
                    "descriptors": "object - 聚合物描述符（可选）",
                    "target_properties": "list[string] - 目标性质列表",
                    "fluorine_content": "float - 氟含量百分比（可选，范围 0-100）",
                    "polymerization_temperature": "float - 聚合温度（可选，范围 20-180）",
                },
                required=["smiles", "target_properties"],
                constraints={
                    "fluorine_content": {"min": 0, "max": 100},
                    "polymerization_temperature": {"min": 20, "max": 180},
                },
                field_options={
                    "target_properties": ["dielectric_constant", "thermal_stability", "tensile_strength", "conductivity", "elastic_modulus", "hydrophobicity", "glass_transition_temperature"],
                },
                field_defaults={"target_properties": ["dielectric_constant"], "fluorine_content": 45.0, "polymerization_temperature": 120.0},
                ui_hints={
                    "smiles": {"widget": "text", "placeholder": "C=C(F)F"},
                    "descriptors": {"widget": "json"},
                    "target_properties": {"widget": "multiselect"},
                    "fluorine_content": {"widget": "number"},
                    "polymerization_temperature": {"widget": "number"},
                    **demo_ui_hint,
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "predictions": "dict - 性质预测值字典",
                    "uncertainty": "dict - 各性质预测的不确定性",
                    "model_version": "string - 模型版本",
                    "confidence_interval": "dict - 置信区间",
                },
                required=["predictions", "uncertainty"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="Python scikit-learn / 预训练模型",
            version="1.0.0",
            validation_metric={"mae": "mock", "r2": "mock"},
            owner="research_engine_team",
            status="active",
            description="演示算法：基于描述符或 SMILES 快速预测目标性质，返回预测值和不确定性",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="mobo_mock",
            name="BO/MOBO 优化推荐",
            type="optimizer",
            algorithm_family="wetlab_optimization",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["RECOMMENDATION_ASK"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "problem_spec_id": "string - ProblemSpec ID（必填）",
                    "historical_observations": "list[object] - 历史 Observation 数据",
                    "candidates": "list[object] - 候选材料列表",
                    "batch_size": "int - 推荐批次大小（默认 10）",
                    "objectives": "list[object] - 优化目标定义",
                    "constraints": "list[object] - 约束条件",
                },
                required=["problem_spec_id", "objectives"],
                field_defaults={"batch_size": 5, "historical_observations": [], "candidates": []},
                ui_hints={
                    "problem_spec_id": {"widget": "hidden", "auto_fill": "problem_spec_id"},
                    "historical_observations": {"widget": "json"},
                    "candidates": {"widget": "json"},
                    "batch_size": {"widget": "number"},
                    "objectives": {"widget": "json"},
                    "constraints": {"widget": "json"},
                    **demo_ui_hint,
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "top_k_candidates": "list[object] - Top-K 候选材料",
                    "pareto_solutions": "list[object] - Pareto 最优解",
                    "recommendation_reasons": "list[string] - 推荐理由",
                    "acquisition_values": "list[float] - 采集函数值",
                    "uncertainty_estimates": "list[float] - 不确定性估计",
                },
                required=["top_k_candidates", "recommendation_reasons"],
            ),
            call_method="REST",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="Python BoTorch / Ax",
            version="1.0.0",
            validation_metric={"top_k_hit_rate": "mock", "hypervolume_improvement": "mock"},
            owner="research_engine_team",
            status="active",
            description="演示算法：基于贝叶斯优化/多目标贝叶斯优化的候选推荐，支持单目标和多目标优化",
        ),
        AlgorithmRegistryEntry(
            algorithm_id="computation_submit_adapter",
            name="计算任务提交",
            type="simulator",
            algorithm_family="computation",
            material_scope=["fluoropolymer", "carbon_polymer", "silicon_polymer", "fluoro_carbon_copolymer", "universal"],
            task_scope=["COMPUTE_PREDICT", "EXPERIMENT_EXECUTION"],
            input_schema=AlgorithmIOSchema(
                fields={
                    "workflow_type": "string - 计算 workflow 类型（LOCAL_STRUCTURE / LOCAL_XTB / ORCA_COMPUTE_ENGINE_LASER）",
                    "smiles": "string - SMILES 表达式（必填）",
                    "engine": "string - 计算引擎",
                    "method": "string - 计算方法",
                    "charge": "int - 电荷（默认 0）",
                    "multiplicity": "int - 自旋多重度（默认 1）",
                    "solvent": "string - 溶剂（可选）",
                    "name": "string - 分子名称（可选）",
                },
                required=["workflow_type", "smiles"],
                field_defaults={
                    "workflow_type": "LOCAL_STRUCTURE",
                    "charge": 0,
                    "multiplicity": 1,
                    "solvent": "",
                    "name": "research-engine-computation",
                },
                ui_hints={
                    "workflow_type": {"widget": "select"},
                    "smiles": {"widget": "text", "placeholder": "CCO"},
                    "engine": {"widget": "hidden"},
                    "method": {"widget": "hidden"},
                    "charge": {"widget": "number"},
                    "multiplicity": {"widget": "number"},
                    "solvent": {"widget": "select"},
                    "name": {"widget": "text"},
                },
                field_options={
                    "workflow_type": ["LOCAL_STRUCTURE", "LOCAL_XTB", "ORCA_COMPUTE_ENGINE_LASER"],
                    "solvent": ["", "WATER", "ACETONITRILE", "TOLUENE", "ETHANOL", "METHANOL", "DCM", "THF"],
                },
            ),
            output_schema=AlgorithmIOSchema(
                fields={
                    "computation_run_id": "string - 创建的 ComputationRun ID",
                    "status": "string - 提交状态",
                    "estimated_duration": "string - 预估耗时",
                },
                required=["computation_run_id", "status"],
            ),
            call_method="SDK",
            trigger_modes=["human_workflow", "autoresearch"],
            runtime_dependency="系统 xTB / CREST / ORCA 可执行文件",
            version="1.0.0",
            validation_metric={"submission_success_rate": "mock"},
            owner="computation_team",
            status="active",
            description="委托给现有 ComputationService 创建 ComputationRun，支持 LOCAL_STRUCTURE、LOCAL_XTB、ORCA_COMPUTE_ENGINE_LASER 三种 workflow",
        ),
    ]


# =============================================================================
# 材料 profile 默认配置
# =============================================================================

DEFAULT_MATERIAL_PROFILES: dict[MaterialScope, dict] = {
    "fluoropolymer": {
        "profile_id": "fluoropolymer",
        "display_name": "氟基高分子",
        "default_algorithm_pipeline": {
            "literature": "weknora_adapter",
            "structure_feature": "polymer_descriptor.default",
            "compute_predict": ["local_xtb_adapter", "fluoropolymer_predictor.v1"],
            "recommender": "mobo.default",
        },
        "key_properties": [
            "dielectric_constant",
            "thermal_stability",
            "fluorine_content",
            "glass_transition_temperature",
        ],
        "typical_variables": [
            "monomer_smiles",
            "fluorine_content",
            "polymerization_temperature",
            "crosslinking_density",
        ],
    },
    "carbon_polymer": {
        "profile_id": "carbon_polymer",
        "display_name": "碳基高分子",
        "default_algorithm_pipeline": {
            "literature": "weknora_adapter",
            "structure_feature": "polymer_descriptor.default",
            "compute_predict": ["local_xtb_adapter"],
            "recommender": "mobo.default",
        },
        "key_properties": [
            "tensile_strength",
            "thermal_stability",
            "conductivity",
        ],
    },
    "silicon_polymer": {
        "profile_id": "silicon_polymer",
        "display_name": "硅基高分子",
        "default_algorithm_pipeline": {
            "literature": "weknora_adapter",
            "structure_feature": "polymer_descriptor.default",
            "compute_predict": ["local_xtb_adapter"],
            "recommender": "mobo.default",
        },
        "key_properties": [
            "thermal_stability",
            "elastic_modulus",
            "hydrophobicity",
        ],
    },
    "fluoro_carbon_copolymer": {
        "profile_id": "fluoro_carbon_copolymer",
        "display_name": "含氟-碳共聚体系",
        "default_algorithm_pipeline": {
            "literature": "weknora_adapter",
            "structure_feature": "polymer_descriptor.default",
            "compute_predict": ["local_xtb_adapter", "fluoropolymer_predictor.v1"],
            "recommender": "mobo.default",
        },
        "key_properties": [
            "dielectric_constant",
            "thermal_stability",
            "mechanical_strength",
            "fluorine_distribution",
        ],
    },
    "universal": {
        "profile_id": "universal",
        "display_name": "通用材料",
        "default_algorithm_pipeline": {
            "literature": "weknora_adapter",
            "structure_feature": "polymer_descriptor.default",
            "compute_predict": ["local_xtb_adapter"],
            "recommender": "mobo.default",
        },
    },
}


# =============================================================================
# 氟基高分子样板 ProblemSpec
# =============================================================================

def build_fluoropolymer_demo_problem_spec(created_by: str = "demo") -> dict:
    """构建氟基高分子样板 ProblemSpec。

    用于 P0 验收和演示，提供完整的变量、目标、约束定义。

    Args:
        created_by: 创建者标识。

    Returns:
        ProblemSpec 创建请求字典。
    """
    return {
        "name": "氟基高分子电解质材料优化演示",
        "material_family": "fluoropolymer",
        "problem_type": "formulation_process_optimization",
        "allowed_execution_modes": ["manual_workbench", "autoresearch"],
        "decision_status": "pending_execution_decision",
        "variables": [
            {
                "name": "monomer_smiles",
                "type": "categorical",
                "role": "structure",
                "categories": [
                    "C=CF",
                    "C=C(F)F",
                    "FC(F)=C(F)F",
                ],
                "description": "氟基单体 SMILES",
            },
            {
                "name": "fluorine_content",
                "type": "continuous",
                "role": "formulation",
                "unit": "percent",
                "bounds": [0.0, 100.0],
                "description": "氟含量百分比",
            },
            {
                "name": "polymerization_temperature",
                "type": "continuous",
                "role": "process",
                "unit": "celsius",
                "bounds": [20.0, 180.0],
                "description": "聚合温度",
            },
        ],
        "objectives": [
            {
                "name": "dielectric_constant",
                "direction": "maximize",
                "unit": "dimensionless",
                "description": "介电常数",
            },
            {
                "name": "thermal_stability",
                "direction": "maximize",
                "unit": "celsius",
                "description": "热稳定性（TGA 分解温度）",
            },
        ],
        "constraints": [
            {
                "name": "synthesizable",
                "type": "hard",
                "description": "合成可行性约束",
            },
            {
                "name": "equipment_temperature_limit",
                "type": "hard",
                "expression": "polymerization_temperature <= 180",
                "description": "设备温度上限",
            },
        ],
        "measurements": [
            {
                "name": "dielectric_constant",
                "condition": "room_temperature",
                "method": "impedance_spectroscopy",
            },
            {
                "name": "thermal_stability",
                "method": "TGA",
            },
        ],
        "description": "氟基高分子电解质材料的多目标优化演示任务，用于验证 ResearchEngine P0 双通道闭环。",
        "created_by": created_by,
    }


# =============================================================================
# 状态转移校验辅助
# =============================================================================

def get_default_stage_contract(stage_key: ResearchStageKey) -> StageGate | None:
    """获取指定阶段的默认 StageContract。

    Args:
        stage_key: 阶段标识。

    Returns:
        对应的 StageGate，若阶段不在默认序列中则返回 None。
    """
    return DEFAULT_STAGE_CONTRACTS.get(stage_key)


def is_p0_gate_stage(stage_key: ResearchStageKey) -> bool:
    """判断指定阶段是否需要 P0 默认人工审批。

    Args:
        stage_key: 阶段标识。

    Returns:
        是否需要人工审批。
    """
    return stage_key in P0_GATE_STAGES
