"""确定性变化检测测试（detect → Signal）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    SourceTier,
    StanceLabel,
)
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord, EventRecord, NDIPoint, StanceRow
from oh_contracts.signals import SignalKind
from oh_pipeline.detect import (
    detect_attention_spikes,
    detect_expectation_gaps,
    detect_narrative_shifts,
    detect_ndi_alerts,
    detect_signals,
)
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry

NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def _bronze(source: str, i: int, ts: datetime, title: str) -> BronzeRecord:
    return BronzeRecord(
        source_id=source,
        item_key=make_item_key(source, f"{source}-{i}", ts),
        external_id=f"{source}-{i}",
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={"title": title, "body": title},
    )


def _stance(
    event_id: str,
    source: str,
    entity: str,
    frame: FrameLabel,
    ts: datetime,
) -> StanceRow:
    return StanceRow(
        event_id=event_id,
        source_id=source,
        entity_id=entity,
        frame=frame,
        stance=StanceLabel.NEUTRAL,
        confidence=0.5,
        engine=ExtractionEngine.RULE,
        item_key=make_item_key(source, f"st-{i}", ts) if (i := 0) == 0 else "",
        ts=ts,
    )


def test_attention_spike_triggers() -> None:
    reg = EntityRegistry(DEFAULT_ENTITIES)
    recs: list[BronzeRecord] = []
    # 基线 5+ 天每天 1 篇，末端 3 天每天 8 篇（fed）
    for d in range(11):
        day = NOW - timedelta(days=10 - d)
        n = 8 if d >= 8 else 1
        for i in range(n):
            recs.append(_bronze("gov", f"{d}-{i}", day - timedelta(hours=1), f"Fed meets {i}"))
    sigs = detect_attention_spikes(recs, reg, NOW, days=14)
    assert any(s.kind == SignalKind.ATTENTION_SPIKE and s.entity_id == "fed" for s in sigs)
    s = next(s for s in sigs if s.entity_id == "fed")
    assert s.metrics["z"] >= 3.0 and s.strength > 0


def test_attention_spike_quiet_entity_ignored() -> None:
    reg = EntityRegistry(DEFAULT_ENTITIES)
    recs = [
        _bronze("gov", str(i), NOW - timedelta(days=i % 10), "Fed routine note") for i in range(10)
    ]
    assert detect_attention_spikes(recs, reg, NOW, days=14) == []


def test_narrative_shift_triggers() -> None:
    base_ts = NOW - timedelta(days=6)
    recent_ts = NOW - timedelta(hours=2)
    rows = [
        _stance("E1", "gov", "fed", FrameLabel.LOSS, base_ts - timedelta(hours=i % 5))
        for i in range(6)
    ] + [
        _stance("E2", "gov", "fed", FrameLabel.GAIN, recent_ts - timedelta(hours=i % 5))
        for i in range(6)
    ]
    sigs = detect_narrative_shifts(rows, NOW)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.kind == SignalKind.NARRATIVE_SHIFT and s.entity_id == "fed"
    assert s.metrics["jsd"] >= 0.30


def test_narrative_shift_insufficient_rows_abstains() -> None:
    rows = [_stance("E1", "gov", "fed", FrameLabel.LOSS, NOW - timedelta(days=6))] * 3
    assert detect_narrative_shifts(rows, NOW) == []


def test_ndi_alert_jump_and_high() -> None:
    events = [EventRecord(event_id="ev-fed", title="t", entities=["fed"], as_of=NOW)]
    pts = [
        NDIPoint(
            event_id="ev-fed",
            ts=NOW - timedelta(days=2),
            ndi=0.20,
            ci_low=None,
            ci_high=None,
            n_sources=12,
            status="ok",
        ),
        NDIPoint(
            event_id="ev-fed",
            ts=NOW - timedelta(days=1),
            ndi=0.62,
            ci_low=None,
            ci_high=None,
            n_sources=12,
            status="ok",
        ),
    ]
    sigs = detect_ndi_alerts(pts, events, NOW)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.kind == SignalKind.NDI_ALERT
    assert s.metrics["delta"] >= 0.15
    assert "升至" in s.what_changed


def test_expectation_gap_triggers() -> None:
    ts = NOW - timedelta(hours=2)
    events = [EventRecord(event_id="ev-fed", title="t", entities=["fed"], as_of=NOW)]
    rows = [
        _stance("ev-fed", "gov", "fed", FrameLabel.LOSS, ts),
        _stance("ev-fed", "gov", "fed", FrameLabel.LOSS, ts),
        _stance("ev-fed", "wscn", "fed", FrameLabel.GAIN, ts),
        _stance("ev-fed", "wscn", "fed", FrameLabel.GAIN, ts),
    ]
    sigs = detect_expectation_gaps(
        {"ev-fed": rows},
        events,
        {"gov": SourceTier.OFFICIAL, "wscn": SourceTier.FINANCIAL_PRESS},
        NOW,
        min_per_source=1,
    )
    assert len(sigs) == 1
    assert sigs[0].kind == SignalKind.EXPECTATION_GAP
    assert sigs[0].metrics["gap"] >= 0.50


def test_detect_signals_end_to_end_sorted() -> None:
    """汇总入口：四类合并、IS 降序、top_n 截断（M2c：排序键由 strength 改为 IS）。"""
    ts = NOW - timedelta(hours=2)
    events = [EventRecord(event_id="ev-fed", title="t", entities=["fed"], as_of=NOW)]
    stances = [
        _stance("ev-fed", "gov", "fed", FrameLabel.LOSS, ts),
        _stance("ev-fed", "wscn", "fed", FrameLabel.GAIN, ts),
    ]
    pts = [
        NDIPoint(
            event_id="ev-fed", ts=ts, ndi=0.7, ci_low=None, ci_high=None, n_sources=5, status="ok"
        )
    ]

    class FakeStore:
        def events_asof(self, now: datetime) -> list[EventRecord]:
            return events

        def stances_asof(self, now: datetime) -> list[StanceRow]:
            return stances

        def ndi_all(self) -> list[NDIPoint]:
            return pts

    tier_map = {"gov": SourceTier.OFFICIAL, "wscn": SourceTier.FINANCIAL_PRESS}
    reg = EntityRegistry(DEFAULT_ENTITIES)
    recs = [
        _bronze("gov", str(i), NOW - timedelta(days=i % 10), "Fed quiet day") for i in range(10)
    ]
    sigs = detect_signals(recs, FakeStore(), reg, tier_map, NOW, min_per_source=1, top_n=5)
    scores = [s.metrics["intelligence_score"] for s in sigs]
    assert scores == sorted(scores, reverse=True)
    assert len(sigs) <= 5
    kinds = {s.kind for s in sigs}
    assert SignalKind.NDI_ALERT in kinds
    assert SignalKind.EXPECTATION_GAP in kinds


def test_entity_type_annotations() -> None:
    """M2c：EntitySpec.entity_type 先验标注 + registry 查询。"""
    reg = EntityRegistry(DEFAULT_ENTITIES)
    assert reg.entity_type("fed") == "central_bank"
    assert reg.entity_type("fomc") == "central_bank"
    assert reg.entity_type("white_house") == "government"
    assert reg.entity_type("trump") == "person"
    assert reg.entity_type("nvidia") == "company_systemic"
    assert reg.entity_type("imf") == "other"  # 国际组织无先验类别
    types = reg.types()
    assert set(types) == set(reg.ids())
    assert types["pboc"] == "central_bank"


def test_narrative_shift_evidence_ids_are_item_keys() -> None:
    """P8 修复：shift 证据链 = 近窗 stance 行 item_key（可追溯 provenance）。"""
    base_ts = NOW - timedelta(days=6)
    recent_ts = NOW - timedelta(hours=2)
    rows = [
        _stance("E1", "gov", "fed", FrameLabel.LOSS, base_ts - timedelta(hours=i % 5))
        for i in range(6)
    ]
    recent_keys = set()
    for i in range(6):
        r = _stance("E2", "gov", "fed", FrameLabel.GAIN, recent_ts - timedelta(hours=i % 5))
        recent_keys.add(r.item_key)
        rows.append(r)
    sigs = detect_narrative_shifts(rows, NOW)
    assert len(sigs) == 1
    assert set(sigs[0].evidence_ids) == recent_keys


def test_detect_signals_enrichment_and_is_rank() -> None:
    """增强字段填充 + IS 排序；evidence 链 event_id→item_key→bronze 可追溯。"""
    ts = NOW - timedelta(hours=2)
    recs = [_bronze("gov", str(i), ts - timedelta(hours=i), "Fed cuts rates") for i in range(3)]
    recs += [_bronze("wscn", str(i), ts - timedelta(hours=i), "Fed cuts rates") for i in range(2)]
    stances = [
        StanceRow(
            event_id="ev-fed-20260828",
            source_id=rec.source_id,
            entity_id="fed",
            frame=FrameLabel.LOSS if rec.source_id == "gov" else FrameLabel.GAIN,
            stance=StanceLabel.NEUTRAL,
            confidence=0.5,
            engine=ExtractionEngine.RULE,
            item_key=rec.item_key,
            ts=rec.published_at,
        )
        for rec in recs
    ]
    pts = [
        NDIPoint(
            event_id="ev-fed-20260828",
            ts=ts,
            ndi=0.70,
            ci_low=None,
            ci_high=None,
            n_sources=5,
            status="ok",
        )
    ]

    class FakeStore:
        def events_asof(self, now: datetime) -> list[EventRecord]:
            return [EventRecord(event_id="ev-fed-20260828", title="t", entities=["fed"], as_of=NOW)]

        def stances_asof(self, now: datetime) -> list[StanceRow]:
            return stances

        def ndi_all(self) -> list[NDIPoint]:
            return pts

    tier_map = {"gov": SourceTier.OFFICIAL, "wscn": SourceTier.FINANCIAL_PRESS}
    reg = EntityRegistry(DEFAULT_ENTITIES)
    sigs = detect_signals(recs, FakeStore(), reg, tier_map, NOW, min_per_source=1, top_n=5)
    ndi = [s for s in sigs if s.kind is SignalKind.NDI_ALERT]
    assert len(ndi) == 1
    s = ndi[0]
    assert s.subject_type == "entity" and s.subject_id == "fed"
    assert s.novelty_score == 1.0  # 首检语义（v1 无信号历史）
    assert s.persistence_score is not None and 0.0 <= s.persistence_score <= 1.0
    assert s.baseline is not None and s.current_value == 0.70
    # gov(L1)+wscn(L3) 双源 → LIMITED(0.4) → IS 高于封顶 40
    assert s.metrics["intelligence_score"] > 40.0
    scores = [x.metrics["intelligence_score"] for x in sigs]
    assert scores == sorted(scores, reverse=True)


def test_detect_signals_spike_is_floored_at_40() -> None:
    """spike 无立场证据 → evidence=0 → IS 封顶 40（弃权语义，不湮灭不冒进）。"""
    reg = EntityRegistry(DEFAULT_ENTITIES)
    recs: list[BronzeRecord] = []
    for d in range(11):
        day = NOW - timedelta(days=10 - d)
        n = 8 if d >= 8 else 1
        for i in range(n):
            recs.append(_bronze("gov", f"{d}-{i}", day - timedelta(hours=1), f"Fed meets {i}"))

    class EmptyStore:
        def events_asof(self, now: datetime) -> list[EventRecord]:
            return []

        def stances_asof(self, now: datetime) -> list[StanceRow]:
            return []

        def ndi_all(self) -> list[NDIPoint]:
            return []

    sigs = detect_signals(recs, EmptyStore(), reg, {}, NOW, min_per_source=1)
    spikes = [s for s in sigs if s.kind is SignalKind.ATTENTION_SPIKE]
    assert len(spikes) == 1
    assert spikes[0].metrics["intelligence_score"] == 40.0
