"""产品层 Facade（阶段 1-b）：内部管线产出 → 面向用户的契约组装。

设计纪律（PRODUCT_AUDIT.md）：
- 新鲜度锚定数据本身（bronze 最新 published_at），绝不冒充「现在」。
- 人话模板：JSD/NDI/confidence 不进主路径字段；内部值仅入 TechnicalAnnex。
- 缺失证据走 EvidenceGap（一等公民），三桶只装真实引文。
- change_id = signal_id（可寻址即可，前端不解读其结构）。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from oh_contracts.briefing import (
    BriefingResponse,
    ChangeBrief,
    ChangeDossier,
    ChangeKind,
    CoverageSummary,
    DataFreshness,
    EvidenceBucket,
    EvidenceCitation,
    EvidenceGap,
    EvidenceSet,
    StalenessLevel,
    StrengthWord,
    SubjectRef,
    TechnicalAnnex,
)
from oh_contracts.enums import SourceTier, StanceLabel
from oh_contracts.schemas import BronzeRecord
from oh_contracts.signals import Signal
from oh_contracts.text import strip_html
from oh_pipeline.detect import detect_signals
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.event_status import assess_event
from oh_pipeline.evidence import build_evidence
from oh_storage.sqlite_store import SqliteStore

_KIND_TO_CHANGE: dict[str, ChangeKind] = {
    "attention_spike": "attention_spike",
    "narrative_shift": "narrative_shift",
    "ndi_alert": "divergence_rise",
    "expectation_gap": "expectation_gap",
}

_HEADLINE: dict[ChangeKind, str] = {
    "attention_spike": "报道注意力异常聚集",
    "narrative_shift": "报道的主导叙事发生转变",
    "divergence_rise": "官方与市场说法的分歧扩大",
    "expectation_gap": "官方口径与市场预期出现错位",
}

_WHAT: dict[ChangeKind, str] = {
    "attention_spike": "同一窗口内的相关报道量显著超出近期基线",
    "narrative_shift": "近期报道的主导框架较前一段时间发生了明显迁移",
    "divergence_rise": "官方语料与市场语料对同一事件的解读差异升至高位",
    "expectation_gap": "官方表述强调稳健，而市场语料聚焦价格与风险",
}

_WHY_NOW: dict[ChangeKind, str] = {
    "attention_spike": "多个此前低频的信源在同一时间窗密集发文",
    "narrative_shift": "框架占比的反转发生在最近的报告窗口内",
    "divergence_rise": "叙事分歧指数在本窗口升至近期高位或出现跳升",
    "expectation_gap": "官方与市场语料的温差在本窗口达到显著水平",
}

_STANCE_TO_BUCKET: dict[str, EvidenceBucket] = {
    StanceLabel.SUPPORTIVE.value: "supporting",
    StanceLabel.CRITICAL.value: "contradicting",
}


def _cjk_label(registry: EntityRegistry, entity_id: str) -> str:
    """实体人话标签：优先含 CJK 的别名，否则首别名，否则 id。"""
    spec = registry.get(entity_id)
    for alias in spec.aliases:
        if any("\u4e00" <= ch <= "\u9fff" for ch in alias):
            return alias
    return spec.aliases[0] if spec.aliases else entity_id


def data_freshness(
    records: Iterable[BronzeRecord],
    *,
    now: datetime,
    lookback_days: int = 3,
) -> DataFreshness:
    """数据新鲜度：以 bronze 最新 published_at 为准（PIT 有效记录）。

    staleness：数据末端距今 <24h fresh / <72h aging / 其余 stale。
    无任何可锚定记录时 as_of 兜底为 now 并标记 stale（诚实降级）。
    """
    newest: datetime | None = None
    window_start: datetime | None = None
    lower = now - timedelta(days=lookback_days)
    for rec in records:
        published = rec.published_at
        if published is None:
            continue
        if newest is None or published > newest:
            newest = published
        if published >= lower and (window_start is None or published < window_start):
            window_start = published
    if newest is None:
        return DataFreshness(
            as_of=now,
            staleness="stale",
            note="数据尚未覆盖任何有效记录",
        )
    gap_hours = (now - newest).total_seconds() / 3600
    level: StalenessLevel = "fresh" if gap_hours < 24 else "aging" if gap_hours < 72 else "stale"
    note = f"数据截至 {newest:%m月%d日 %H:%M} UTC"
    return DataFreshness(
        as_of=newest,
        coverage_start=window_start,
        coverage_end=newest,
        staleness=level,
        note=note,
    )


def _subjects(signal: Signal, registry: EntityRegistry) -> list[SubjectRef]:
    """信号 → 用户引用：实体必带；event 维度信号附事件引用。"""
    label = _cjk_label(registry, signal.entity_id)
    refs = [SubjectRef(kind="entity", id=signal.entity_id, label=label)]
    for evid in signal.evidence_ids:
        if evid.startswith("ev-"):
            refs.append(SubjectRef(kind="event", id=evid, label=evid))
            break
    return refs


def _strength_word(strength: float) -> StrengthWord:
    """Signal.strength（0-100 分数）→ 人话分档。"""
    if strength >= 70:
        return "strong"
    if strength >= 40:
        return "notable"
    if strength > 0:
        return "minor"
    return "insufficient"


def _brief(signal: Signal, registry: EntityRegistry) -> ChangeBrief:
    kind = _KIND_TO_CHANGE.get(signal.kind.value, "attention_spike")
    is_score = float(signal.metrics.get("intelligence_score", 0.0) or 0.0)
    urgency = "high" if is_score >= 80 else "medium" if is_score >= 50 else "low"
    return ChangeBrief(
        change_id=signal.signal_id,
        kind=kind,
        headline=_HEADLINE[kind],
        what=_WHAT[kind],
        why_now=_WHY_NOW[kind],
        strength_word=_strength_word(float(signal.strength)),
        urgency=urgency,
        subjects=_subjects(signal, registry),
    )


def build_briefing(
    *,
    bronze_iter: Iterable[BronzeRecord],
    store: SqliteStore,
    registry: EntityRegistry,
    tier_map: dict[str, SourceTier],
    now: datetime,
    days: int = 3,
    top: int = 5,
    min_per_source: int = 10,
) -> BriefingResponse:
    """Briefing 页数据面：DataFreshness + 有限 ChangeBrief 队列。

    changes 为空 =「今天没有值得看的变化」（硬验收 7：no change 显式状态，
    前端按 changes 为空 + freshness 渲染，而非空白页）。
    """
    records = list(bronze_iter)
    fresh = data_freshness(records, now=now, lookback_days=days)
    signals = detect_signals(
        iter(records),
        store,
        registry,
        tier_map,
        now,
        min_per_source=min_per_source,
        top_n=max(1, min(top, 30)),
    )
    return BriefingResponse(
        freshness=fresh,
        changes=[_brief(s, registry) for s in signals],
    )


def _relevant_quote(
    text: str,
    aliases: list[str],
    *,
    limit: int = 400,
) -> str:
    """质量门 1.5-b：引文清洗 + 实体相关性切取。

    - strip_html 清洗（华见等源 body 含标签，绝不透出原始 HTML）。
    - 优先从第一个含实体别名的句子起截取（信号相关性门：引文必须讲该实体，
      而非文章任意前 400 字符——多主题早报正文常以无关主题开头）。
    - 无别名命中时退回首句起的窗口（诚实：仍是清洗后的全文窗口）。
    """
    clean = strip_html(text).strip()
    if not clean:
        return ""
    lowered = clean.lower()
    start = 0
    for alias in aliases:
        idx = lowered.find(alias.lower())
        if idx >= 0 and (start == 0 or idx < start):
            start = idx
    if start:
        # 回退到句首，避免从词中间截断
        for sent_start in (clean.rfind("。", 0, start), clean.rfind(". ", 0, start)):
            if 0 < sent_start < start:
                start = sent_start + 1
                break
    return clean[start : start + limit]


def _citations(
    item_keys: Iterable[str],
    bronze_by_key: dict[str, BronzeRecord],
    tier_map: dict[str, SourceTier],
    aliases: list[str],
) -> list[EvidenceCitation]:
    out: list[EvidenceCitation] = []
    for key in item_keys:
        rec = bronze_by_key.get(key)
        if rec is None:
            continue
        tier = tier_map.get(rec.source_id)
        if tier is None:
            continue
        normalized = rec.normalized
        body = str(normalized.get("body") or "")
        title = str(normalized.get("title") or "")
        quote = _relevant_quote(body or title, aliases)
        if not quote:
            continue
        out.append(
            EvidenceCitation(
                item_key=rec.item_key,
                source_id=rec.source_id,
                source_tier=tier,
                title=title or rec.item_key,
                quote=quote,
                url=str(normalized.get("url") or "") or None,
                published_at=rec.published_at,
            )
        )
    return out


def bucket_evidence(
    signal: Signal,
    *,
    bronze_by_key: dict[str, BronzeRecord],
    store: SqliteStore,
    tier_map: dict[str, SourceTier],
    as_of: datetime,
    registry: EntityRegistry | None = None,
) -> EvidenceSet:
    """信号证据链 → 三桶 + 缺口。

    分桶依据：stance 行的 SUPPORTIVE/CRITICAL 直接落桶；
    其余（NEUTRAL/ABSTAIN/无 stance 行的引文）进 context。
    item_key 语义直接命中反查；event_id 语义经 stance 行展开。
    registry 提供实体别名供引文相关性切取（1.5-b 质量门）。
    """
    aliases = list(registry.get(signal.entity_id).aliases) if registry is not None else []
    rows = store.stances_asof(as_of)
    rows_by_key: dict[str, list] = {}
    for r in rows:
        rows_by_key.setdefault(r.item_key, []).append(r)
    item_keys: list[str] = []
    for evid in signal.evidence_ids:
        if evid in bronze_by_key:
            item_keys.append(evid)
        else:
            item_keys.extend(r.item_key for r in rows if r.event_id == evid)
    citations = _citations(item_keys, bronze_by_key, tier_map, aliases)

    buckets: dict[EvidenceBucket, list[EvidenceCitation]] = {
        "supporting": [],
        "contradicting": [],
        "context": [],
    }
    seen: set[str] = set()
    for cite in citations:
        if cite.item_key in seen:
            continue
        seen.add(cite.item_key)
        stance_rows = rows_by_key.get(cite.item_key, [])
        bucket: EvidenceBucket = "context"
        for r in stance_rows:
            stance_value = r.stance.value if hasattr(r.stance, "value") else str(r.stance)
            mapped = _STANCE_TO_BUCKET.get(stance_value)
            if mapped is not None:
                bucket = mapped
                break
        buckets[bucket].append(cite)

    gaps = _evidence_gaps(signal, buckets)
    return EvidenceSet(**buckets, gaps=gaps)


def _evidence_gaps(
    signal: Signal,
    buckets: dict[EvidenceBucket, list[EvidenceCitation]],
) -> list[EvidenceGap]:
    """确定性缺口检测：官方一手缺失 / 单一来源结构。"""
    gaps: list[EvidenceGap] = []
    supporting = buckets["supporting"] + buckets["contradicting"] + buckets["context"]
    n_primary = sum(1 for c in supporting if c.source_tier is SourceTier.OFFICIAL)
    n_sources = len({c.source_id for c in supporting})
    subject = SubjectRef(kind="entity", id=signal.entity_id, label=signal.entity_id)
    if n_primary == 0 and supporting:
        gaps.append(
            EvidenceGap(
                gap_id=f"gap-noprimary-{signal.signal_id}",
                expectation="缺少官方一手来源的直接表态",
                reason="no_primary_source",
                subject=subject,
                suggestion="等待官方声明、会议纪要或新闻发布会文本",
            )
        )
    if 0 < n_sources <= 1:
        gaps.append(
            EvidenceGap(
                gap_id=f"gap-single-{signal.signal_id}",
                expectation="需要第二家独立信源交叉验证",
                reason="single_cluster",
                subject=subject,
                suggestion="观察其他语种或不同层级来源是否跟进报道",
            )
        )
    return gaps


def build_dossier(
    change_id: str,
    *,
    bronze_iter: Iterable[BronzeRecord],
    store: SqliteStore,
    registry: EntityRegistry,
    tier_map: dict[str, SourceTier],
    now: datetime,
    days: int = 3,
    min_per_source: int = 10,
) -> ChangeDossier | None:
    """变化详情包：change_id 反查信号 → Dossier（未命中返回 None）。"""
    records = list(bronze_iter)
    fresh = data_freshness(records, now=now, lookback_days=days)
    signals = detect_signals(
        iter(records),
        store,
        registry,
        tier_map,
        now,
        min_per_source=min_per_source,
        top_n=50,
    )
    signal = next((s for s in signals if s.signal_id == change_id), None)
    if signal is None:
        return None

    bronze_by_key = {r.item_key: r for r in records}
    evidence = bucket_evidence(
        signal,
        bronze_by_key=bronze_by_key,
        store=store,
        tier_map=tier_map,
        as_of=now,
        registry=registry,
    )

    # 质量门 1.5-b：coverage 一律从分桶引文实算（与 EvidenceSet 严格一致），
    # 事件评估只贡献 status；杜绝「独立源 0 却有三桶」的信任矛盾。
    known_events = {e.event_id for e in store.events_asof(now)}
    event_ids = [e for e in signal.evidence_ids if e in known_events]
    status = "developing"
    if event_ids:
        ev_id = event_ids[0]
        ev_rows = [r for r in store.stances_asof(now) if r.event_id == ev_id]
        recs = [bronze_by_key[r.item_key] for r in ev_rows if r.item_key in bronze_by_key]
        evidence_items = build_evidence(recs, tier_map)
        if evidence_items:
            status = assess_event(ev_id, evidence_items, ev_rows).status.value

    technical = TechnicalAnnex(
        signal_id=signal.signal_id,
        engine="offline",
        intelligence_score=signal.metrics.get("intelligence_score"),
        ndi=signal.metrics.get("ndi"),
        jsd=signal.metrics.get("jsd"),
        temperature_gap=signal.metrics.get("temperature_gap"),
    )
    brief = _brief(signal, registry)
    all_cites = evidence.supporting + evidence.contradicting + evidence.context
    published = [c.published_at for c in all_cites if c.published_at is not None]
    span_days = (
        (max(published) - min(published)).total_seconds() / 86400 if len(published) >= 2 else 0.0
    )
    n_sources = len({c.source_id for c in all_cites})
    n_primary = len({c.source_id for c in all_cites if c.source_tier is SourceTier.OFFICIAL})
    if all_cites:
        coverage_note = f"{n_sources} 个独立信源，其中 {n_primary} 个官方一手"
    else:
        coverage_note = "暂无可用的覆盖统计信息"
    coverage = CoverageSummary(
        n_independent_sources=n_sources,
        n_primary_sources=n_primary,
        time_span_days=round(span_days, 2),
        languages=sorted({c.source_id.split(":", 1)[0] for c in all_cites}),
        note=coverage_note,
    )
    return ChangeDossier(
        change_id=signal.signal_id,
        kind=brief.kind,
        headline=brief.headline,
        what=brief.what,
        why_now=brief.why_now,
        status=status,
        subjects=brief.subjects,
        evidence=evidence,
        coverage=coverage,
        freshness=fresh,
        technical=technical,
    )
