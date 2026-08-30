"""事件状态推导测试：四态判定 / contested JSD 门 / 置信度 / 观察模板。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_contracts.enums import FrameLabel, SourceTier, StanceLabel
from oh_contracts.narrative import (
    EventStatus,
    EvidenceItem,
    EvidenceRole,
    EvidenceStrength,
)
from oh_contracts.schemas import StanceRow
from oh_pipeline.event_status import (
    CONTESTED_JSD_THRESHOLD,
    assess_event,
    derive_status,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
TIER_MAP = {
    "gov": SourceTier.OFFICIAL,
    "gov2": SourceTier.OFFICIAL,
    "press": SourceTier.FINANCIAL_PRESS,
}


def _item(source: str, role: EvidenceRole, idx: int = 0) -> EvidenceItem:
    return EvidenceItem(
        item_key=f"{source}:{idx}",
        source_id=source,
        role=role,
        quote="quote",
        published_at=TS,
    )


def _row(source: str, frame: FrameLabel, idx: int = 0, event: str = "E01") -> StanceRow:
    return StanceRow(
        event_id=event,
        source_id=source,
        entity_id="fed",
        frame=frame,
        stance=StanceLabel.NEUTRAL,
        confidence=0.7,
        engine="rule",
        item_key=f"{source}:{idx}",
        ts=TS,
    )


def test_unverified_below_three_sources() -> None:
    items = [_item("gov", EvidenceRole.PRIMARY), _item("press", EvidenceRole.COMMENTARY)]
    status, jsd = derive_status(items)
    assert status is EventStatus.UNVERIFIED
    assert jsd is None


def test_developing_multi_source_no_primary() -> None:
    items = [
        _item("press1", EvidenceRole.COMMENTARY),
        _item("press2", EvidenceRole.COMMENTARY),
        _item("press3", EvidenceRole.COMMENTARY),
    ]
    assert derive_status(items)[0] is EventStatus.DEVELOPING


def test_confirmed_with_primary_and_enough_sources() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("press1", EvidenceRole.COMMENTARY),
        _item("press2", EvidenceRole.COMMENTARY),
    ]
    status, jsd = derive_status(items, [_row("gov", FrameLabel.GAIN)])
    assert status is EventStatus.CONFIRMED
    assert jsd is None  # 仅 1 个 primary 源有立场行 → 无法判冲突


def test_contested_when_official_frames_diverge() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("gov2", EvidenceRole.PRIMARY),
        _item("press", EvidenceRole.COMMENTARY),
    ]
    # 每源 10 行：α=0.5 平滑的地板效应下，2 行/源的极化分布 JSD 仅 ~0.46，
    # 达不到 0.5 冲突门；10 行/源的单峰对峙 JSD ~0.79。
    rows = [_row("gov", FrameLabel.LOSS, idx=i) for i in range(10)]
    rows += [_row("gov2", FrameLabel.GAIN, idx=i) for i in range(10, 20)]
    status, jsd = derive_status(items, rows)
    assert status is EventStatus.CONTESTED
    assert jsd is not None and jsd >= CONTESTED_JSD_THRESHOLD


def test_confirmed_when_official_frames_agree() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("gov2", EvidenceRole.PRIMARY),
        _item("press", EvidenceRole.COMMENTARY),
    ]
    rows = [
        _row("gov", FrameLabel.GAIN, idx=0),
        _row("gov", FrameLabel.GAIN, idx=1),
        _row("gov2", FrameLabel.GAIN, idx=2),
        _row("gov2", FrameLabel.GAIN, idx=3),
    ]
    status, jsd = derive_status(items, rows)
    assert status is EventStatus.CONFIRMED
    assert jsd is not None and jsd < CONTESTED_JSD_THRESHOLD


def test_assess_event_offline_fields_and_templates() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("press1", EvidenceRole.COMMENTARY),
        _item("press2", EvidenceRole.COMMENTARY),
        _item("press3", EvidenceRole.COMMENTARY),
    ]
    a = assess_event("ev-fed-20260826", items)
    assert a.engine == "offline"
    assert a.status is EventStatus.CONFIRMED
    assert a.evidence_strength is EvidenceStrength.MODERATE
    assert a.n_independent_sources == 4
    assert a.n_primary_sources == 1
    assert "4 个独立源" in a.observation and "1 个官方一手源" in a.observation

    developing = assess_event(
        "ev-x", [_item(f"press{i}", EvidenceRole.COMMENTARY) for i in range(3)]
    )
    assert "暂无官方一手源佐证" in developing.observation

    unverified = assess_event("ev-y", items[:1])
    assert unverified.status is EventStatus.UNVERIFIED
    assert "独立源不足" in unverified.observation


def test_confidence_deterministic_coverage_formula() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("gov2", EvidenceRole.PRIMARY),
        _item("press", EvidenceRole.COMMENTARY),
    ]
    a = assess_event("ev-fed-20260826", items)
    # 源覆盖 min(3/8,1)=0.375，primary 覆盖 min(2/2,1)=1 → 0.5*0.375+0.5*1
    assert a.confidence == round(0.5 * 0.375 + 0.5 * 1.0, 3)


def test_contested_observation_reports_jsd() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("gov2", EvidenceRole.PRIMARY),
        _item("press", EvidenceRole.COMMENTARY),
    ]
    rows = [_row("gov", FrameLabel.LOSS, idx=i) for i in range(10)]
    rows += [_row("gov2", FrameLabel.GAIN, idx=i) for i in range(10, 20)]
    a = assess_event("ev-fed-20260826", items, rows)
    assert a.status is EventStatus.CONTESTED
    assert "JSD=" in a.observation
