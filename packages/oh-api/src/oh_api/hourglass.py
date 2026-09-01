"""Orange Hourglass 场景聚合（阶段 1.5-c）。

把两窗 bronze 覆盖、stance 框架份额、过质量门变化与引文
聚合为单一 HourglassScene——前端只渲染不拼图。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime, timedelta

from oh_api.briefing import (
    bucket_evidence,
    build_briefing_with_signals,
    data_freshness,
)
from oh_contracts.briefing import BriefingResponse, EvidenceCitation, EvidenceSet
from oh_contracts.enums import SourceTier
from oh_contracts.hourglass import (
    HourglassScene,
    NarrativeStream,
    QualifiedChange,
    QualityWarning,
    SourceStream,
    TimeWindow,
)
from oh_contracts.schemas import BronzeRecord
from oh_contracts.signals import Signal
from oh_pipeline.entities import EntityRegistry
from oh_storage.protocols import SilverStore

_FRAME_ZH: dict[str, str] = {
    "loss": "损失",
    "gain": "收益",
    "responsibility": "责任",
    "conflict": "冲突",
    "human_interest": "人情",
    "other": "其他",
}

_MAX_SOURCE_STREAMS = 12
_MAX_QUALIFIED = 5
_MAX_EVIDENCE_REFS = 20
_LOW_COVERAGE_FLOOR = 5


def _iso_window(now: datetime, days: int) -> tuple[datetime, datetime, datetime]:
    """返回 (baseline_start, window_start, now)：两等长窗。"""
    window_start = now - timedelta(days=days)
    baseline_start = now - timedelta(days=2 * days)
    return baseline_start, window_start, now


def _split_window(
    records: list[BronzeRecord],
    lo: datetime,
    hi: datetime,
) -> list[BronzeRecord]:
    """published_at ∈ [lo, hi) 的记录（无 published_at 的不进窗，PIT 同规）。"""
    out = []
    for r in records:
        ts = r.published_at
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if lo <= ts < hi:
            out.append(r)
    return out


def _tier_cluster(tier: SourceTier | None) -> str:
    return "official" if tier is SourceTier.OFFICIAL else "market"


def _source_streams(
    base: list[BronzeRecord],
    cur: list[BronzeRecord],
    tier_map: dict[str, SourceTier],
) -> list[SourceStream]:
    base_n = Counter(r.source_id for r in base)
    cur_n = Counter(r.source_id for r in cur)
    ranked = sorted(
        set(base_n) | set(cur_n),
        key=lambda s: (-(cur_n.get(s, 0) + base_n.get(s, 0)), s),
    )[:_MAX_SOURCE_STREAMS]
    return [
        SourceStream(
            source_id=s,
            label=s,
            tier=tier_map.get(s).value if s in tier_map else "",
            cluster=_tier_cluster(tier_map.get(s)),
            n_baseline=base_n.get(s, 0),
            n_current=cur_n.get(s, 0),
        )
        for s in ranked
    ]


def _share(counts: Counter[str]) -> dict[str, float]:
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in counts.items()}


def _narrative_streams(
    rows: list,
    lo_cur: datetime,
    lo_base: datetime,
    now: datetime,
    tier_map: dict[str, SourceTier],
) -> list[NarrativeStream]:
    """两窗框架份额流带（stance 行 ts 分窗；cluster_split=官方 vs 市场份额）。"""
    base_frames: Counter[str] = Counter()
    cur_frames: Counter[str] = Counter()
    base_cluster: dict[str, Counter[str]] = {}
    cur_cluster: dict[str, Counter[str]] = {}
    for r in rows:
        ts = r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=UTC)
        if ts > now:
            continue
        frame = r.frame.value if hasattr(r.frame, "value") else str(r.frame)
        if frame not in _FRAME_ZH:
            frame = "other"
        cluster = _tier_cluster(tier_map.get(r.source_id))
        if ts >= lo_cur:
            cur_frames[frame] += 1
            cur_cluster.setdefault(frame, Counter())[cluster] += 1
        elif ts >= lo_base:
            base_frames[frame] += 1
            base_cluster.setdefault(frame, Counter())[cluster] += 1
    base_share = _share(base_frames)
    cur_share = _share(cur_frames)
    frames = sorted(set(base_share) | set(cur_share), key=lambda f: (-(cur_share.get(f, 0.0)), f))
    return [
        NarrativeStream(
            frame=f,  # type: ignore[arg-type]
            label=_FRAME_ZH[f],
            share_baseline=round(base_share.get(f, 0.0), 4),
            share_current=round(cur_share.get(f, 0.0), 4),
            n_baseline=base_frames.get(f, 0),
            n_current=cur_frames.get(f, 0),
            cluster_split_baseline={
                k: round(v, 4) for k, v in _share(base_cluster.get(f, Counter())).items()
            },
            cluster_split_current={
                k: round(v, 4) for k, v in _share(cur_cluster.get(f, Counter())).items()
            },
        )
        for f in frames
    ]


def _hero_gate(
    ev: EvidenceSet,
    sig: Signal,
    registry: EntityRegistry,
) -> list[str]:
    """Hero Eligibility Gate（阶段 1.5-d）：变化进 Hero 区的硬门。

    判定（全部满足才过门）：
    1. ≥2 独立来源（source_id 去重；source_id 即媒体源，去重即非同媒体）。
    2. 实体相关性：至少一条引文 quote/title 命中主体别名
       （_relevant_quote 切取保证 + gate 显式断言双保险）。
    3. 引文 HTML 已清洗（quote 无 "<"）。
    过期显式（staleness）由 quality_warnings 承担，不在本门拦截。
    """
    cites = [*(ev.supporting or []), *(ev.contradicting or []), *(ev.context or [])]
    if not cites:
        return ["无任何可展示引文"]
    reasons: list[str] = []
    n_sources = len({c.source_id for c in cites})
    if n_sources < 2:
        reasons.append(f"独立来源仅 {n_sources} 个（Hero 区要求 ≥2）")
    spec = registry.get(sig.entity_id)
    aliases = list(spec.aliases) if spec else []
    if aliases and not any(
        any(a.lower() in f"{c.title}{c.quote}".lower() for a in aliases) for c in cites
    ):
        reasons.append("引文未命中主体别名（实体相关性不足）")
    if any("<" in c.quote for c in cites):
        reasons.append("引文含未清洗 HTML")
    return reasons


def _qualified_changes(
    briefing: BriefingResponse,
    signals: list[Signal],
    *,
    bronze_by_key: dict[str, BronzeRecord],
    store: SilverStore,
    tier_map: dict[str, SourceTier],
    registry: EntityRegistry,
    now: datetime,
) -> tuple[list[QualifiedChange], list[EvidenceCitation], int]:
    """腰部 Change Point + 证据引用（supporting 桶前 2 条/变化）+ Gate 拦截计数。

    changes 与 signals 同序（同一次 detect_signals 产出），zip 配对回查证据链。
    每个 change 先组装证据再过 Hero Gate（1.5-d），未过门不进入腰部。
    """
    changes: list[QualifiedChange] = []
    refs: dict[str, EvidenceCitation] = {}
    gated_out = 0
    for b, sig in zip(briefing.changes[:_MAX_QUALIFIED], signals, strict=False):
        try:
            ev = bucket_evidence(
                sig,
                bronze_by_key=bronze_by_key,
                store=store,
                tier_map=tier_map,
                as_of=now,
                registry=registry,
            )
        except (KeyError, ValueError):
            gated_out += 1
            continue
        if _hero_gate(ev, sig, registry):
            gated_out += 1
            continue
        changes.append(
            QualifiedChange(
                change_id=b.change_id,
                kind=b.kind,
                headline=b.headline,
                what=b.what,
                why_now=b.why_now,
                strength_word=b.strength_word,
                urgency=b.urgency,
                subjects=[s.label for s in (b.subjects or [])],
            )
        )
        for c in (ev.supporting or ev.context or [])[:2]:
            if c.item_key not in refs:
                refs[c.item_key] = c
    return changes, list(refs.values())[:_MAX_EVIDENCE_REFS], gated_out


def _warnings(
    cur: TimeWindow,
    streams: list[SourceStream],
    changes: list[QualifiedChange],
    freshness_staleness: str,
    gated_out: int = 0,
) -> list[QualityWarning]:
    out: list[QualityWarning] = []
    if cur.n_articles == 0:
        out.append(QualityWarning(code="window_empty", message="当前窗口内没有可展示的文章覆盖"))
        return out
    if cur.n_articles < _LOW_COVERAGE_FLOOR:
        out.append(
            QualityWarning(
                code="low_coverage",
                message=f"当前窗口仅 {cur.n_articles} 篇文章，覆盖不足以支撑稳健对比",
            )
        )
    if streams:
        top = max(streams, key=lambda s: s.n_current)
        if cur.n_sources >= 2 and top.n_current > cur.n_articles * 0.5:
            out.append(
                QualityWarning(
                    code="single_source_dominant",
                    message=f"「{top.label}」占当前窗口覆盖过半，观点可能单一",
                )
            )
    if freshness_staleness == "stale":
        out.append(QualityWarning(code="stale_data", message="数据已明显过期，请谨慎解读时间对比"))
    if gated_out > 0:
        out.append(
            QualityWarning(
                code="gate_insufficient_coverage",
                message=f"{gated_out} 个变化因覆盖不足（独立来源/相关性/引文质量）未进入主视图",
            )
        )
    if not changes:
        out.append(
            QualityWarning(
                code="no_qualified_changes",
                message="窗口内没有通过质量门的变化，腰部为空",
            )
        )
    return out


def build_hourglass(
    *,
    bronze_iter,
    store: SilverStore,
    registry: EntityRegistry,
    tier_map: dict[str, SourceTier],
    now: datetime,
    days: int = 7,
    min_per_source: int = 10,
    top: int = 5,
) -> HourglassScene:
    """沙漏场景唯一聚合入口（后端拼图，前端渲染）。"""
    records = list(bronze_iter)
    lo_base, lo_cur, _ = _iso_window(now, max(1, days))
    base = _split_window(records, lo_base, lo_cur)
    cur = _split_window(records, lo_cur, now)

    baseline_w = TimeWindow(
        start=lo_base.isoformat(),
        end=lo_cur.isoformat(),
        n_articles=len(base),
        n_sources=len({r.source_id for r in base}),
    )
    current_w = TimeWindow(
        start=lo_cur.isoformat(),
        end=now.isoformat(),
        n_articles=len(cur),
        n_sources=len({r.source_id for r in cur}),
    )
    streams = _source_streams(base, cur, tier_map)
    rows = store.stances_asof(now)
    narr = _narrative_streams(rows, lo_cur, lo_base, now, tier_map)

    briefing, signals = build_briefing_with_signals(
        bronze_iter=iter(records),
        store=store,
        registry=registry,
        tier_map=tier_map,
        now=now,
        days=max(1, days),
        top=top,
        min_per_source=min_per_source,
    )
    bronze_by_key = {r.item_key: r for r in records}
    changes, refs, gated_out = _qualified_changes(
        briefing,
        signals,
        bronze_by_key=bronze_by_key,
        store=store,
        tier_map=tier_map,
        registry=registry,
        now=now,
    )
    freshness = data_freshness(records, now=now, lookback_days=max(1, days))
    warnings = _warnings(current_w, streams, changes, freshness.staleness, gated_out)

    seed = f"{baseline_w.start}|{current_w.end}"
    scene_id = f"hg-{now:%Y%m%d}-{hashlib.sha1(seed.encode()).hexdigest()[:8]}"
    return HourglassScene(
        scene_id=scene_id,
        generated_at=now.isoformat(),
        baseline_window=baseline_w,
        current_window=current_w,
        source_streams=streams,
        narrative_streams=narr,
        qualified_changes=changes,
        evidence_refs=refs,
        freshness=freshness,
        quality_warnings=warnings,
    )
