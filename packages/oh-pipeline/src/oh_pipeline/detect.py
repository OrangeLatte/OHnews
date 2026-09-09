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
from oh_contracts.ranking import (
    entity_importance,
    impact_factor,
    intelligence_score,
    novelty_factor,
)
from oh_contracts.schemas import EventRecord, StanceRow
from oh_contracts.signals import Signal, SignalKind

from oh_pipeline.divergence import dirichlet_smooth, js_divergence, temperature_gap
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.evidence import assess_strength, build_evidence

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
PERSIST_WINDOW_DAYS = 3  # persistence 因子：近 3 日实体 stance 覆盖天数占比


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
                # P8 修复：证据链 = 近窗 stance 行的 item_key provenance
                # （原实现误挂全事件集合，无法追溯具体来源）
                evidence_ids=sorted({r.item_key for r in recent}),
                evidence_kind="item_key",
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
    entities_of = {e.event_id: (e.entities or []) for e in events}
    by_event: dict[str, list[Any]] = {}
    for p in points:
        # PIT 纪律：丢弃 ts 晚于 now 的点位（ndi_all 为全量接口，过滤责任在消费侧）
        if p.ts > now:
            continue
        if p.status == "ok" and p.ndi is not None:
            by_event.setdefault(p.event_id, []).append(p)
    sigs: list[Signal] = []
    for event_id, ps in sorted(by_event.items()):
        ents = entities_of.get(event_id) or []
        if not ents:
            # 事件缺实体归属（含被锚点过滤的显式事件）：跳过而非产 '?' 脏信号
            continue
        ps = sorted(ps, key=lambda x: x.ts)
        latest, prev = ps[-1], (ps[-2] if len(ps) >= 2 else None)
        delta = (latest.ndi - prev.ndi) if prev is not None else 0.0
        if latest.ndi < high and delta < jump:
            continue
        entity_id = ents[0]
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
    entities_of = {e.event_id: (e.entities or []) for e in events}
    sigs: list[Signal] = []
    for event_id in sorted(rows_by_event):
        rows = rows_by_event[event_id]
        gap = temperature_gap(rows, tier_map, min_per_source=min_per_source)
        if gap is None or gap < threshold:
            continue
        ents = entities_of.get(event_id) or []
        if not ents:
            # 事件缺实体归属：跳过而非产 '?' 脏信号
            continue
        entity_id = ents[0]
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


def _baseline_current(sig: Signal) -> tuple[float | None, float | None]:
    """解释层基线/当前值（kind 相关，取自检测器 metrics，确定性）。"""
    m = sig.metrics
    if sig.kind is SignalKind.NDI_ALERT:
        return (round(m["ndi"] - m["delta"], 4), m["ndi"])
    if sig.kind is SignalKind.EXPECTATION_GAP:
        return (0.0, m["gap"])
    if sig.kind is SignalKind.NARRATIVE_SHIFT:
        return (0.0, m["jsd"])
    return (None, m.get("recent_articles"))


def _enhance_signals(
    sigs: Sequence[Signal],
    *,
    bronze_index: Mapping[str, Any],
    rows_by_entity: Mapping[str, Sequence[StanceRow]],
    rows_by_event: Mapping[str, Sequence[StanceRow]],
    tier_map: Mapping[str, SourceTier],
    registry: EntityRegistry,
    min_per_source: int,
) -> list[Signal]:
    """Signal 增强（RECONSTRUCTION §D，纯规则）：subject/novelty/persistence/IS。

    五因子确定性来源：
    - importance: registry.entity_type → entity_importance 先验
    - novelty: novelty_factor(0)=1.0——v1 无信号历史存储，全部信号均为首次检出；
      局限：当前 novelty 无区分度，信号持久化落地后应接真实 first_seen
    - evidence: evidence_ids 按 evidence_kind 解析为 bronze 证据
      （item_key 直查索引；event_id 经 rows_by_event 反查）→ assess_strength 分档分；
      spike 无立场证据 → 0（IS 封顶 40）
    - persistence: 实体近 PERSIST_WINDOW_DAYS 日 stance 行覆盖天数占比
    - impact: 实体 stance 行温差 temperature_gap → impact_factor（无数据取 0.5）
    """
    out: list[Signal] = []
    for sig in sigs:
        rows = rows_by_entity.get(sig.entity_id, ())
        keys: list[str] = []
        if sig.evidence_ids:
            for ref in sig.evidence_ids:
                if ref in bronze_index:
                    keys.append(ref)
                else:
                    keys.extend(r.item_key for r in rows_by_event.get(ref, ()))
        matched = [bronze_index[k] for k in sorted(set(keys)) if k in bronze_index]
        evidence = assess_strength(build_evidence(matched, tier_map)).score
        cut = sig.as_of - timedelta(days=PERSIST_WINDOW_DAYS)
        n_days = len({r.ts.date() for r in rows if r.ts >= cut})
        persistence = min(1.0, n_days / PERSIST_WINDOW_DAYS)
        gap = temperature_gap(rows, tier_map, min_per_source=min_per_source) if rows else None
        novelty = novelty_factor(0.0)
        score = intelligence_score(
            importance=entity_importance(
                registry.entity_type(sig.entity_id) if sig.entity_id in registry.ids() else "other"
            ),
            novelty=novelty,
            evidence=evidence,
            persistence=persistence,
            impact=impact_factor(gap),
        )
        baseline, current = _baseline_current(sig)
        out.append(
            sig.model_copy(
                update={
                    "subject_type": "entity",
                    "subject_id": sig.entity_id,
                    "novelty_score": novelty,
                    "persistence_score": persistence,
                    "baseline": baseline,
                    "current_value": current,
                    "metrics": {**sig.metrics, "intelligence_score": score},
                }
            )
        )
    return out


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
    """四检测器汇总 → Signal 增强（§D）→ Intelligence Score 排序 Top-N。

    排序键 (-IS, signal_id)：IS 并列时 signal_id 字典序保确定性。
    IS∈[0,40] 为「有变化但证据不足」区（evidence=0 封顶语义）。
    """
    events = store.events_asof(now)
    rows = store.stances_asof(now)
    sigs: list[Signal] = []
    sigs += detect_attention_spikes(list(bronze_iter), registry, now)
    sigs += detect_narrative_shifts(rows, now)
    sigs += detect_ndi_alerts(store.ndi_all(), events, now)
    rows_by_entity: dict[str, list[StanceRow]] = {}
    rows_by_event: dict[str, list[StanceRow]] = {}
    for r in rows:
        rows_by_entity.setdefault(r.entity_id, []).append(r)
        rows_by_event.setdefault(r.event_id, []).append(r)
    sigs += detect_expectation_gaps(
        rows_by_event, events, tier_map, now, min_per_source=min_per_source
    )
    sigs = _enhance_signals(
        sigs,
        bronze_index={rec.item_key: rec for rec in bronze_iter},
        rows_by_entity=rows_by_entity,
        rows_by_event=rows_by_event,
        tier_map=tier_map,
        registry=registry,
        min_per_source=min_per_source,
    )
    sigs.sort(key=lambda s: (-s.metrics["intelligence_score"], s.signal_id))
    return sigs[:top_n]
