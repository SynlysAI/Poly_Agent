"""ResearchEngine Mock 算法执行器。

实现 P0 人工算法通道所需的 BaseMockRunner 基类及 5 个 mock runner。
所有 mock runner 通过 algorithm_id 路由到对应实现，
每个 mock 返回确定性输出（相同输入 → 相同输出），可被测试断言。
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone

from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import AlgorithmRegistryRepository


class BaseMockRunner:
    """Mock 算法执行器基类。

    子类需设置 algorithm_id 并实现 run() 方法。
    所有 mock runner 共享输入校验、输出序列化和 artifact 生成逻辑。
    """

    algorithm_id: str = ""  # 子类设置

    def validate_input(self, input_snapshot: dict) -> None:
        """按 AlgorithmRegistryEntry.input_schema 校验输入。

        校验必填字段是否存在、基础类型和边界约束。

        Args:
            input_snapshot: 用户提交的输入快照。

        Raises:
            ValueError: 输入校验失败。
        """
        entry = AlgorithmRegistryRepository.find_one({"algorithm_id": self.algorithm_id})
        if entry is None:
            raise ValueError(f"算法 '{self.algorithm_id}' 未在 AlgorithmRegistry 中注册")

        input_schema = entry.get("input_schema", {})
        required_fields = input_schema.get("required", [])

        for field in required_fields:
            if field not in input_snapshot or input_snapshot.get(field) is None:
                raise ValueError(f"缺少必填字段: '{field}'")

        # 校验边界约束
        constraints = input_schema.get("constraints", {})
        for field_name, constraint in constraints.items():
            if field_name not in input_snapshot or input_snapshot[field_name] is None:
                continue
            value = input_snapshot[field_name]
            if "min" in constraint and value < constraint["min"]:
                raise ValueError(
                    f"字段 '{field_name}' 值 {value} 小于最小值 {constraint['min']}"
                )
            if "max" in constraint and value > constraint["max"]:
                raise ValueError(
                    f"字段 '{field_name}' 值 {value} 大于最大值 {constraint['max']}"
                )

    def run(self, input_snapshot: dict) -> dict:
        """执行 mock 逻辑，返回 output_summary。

        Args:
            input_snapshot: 校验后的输入快照。

        Returns:
            结构化输出摘要字典。

        Raises:
            NotImplementedError: 子类必须实现此方法。
        """
        raise NotImplementedError

    def get_artifact_specs(self, output_summary: dict) -> list[dict]:
        """从 output_summary 生成 artifact 规格。

        Args:
            output_summary: run() 返回的输出摘要。

        Returns:
            artifact 规格列表，每项包含 type、name、content 等字段。
        """
        return [
            {
                "type": "json_artifact",
                "name": f"{self.algorithm_id}_output",
                "content": json.dumps(output_summary, ensure_ascii=False, indent=2),
                "content_type": "application/json",
                "description": f"{self.algorithm_id} mock 算法运行输出",
            }
        ]

    # ------------------------------------------------------------------
    # 确定性随机工具
    # ------------------------------------------------------------------

    @staticmethod
    def _seeded_random(seed_str: str) -> random.Random:
        """从输入生成确定性随机数生成器。

        Args:
            seed_str: 种子字符串（来自输入快照的关键字段）。

        Returns:
            确定性 random.Random 实例。
        """
        seed_hash = hashlib.sha256(seed_str.encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_hash[:8], byteorder="big")
        return random.Random(seed_int)


# =============================================================================
# 1. literature_mock：文献检索
# =============================================================================


class LiteratureMockRunner(BaseMockRunner):
    """文献检索 mock 执行器。

    模拟面向材料体系和目标性质的文献检索，
    返回确定性生成的 knowledge cards 和候选来源。
    """

    algorithm_id = "literature_mock"

    def run(self, input_snapshot: dict) -> dict:
        """执行文献检索 mock 逻辑。

        Args:
            input_snapshot: 包含 keywords、material_family、target_properties 等字段。

        Returns:
            包含 knowledge_cards、candidate_sources、literature_summary 的输出摘要。
        """
        keywords = input_snapshot.get("keywords", "")
        material_family = input_snapshot.get("material_family", "fluoropolymer")
        target_properties = input_snapshot.get("target_properties", [])
        max_results = input_snapshot.get("max_results", 20)

        rng = self._seeded_random(keywords)

        # 模拟知识卡片
        paper_templates = [
            {
                "title": f"基于{keywords}的新型{material_family}材料的合成与表征",
                "authors": ["Zhang W.", "Li X.", "Wang Y."],
                "year": 2024,
                "abstract": f"本研究探索了{keywords}在{material_family}体系中的应用，"
                f"通过系统的合成和表征方法，评估了材料的热稳定性、介电性能和力学强度。",
                "relevance_score": round(0.85 + rng.random() * 0.14, 2),
            },
            {
                "title": f"{material_family}电解质的多尺度计算研究",
                "authors": ["Chen L.", "Liu H.", "Zhao M."],
                "year": 2023,
                "abstract": f"采用第一性原理计算和分子动力学模拟，系统研究了{material_family}"
                f"电解质的离子传导机制和界面稳定性，为电解质设计提供了理论指导。",
                "relevance_score": round(0.78 + rng.random() * 0.21, 2),
            },
            {
                "title": f"机器学习辅助的{material_family}材料性能预测",
                "authors": ["Kim J.", "Park S."],
                "year": 2024,
                "abstract": f"基于图神经网络和迁移学习，构建了{material_family}材料性质预测模型，"
                f"覆盖介电常数、热稳定性和机械强度等关键性能指标。",
                "relevance_score": round(0.72 + rng.random() * 0.27, 2),
            },
            {
                "title": f"面向{keywords}的高通量筛选研究进展",
                "authors": ["Anderson R.", "Brown T.", "Davis K."],
                "year": 2023,
                "abstract": f"综述了近年来在{keywords}领域的高通量实验和计算方法，"
                f"讨论了不同{material_family}候选材料的筛选策略和优化方向。",
                "relevance_score": round(0.65 + rng.random() * 0.30, 2),
            },
            {
                "title": f"{material_family}材料的失效机制与寿命预测",
                "authors": ["Tanaka H.", "Suzuki K."],
                "year": 2022,
                "abstract": f"通过加速老化实验和多物理场模拟，分析了{material_family}材料"
                f"在不同工况下的失效模式，建立了寿命预测模型。",
                "relevance_score": round(0.60 + rng.random() * 0.25, 2),
            },
        ]

        # 按相关度排序并限制数量
        papers = sorted(paper_templates, key=lambda p: p["relevance_score"], reverse=True)
        papers = papers[: min(max_results, len(papers))]

        # 生成候选来源
        candidate_sources = []
        if "SMILES" in keywords.upper() or "结构" in keywords:
            candidate_sources.append({
                "source_type": "patent",
                "identifier": "CN2024XXXXXX",
                "description": f"专利中披露的{material_family}单体结构",
                "smiles_hints": ["C=CF", "C=C(F)F", "FC(F)=C(F)F"],
            })
        if "氟" in keywords or "fluorine" in keywords.lower():
            candidate_sources.append({
                "source_type": "database",
                "identifier": "FluoroBase-2024",
                "description": "氟基高分子数据库，收录 1,200+ 单体结构",
                "entry_count": 1250,
            })
        candidate_sources.append({
            "source_type": "literature",
            "identifier": f"review-{material_family}-2024",
            "description": f"{material_family}材料体系综述中的候选分子列表",
        })

        # 文献摘要
        prop_str = "、".join(target_properties) if target_properties else "关键性能"
        literature_summary = (
            f"针对'{keywords}'的文献检索共发现 {len(papers)} 篇相关论文，"
            f"涉及{material_family}材料体系的{prop_str}。"
            f"其中 3 篇来自 2024 年的最新研究，覆盖合成、计算和机器学习方法。"
            f"建议重点关注基于 GNN 的性质预测和基于 DFT 的计算验证方法。"
        )

        return {
            "knowledge_cards": papers,
            "candidate_sources": candidate_sources,
            "literature_summary": literature_summary,
            "total_results": len(papers),
        }


# =============================================================================
# 2. polymer_descriptor_mock：聚合物描述符生成
# =============================================================================


class PolymerDescriptorMockRunner(BaseMockRunner):
    """聚合物描述符生成 mock 执行器。

    模拟基于单体 SMILES 的聚合物描述符计算，
    返回确定性生成的分子描述符字典。
    """

    algorithm_id = "polymer_descriptor_mock"

    def run(self, input_snapshot: dict) -> dict:
        """执行描述符生成 mock 逻辑。

        基于 SMILES 字符串的哈希值生成确定性描述符。

        Args:
            input_snapshot: 包含 smiles、polymer_type、composition 等字段。

        Returns:
            包含 descriptors、molecular_weight、logp、tpsa 等字段的输出摘要。
        """
        smiles = input_snapshot.get("smiles", "")
        polymer_type = input_snapshot.get("polymer_type", "homopolymer")

        rng = self._seeded_random(smiles)

        # 基于 SMILES 长度和哈希映射生成有意义的描述符
        smiles_len = len(smiles)

        # 分子量估算（基于 SMILES 长度和字符类型）
        base_mw = 100.0 + smiles_len * 15.5 + rng.random() * 50.0
        if polymer_type == "copolymer":
            base_mw *= 1.5

        mw = round(base_mw, 2)
        logp = round(1.0 + smiles_len * 0.12 + rng.random() * 1.5, 2)
        tpsa = round(20.0 + smiles_len * 3.5 + rng.random() * 25.0, 2)
        num_rotatable_bonds = max(1, int(smiles_len * 0.15 + rng.random() * 3))
        num_h_acceptors = max(1, int(smiles_len * 0.10 + rng.random() * 2))
        num_h_donors = max(0, int(smiles_len * 0.06 + rng.random() * 1))
        num_heavy_atoms = max(2, int(smiles_len * 0.20 + rng.random() * 4))
        num_rings = max(0, int(smiles_len * 0.04 + rng.random() * 1))
        fraction_sp3 = round(0.3 + rng.random() * 0.4, 2)
        molar_refractivity = round(base_mw * 0.28 + rng.random() * 10.0, 2)

        # 生成指纹位列表（确定性）
        fingerprint_bits = sorted(
            [int(rng.random() * 2048) for _ in range(32 + int(smiles_len * 0.5))]
        )[:64]

        descriptors = {
            "molecular_weight": mw,
            "logp": logp,
            "tpsa": tpsa,
            "num_rotatable_bonds": num_rotatable_bonds,
            "num_h_acceptors": num_h_acceptors,
            "num_h_donors": num_h_donors,
            "num_heavy_atoms": num_heavy_atoms,
            "num_rings": num_rings,
            "fraction_sp3": fraction_sp3,
            "molar_refractivity": molar_refractivity,
        }

        return {
            "descriptors": descriptors,
            "molecular_weight": mw,
            "logp": logp,
            "tpsa": tpsa,
            "rotatable_bonds": num_rotatable_bonds,
            "h_bond_donors": num_h_donors,
            "h_bond_acceptors": num_h_acceptors,
            "fingerprint_bits": fingerprint_bits,
            "polymer_type": polymer_type,
        }


# =============================================================================
# 3. property_predictor_mock：性质预测
# =============================================================================


class PropertyPredictorMockRunner(BaseMockRunner):
    """性质预测 mock 执行器。

    模拟基于描述符或 SMILES 的目标性质预测，
    返回预测值和不确定性估计。
    """

    algorithm_id = "property_predictor_mock"

    # 各性质的基准值和缩放因子
    _PROPERTY_BASES: dict[str, tuple[float, float]] = {
        "dielectric_constant": (3.5, 8.0),
        "thermal_stability": (280.0, 120.0),
        "fluorine_content": (35.0, 40.0),
        "glass_transition_temperature": (120.0, 80.0),
        "tensile_strength": (45.0, 25.0),
        "conductivity": (0.001, 0.01),
        "elastic_modulus": (2.5, 1.5),
        "hydrophobicity": (110.0, 25.0),
        "cost": (500.0, 300.0),
    }

    def run(self, input_snapshot: dict) -> dict:
        """执行性质预测 mock 逻辑。

        基于 SMILES 哈希和氟含量等输入生成确定性预测结果。

        Args:
            input_snapshot: 包含 smiles、target_properties、fluorine_content 等字段。

        Returns:
            包含 predictions、uncertainty、confidence_interval 等字段的输出摘要。
        """
        smiles = input_snapshot.get("smiles", "")
        target_properties = input_snapshot.get("target_properties", [])
        fluorine_content = input_snapshot.get("fluorine_content", 30.0)
        polymerization_temperature = input_snapshot.get("polymerization_temperature", 120.0)

        rng = self._seeded_random(smiles)
        smiles_len = len(smiles)

        predictions: dict[str, float] = {}
        uncertainty: dict[str, float] = {}
        confidence_interval: dict[str, dict[str, float]] = {}

        for prop_name in target_properties:
            base, scale = self._PROPERTY_BASES.get(prop_name, (50.0, 50.0))

            # 基于 SMILES 哈希和输入参数的确定性预测
            f_content_effect = (fluorine_content - 30.0) * 0.02 if "fluorine" in smiles.lower() or "F" in smiles else 0.0
            temp_effect = (polymerization_temperature - 100.0) * 0.005

            predicted = base + rng.random() * scale + f_content_effect + temp_effect
            predicted = round(max(0.0, predicted), 4)

            # 不确定性通常为预测值的 5-15%
            uncertainty_pct = 0.05 + rng.random() * 0.10
            unc = round(predicted * uncertainty_pct, 4)

            predictions[prop_name] = predicted
            uncertainty[prop_name] = unc
            confidence_interval[prop_name] = {
                "lower": round(predicted - 1.96 * unc, 4),
                "upper": round(predicted + 1.96 * unc, 4),
                "confidence_level": 0.95,
            }

        # 生成重要性分析
        importance = []
        if smiles_len > 0:
            importance.append({
                "feature": "SMILES 分子指纹",
                "importance": round(0.3 + rng.random() * 0.3, 3),
            })
        if fluorine_content > 0:
            importance.append({
                "feature": "氟含量",
                "importance": round(0.15 + rng.random() * 0.2, 3),
            })
        if polymerization_temperature > 0:
            importance.append({
                "feature": "聚合温度",
                "importance": round(0.10 + rng.random() * 0.15, 3),
            })

        return {
            "predictions": predictions,
            "uncertainty": uncertainty,
            "model_version": "mock-predictor-v1.0.0",
            "confidence_interval": confidence_interval,
            "feature_importance": importance,
        }


# =============================================================================
# 4. mobo_mock：BO/MOBO 优化推荐
# =============================================================================


class MOBOMockRunner(BaseMockRunner):
    """BO/MOBO 优化推荐 mock 执行器。

    模拟基于贝叶斯优化的候选材料推荐，
    返回 Top-K 候选、Pareto 解及推荐理由。
    """

    algorithm_id = "mobo_mock"

    def run(self, input_snapshot: dict) -> dict:
        """执行 BO/MOBO 推荐 mock 逻辑。

        基于 problem_spec 中的目标和约束生成确定性 Top-K 候选。

        Args:
            input_snapshot: 包含 problem_spec_id、objectives、constraints 等字段。

        Returns:
            包含 top_k_candidates、pareto_solutions、recommendation_reasons 的输出摘要。
        """
        problem_spec_id = input_snapshot.get("problem_spec_id", "ps_unknown")
        objectives = input_snapshot.get("objectives", [])
        batch_size = input_snapshot.get("batch_size", 5)

        rng = self._seeded_random(problem_spec_id)

        # 模拟候选材料
        candidate_templates = [
            {
                "smiles": "C=CF",
                "name": "氟乙烯均聚物",
                "formula_description": "poly(vinyl fluoride)",
            },
            {
                "smiles": "C=C(F)F",
                "name": "偏氟乙烯均聚物",
                "formula_description": "poly(vinylidene fluoride)",
            },
            {
                "smiles": "FC(F)=C(F)F",
                "name": "全氟丙烯均聚物",
                "formula_description": "poly(hexafluoropropylene)",
            },
            {
                "smiles": "C=C(F)C(=O)O",
                "name": "氟代丙烯酸酯聚合物",
                "formula_description": "poly(fluoroacrylate)",
            },
            {
                "smiles": "C=CF.C=C(F)F",
                "name": "氟乙烯-偏氟乙烯共聚物",
                "formula_description": "poly(VF-co-VDF)",
            },
        ]

        candidates = []
        for i in range(min(batch_size, len(candidate_templates) * 2)):
            template = candidate_templates[i % len(candidate_templates)]
            rank = i + 1

            # 生成预测值
            predicted_values: dict[str, float] = {}
            for obj in objectives:
                obj_name = obj.get("name", f"property_{i}")
                direction = obj.get("direction", "maximize")
                # 不同候选有不同评分
                base_score = 0.5 + rng.random() * 0.5
                # 排名靠前的候选得分更高
                rank_bonus = max(0, (batch_size - rank) / batch_size * 0.3)
                predicted = round(base_score * (0.7 + rank_bonus), 4)
                predicted_values[obj_name] = predicted

            candidates.append({
                "rank": rank,
                "smiles": template["smiles"],
                "name": template["name"],
                "formula_description": template["formula_description"],
                "predicted_values": predicted_values,
                "reason": f"候选 #{rank}：{template['name']} 在多个目标上表现均衡，"
                f"合成路径成熟，适合首轮实验验证",
                "acquisition_value": round(0.5 + rng.random() * 0.5, 4),
            })

        # Pareto 前端（取排名前 3 的候选）
        pareto = [c for c in candidates[:3]]

        # 推荐理由汇总
        recommendation_reasons = [
            f"基于 {len(objectives)} 个优化目标的 MOBO 分析，推荐 {len(candidates)} 个候选材料",
            f"排名前三的候选覆盖了 {objectives[0].get('name', '目标1')} 的高值区域" if objectives else "",
            "建议优先实验验证排名 Top-3 的候选，以快速探索 Pareto 前沿",
            "所有推荐候选的合成路径均经过合成可行性评估",
        ]

        return {
            "top_k_candidates": candidates,
            "pareto_solutions": pareto,
            "recommendation_reasons": [r for r in recommendation_reasons if r],
            "acquisition_values": [c["acquisition_value"] for c in candidates],
            "uncertainty_estimates": [round(0.05 + rng.random() * 0.15, 4) for _ in candidates],
            "optimization_method": "qNEHVI (q-Noisy Expected Hypervolume Improvement)",
        }


# =============================================================================
# 5. computation_submit_adapter：计算任务提交适配器
# =============================================================================


class ComputationSubmitAdapter(BaseMockRunner):
    """计算任务提交适配器。

    委托给现有 ComputationService 创建 ComputationRun，
    不重新实现计算系统。将返回的 run_id 填入 output_summary。
    """

    algorithm_id = "computation_submit_adapter"

    def validate_input(self, input_snapshot: dict) -> None:
        """校验计算任务的输入。

        额外校验 workflow_type 必须是受支持的 workflow。

        Args:
            input_snapshot: 包含 workflow_type、smiles、engine 等字段。

        Raises:
            ValueError: 输入校验失败。
        """
        super().validate_input(input_snapshot)

        allowed_workflows = {"LOCAL_STRUCTURE", "LOCAL_XTB", "ORCA_COMPUTE_ENGINE_LASER"}
        workflow_type = input_snapshot.get("workflow_type", "")
        if workflow_type not in allowed_workflows:
            raise ValueError(
                f"不支持的 workflow_type: '{workflow_type}'，"
                f"允许的值: {', '.join(sorted(allowed_workflows))}"
            )

    def run(self, input_snapshot: dict) -> dict:
        """创建计算任务并返回 ComputationRun 引用。

        注意：此方法只返回 output_summary 结构，
        实际的 ComputationRun 创建由 AlgorithmRun service 层调用
        ComputationService.create_run() 完成。
        此 runner 仅负责校验和构建输出摘要模板。

        Args:
            input_snapshot: 计算任务输入。

        Returns:
            包含 computation_run_id 的输出摘要（由 service 层填充）。
        """
        workflow_type = input_snapshot.get("workflow_type", "LOCAL_XTB")
        smiles = input_snapshot.get("smiles", "")

        # 预估计算耗时
        estimated_durations = {
            "LOCAL_STRUCTURE": "1-3 分钟",
            "LOCAL_XTB": "10-30 分钟",
            "ORCA_COMPUTE_ENGINE_LASER": "1-6 小时",
        }

        return {
            "computation_run_id": "",  # 由 service 层创建 ComputationRun 后填充
            "status": "submitted",
            "workflow_type": workflow_type,
            "smiles": smiles,
            "estimated_duration": estimated_durations.get(workflow_type, "未知"),
            "message": "ComputationRun 已通过 ComputationService 创建，"
            "AlgorithmRun 保存 linked_computation_run_id 指向 ComputationRun",
        }


# =============================================================================
# Runner 注册表与路由
# =============================================================================

# algorithm_id -> runner 实例的映射
_RUNNER_REGISTRY: dict[str, BaseMockRunner] = {}


def _build_registry() -> dict[str, BaseMockRunner]:
    """构建 runner 注册表。

    Returns:
        algorithm_id 到 runner 实例的映射字典。
    """
    runners: list[BaseMockRunner] = [
        LiteratureMockRunner(),
        PolymerDescriptorMockRunner(),
        PropertyPredictorMockRunner(),
        MOBOMockRunner(),
        ComputationSubmitAdapter(),
    ]
    return {r.algorithm_id: r for r in runners}


def get_runner(algorithm_id: str) -> BaseMockRunner | None:
    """根据 algorithm_id 获取对应的 mock runner。

    Args:
        algorithm_id: 算法标识。

    Returns:
        对应的 BaseMockRunner 实例，若找不到则返回 None。
    """
    if not _RUNNER_REGISTRY:
        _RUNNER_REGISTRY.update(_build_registry())
    return _RUNNER_REGISTRY.get(algorithm_id)


def get_available_runner_ids() -> list[str]:
    """获取所有已注册的 runner algorithm_id 列表。

    Returns:
        algorithm_id 列表。
    """
    if not _RUNNER_REGISTRY:
        _RUNNER_REGISTRY.update(_build_registry())
    return list(_RUNNER_REGISTRY.keys())
