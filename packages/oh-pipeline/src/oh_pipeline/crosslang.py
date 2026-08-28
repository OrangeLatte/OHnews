"""Phase 7 跨语言门禁（裁决 F：三级门禁 + 语域基线归零）。

定义：
- 原始距离 raw(e) = 同一事件 e 的两语言官方簇框架分布的 JS 距离
  （只取 tier=OFFICIAL 且语言匹配的源，源样本门 N_s ≥ min_per_source）
- D₀ = null 集距离分布（null 事件 = 无实质分歧的常规事件，如符合预期的
  例行数据发布；标注者只看原始信源）
- 校正距离 = raw − mean(D₀)；告警条件 = 校正距离 > τ（D₀ 95 分位）
- 低置信标签：跨语言点位（language="cross"）由 oh-contracts 强制
  low_confidence=True，无豁免路径

四条件解锁门禁（全部满足才允许跨语言告警语义，README 措辞纪律联动）：
1. zh within-language 管线稳定 ≥ 28 天（首个 ok 点位起算）
2. en within-language 管线稳定 ≥ 28 天
3. null 集 ≥ 50 且 D₀ σ 收敛
4. 低置信标签强制机制启用（schema 层校验，常开）

门禁未过时本模块只输出 locked 报告与描述性数字，禁止任何告警语义。
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from oh_contracts.constants import JEFFREYS_ALPHA, N_MIN_SAMPLES
from oh_contracts.enums import FrameLabel, SourceTier
from oh_contracts.schemas import NDIPoint, StanceRow

from oh_pipeline.divergence import dirichlet_smooth, js_divergence

_FRAMES: tuple[FrameLabel, ...] = tuple(FrameLabel)

GATE_MIN_NULL = 50
GATE_MIN_STABLE_DAYS = 28
GATE_CONVERGENCE_CV = 0.15
GATE_ABS_STD_FLOOR = 0.05
TAU_QUANTILE = 0.95


def official_lang_distribution(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    lang_map: Mapping[str, str],
    language: str,
    *,
    alpha: float = JEFFREYS_ALPHA,
    min_per_source: int = N_MIN_SAMPLES,
) -> dict[FrameLabel, float] | None:
    """单语言官方簇框架分布（Dirichlet 平滑后源等权平均）。

    返回 None = 该语言无满足样本门的官方源（该事件不可参与跨语言计算）。
    """
    by_source: dict[str, list[StanceRow]] = {}
    for r in rows:
        if tier_map.get(r.source_id) is not SourceTier.OFFICIAL:
            continue
        if lang_map.get(r.source_id) != language:
            continue
        by_source.setdefault(r.source_id, []).append(r)

    dists: list[dict[FrameLabel, float]] = []
    for srows in by_source.values():
        if len(srows) < min_per_source:
            continue
        counts: dict[FrameLabel, int] = {}
        for r in srows:
            counts[r.frame] = counts.get(r.frame, 0) + 1
        dists.append(dirichlet_smooth(counts, alpha))
    if not dists:
        return None
    return {f: sum(d[f] for d in dists) / len(dists) for f in _FRAMES}


def cross_language_distance(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    lang_map: Mapping[str, str],
    lang_a: str,
    lang_b: str,
    *,
    alpha: float = JEFFREYS_ALPHA,
    min_per_source: int = N_MIN_SAMPLES,
) -> float | None:
    """两语言官方簇 JS 距离（原始值）；任一语言簇缺失 → None（弃权）。"""
    pa = official_lang_distribution(
        rows, tier_map, lang_map, lang_a, alpha=alpha, min_per_source=min_per_source
    )
    pb = official_lang_distribution(
        rows, tier_map, lang_map, lang_b, alpha=alpha, min_per_source=min_per_source
    )
    if pa is None or pb is None:
        return None
    return js_divergence(pa, pb)


def cross_language_point(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    lang_map: Mapping[str, str],
    as_of: datetime,
    *,
    event_id: str | None = None,
    lang_a: str = "zh",
    lang_b: str = "en",
    alpha: float = JEFFREYS_ALPHA,
    min_per_source: int = N_MIN_SAMPLES,
) -> NDIPoint:
    """跨语言点位（language="cross"，schema 强制 low_confidence=True）。

    措辞纪律：即使 gate 解锁后，cross 点位也仅是"二级叠加低置信"信号，
    永不参与 within-language 主序列（ndi_series 权威序列不含 cross 行）。
    """
    n_sources = sum(
        1
        for s in {r.source_id for r in rows}
        if tier_map.get(s) is SourceTier.OFFICIAL and lang_map.get(s) in (lang_a, lang_b)
    )
    raw = cross_language_distance(
        rows,
        tier_map,
        lang_map,
        lang_a,
        lang_b,
        alpha=alpha,
        min_per_source=min_per_source,
    )
    if raw is None:
        return NDIPoint(
            event_id=event_id or (rows[0].event_id if rows else ""),
            ts=as_of,
            ndi=None,
            n_sources=n_sources,
            status="abstain",
            language="cross",
            low_confidence=True,
        )
    return NDIPoint(
        event_id=event_id or (rows[0].event_id if rows else ""),
        ts=as_of,
        ndi=round(raw, 6),
        n_sources=n_sources,
        status="ok",
        language="cross",
        low_confidence=True,
    )


@dataclass(frozen=True)
class BaselineEstimate:
    """D₀ 语域基线（null 集距离分布的充分统计量）。"""

    n_null: int
    mean: float
    std: float
    tau: float
    converged: bool


def estimate_baseline(
    distances: Sequence[float],
    *,
    min_null: int = GATE_MIN_NULL,
    cv: float = GATE_CONVERGENCE_CV,
    abs_std_floor: float = GATE_ABS_STD_FLOOR,
) -> BaselineEstimate:
    """D₀ 估计：mean/std/τ(95 分位) + σ 收敛判定。

    收敛判定：n ≥ min_null 且（CV = std/mean ≤ cv；mean 近 0 时改用
    绝对 std ≤ abs_std_floor）。
    """
    if not distances:
        return BaselineEstimate(n_null=0, mean=0.0, std=0.0, tau=0.0, converged=False)
    xs = sorted(distances)
    n = len(xs)
    mean = statistics.fmean(xs)
    std = statistics.stdev(xs) if n >= 2 else 0.0
    k = (n - 1) * TAU_QUANTILE
    lo, hi = math.floor(k), math.ceil(k)
    tau = xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
    converged = n >= min_null and (std / mean <= cv if mean > 0 else std <= abs_std_floor)
    return BaselineEstimate(
        n_null=n,
        mean=round(mean, 6),
        std=round(std, 6),
        tau=round(tau, 6),
        converged=converged,
    )


def corrected_distance(raw: float, baseline: BaselineEstimate) -> float:
    """语域归零：raw − mean(D₀)。"""
    return raw - baseline.mean


def should_alert(correction: float, baseline: BaselineEstimate) -> bool:
    """告警语义仅当 D₀ 收敛且校正距离超 τ；未收敛一律 False（locked）。"""
    if not baseline.converged:
        return False
    return correction > baseline.tau


@dataclass(frozen=True)
class GateCondition:
    """单条 gate 条件的评估结果。"""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateReport:
    """四条件 gate 报告（裁决 F）。"""

    conditions: tuple[GateCondition, ...]
    unlocked: bool
    baseline: BaselineEstimate


def evaluate_gate(
    *,
    zh_first_ts: datetime | None,
    en_first_ts: datetime | None,
    now: datetime,
    baseline: BaselineEstimate,
    min_days: int = GATE_MIN_STABLE_DAYS,
    min_null: int = GATE_MIN_NULL,
) -> GateReport:
    """四条件评估：zh/en 稳定天数、null 集规模+收敛、低置信标签机制。"""

    def _days(first: datetime | None) -> int:
        return max(0, (now - first).days) if first is not None else 0

    zh_days = _days(zh_first_ts)
    en_days = _days(en_first_ts)
    conditions = (
        GateCondition(
            f"zh within-language 稳定 ≥ {min_days} 天",
            zh_days >= min_days,
            f"实际 {zh_days} 天（首个 ok 点位 {zh_first_ts or '无'}）",
        ),
        GateCondition(
            f"en within-language 稳定 ≥ {min_days} 天",
            en_days >= min_days,
            f"实际 {en_days} 天（首个 ok 点位 {en_first_ts or '无'}）",
        ),
        GateCondition(
            f"null 集 ≥ {min_null} 且 D₀ σ 收敛",
            baseline.n_null >= min_null and baseline.converged,
            f"实际 {baseline.n_null} 个（含距离），converged={baseline.converged}",
        ),
        GateCondition(
            "低置信标签机制启用（cross 点位 schema 强制）",
            True,
            "oh-contracts NDIPoint.model_post_init 强制，常开",
        ),
    )
    return GateReport(
        conditions=conditions,
        unlocked=all(c.passed for c in conditions),
        baseline=baseline,
    )
