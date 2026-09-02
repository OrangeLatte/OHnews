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
