"""数值归一化工具。"""

from __future__ import annotations


def coerce_unit_ratio(value, default: float = 0.5) -> float:
    """将输入值限制到 0.0-1.0 区间，失败时回退到默认值。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))