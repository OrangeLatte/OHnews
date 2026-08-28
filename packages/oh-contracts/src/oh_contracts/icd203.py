"""ICD 203 情报置信语言（Director of National Intelligence 标准）。

INTEL BRIEF 的 Key Judgments 强制挂概率语言——用词与数值区间一一映射，
禁用裸数字或"高/低"式模糊置信（超越 TradingAgents 的 confidence: high/low）。

依据：ODNI Intelligence Community Directive 203 (2015) +
National Intelligence Council 惯用概率带。
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ProbabilityTerm", "PROBABILITY_RANGES", "term_for_probability"]


class ProbabilityTerm(StrEnum):
    """ICD 203 概率语言（词 → 区间，Zh 副标为研究档案展示用）。"""

    ALMOST_CERTAIN = "almost_certain"  # 几乎必然
    HIGHLY_LIKELY = "highly_likely"  # 极可能
    LIKELY = "likely"  # 可能
    ROUGHLY_EVEN = "roughly_even"  # 大致对半
    UNLIKELY = "unlikely"  # 不太可能
    HIGHLY_UNLIKELY = "highly_unlikely"  # 极不可能
    ALMOST_IMPOSSIBLE = "almost_impossible"  # 几乎不可能


PROBABILITY_RANGES: dict[ProbabilityTerm, tuple[float, float]] = {
    ProbabilityTerm.ALMOST_CERTAIN: (0.95, 1.0),
    ProbabilityTerm.HIGHLY_LIKELY: (0.80, 0.95),
    ProbabilityTerm.LIKELY: (0.55, 0.80),
    ProbabilityTerm.ROUGHLY_EVEN: (0.45, 0.55),
    ProbabilityTerm.UNLIKELY: (0.20, 0.45),
    ProbabilityTerm.HIGHLY_UNLIKELY: (0.05, 0.20),
    ProbabilityTerm.ALMOST_IMPOSSIBLE: (0.0, 0.05),
}


def term_for_probability(p: float) -> ProbabilityTerm:
    """数值概率 → ICD 203 置信语言（区间含下界不含上界，端点归并）。"""
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"概率越界 [0,1]: {p}")
    if p >= 0.95:
        return ProbabilityTerm.ALMOST_CERTAIN
    if p >= 0.80:
        return ProbabilityTerm.HIGHLY_LIKELY
    if p >= 0.55:
        return ProbabilityTerm.LIKELY
    if p > 0.45:
        return ProbabilityTerm.ROUGHLY_EVEN
    if p > 0.20:
        return ProbabilityTerm.UNLIKELY
    if p > 0.05:
        return ProbabilityTerm.HIGHLY_UNLIKELY
    return ProbabilityTerm.ALMOST_IMPOSSIBLE
