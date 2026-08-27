"""统计层（裁决 A：divergence_engine 纯统计只读 stance_table，无 LLM 参与）。

公式（数据科学家裁决）：
- Dirichlet 平滑：P̂_s(f) = (n_{s,f} + α) / (N_s + Kα)，α=0.5（Jeffreys）
- NDI：NDI_e(t) = JSD_2(P_official, P_market)（sqrt 化为距离，∈[0,1]），
  P_cluster = 簇内各源分布的等权平均（仅 N_s ≥ N_min 的源参与）
- 温差：ΔT = Σ_f |P_official(f) − P_market(f)|（L1 距离）
- 置信区间：簇内分层重采样 → percentile bootstrap CI

弃权门（裁决：样本门不过 → NA，禁止噪声放大）：
- 任一簇无满足 N_s ≥ N_min 的源，或参与源数 < 2 → abstain（ndi=None）
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from datetime import datetime

from oh_contracts.constants import (
    BOOTSTRAP_RESAMPLES,
    JEFFREYS_ALPHA,
    N_MIN_SAMPLES,
)
from oh_contracts.enums import FrameLabel, SourceTier
from oh_contracts.schemas import NDIPoint, StanceRow

_FRAMES: tuple[FrameLabel, ...] = tuple(FrameLabel)
_K = len(_FRAMES)

MarketClusters = Mapping[str, frozenset[str]]
"""source_id → 允许的簇名集合（本模块按 tier 推导，此类型仅作文档）。"""


def dirichlet_smooth(
    counts: Mapping[FrameLabel, int],
    alpha: float = JEFFREYS_ALPHA,
) -> dict[FrameLabel, float]:
    """(n_f + α) / (N + Kα)；缺失框架按 0 计。"""
    total = sum(counts.get(f, 0) for f in _FRAMES)
    denom = total + _K * alpha
    if denom <= 0:
        raise ValueError("counts 总和与 alpha 不可同时为 0")
    return {f: (counts.get(f, 0) + alpha) / denom for f in _FRAMES}


def js_divergence(p: Mapping[FrameLabel, float], q: Mapping[FrameLabel, float]) -> float:
    """base-2 Jensen-Shannon 距离 sqrt(JSD)：0=同分布，1=支撑不相交。"""

    def _h(r: Mapping[FrameLabel, float]) -> float:
        return -sum(v * math.log2(v) for v in r.values() if v > 0)

    m = {f: (p.get(f, 0.0) + q.get(f, 0.0)) / 2 for f in _FRAMES}
    jsd = _h(m) - (_h(p) + _h(q)) / 2
    return math.sqrt(max(0.0, min(1.0, jsd)))


def l1_gap(p: Mapping[FrameLabel, float], q: Mapping[FrameLabel, float]) -> float:
    """温差 ΔT = Σ_f |P_official(f) − P_market(f)|。"""
    return sum(abs(p.get(f, 0.0) - q.get(f, 0.0)) for f in _FRAMES)


def _source_distributions(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    alpha: float,
    min_per_source: int,
    clusters: Mapping[str, frozenset[SourceTier]],
) -> dict[str, dict[FrameLabel, float]] | None:
    """按簇聚合源分布：仅统计 N_s ≥ min_per_source 的源；簇分布=源分布等权平均。

    返回 None 表示任一簇无合格源（弃权）。
    """
    by_source: dict[str, list[StanceRow]] = {}
    for r in rows:
        by_source.setdefault(r.source_id, []).append(r)

    result: dict[str, dict[FrameLabel, float]] = {}
    for cluster_name, tiers in clusters.items():
        dists: list[dict[FrameLabel, float]] = []
        for source_id, srows in by_source.items():
            if tier_map.get(source_id) not in tiers:
                continue
            if len(srows) < min_per_source:
                continue
            counts: dict[FrameLabel, int] = {}
            for r in srows:
                counts[r.frame] = counts.get(r.frame, 0) + 1
            dists.append(dirichlet_smooth(counts, alpha))
        if not dists:
            return None
        result[cluster_name] = {f: sum(d[f] for d in dists) / len(dists) for f in _FRAMES}
    if len(result) < 2:
        return None
    return result


def _cluster_resample(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    tiers: frozenset[SourceTier],
    alpha: float,
    min_per_source: int,
    rng: random.Random,
) -> dict[FrameLabel, float] | None:
    """簇内分层重采样：每源有放回抽 N_s 行 → 源分布 → 等权平均。"""
    by_source: dict[str, list[StanceRow]] = {}
    for r in rows:
        if tier_map.get(r.source_id) in tiers:
            by_source.setdefault(r.source_id, []).append(r)

    dists: list[dict[FrameLabel, float]] = []
    for srows in by_source.values():
        if len(srows) < min_per_source:
            continue
        sample = [srows[rng.randrange(len(srows))] for _ in range(len(srows))]
        counts: dict[FrameLabel, int] = {}
        for r in sample:
            counts[r.frame] = counts.get(r.frame, 0) + 1
        dists.append(dirichlet_smooth(counts, alpha))
    if not dists:
        return None
    return {f: sum(d[f] for d in dists) / len(dists) for f in _FRAMES}


DEFAULT_CLUSTERS: dict[str, frozenset[SourceTier]] = {
    "official": frozenset({SourceTier.OFFICIAL}),
    "market": frozenset({SourceTier.WIRE, SourceTier.FINANCIAL_PRESS, SourceTier.SOCIAL}),
}


def ndi_for_event(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    as_of: datetime,
    *,
    alpha: float = JEFFREYS_ALPHA,
    min_per_source: int = N_MIN_SAMPLES,
    clusters: Mapping[str, frozenset[SourceTier]] | None = None,
    n_boot: int = BOOTSTRAP_RESAMPLES,
    seed: int = 42,
) -> NDIPoint:
    """单事件 NDI 点位（官方簇 vs 市场簇框架分布 JSD 距离）。

    措辞纪律（裁决 B）：NDI = 叙事分歧指数，描述性监测指标；
    测量效度 ρ≥0.8 通过并预注册前，禁称"雷达信号/预测器"。
    """
    cluster_map = clusters if clusters is not None else DEFAULT_CLUSTERS
    dists = _source_distributions(rows, tier_map, alpha, min_per_source, cluster_map)
    n_sources = sum(
        1
        for s in {r.source_id for r in rows}
        if tier_map.get(s) in set().union(*cluster_map.values())
    )
    if dists is None:
        return NDIPoint(
            event_id=rows[0].event_id if rows else "",
            ts=as_of,
            ndi=None,
            n_sources=n_sources,
            status="abstain",
        )
    names = sorted(dists)
    p, q = dists[names[0]], dists[names[1]]
    point = js_divergence(p, q)

    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_boot):
        bp = _cluster_resample(rows, tier_map, cluster_map[names[0]], alpha, min_per_source, rng)
        bq = _cluster_resample(rows, tier_map, cluster_map[names[1]], alpha, min_per_source, rng)
        if bp is not None and bq is not None:
            boots.append(js_divergence(bp, bq))
    if len(boots) >= max(2, n_boot // 10):
        boots.sort()

        def _pct(x: float) -> float:
            k = (len(boots) - 1) * x
            lo = math.floor(k)
            hi = math.ceil(k)
            return boots[lo] + (boots[hi] - boots[lo]) * (k - lo)

        ci_low, ci_high = _pct(0.025), _pct(0.975)
    else:
        ci_low, ci_high = None, None

    return NDIPoint(
        event_id=rows[0].event_id,
        ts=as_of,
        ndi=round(point, 6),
        ci_low=round(ci_low, 6) if ci_low is not None else None,
        ci_high=round(ci_high, 6) if ci_high is not None else None,
        n_sources=n_sources,
        status="ok",
    )


def temperature_gap(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    *,
    alpha: float = JEFFREYS_ALPHA,
    min_per_source: int = N_MIN_SAMPLES,
    clusters: Mapping[str, frozenset[SourceTier]] | None = None,
) -> float | None:
    """官方-市场温差 ΔT；门禁不过返回 None（弃权）。"""
    cluster_map = clusters if clusters is not None else DEFAULT_CLUSTERS
    dists = _source_distributions(rows, tier_map, alpha, min_per_source, cluster_map)
    if dists is None:
        return None
    names = sorted(dists)
    return round(l1_gap(dists[names[0]], dists[names[1]]), 6)
