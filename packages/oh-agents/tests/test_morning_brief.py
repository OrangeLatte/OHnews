"""晨报：NDI 环比 + 证据链回溯 + 文本渲染。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from conftest import TIER_MAP, make_now, seed_event
from oh_agents.morning_brief import build_brief
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def _setup(tmp_path: Path, two_days: bool):
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    now = make_now()
    ev1 = seed_event(bronze, store, "E01", now)
    if two_days:
        seed_event(bronze, store, "E02", now - timedelta(days=1))
    return bronze, store, now, ev1


def test_brief_single_day_cold_start(tmp_path: Path) -> None:
    bronze, store, now, ev = _setup(tmp_path, two_days=False)
    run_pipeline(
        bronze,
        store,
        store,
        [ev],
        TIER_MAP,
        as_of=now,
        lookback_days=1,
        min_per_source=10,
    )
    brief = build_brief(bronze, store, store, ["fed"], now=now)
    assert len(brief.items) == 1
    item = brief.items[0]
    assert item.entity_ids == ("fed",)
    assert item.ndi > 0.7
    assert item.prev_ndi is None and item.delta is None
    assert item.regime == "cold_start"
    assert len(item.evidence) == 3
    assert all(e.startswith("[gov]") or e.startswith("[wscn]") for e in item.evidence)
    text = brief.render_text()
    assert "晨报" in text and "cold_start" in text and "非收益预测器" in text


def test_brief_two_days_delta(tmp_path: Path) -> None:
    bronze, store, now, ev = _setup(tmp_path, two_days=True)
    for day in (now - timedelta(days=1), now):
        run_pipeline(
            bronze,
            store,
            store,
            [ev],
            TIER_MAP,
            as_of=day,
            lookback_days=1,
            min_per_source=10,
        )
    brief = build_brief(bronze, store, store, ["fed"], now=now)
    assert brief.items[0].delta is not None


def test_brief_watchlist_miss(tmp_path: Path) -> None:
    bronze, store, now, ev = _setup(tmp_path, two_days=False)
    run_pipeline(
        bronze, store, store, [ev], TIER_MAP, as_of=now, lookback_days=1, min_per_source=10
    )
    brief = build_brief(bronze, store, store, ["ecb"], now=now)
    assert brief.items == ()
    assert "无 NDI 事件" in brief.render_text()
