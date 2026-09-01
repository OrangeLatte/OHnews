"""oh_api.metrics（埋点指标看板）测试：counters/比率/时延中位数/空表/端点。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from oh_agents.product_events import ProductEvent, ProductEventStore
from oh_api.metrics import build_router, compute_metrics

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _ev(event: str, session: str, ts: datetime) -> ProductEvent:
    """直接构造 ProductEvent（绕过 sqlite，纯 compute_metrics 单测用）。"""
    return ProductEvent(
        event=event,
        session=session,
        object_id="sig-x",
        from_page="/",
        freshness="daily",
        meta={},
        ts=ts,
    )


def test_counters_and_ratios(tmp_path: Path) -> None:
    """经 ProductEventStore 写读回：12 事件闭集计数 + 比率 round 3。"""
    store = ProductEventStore(tmp_path / "product_events.sqlite")
    store.append("briefing_viewed", "s1", ts=T0)
    store.append("change_opened", "s1", object_id="sig-a", ts=T0 + timedelta(seconds=30))
    store.append("evidence_opened", "s1", object_id="sig-a", ts=T0 + timedelta(seconds=40))
    store.append("evidence_opened", "s2", object_id="sig-b", ts=T0)
    store.append("watch_created", "s2", ts=T0)

    m = compute_metrics(store.recent(10_000), now=NOW)
    assert len(m["counters"]) == 12
    assert m["counters"]["briefing_viewed"] == 1
    assert m["counters"]["evidence_opened"] == 2
    assert m["counters"]["judgment_saved"] == 0  # 闭集缺失补 0
    assert m["evidence_drill_rate"] == round(2 / 1, 3)
    assert m["watch_review_rate"] == 0.0  # created>0, reviewed=0 → 0 而非 None
    assert m["n_sessions"] == 2
    assert m["data_window"]["last_ts"] is not None and m["data_window"]["first_ts"] is not None


def test_ratio_zero_denominator_none() -> None:
    """分母为 0 → None（不虚构 0%）。"""
    events = [_ev("briefing_viewed", "s1", T0)]
    m = compute_metrics(events, now=NOW)
    assert m["evidence_drill_rate"] is None
    assert m["judgment_rate"] is None
    assert m["watch_review_rate"] is None  # watch_created=0 → None
    assert m["time_to_first_change_median_sec"] is None


def test_time_to_first_change_median_two_sessions() -> None:
    """多条 session 样本取中位数；非正差与缺 briefing 的 session 被剔除。

    注：按规格，'ssr' 仅在 n_sessions 排除；其时间差样本仍进入中位数（规格原文
    未对 time-to-first-change 做 ssr 过滤，且中位数对离群 session 天然稳健）。
    """
    events = [
        _ev("briefing_viewed", "s1", T0),
        _ev("change_opened", "s1", T0 + timedelta(seconds=30)),
        _ev("briefing_viewed", "s2", T0 + timedelta(seconds=10)),
        _ev("change_opened", "s2", T0 + timedelta(seconds=100)),
        # 负差样本：change 早于 briefing → 剔除
        _ev("briefing_viewed", "s3", T0 + timedelta(seconds=60)),
        _ev("change_opened", "s3", T0),
        # 无 briefing 的 session → 剔除；'ssr' → 不计 n_sessions（但计入中位数）
        _ev("change_opened", "s4", T0),
        _ev("briefing_viewed", "ssr", T0),
        _ev("change_opened", "ssr", T0 + timedelta(seconds=5)),
    ]
    m = compute_metrics(events, now=NOW)
    assert m["time_to_first_change_median_sec"] == 30.0  # median(30, 90, 5)
    assert m["n_sessions"] == 4  # s1/s2/s3/s4 有事件即计；仅排除 'ssr'


def test_empty_events_safe() -> None:
    """空事件表：全 0 计数、None 比率、None 窗口——不抛异常。"""
    m = compute_metrics([], now=NOW)
    assert set(m["counters"].values()) == {0}
    assert m["evidence_drill_rate"] is None
    assert m["judgment_rate"] is None
    assert m["watch_review_rate"] is None
    assert m["time_to_first_change_median_sec"] is None
    assert m["n_sessions"] == 0
    assert m["data_window"] == {"first_ts": None, "last_ts": None}


def test_router_endpoint(tmp_path: Path) -> None:
    """build_router 挂载即用：GET /api/metrics 与主线 lambda 注入同构。"""
    db = tmp_path / "product_events.sqlite"
    store = ProductEventStore(db)
    store.append("briefing_viewed", "s1", ts=T0)
    app = FastAPI()
    app.include_router(build_router(lambda: ProductEventStore(db)))
    r = TestClient(app).get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["counters"]["briefing_viewed"] == 1
    assert data["n_sessions"] == 1
