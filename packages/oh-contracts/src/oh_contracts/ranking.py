"""Intelligence Score（RECONSTRUCTION §H）。

排名模型：加权线和 + 证据门禁（乘性封顶）。
不盲乘的理由：五因子中 Evidence=0 的语义是「弃权」而非「0 分」；
线性乘法会让单零因子湮灭其他维度，且量纲不可比。

IS = 100 × (0.30·Imp + 0.20·Nov + 0.25·Ev + 0.15·Per + 0.10·Imp) × G(Ev)

IS∈[0,40] = 「有变化但证据不足」区；首页只展示 IS≥40 的 Top 3-5。
"""

from __future__ import annotations

import math

__all__ = [
    "WEIGHTS",
    "IS_FLOOR_INSUFFICIENT",
    "entity_importance",
    "novelty_factor",
    "impact_factor",
    "intelligence_score",
]

WEIGHTS: dict[str, float] = {
    "importance": 0.30,
    "novelty": 0.20,
    "evidence": 0.25,
    "persistence": 0.15,
    "impact": 0.10,
}

IS_FLOOR_INSUFFICIENT = 40.0


def entity_importance(entity_type: str) -> float:
    """实体重要性先验（央行 > 政府 > 系统性公司 > 其他）。"""
    return {
        "central_bank": 1.0,
        "government": 0.9,
        "company_systemic": 0.7,
        "company": 0.6,
        "person": 0.5,
    }.get(entity_type, 0.5)


def novelty_factor(first_seen_days_ago: float) -> float:
    """新颖度：首次检出=1.0，随时间指数衰减（半衰期约 5 天）。"""
    return math.exp(-max(first_seen_days_ago, 0.0) / 7.0)


def impact_factor(temperature_gap: float | None) -> float:
    """影响潜力：官方-市场温差为代理变量；无温差数据取中性 0.5。"""
    if temperature_gap is None:
        return 0.5
    return 0.5 + 0.5 * min(max(temperature_gap, 0.0), 1.0)


def intelligence_score(
    *,
    importance: float,
    novelty: float,
    evidence: float,
    persistence: float,
    impact: float,
) -> float:
    """加权线和 + 证据门禁。

    各因子∈[0,1]；evidence=0（Insufficient）时整分封顶 40（降权不湮灭）。
    """
    vals = {
        "importance": min(max(importance, 0.0), 1.0),
        "novelty": min(max(novelty, 0.0), 1.0),
        "evidence": min(max(evidence, 0.0), 1.0),
        "persistence": min(max(persistence, 0.0), 1.0),
        "impact": min(max(impact, 0.0), 1.0),
    }
    base = sum(WEIGHTS[k] * v for k, v in vals.items())
    score = 100.0 * base
    if vals["evidence"] <= 0.0:
        score = min(score, IS_FLOOR_INSUFFICIENT)
    return round(min(max(score, 0.0), 100.0), 1)
