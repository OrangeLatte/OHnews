"""统计层：Dirichlet 平滑 / JSD / 样本门弃权 / bootstrap CI / 温差。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from oh_contracts.constants import N_MIN_SAMPLES
from oh_contracts.enums import FrameLabel, SourceTier, StanceLabel
from oh_contracts.schemas import StanceRow
from oh_pipeline.divergence import (
    dirichlet_smooth,
    js_divergence,
    l1_gap,
    ndi_for_event,
    temperature_gap,
)

TS = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
TIER_MAP = {
    "gov": SourceTier.OFFICIAL,
    "wscn": SourceTier.FINANCIAL_PRESS,
    "weibo": SourceTier.SOCIAL,
}


def _row(source: str, frame: FrameLabel, idx: int, event: str = "E01") -> StanceRow:
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


def _polarized_rows() -> list[StanceRow]:
    """官方簇全 LOSS vs 市场簇全 GAIN（各 12 行，过样本门）。"""
    return [_row("gov", FrameLabel.LOSS, i) for i in range(12)] + [
        _row("wscn", FrameLabel.GAIN, 100 + i) for i in range(12)
    ]


def _mixed_rows() -> list[StanceRow]:
    """两簇分布相同的混合行。"""
    frames = [FrameLabel.LOSS, FrameLabel.GAIN, FrameLabel.CONFLICT]
    out = [_row("gov", frames[i % 3], i) for i in range(12)]
    out += [_row("wscn", frames[i % 3], 100 + i) for i in range(12)]
    return out


def test_dirichlet_smooth_normalizes() -> None:
    dist = dirichlet_smooth({FrameLabel.LOSS: 3, FrameLabel.GAIN: 1})
    assert len(dist) == len(FrameLabel)
    assert dist[FrameLabel.LOSS] > dist[FrameLabel.GAIN]
    assert dist[FrameLabel.OTHER] > 0  # 未观测框架获得先验质量
    assert sum(dist.values()) == pytest.approx(1.0)


def test_jsd_bounds() -> None:
    p = dirichlet_smooth({FrameLabel.LOSS: 10})
    q_same = dirichlet_smooth({FrameLabel.LOSS: 10})
    q_orth = dirichlet_smooth({FrameLabel.GAIN: 10})
    assert js_divergence(p, q_same) == pytest.approx(0.0)
    # 平滑后无零概率：正交分布的 JSD 距离理论值 ≈ 0.787（K=6, α=0.5, n=10）
    assert 0.75 < js_divergence(p, q_orth) < 0.85


def test_l1_gap_bounds() -> None:
    p = dirichlet_smooth({FrameLabel.LOSS: 10})
    q = dirichlet_smooth({FrameLabel.GAIN: 10})
    # 两簇仅在 LOSS/GAIN 上互换质量：L1 = 2×n/(N+Kα) = 20/13
    assert l1_gap(p, q) == pytest.approx(2 * 10 / 13)
    assert l1_gap(p, p) == pytest.approx(0.0)


def test_ndi_polarized_high() -> None:
    point = ndi_for_event(_polarized_rows(), TIER_MAP, TS)
    assert point.status == "ok"
    assert point.ndi is not None
    assert point.ndi > 0.7


def test_ndi_mixed_low() -> None:
    point = ndi_for_event(_mixed_rows(), TIER_MAP, TS)
    assert point.status == "ok"
    assert point.ndi is not None
    assert point.ndi < 0.35


def test_ndi_ci_covers_point_estimate() -> None:
    point = ndi_for_event(_mixed_rows(), TIER_MAP, TS)
    assert point.ci_low is not None and point.ci_high is not None
    assert point.ci_low <= point.ndi <= point.ci_high


def test_ndi_sample_gate_abstains() -> None:
    """每源 < N_min → 弃权（ndi=None），禁止有限样本噪声放大。"""
    rows = [_row("gov", FrameLabel.LOSS, i) for i in range(N_MIN_SAMPLES - 1)]
    rows += [_row("wscn", FrameLabel.GAIN, 100 + i) for i in range(3)]
    point = ndi_for_event(rows, TIER_MAP, TS)
    assert point.status == "abstain"
    assert point.ndi is None


def test_ndi_missing_cluster_abstains() -> None:
    """只有一个簇有合格源 → 弃权。"""
    rows = [_row("gov", FrameLabel.LOSS, i) for i in range(12)]
    point = ndi_for_event(rows, TIER_MAP, TS)
    assert point.status == "abstain"


def test_temperature_gap_polarized_and_none() -> None:
    assert temperature_gap(_polarized_rows(), TIER_MAP) > 1.4
    assert temperature_gap(_mixed_rows(), TIER_MAP) < 0.5
    sparse = [_row("gov", FrameLabel.LOSS, i) for i in range(4)]
    assert temperature_gap(sparse, TIER_MAP) is None


def test_ndi_deterministic_with_seed() -> None:
    rows = _mixed_rows()
    a = ndi_for_event(rows, TIER_MAP, TS, seed=7)
    b = ndi_for_event(rows, TIER_MAP, TS, seed=7)
    assert (a.ndi, a.ci_low, a.ci_high) == (b.ndi, b.ci_low, b.ci_high)
