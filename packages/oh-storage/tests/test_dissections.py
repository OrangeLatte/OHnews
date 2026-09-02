"""M5-A3：article_dissections 表 roundtrip/幂等/PIT。"""

from datetime import UTC, datetime

from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def _store(tmp_path) -> SqliteStore:
    return SqliteStore(connect(tmp_path / "silver.sqlite"))


def test_roundtrip_and_defaults(tmp_path) -> None:
    s = _store(tmp_path)
    payload = {"item_key": "k1", "title": "T", "elements": [], "model_hint": "glm-5.3"}
    s.upsert_dissection("k1", payload, "llm", datetime(2026, 9, 2, tzinfo=UTC), language="zh")
    got = s.get_dissection("k1")
    assert got is not None
    assert got["title"] == "T" and got["engine"] == "llm" and got["language"] == "zh"
    assert got["dissected_at"].startswith("2026-09-02")
    assert s.count_dissections() == 1


def test_idempotent_upsert_overwrites(tmp_path) -> None:
    s = _store(tmp_path)
    s.upsert_dissection("k1", {"v": 1}, "llm", datetime(2026, 9, 1, tzinfo=UTC))
    s.upsert_dissection("k1", {"v": 2}, "llm", datetime(2026, 9, 2, tzinfo=UTC))
    assert s.count_dissections() == 1
    assert s.get_dissection("k1")["v"] == 2  # type: ignore[index]


def test_pit_boundary_inclusive_and_missing(tmp_path) -> None:
    s = _store(tmp_path)
    s.upsert_dissection("k1", {}, "llm", datetime(2026, 9, 2, 12, 0, tzinfo=UTC))
    got = s.dissections_asof(datetime(2026, 9, 2, 12, 0, tzinfo=UTC))
    assert [d["item_key"] for d in got] == ["k1"]
    assert s.dissections_asof(datetime(2026, 9, 2, 11, 59, tzinfo=UTC)) == []
    assert s.get_dissection("ghost") is None


def test_dissection_queue_flow(tmp_path) -> None:
    store = _store(tmp_path)
    """B0 队列：入队幂等/按分排序/裁决流转。"""
    store.queue_upsert(
        "k1", score=0.9, reasons=["官方一手来源"], created_at="2026-09-02T00:00:00+00:00"
    )
    store.queue_upsert("k1", score=0.1, reasons=["dup"], created_at="2026-09-02T00:00:01+00:00")
    store.queue_upsert("k2", score=0.7, reasons=[], created_at="2026-09-02T00:00:00+00:00")
    items = store.queue_items(limit=10)
    assert [i["item_key"] for i in items] == ["k1", "k2"]
    assert items[0]["score"] == 0.9 and items[0]["reasons"] == ["官方一手来源"]
    assert store.queue_decide("k1", status="accepted", decided_at="2026-09-02T01:00:00+00:00")
    assert not store.queue_decide(
        "ghost", status="accepted", decided_at="2026-09-02T01:00:00+00:00"
    )
    assert [i["item_key"] for i in store.queue_items(status="accepted")] == ["k1"]
    assert store.queue_count() == 2
