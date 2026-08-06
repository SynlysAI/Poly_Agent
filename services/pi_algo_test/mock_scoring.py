"""PI 合成难度评分 Mock 引擎（轻量确定性实现）。

按同目录 PI_synthesis_difficulty_scoring_rules_v1.0.json 的工艺区间
对 diamine/dianhydride/solvent 组合做确定性打分，输出与评分规则 JSON
required_model_output_schema 对齐的结构化结果，并额外携带
difficulty_score / recommended_parameters / selected_process 等
供平台实验模板与下发配置直接使用。

算法是 mock：内部逻辑为输入特征哈希派生的确定性打分；
后续接入真实评分算法时只需替换本模块实现，HTTP 接口契约保持不变。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).resolve().parent / "PI_synthesis_difficulty_scoring_rules_v1.0.json"

# 维度与子维度上限（与评分规则 JSON 保持一致）
R_MAX, H_MAX, S_MAX, U_MAX = 35, 25, 25, 15
R_DI_MAX, R_DA_MAX = 20, 15
H_DI_MAX, H_DA_MAX, H_CONF_MAX, H_ASYM_MAX = 8, 8, 5, 4
S_MONOMER_MAX, S_POLYMER_MAX, S_VISCOSITY_MAX = 10, 8, 7
U_WATER_MAX, U_OXIDATION_MAX, U_THERMAL_MAX, U_GEL_MAX = 5, 3, 3, 4

WATER_DELTA = {"high": 2, "wet": 2, "unknown": 1, "low": 0, "dry": -1}

_cached_rules: dict[str, Any] | None = None


def load_rules() -> dict[str, Any]:
    """加载评分规则 JSON（首次调用后缓存）。"""
    global _cached_rules
    if _cached_rules is None:
        if not RULES_PATH.exists():
            raise FileNotFoundError(f"评分规则文件不存在: {RULES_PATH}")
        _cached_rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return _cached_rules


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _split_with_caps(total: int, weights: tuple[float, ...], caps: tuple[int, ...]) -> list[int]:
    """按权重把 total 拆成若干部分，保证 sum(parts) == total 且 parts[i] <= caps[i]。"""
    parts = [int(total * weight) for weight in weights]
    remainder = total - sum(parts)
    for index in range(len(parts)):
        if remainder <= 0:
            break
        if parts[index] < caps[index]:
            parts[index] += 1
            remainder -= 1
    if remainder > 0:
        for index in range(len(parts)):
            if remainder <= 0:
                break
            add = min(remainder, caps[index] - parts[index])
            if add > 0:
                parts[index] += add
                remainder -= add
    if sum(parts) != total:
        raise AssertionError(f"拆分结果不等于总量: {parts} != {total}")
    return parts


def _select_process(total_d: int, rules: dict[str, Any]) -> dict[str, Any]:
    """按评分规则 JSON 的 initial_mapping 与 process_packages 选择工艺包。"""
    mapping = rules["selection_algorithm"]["initial_mapping"]
    packages = {item["process_id"]: item for item in rules["process_packages"]}
    process_id = None
    for item in mapping:
        if item["D_min"] <= total_d <= item["D_max"]:
            process_id = item["process_id"]
            break
    if process_id is None:
        raise ValueError(f"难度分 {total_d} 未命中任何工艺区间")
    package = packages[process_id]
    return {
        "process_id": process_id,
        "temperature_c": package["temperature_c"],
        "reaction_time_h": package["reaction_time_h"],
        "solvent_volume_ml": package["solvent_volume_ml"],
    }


def score(input_snapshot: dict[str, Any]) -> dict[str, Any]:
    """对 PI 单体组合做确定性评分，返回完整输出契约 JSON。"""
    diamine = str(input_snapshot.get("diamine") or "").strip()
    dianhydride = str(input_snapshot.get("dianhydride") or "").strip()
    solvent = str(input_snapshot.get("solvent") or "").strip()
    if not diamine or not dianhydride or not solvent:
        raise ValueError("diamine/dianhydride/solvent 为必填字段")

    rules = load_rules()
    digest = hashlib.sha256(f"{diamine}|{dianhydride}|{solvent}".encode("utf-8")).digest()
    hash_value = int.from_bytes(digest[:8], "big")

    # 基础分：由输入派生 D（5..100），再按 R/H/S/U = 35/25/25/15 权重拆分
    base_d = 5 + (hash_value % 96)
    r, h_score, s_score, u_score = _split_with_caps(
        base_d, (0.35, 0.25, 0.25, 0.15), (R_MAX, H_MAX, S_MAX, U_MAX)
    )

    # 可选字段修正（溶解度/水分/惰性气氛），保持 D = R+H+S+U
    s_delta = 0
    for key in ("diamine_solubility", "dianhydride_solubility"):
        value = input_snapshot.get(key)
        if isinstance(value, (int, float)):
            s_delta += _clamp(int(value) - 2, -2, 3)
    s_score = _clamp(s_score + _clamp(s_delta, -4, 4), 0, S_MAX)

    u_delta = WATER_DELTA.get(str(input_snapshot.get("water_content_status") or "").strip().lower(), 0)
    if input_snapshot.get("inert_atmosphere_status") is False:
        u_delta += 1
    u_score = _clamp(u_score + _clamp(u_delta, -2, 2), 0, U_MAX)

    total_d = r + h_score + s_score + u_score
    selected = _select_process(total_d, rules)

    # 子维度拆分
    r_di, r_da = _split_with_caps(r, (0.55, 0.45), (R_DI_MAX, R_DA_MAX))
    h_di, h_da, h_conf, h_asym = _split_with_caps(
        h_score, (0.3, 0.3, 0.2, 0.2), (H_DI_MAX, H_DA_MAX, H_CONF_MAX, H_ASYM_MAX)
    )
    s_monomer, s_polymer, s_viscosity = _split_with_caps(
        s_score, (0.4, 0.3, 0.3), (S_MONOMER_MAX, S_POLYMER_MAX, S_VISCOSITY_MAX)
    )
    u_water, u_oxidation, u_thermal, u_gel = _split_with_caps(
        u_score, (0.3, 0.2, 0.2, 0.3), (U_WATER_MAX, U_OXIDATION_MAX, U_THERMAL_MAX, U_GEL_MAX)
    )

    risk_tags: list[str] = []
    if s_score >= 17:
        risk_tags.append("POOR_SOLUBILITY")
    if s_viscosity >= 5:
        risk_tags.append("FAST_VISCOSITY")
    if u_water >= 5:
        risk_tags.append("HYDROLYSIS_RISK")
    if u_oxidation >= 2:
        risk_tags.append("OXIDATION_RISK")
    if u_gel >= 4:
        risk_tags.append("GEL_RISK")
    if r <= 8:
        risk_tags.append("HIGH_EXOTHERM")
    if h_score >= 17:
        risk_tags.append("HIGH_STERIC")

    evidence = [
        f"mock 确定性评分：由 diamine='{diamine}', dianhydride='{dianhydride}', solvent='{solvent}' 派生基础分",
        "评分规则来源：PI_synthesis_difficulty_scoring_rules_v1.0.json（随服务分发）",
    ]
    chemical_d = r + h_score
    physical_d = s_score + u_score

    return {
        "assessment_version": "pi_synthesis_mock@1.0.0",
        "input": {
            "diamine_id": diamine,
            "dianhydride_id": dianhydride,
            "solvent": solvent,
        },
        "score_details": {
            "R": {
                "R_DI_base": r_di,
                "R_DI_corrections": [],
                "R_DI": r_di,
                "R_DA_base": r_da,
                "R_DA_corrections": [],
                "R_DA": r_da,
                "R_total": r,
            },
            "H": {
                "H_DI": h_di,
                "H_DA": h_da,
                "H_conf": h_conf,
                "H_asym": h_asym,
                "H_total": h_score,
                "evidence": evidence,
            },
            "S": {
                "S_monomer": s_monomer,
                "S_polymer": s_polymer,
                "S_viscosity": s_viscosity,
                "S_total": s_score,
                "evidence": evidence,
            },
            "U": {
                "U_water": u_water,
                "U_oxidation": u_oxidation,
                "U_thermal": u_thermal,
                "U_gel": u_gel,
                "U_total": u_score,
                "evidence": evidence,
            },
        },
        "calculation": {
            "chemical_difficulty_C": chemical_d,
            "physical_execution_difficulty_P": physical_d,
            "total_difficulty_D": total_d,
            "formula_check": f"R({r})+H({h_score})+S({s_score})+U({u_score})={total_d}",
        },
        "risk_tags": risk_tags,
        "initial_process": selected,
        "override_applied": False,
        "override_reason": [],
        "selected_process": selected,
        "confidence": 0.85,
        "applicability": "IN_DOMAIN",
        "difficulty_score": total_d,
        "recommended_parameters": {
            "diamine": diamine,
            "dianhydride": dianhydride,
            "solvent": solvent,
        },
    }
