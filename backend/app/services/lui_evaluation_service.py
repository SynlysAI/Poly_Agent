"""LUI Agent 任务级评测基线读取服务。

与 `assistant_quality_service` 的分层：质量服务聚合生产链路侧指标
（路由、提案、执行、续答），本服务读取离线评测受控基线，提供
任务级 M1–M8 结果质量汇总。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_BASELINE_DIR = (
    Path(__file__).resolve().parents[2] / "evaluation" / "lui" / "baselines"
)
BASELINE_MODE_PATTERN = re.compile(r"^(smoke|full)-[\w.-]+\.json$")


def list_baseline_modes(baseline_dir: str | Path = DEFAULT_BASELINE_DIR) -> list[str]:
    """列出基线目录下可用的评测模式。

    Args:
        baseline_dir: 基线 JSON 目录。

    Returns:
        去重排序后的模式列表（smoke/full）。
    """
    directory = Path(baseline_dir)
    if not directory.is_dir():
        return []
    modes = {
        match.group(1)
        for name in (item.name for item in directory.glob("*.json"))
        if (match := BASELINE_MODE_PATTERN.match(name))
    }
    return sorted(modes)


def load_baseline_summary(
    mode: str = "smoke",
    baseline_dir: str | Path = DEFAULT_BASELINE_DIR,
) -> dict[str, Any]:
    """读取指定模式下最新的受控评测基线并投影为页面汇总。

    Args:
        mode: 评测模式（smoke/full）。
        baseline_dir: 基线 JSON 目录。

    Returns:
        含 available 标记、基线元信息、M1–M8 汇总、分桶/模式拆解
        与人工抽检结论的字典；基线不存在时 available=False。
    """
    if mode not in {"smoke", "full"}:
        raise ValueError(f"unsupported baseline mode: {mode}")
    directory = Path(baseline_dir)
    available_modes = list_baseline_modes(directory)
    if mode not in available_modes:
        return {
            "available": False,
            "mode": mode,
            "available_modes": available_modes,
            "message": f"no {mode} baseline found under {directory}",
        }
    candidates = [
        item
        for item in directory.glob(f"{mode}-*.json")
        if BASELINE_MODE_PATTERN.match(item.name)
    ]
    # 以文件名中的生成日期为准，缺失时回退修改时间。
    latest = max(
        candidates,
        key=lambda item: (
            item.stem.split("-", 1)[1],
            item.stat().st_mtime,
        ),
    )
    payload = json.loads(latest.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    return {
        "available": True,
        "mode": mode,
        "source_file": latest.name,
        "available_modes": available_modes,
        "evaluation_id": payload.get("evaluation_id"),
        "dataset_version": payload.get("dataset_version"),
        "generated_at": payload.get("generated_at"),
        "summary": payload.get("summary") or {},
        "metrics": payload.get("metrics") or {},
        "by_category": payload.get("by_category") or {},
        "by_mode": payload.get("by_mode") or {},
        "manual_review": metadata.get("manual_review"),
        "facts_source": metadata.get("facts_source"),
    }
