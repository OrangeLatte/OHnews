"""分歧构成解剖（anatomy）：把 NDI 拆解为"簇对 × 主体"可交互数据。

递进关系（分析工作台主叙事线）：
NDI（终点数字）→ cluster_pairwise（分歧在哪些信源簇对）
→ cluster_distributions（每簇框架分布）
→ entity_opposition（分歧落在哪些主体：官方 vs 市场谁挺谁批）

纯统计只读（裁决 A）；样本数随行返回，前端据实显示置信。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations

from oh_contracts.constants import JEFFREYS_ALPHA
from oh_contracts.enums import FrameLabel, SourceTier, StanceLabel
from oh_contracts.schemas import StanceRow

from oh_pipeline.divergence import dirichlet_smooth, js_divergence

_TIERS: tuple[SourceTier, ...] = tuple(SourceTier)


def cluster_distributions(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    alpha: float = JEFFREYS_ALPHA,
) -> dict[str, dict[str, float]]:
    """按 tier 簇聚合框架分布（簇内全部行，Dirichlet 平滑）。"""
    by_tier: dict[SourceTier, dict[FrameLabel, int]] = {}
    for r in rows:
        tier = tier_map.get(r.source_id)
        if tier is None:
            continue
        counts = by_tier.setdefault(tier, {})
        counts[r.frame] = counts.get(r.frame, 0) + 1
    return {
        tier.value: {f.value: round(v, 4) for f, v in dirichlet_smooth(counts, alpha).items()}
        for tier, counts in sorted(by_tier.items())
    }


def cluster_pairwise(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    alpha: float = JEFFREYS_ALPHA,
) -> list[dict[str, object]]:
    """tier 簇两两 JSD 距离（含各自样本数），按距离降序。"""
    by_tier: dict[SourceTier, dict[FrameLabel, int]] = {}
    for r in rows:
        tier = tier_map.get(r.source_id)
        if tier is None:
            continue
        counts = by_tier.setdefault(tier, {})
        counts[r.frame] = counts.get(r.frame, 0) + 1
    dists = {t: dirichlet_smooth(c, alpha) for t, c in by_tier.items()}
    pairs: list[dict[str, object]] = []
    for a, b in combinations(_TIERS, 2):
        if a not in dists or b not in dists:
            continue
        pairs.append(
            {
                "a": a.value,
                "b": b.value,
                "jsd": round(js_divergence(dists[a], dists[b]), 4),
                "n_a": sum(by_tier[a].values()),
                "n_b": sum(by_tier[b].values()),
                "official_vs_market": SourceTier.OFFICIAL in {a, b},
            }
        )
    pairs.sort(key=lambda p: -float(p["jsd"]))
    return pairs


def entity_opposition(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
) -> list[dict[str, object]]:
    """主体级官方 vs 市场立场对立表，按 gap 降序。

    gap = |supportive 份额差| + |critical 份额差|（两侧都有样本才计入）。
    """
    by_entity: dict[str, dict[str, dict[StanceLabel, int]]] = {}
    for r in rows:
        tier = tier_map.get(r.source_id)
        if tier is None:
            continue
        side = "official" if tier is SourceTier.OFFICIAL else "market"
        slots = by_entity.setdefault(r.entity_id, {"official": {}, "market": {}})
        slots[side][r.stance] = slots[side].get(r.stance, 0) + 1

    def _pct(counts: Mapping[StanceLabel, int]) -> dict[str, float]:
        total = sum(counts.values())
        if total == 0:
            return {}
        return {s.value: counts.get(StanceLabel(s), 0) / total for s in StanceLabel}

    out: list[dict[str, object]] = []
    for entity_id, slots in by_entity.items():
        off = _pct(slots["official"])
        mkt = _pct(slots["market"])
        if not off or not mkt:
            continue
        gap = sum(abs(off.get(s, 0.0) - mkt.get(s, 0.0)) for s in ("supportive", "critical"))
        out.append(
            {
                "entity_id": entity_id,
                "official": {k: round(v, 4) for k, v in off.items()},
                "market": {k: round(v, 4) for k, v in mkt.items()},
                "n_official": sum(slots["official"].values()),
                "n_market": sum(slots["market"].values()),
                "gap": round(gap, 4),
            }
        )
    out.sort(key=lambda d: -float(d["gap"]))
    return out
