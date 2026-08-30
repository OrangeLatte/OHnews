"""annotations 表（M3-S1）：幂等 upsert + PIT 读取。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def test_annotation_upsert_get_roundtrip(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    payload = {"item_key": "k-1", "roles": [], "emotions": {"intensity": 0.3}}
    store.upsert_annotation("k-1", payload, "lexicon", _NOW)
    got = store.get_annotation("k-1")
    assert got is not None
    assert got["engine"] == "lexicon"
    assert got["annotated_at"] == _NOW.isoformat()
    assert got["item_key"] == "k-1"
    assert got["emotions"]["intensity"] == 0.3


def test_annotation_idempotent_overwrite(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    store.upsert_annotation("k-1", {"v": 1}, "lexicon", _NOW)
    later = datetime(2026, 9, 1, tzinfo=UTC)
    store.upsert_annotation("k-1", {"v": 2}, "llm", later)
    assert store.count_annotations() == 1
    got = store.get_annotation("k-1")
    assert got is not None and got["v"] == 2 and got["engine"] == "llm"


def test_annotation_pit_asof(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    d1 = datetime(2026, 8, 29, tzinfo=UTC)
    d2 = datetime(2026, 8, 30, tzinfo=UTC)
    store.upsert_annotation("k-old", {"a": 1}, "lexicon", d1)
    store.upsert_annotation("k-new", {"a": 2}, "lexicon", d2)
    # <= 语义（同 stances_asof 惯例）：边界点含
    keys = {r["item_key"] for r in store.annotations_asof(d2)}
    assert keys == {"k-old", "k-new"}
    keys_d1 = {r["item_key"] for r in store.annotations_asof(d1)}
    assert keys_d1 == {"k-old"}
    assert store.get_annotation("k-new") is not None


def test_annotation_missing_returns_none(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    assert store.get_annotation("ghost") is None
