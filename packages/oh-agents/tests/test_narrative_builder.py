"""narrative_builder 测试：弃权门/幂等/provenance/簇映射/momentum/NDI/迁移。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_agents.narrative_builder import build_narrative
from oh_contracts.constants import N_MIN_SAMPLES
from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    SourceTier,
    StanceLabel,
)
from oh_contracts.schemas import StanceRow

_AS_OF = datetime(2026, 8, 30, tzinfo=UTC)
_WINDOW = "2026-08-24/30"
_TIER_MAP = {
    "govcn": SourceTier.OFFICIAL,
    "wscn": SourceTier.FINANCIAL_PRESS,
    "x": SourceTier.SOCIAL,
}

_seq = 0


def _row(
    source: str,
    ts: datetime,
    *,
    stance: StanceLabel = StanceLabel.NEUTRAL,
    frame: FrameLabel = FrameLabel.OTHER,
    item_key: str | None = None,
) -> StanceRow:
    global _seq
    _seq += 1
    return StanceRow(
        event_id="ev-fed-20260830",
        source_id=source,
        entity_id="fed",
        frame=frame,
        stance=stance,
        confidence=0.8,
        engine=ExtractionEngine.RULE,
        item_key=item_key or f"{source}-{_seq}",
        ts=ts,
    )


def _uniform(
    source: str,
    frame: FrameLabel,
    stance: StanceLabel = StanceLabel.NEUTRAL,
) -> list[StanceRow]:
    return [
        _row(source, datetime(2026, 8, 20 + i % 10, tzinfo=UTC), stance=stance, frame=frame)
        for i in range(N_MIN_SAMPLES)
    ]


def test_below_sample_gate_abstains() -> None:
    rows = _uniform("wscn", FrameLabel.GAIN)[: N_MIN_SAMPLES - 1]
    assert build_narrative("fed", _WINDOW, rows, _TIER_MAP, as_of=_AS_OF) == []


def test_all_abstain_rows_abstains() -> None:
    rows = _uniform("wscn", FrameLabel.OTHER, StanceLabel.ABSTAIN)
    assert build_narrative("fed", _WINDOW, rows, _TIER_MAP, as_of=_AS_OF) == []


def test_idempotent_and_identity_fields() -> None:
    rows = _uniform("wscn", FrameLabel.GAIN)
    (a,) = build_narrative("fed", _WINDOW, rows, _TIER_MAP, as_of=_AS_OF)
    (b,) = build_narrative("fed", _WINDOW, rows, _TIER_MAP, as_of=_AS_OF)
    assert a == b
    assert a.narrative_id == f"nar-fed-{_WINDOW}"
    assert a.engine == "offline"
    assert a.entity_id == "fed"
    assert a.first_seen == min(r.ts for r in rows)
    expected_conf = round(0.5 * min(1 / 8, 1.0) + 0.5 * min(0 / 2, 1.0), 3)
    assert a.confidence == expected_conf


def test_provenance_split_by_stance() -> None:
    rows = (
        [
            _row(
                "wscn",
                datetime(2026, 8, 20, tzinfo=UTC),
                stance=StanceLabel.SUPPORTIVE,
                frame=FrameLabel.GAIN,
                item_key=f"ik-s{i}",
            )
            for i in range(5)
        ]
        + [
            _row(
                "wscn",
                datetime(2026, 8, 21, tzinfo=UTC),
                stance=StanceLabel.CRITICAL,
                frame=FrameLabel.LOSS,
                item_key=f"ik-c{i}",
            )
            for i in range(3)
        ]
        + [
            _row(
                "wscn",
                datetime(2026, 8, 22, tzinfo=UTC),
                stance=StanceLabel.NEUTRAL,
                frame=FrameLabel.OTHER,
                item_key=f"ik-n{i}",
            )
            for i in range(2)
        ]
    )
    (nar,) = build_narrative("fed", _WINDOW, rows, _TIER_MAP, as_of=_AS_OF)
    assert nar.supporting_item_keys == [f"ik-s{i}" for i in range(5)]
    assert nar.opposing_item_keys == [f"ik-c{i}" for i in range(3)]
    assert not (set(nar.supporting_item_keys) & set(nar.opposing_item_keys))
    assert "ik-n0" not in nar.supporting_item_keys + nar.opposing_item_keys


def test_source_cluster_mapping() -> None:
    cases = {
        "govcn": "official",
        "wscn": "financial_press",
        "x": "social",
    }
    for source, expected in cases.items():
        rows = _uniform(source, FrameLabel.OTHER)
        (nar,) = build_narrative("fed", _WINDOW, rows, _TIER_MAP, as_of=_AS_OF)
        assert nar.source_cluster == expected, source
    mixed = _uniform("govcn", FrameLabel.OTHER) + _uniform("wscn", FrameLabel.OTHER)
    (nar,) = build_narrative("fed", _WINDOW, mixed, _TIER_MAP, as_of=_AS_OF)
    assert nar.source_cluster == "mixed"


def test_momentum_density() -> None:
    early = [
        _row("wscn", datetime(2026, 8, 1, tzinfo=UTC), frame=FrameLabel.OTHER) for _ in range(8)
    ]
    late = [
        _row("wscn", datetime(2026, 8, 10, tzinfo=UTC), frame=FrameLabel.OTHER) for _ in range(2)
    ]
    (fading,) = build_narrative("fed", _WINDOW, early + late, _TIER_MAP, as_of=_AS_OF)
    assert fading.momentum == "fading"

    (rising,) = build_narrative("fed", _WINDOW, early[:2] + late * 4, _TIER_MAP, as_of=_AS_OF)
    assert rising.momentum == "rising"

    (steady,) = build_narrative("fed", _WINDOW, early[:5] + late * 3, _TIER_MAP, as_of=_AS_OF)
    assert steady.momentum == "steady"


def test_divergence_measured_vs_fallback() -> None:
    contested = _uniform("govcn", FrameLabel.LOSS) + _uniform("wscn", FrameLabel.GAIN)
    (nar,) = build_narrative("fed", _WINDOW, contested, _TIER_MAP, as_of=_AS_OF)
    assert nar.divergence > 0.0
    assert nar.divergence <= 1.0
    assert "NDI=" in nar.statement

    single_cluster = _uniform("wscn", FrameLabel.GAIN)
    (nar2,) = build_narrative("fed", _WINDOW, single_cluster, _TIER_MAP, as_of=_AS_OF)
    assert nar2.divergence == 0.0
    assert "暂不可测" in nar2.statement


def test_baseline_frame_migration_and_delta() -> None:
    base = _uniform("govcn", FrameLabel.LOSS) + _uniform("wscn", FrameLabel.LOSS)
    cur = (
        _uniform("govcn", FrameLabel.LOSS)
        + _uniform("wscn", FrameLabel.GAIN)
        + [_row("wscn", datetime(2026, 8, 25, tzinfo=UTC), frame=FrameLabel.GAIN) for _ in range(2)]
    )
    (nar,) = build_narrative("fed", _WINDOW, cur, _TIER_MAP, as_of=_AS_OF, baseline_rows=base)
    assert "由「损失」迁移至「收益」" in nar.statement
    assert "叙事分歧较前窗上升" in nar.statement

    same = _uniform("wscn", FrameLabel.GAIN)
    (nar2,) = build_narrative("fed", _WINDOW, same, _TIER_MAP, as_of=_AS_OF, baseline_rows=same)
    assert "与前窗主导框架一致" in nar2.statement


def test_migration_without_measurable_delta() -> None:
    base = _uniform("wscn", FrameLabel.LOSS)
    cur = _uniform("wscn", FrameLabel.GAIN)
    (nar,) = build_narrative("fed", _WINDOW, cur, _TIER_MAP, as_of=_AS_OF, baseline_rows=base)
    assert "由「损失」迁移至「收益」" in nar.statement
    assert "叙事分歧较前窗" not in nar.statement
