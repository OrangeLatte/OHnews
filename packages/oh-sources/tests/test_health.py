"""SourceHealthTracker 测试：四维统计 / 健康分 / 降级清单（tmp sqlite，全离线）。"""

from datetime import UTC, datetime, timedelta

import pytest
from oh_sources.health import SourceHealthTracker


@pytest.fixture()
def tracker(tmp_path):
    t = SourceHealthTracker(tmp_path / "health.sqlite")
    yield t
    t.close()


def _seed(tracker: SourceHealthTracker, source_id: str, spec: list[tuple[bool, int, int]]) -> None:
    """直接注入历史行（绕过 now()）；spec 逐条 (ok, n_items, n_written)。"""
    now = datetime.now(UTC)
    for i, (ok, items, written) in enumerate(spec):
        started = (now - timedelta(hours=48 * i + 1)).isoformat()
        tracker._conn.execute(
            "INSERT INTO source_fetch_logs(source_id, started_at, ok, n_items, n_written,"
            " error, duration_ms) VALUES (?, ?, ?, ?, ?, NULL, 100.0)",
            (source_id, started, int(ok), items, written),
        )
    tracker._conn.commit()


def test_stats_and_score(tracker):
    _seed(tracker, "good", [(True, 10, 8), (True, 10, 9), (False, 0, 0)])
    s = tracker.stats("good")
    assert s["runs"] == 3
    assert s["success_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["produced_rate"] == 1.0
    assert s["duplicate_rate"] == pytest.approx(1 - 17 / 20, abs=1e-3)
    score = tracker.health_score("good")
    assert score is not None and 0.0 < score <= 1.0


def test_empty_source_returns_none_score(tracker):
    assert tracker.stats("ghost")["runs"] == 0
    assert tracker.health_score("ghost") is None


def test_stale_source_penalized(tracker):
    """最近成功 >48h → 健康分减半。"""
    _seed(tracker, "stale", [(True, 10, 10)])
    fresh = tracker.health_score("stale")
    # 人为把唯一 ok 行改到 72h 前
    old = (datetime.now(UTC) - timedelta(hours=72)).isoformat()
    tracker._conn.execute("UPDATE source_fetch_logs SET started_at=?", (old,))
    tracker._conn.commit()
    stale = tracker.health_score("stale")
    assert fresh is not None and stale is not None
    assert stale == pytest.approx(fresh * 0.5, abs=1e-6)


def test_degraded_sources(tracker):
    _seed(tracker, "bad", [(False, 0, 0), (False, 0, 0), (False, 0, 0)])
    _seed(tracker, "good", [(True, 5, 5)])
    degraded = tracker.degraded_sources(min_score=0.3)
    assert "bad" in degraded
    assert "good" not in degraded
