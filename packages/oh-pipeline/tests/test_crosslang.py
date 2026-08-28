"""Phase 7 跨语言门禁（裁决 F）：D₀ 估计 / 校正距离 / 四条件 gate / cross 点位。"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import pytest
from oh_contracts.enums import FrameLabel, SourceTier, StanceLabel
from oh_contracts.schemas import NDIPoint, StanceRow
from oh_pipeline.crosslang import (
    BaselineEstimate,
    corrected_distance,
    cross_language_distance,
    cross_language_point,
    estimate_baseline,
    evaluate_gate,
    official_lang_distribution,
    should_alert,
)
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

TS = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
TIER_MAP = {
    "gov_zh": SourceTier.OFFICIAL,
    "gov_en": SourceTier.OFFICIAL,
    "wscn": SourceTier.FINANCIAL_PRESS,
}
LANG_MAP = {"gov_zh": "zh", "gov_en": "en", "wscn": "zh"}


def _stance(source: str, frame: FrameLabel, idx: int, ts: datetime = TS) -> StanceRow:
    return StanceRow(
        event_id="E01",
        source_id=source,
        entity_id="fed",
        frame=frame,
        stance=StanceLabel.NEUTRAL,
        confidence=0.7,
        engine="rule",
        item_key=f"{source}:{idx}",
        ts=ts,
    )


def _cluster_rows(source: str, frame: FrameLabel, n: int) -> list[StanceRow]:
    return [_stance(source, frame, i) for i in range(n)]


# -- official_lang_distribution -----------------------------------------------


def test_official_lang_distribution_filters_tier_and_language() -> None:
    rows = (
        _cluster_rows("gov_zh", FrameLabel.LOSS, 2)
        + _cluster_rows("gov_en", FrameLabel.GAIN, 2)
        + _cluster_rows("wscn", FrameLabel.CONFLICT, 9)  # 非 official，须被排除
    )
    zh = official_lang_distribution(rows, TIER_MAP, LANG_MAP, "zh", min_per_source=2)
    assert zh is not None
    # zh 簇只含 gov_zh（loss 主导）；wscn 非 official 不参与
    assert max(zh, key=lambda f: zh[f]) is FrameLabel.LOSS
    en = official_lang_distribution(rows, TIER_MAP, LANG_MAP, "en", min_per_source=2)
    assert en is not None
    assert max(en, key=lambda f: en[f]) is FrameLabel.GAIN


def test_official_lang_distribution_sample_gate() -> None:
    rows = _cluster_rows("gov_zh", FrameLabel.LOSS, 1)  # < min_per_source=2
    assert official_lang_distribution(rows, TIER_MAP, LANG_MAP, "zh", min_per_source=2) is None


def test_cross_language_distance_orders_and_abstains() -> None:
    same = _cluster_rows("gov_zh", FrameLabel.LOSS, 3) + _cluster_rows("gov_en", FrameLabel.LOSS, 3)
    diff = _cluster_rows("gov_zh", FrameLabel.LOSS, 3) + _cluster_rows("gov_en", FrameLabel.GAIN, 3)
    d_same = cross_language_distance(same, TIER_MAP, LANG_MAP, "zh", "en", min_per_source=3)
    d_diff = cross_language_distance(diff, TIER_MAP, LANG_MAP, "zh", "en", min_per_source=3)
    assert d_same is not None and d_diff is not None
    assert d_diff > d_same
    assert d_same < 0.1  # 同框架分布近 0（Dirichlet 平滑下不完全为 0）
    # 单语言缺官方源 → 弃权
    assert (
        cross_language_distance(same[:3], TIER_MAP, LANG_MAP, "zh", "en", min_per_source=3) is None
    )


def test_cross_language_point_forces_low_confidence() -> None:
    rows = _cluster_rows("gov_zh", FrameLabel.LOSS, 3) + _cluster_rows("gov_en", FrameLabel.GAIN, 3)
    point = cross_language_point(rows, TIER_MAP, LANG_MAP, TS, event_id="E01", min_per_source=3)
    assert point.status == "ok"
    assert point.language == "cross"
    assert point.low_confidence is True
    assert point.ndi is not None and 0.0 <= point.ndi <= 1.0
    # schema 层拦截：cross 点位不得绕过低置信标签
    with pytest.raises(ValueError, match="低置信"):
        NDIPoint(
            event_id="E01",
            ts=TS,
            ndi=0.5,
            n_sources=2,
            status="ok",
            language="cross",
            low_confidence=False,
        )
    # 任一语言弃权 → abstain（cross 也强制 low_confidence=True）
    abstain = cross_language_point(
        rows[:3], TIER_MAP, LANG_MAP, TS, event_id="E01", min_per_source=3
    )
    assert abstain.status == "abstain" and abstain.ndi is None


# -- estimate_baseline / 校正 / 告警 -------------------------------------------


def test_estimate_baseline_empty_and_unconverged() -> None:
    empty = estimate_baseline([])
    assert empty.n_null == 0 and not empty.converged
    few = estimate_baseline([0.2, 0.21, 0.19, 0.2])
    assert few.n_null == 4 and not few.converged  # n < 50


def test_estimate_baseline_converged_and_tau_quantile() -> None:
    rng = random.Random(7)
    xs = [0.20 + rng.gauss(0, 0.01) for _ in range(60)]
    b = estimate_baseline(xs)
    assert b.n_null == 60 and b.converged
    assert abs(b.mean - 0.20) < 0.01
    assert b.std < 0.02
    # τ = 95 分位：约 5% 样本超过 τ
    exceed = sum(1 for x in xs if x > b.tau)
    assert exceed <= max(3, int(0.1 * len(xs)))


def test_corrected_and_alert_locked_vs_unlocked() -> None:
    raw = [0.20 + 0.01 * ((i % 7) / 7) for i in range(50)]
    b = estimate_baseline(raw)
    assert b.converged
    corr = corrected_distance(0.45, b)
    assert corr == pytest.approx(0.45 - b.mean, abs=1e-6)
    assert should_alert(corr, b) is True  # 0.45 显著超 D₀
    assert should_alert(0.01, b) is False
    # 未收敛基线 → 永不告警（locked 语义）
    locked = BaselineEstimate(n_null=3, mean=0.2, std=0.01, tau=0.25, converged=False)
    assert should_alert(0.9, locked) is False


# -- evaluate_gate 四条件 -------------------------------------------------------


def test_gate_all_locked_when_no_data() -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    report = evaluate_gate(
        zh_first_ts=None,
        en_first_ts=None,
        now=now,
        baseline=estimate_baseline([]),
    )
    assert not report.unlocked
    names = [c.passed for c in report.conditions]
    assert names == [False, False, False, True]  # 仅低置信机制常开


def test_gate_unlocked_requires_all_four() -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    first = now - timedelta(days=40)
    rng = random.Random(1)
    xs = [0.2 + rng.gauss(0, 0.005) for _ in range(55)]
    baseline = estimate_baseline(xs)
    assert baseline.converged
    report = evaluate_gate(
        zh_first_ts=first,
        en_first_ts=first,
        now=now,
        baseline=baseline,
    )
    assert report.unlocked
    # null 集不足 → 锁定
    short = evaluate_gate(
        zh_first_ts=first,
        en_first_ts=first,
        now=now,
        baseline=estimate_baseline(xs[:10]),
    )
    assert not short.unlocked


# -- storage：null_events 与 ndi_first_ts --------------------------------------


def test_store_null_events_roundtrip_and_first_ts() -> None:
    store = SqliteStore(connect(":memory:"))
    store.register_null_event("E01", "fed", "例行决议符合预期", TS)
    store.register_null_event("E01", "fed", "例行决议符合预期", TS, notes="修订")  # 幂等更新
    store.register_null_event("E02", "boe", "例行 CPI 发布", TS + timedelta(days=1))
    store.set_null_distance("E01", 0.31)
    rows = store.null_events()
    assert len(rows) == 2
    assert rows[0]["distance"] == 0.31 and rows[0]["notes"] == "修订"
    assert rows[1]["distance"] is None
    assert store.null_distances() == [0.31]
    with pytest.raises(KeyError):
        store.set_null_distance("E404", 0.5)
    # ndi_first_ts：仅统计 ok 点位
    assert store.ndi_first_ts("zh") is None
    store.append_ndi(
        NDIPoint(event_id="E01", ts=TS, ndi=0.3, n_sources=2, status="ok", language="zh")
    )
    store.append_ndi(
        NDIPoint(
            event_id="E01", ts=TS + timedelta(hours=1), n_sources=2, status="abstain", language="zh"
        )
    )
    store.append_ndi(
        NDIPoint(
            event_id="E02",
            ts=TS + timedelta(days=1),
            ndi=0.4,
            n_sources=2,
            status="ok",
            language="zh",
        )
    )
    first = store.ndi_first_ts("zh")
    assert first is not None and math.isclose(first.timestamp(), TS.timestamp())
