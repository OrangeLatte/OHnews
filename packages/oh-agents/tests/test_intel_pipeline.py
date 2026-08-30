"""M2f 编排测试：build_daily_intel 分层产出、排序、幂等与 PIT 截断。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

from oh_agents.intel_pipeline import build_daily_intel
from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    SourceTier,
    StanceLabel,
)
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord, EventRecord, NDIPoint, StanceRow
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry

NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)
_SEQ = count()


def _pair(
    source: str,
    ts: datetime,
    title: str,
    event_id: str,
    entity: str,
    frame: FrameLabel,
) -> tuple[BronzeRecord, StanceRow]:
    """item_key 对齐的 bronze + stance 对（evidence 反查链路成立）。"""
    key = make_item_key(source, f"it-{next(_SEQ)}", ts)
    rec = BronzeRecord(
        source_id=source,
        item_key=key,
        external_id=key,
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={"title": title, "body": title},
    )
    row = StanceRow(
        event_id=event_id,
        source_id=source,
        entity_id=entity,
        frame=frame,
        stance=StanceLabel.NEUTRAL,
        confidence=0.5,
        engine=ExtractionEngine.RULE,
        item_key=key,
        ts=ts,
    )
    return rec, row


def _fixture(
    with_future: bool = False,
) -> tuple[list[BronzeRecord], list[StanceRow], list[NDIPoint]]:
    """fed 双源极化 12 行（govcn=官方 loss / wscn=市场 gain），标题不含实体词以避开 spike。"""
    recs: list[BronzeRecord] = []
    rows: list[StanceRow] = []
    plan = [("govcn", FrameLabel.LOSS), ("wscn", FrameLabel.GAIN)]
    for i in range(6):
        ts = NOW - timedelta(days=5 - i, hours=1)
        for source, frame in plan:
            rec, row = _pair(source, ts, f"market report {i}", "ev-fed-20260828", "fed", frame)
            recs.append(rec)
            rows.append(row)
    pts = [
        NDIPoint(
            event_id="ev-fed-20260828",
            ts=NOW - timedelta(hours=1),
            ndi=0.7,
            ci_low=None,
            ci_high=None,
            n_sources=5,
            status="ok",
        )
    ]
    if with_future:
        rec, row = _pair(
            "govcn", NOW + timedelta(days=1), "future", "ev-future", "fed", FrameLabel.LOSS
        )
        recs.append(rec)
        rows.append(row)
        pts.append(
            NDIPoint(
                event_id="ev-future",
                ts=NOW + timedelta(hours=1),
                ndi=0.9,
                ci_low=None,
                ci_high=None,
                n_sources=2,
                status="ok",
            )
        )
    return recs, rows, pts


class FakeStore:
    """模拟真实 storage 语义：as_of 接口自行过滤 PIT 之外的数据。"""

    def __init__(
        self,
        events: list[EventRecord],
        rows: list[StanceRow],
        pts: list[NDIPoint],
    ) -> None:
        self._events = events
        self._rows = rows
        self._pts = pts

    def events_asof(self, now: datetime) -> list[EventRecord]:
        return [e for e in self._events if e.as_of <= now]

    def stances_asof(self, now: datetime) -> list[StanceRow]:
        return [r for r in self._rows if r.ts <= now]

    def ndi_all(self) -> list[NDIPoint]:
        return self._pts


def _world(with_future: bool = False) -> tuple[list[BronzeRecord], FakeStore]:
    """bronze/stance/NDI 单次同源构造（item_key 全局递增，禁止二次调用 _fixture 拼装）。"""
    recs, rows, pts = _fixture(with_future)
    events = [EventRecord(event_id="ev-fed-20260828", title="t", entities=["fed"], as_of=NOW)]
    return recs, FakeStore(events, rows, pts)


_TIER = {"govcn": SourceTier.OFFICIAL, "wscn": SourceTier.FINANCIAL_PRESS}


def _run(**kw):
    recs, store = _world()
    return build_daily_intel(
        recs,
        store,
        EntityRegistry(DEFAULT_ENTITIES),
        _TIER,
        as_of=NOW,
        lookback_days=7,
        **kw,
    )


def test_daily_intel_layers() -> None:
    """四层齐备：评估 / 信号 / 叙事 / 洞察，且关联链闭合。"""
    d = _run()
    assert len(d.assessments) == 1
    a = d.assessments[0]
    assert a.event_id == "ev-fed-20260828"
    assert a.status.value == "unverified"  # 双源 → 低于 3 独立源门
    assert a.evidence_strength.value == "limited"  # n_sources=2
    assert {s.kind for s in d.signals} == {"ndi_alert", "expectation_gap"}
    scores = [s.metrics["intelligence_score"] for s in d.signals]
    assert scores == sorted(scores, reverse=True)
    assert len(d.narratives) == 1  # 12 行近窗过样本门，单条主导叙事
    n = d.narratives[0]
    assert n.narrative_id.startswith("nar-fed-") and n.engine == "offline"
    assert len(d.insights) == len(d.signals)
    by_sig = {i.related_signal_ids[0]: i for i in d.insights}
    for s in d.signals:
        ins = by_sig[s.signal_id]
        assert ins.insight_id == f"ins-{s.signal_id}"
        assert ins.engine == "offline"
        assert ins.as_of == s.as_of and ins.generated_at == NOW
        assert ins.evidence_strength.value == "limited"  # 保守取评估档
        assert ins.alternative_explanations
    assert any("ev-fed-20260828" in i.related_event_ids for i in d.insights)
    assert all(by_sig[s.signal_id].related_narrative_ids == [n.narrative_id] for s in d.signals)


def test_daily_intel_topn_truncates() -> None:
    d = _run(top_n=1)
    assert len(d.signals) == 1
    assert len(d.insights) == 1


def test_daily_intel_idempotent() -> None:
    """同 as_of 重跑逐位相等（确定性编排审计门）。"""
    assert _run() == _run()


def test_daily_intel_pit_cut() -> None:
    """future 行与 future NDI 点被 as_of 接口过滤，不得进入任何层。"""
    recs, store = _world(with_future=True)
    d = build_daily_intel(
        recs,
        store,
        EntityRegistry(DEFAULT_ENTITIES),
        _TIER,
        as_of=NOW,
        lookback_days=7,
    )
    assert {a.event_id for a in d.assessments} == {"ev-fed-20260828"}
    assert {s.kind for s in d.signals} == {"ndi_alert", "expectation_gap"}


def test_daily_intel_narrative_abstain() -> None:
    """实体行数低于样本门 → 无叙事；洞察层仍产（证据强度降为 insufficient）。"""
    recs: list[BronzeRecord] = []
    rows: list[StanceRow] = []
    for i in range(5):
        rec, row = _pair(
            "wscn", NOW - timedelta(hours=i + 1), f"r{i}", "ev-fed-20260828", "fed", FrameLabel.GAIN
        )
        recs.append(rec)
        rows.append(row)
    events = [EventRecord(event_id="ev-fed-20260828", title="t", entities=["fed"], as_of=NOW)]
    d = build_daily_intel(
        recs,
        FakeStore(events, rows, []),
        EntityRegistry(DEFAULT_ENTITIES),
        _TIER,
        as_of=NOW,
        lookback_days=7,
    )
    assert d.narratives == ()
    assert d.assessments[0].evidence_strength.value == "insufficient"
    assert d.signals == () and d.insights == ()  # 洞察层由信号驱动，无信号即空
