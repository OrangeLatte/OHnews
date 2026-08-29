"""确定性变化检测 → Signal（REDESIGN §4/§7：Detect 层不 Agent 化）。

四个检测器各回答一个用户问题；全部纯统计、可重放、只用 as_of 及更早
信息（PIT 由 store.events_asof/stances_asof 保证）。产出收敛为统一
Signal 对象，前端 Today 页直接消费。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from oh_contracts.enums import FrameLabel, SourceTier
from oh_contracts.schemas import EventRecord, StanceRow
from oh_contracts.signals import Signal, SignalKind

from oh_pipeline.divergence import dirichlet_smooth, js_divergence, temperature_gap
from oh_pipeline.entities import EntityRegistry

_FRAME_ORDER: tuple[FrameLabel, ...] = tuple(FrameLabel)

# 检测阈值（REDESIGN §7：门槛预注册，改动需过五问）
SPIKE_Z = 3.0
SHIFT_JSD = 0.30
NDI_HIGH = 0.50
NDI_JUMP = 0.15
GAP_HIGH = 0.50
ATTENTION_TAIL_DAYS = 3
ATTENTION_BASE_DAYS = 5
SHIFT_RECENT_DAYS = 3
SHIFT_BASE_DAYS = 5
SHIFT_MIN_ROWS = 5


def _bucket_by_day(
    items: Sequence[Any],
    ts_of: Callable[[Any], datetime | None],
    now: datetime,
    days: int,
) -> dict[datetime, list[Any]]:
    """按 UTC 日分桶（旧→新共 days 天）。ts 缺失或越界丢弃。"""
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets: dict[datetime, list[Any]] = {}
    for i in range(days):
        buckets[start + timedelta(days=i)] = []
    for it in items:
        ts = ts_of(it)
        if ts is None:
            continue
        day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if day in buckets:
            buckets[day].append(it)
    return buckets


def _tail_z(counts: Sequence[int], tail: int) -> float | None:
    """末端 tail 日均值相对前段基线的 z 分；基线不足或零方差返回 None。"""
    if len(counts) < tail + ATTENTION_BASE_DAYS:
        return None
    base = list(counts[:-tail])
    tail_mean = sum(counts[-tail:]) / tail
    bmean = sum(base) / len(base)
    var = sum((x - bmean) ** 2 for x in base) / len(base)
    if var <= 0:
        return None
    return (tail_mean - bmean) / (var**0.5)


def detect_attention_spikes(
    bronze_records: Sequence[Any],
    registry: EntityRegistry,
    now: datetime,
    *,
    days: int = 14,
    entity_texts: Mapping[str, str] | None = None,
) -> list[Signal]:
    """ATTENTION_SPIKE：per-entity 逐日文章量 z 分（Scout 同构，纯统计）。"""
    rows: list[tuple[datetime, list[str]]] = []
    for rec in bronze_records:
        ts = rec.published_at
        text = entity_texts.get(rec.item_key) if entity_texts else None
        if text is None:
            norm = rec.normalized or {}
            text = f"{norm.get('title') or ''}\n{str(norm.get('body') or '')[:600]}"
        rows.append((ts, [e for e in registry.match(text) if e]))
    sigs: list[Signal] = []
    entities = sorted({e for _, es in rows for e in es})
    for entity_id in entities:
        per_day = _bucket_by_day(
            [ts for ts, es in rows if entity_id in es],
            lambda ts: ts,
            now,
            days,
        )
        counts = [len(v) for _, v in sorted(per_day.items())]
        z = _tail_z(counts, ATTENTION_TAIL_DAYS)
        if z is None or z < SPIKE_Z:
            continue
        recent = sum(counts[-ATTENTION_TAIL_DAYS:])
        sigs.append(
            Signal(
                signal_id=f"sig-spike-{entity_id}-{now:%Y%m%d}",
                kind=SignalKind.ATTENTION_SPIKE,
                entity_id=entity_id,
                title=f"{entity_id.upper()} Attention Spike",
                what_changed=(
                    f"过去 {ATTENTION_TAIL_DAYS} 天 {recent} 篇相关文章，为此前基线的 {z:.1f}σ 突增"
                ),
                why_it_matters="注意力快速聚集通常先于叙事形成，值得优先核查",
                metrics={"z": round(z, 3), "recent_articles": float(recent)},
                strength=min(100.0, z * 18.0),
                confidence=min(1.0, recent / 15),
                evidence_ids=[],
                detected_at=now,
                as_of=now,
            )
        )
    return sigs


def detect_narrative_shifts(
    rows: Sequence[StanceRow],
    now: datetime,
    *,
    recent_days: int = SHIFT_RECENT_DAYS,
    base_days: int = SHIFT_BASE_DAYS,
    min_rows: int = SHIFT_MIN_ROWS,
    threshold: float = SHIFT_JSD,
) -> list[Signal]:
    """NARRATIVE_SHIFT：近窗 vs 基线窗框架分布 JSD（同实体跨期比较）。"""
    events = sorted({r.event_id for r in rows})
    sigs: list[Signal] = []
    for entity_id in sorted({r.entity_id for r in rows}):
        erows = [r for r in rows if r.entity_id == entity_id]
        recent_cut = now - timedelta(days=recent_days)
        base_cut = now - timedelta(days=recent_days + base_days)
        recent = [r for r in erows if recent_cut < r.ts <= now]
        base = [r for r in erows if base_cut < r.ts <= recent_cut]
        if len(recent) < min_rows or len(base) < min_rows:
            continue

        def _dist(sub: list[StanceRow]) -> dict[FrameLabel, float]:
            counts: dict[FrameLabel, float] = {f: 0.0 for f in _FRAME_ORDER}
            for r in sub:
                counts[r.frame] += 1.0
            return dirichlet_smooth(counts)

        d = js_divergence(_dist(recent), _dist(base))
        if d < threshold:
            continue
        top = max(_dist(recent), key=lambda f: _dist(recent)[f])
        sigs.append(
            Signal(
                signal_id=f"sig-shift-{entity_id}-{now:%Y%m%d}",
                kind=SignalKind.NARRATIVE_SHIFT,
                entity_id=entity_id,
                title=f"{entity_id.upper()} Narrative Shift",
                what_changed=(f"叙事框架分布发生迁移（JSD {d:.2f}），近窗主导框架转向 {top.value}"),
                why_it_matters="框架迁移意味着信息环境对同一主题的讲述方式正在改变",
                metrics={
                    "jsd": round(d, 4),
                    "n_recent": float(len(recent)),
                    "n_base": float(len(base)),
                },
                strength=min(100.0, d * 130.0),
                confidence=min(1.0, (len(recent) + len(base)) / 30),
                evidence_ids=events,
                detected_at=now,
                as_of=now,
            )
        )
    return sigs


def detect_ndi_alerts(
    points: Sequence[Any],
    events: Sequence[EventRecord],
    now: datetime,
    *,
    high: float = NDI_HIGH,
    jump: float = NDI_JUMP,
) -> list[Signal]:
    """NDI_ALERT：最新 ok 点位处于高位或相对上一 ok 点大幅上升。"""
    entities_of = {e.event_id: (e.entities or ["?"]) for e in events}
    by_event: dict[str, list[Any]] = {}
    for p in points:
        if p.status == "ok" and p.ndi is not None:
            by_event.setdefault(p.event_id, []).append(p)
    sigs: list[Signal] = []
    for event_id, ps in sorted(by_event.items()):
        ps = sorted(ps, key=lambda x: x.ts)
        latest, prev = ps[-1], (ps[-2] if len(ps) >= 2 else None)
        delta = (latest.ndi - prev.ndi) if prev is not None else 0.0
        if latest.ndi < high and delta < jump:
            continue
        entity_id = entities_of.get(event_id, ["?"])[0]
        if delta >= jump:
            what = f"叙事分歧指数由 {prev.ndi:.2f} 升至 {latest.ndi:.2f}（Δ{delta:+.2f}）"
            strength = min(100.0, delta * 400.0)
        else:
            what = f"叙事分歧指数处于高位 {latest.ndi:.2f}"
            strength = latest.ndi * 100.0
        sigs.append(
            Signal(
                signal_id=f"sig-ndi-{event_id}-{now:%Y%m%d}",
                kind=SignalKind.NDI_ALERT,
                entity_id=entity_id,
                title=f"{entity_id.upper()} Narrative Divergence",
                what_changed=what,
                why_it_matters="不同信息群体对同一事件的讲述出现明显差异（描述性监测，非预测）",
                metrics={
                    "ndi": latest.ndi,
                    "delta": round(delta, 4),
                    "n_sources": float(latest.n_sources),
                },
                strength=strength,
                confidence=min(1.0, latest.n_sources / 15),
                evidence_ids=[event_id],
                detected_at=now,
                as_of=now,
            )
        )
    return sigs


def detect_expectation_gaps(
    rows_by_event: Mapping[str, Sequence[StanceRow]],
    events: Sequence[EventRecord],
    tier_map: Mapping[str, SourceTier],
    now: datetime,
    *,
    min_per_source: int,
    threshold: float = GAP_HIGH,
) -> list[Signal]:
    """EXPECTATION_GAP：官方-市场温差 ΔT（认知/预期错位）。"""
    entities_of = {e.event_id: (e.entities or ["?"]) for e in events}
    sigs: list[Signal] = []
    for event_id in sorted(rows_by_event):
        rows = rows_by_event[event_id]
        gap = temperature_gap(rows, tier_map, min_per_source=min_per_source)
        if gap is None or gap < threshold:
            continue
        entity_id = entities_of.get(event_id, ["?"])[0]
        sigs.append(
            Signal(
                signal_id=f"sig-gap-{event_id}-{now:%Y%m%d}",
                kind=SignalKind.EXPECTATION_GAP,
                entity_id=entity_id,
                title=f"{entity_id.upper()} Expectation Gap",
                what_changed=f"官方与市场信息簇的框架分布温差达 {gap:.2f}",
                why_it_matters="官方沟通与市场解读之间可能正在出现预期错位",
                metrics={"gap": gap, "n_rows": float(len(rows))},
                strength=min(100.0, gap * 110.0),
                confidence=min(1.0, len(rows) / 30),
                evidence_ids=[event_id],
                detected_at=now,
                as_of=now,
            )
        )
    return sigs


def detect_signals(
    bronze_iter: Sequence[Any],
    store: Any,
    registry: EntityRegistry,
    tier_map: Mapping[str, SourceTier],
    now: datetime,
    *,
    min_per_source: int = 10,
    top_n: int = 10,
) -> list[Signal]:
    """汇总四类检测器 → Top-N Signal 列表（strength 降序，确定性排序）。"""
    events = store.events_asof(now)
    rows = store.stances_asof(now)
    sigs: list[Signal] = []
    sigs += detect_attention_spikes(list(bronze_iter), registry, now)
    sigs += detect_narrative_shifts(rows, now)
    sigs += detect_ndi_alerts(store.ndi_all(), events, now)
    rows_by_event: dict[str, list[StanceRow]] = {}
    for r in rows:
        rows_by_event.setdefault(r.event_id, []).append(r)
    sigs += detect_expectation_gaps(
        rows_by_event, events, tier_map, now, min_per_source=min_per_source
    )
    sigs.sort(key=lambda s: (-s.strength, s.signal_id))
    return sigs[:top_n]
