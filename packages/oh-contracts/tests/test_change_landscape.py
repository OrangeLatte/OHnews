"""ChangeLandscape 契约测试（阶段 1.5-c）。"""

import pytest
from oh_contracts.change_landscape import (
    ChangeLandscape,
    NarrativeStream,
    QualityWarning,
    SourceStream,
    TimeWindow,
)
from pydantic import ValidationError


def _scene() -> ChangeLandscape:
    from oh_contracts.briefing import DataFreshness

    return ChangeLandscape(
        scene_id="hg-20260901-abcd1234",
        generated_at="2026-09-01T00:00:00+00:00",
        baseline_window=TimeWindow(
            start="2026-08-18T00:00:00+00:00", end="2026-08-25T00:00:00+00:00"
        ),
        current_window=TimeWindow(
            start="2026-08-25T00:00:00+00:00", end="2026-09-01T00:00:00+00:00"
        ),
        source_streams=[
            SourceStream(
                source_id="govcn",
                label="govcn",
                tier="L1",
                cluster="official",
                n_baseline=3,
                n_current=5,
            ),
        ],
        narrative_streams=[
            NarrativeStream(frame="gain", label="收益", share_baseline=0.4, share_current=0.6),
        ],
        freshness=DataFreshness(
            as_of="2026-08-30T08:15:00+00:00",
            coverage_start="2026-08-27T00:00:00+00:00",
            staleness="aging",
            note="数据截至 2026-08-30",
        ),
    )


def test_roundtrip_preserves_streams() -> None:
    s = _scene()
    data = s.model_dump(mode="json")
    again = ChangeLandscape.model_validate(data)
    assert again == s
    assert again.source_streams[0].cluster == "official"
    assert again.narrative_streams[0].label == "收益"


def test_narrative_share_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        NarrativeStream(frame="gain", label="收益", share_current=1.5)


def test_frame_is_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        NarrativeStream(frame="bullish", label="看涨")


def test_warning_code_closed_vocabulary() -> None:
    QualityWarning(code="low_coverage", message="覆盖不足样本说明文字")
    QualityWarning(code="gate_insufficient_coverage", message="变化因覆盖不足被质量门拦截")
    with pytest.raises(ValidationError):
        QualityWarning(code="bad_luck", message="未知告警码应被拒绝")


def test_qualified_change_headline_gate() -> None:
    from oh_contracts.change_landscape import QualifiedChange

    with pytest.raises(ValidationError):
        QualifiedChange(change_id="sig-x", kind="narrative_shift", headline="太短")
