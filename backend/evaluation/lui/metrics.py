"""LUI 评测的数值聚合工具。"""

from __future__ import annotations

import math


def percentile(values: list[float], fraction: float) -> float | None:
    """按最近秩法计算百分位数。

    Args:
        values: 数值样本。
        fraction: 0-1 之间的百分位。

    Returns:
        对应百分位数；空样本返回 None。
    """
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def mean(values: list[float]) -> float | None:
    """计算算术平均；空样本返回 None。"""
    if not values:
        return None
    return round(sum(float(item) for item in values) / len(values), 6)


def safe_ratio(numerator: int, denominator: int) -> float | None:
    """返回安全比值；分母为 0 时返回 None。"""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)
