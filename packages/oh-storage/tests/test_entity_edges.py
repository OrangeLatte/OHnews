"""entity_edges 表（M3-S3）：批量幂等 upsert + PIT 读取。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def _edge(src: str, dst: str, kind: str = "co_occurs", weight: float = 1.0) -> dict[str, object]:
    return {
        "edge_key": f"{src}|{dst}|{kind}",
        "src": src,
        "dst": dst,
        "kind": kind,
        "weight": weight,
        "first_seen": "2026-08-29T00:00:00+00:00",
        "last_seen": "2026-08-30T00:00:00+00:00",
        "evidence": ["evt-1"],
    }


def test_edge_upsert_roundtrip(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    assert store.upsert_edges([]) == 0
    store.upsert_edges([_edge("fed", "fomc", "parent_of")])
    rows = store.edges_asof(_NOW)
    assert len(rows) == 1
    r = rows[0]
    assert (r["src"], r["dst"], r["kind"]) == ("fed", "fomc", "parent_of")
    assert r["weight"] == 1.0
    assert r["evidence"] == ["evt-1"]
    assert store.count_edges() == 1


def test_edge_idempotent_overwrite(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    store.upsert_edges([_edge("fed", "fomc", "co_occurs", weight=1.0)])
    store.upsert_edges([_edge("fed", "fomc", "co_occurs", weight=3.0)])
    assert store.count_edges() == 1
    rows = store.edges_asof(_NOW)
    assert rows[0]["weight"] == 3.0


def test_edge_pit_asof(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    e_old = _edge("fed", "fomc")
    e_new = _edge("fed", "ecb")
    e_new["last_seen"] = "2026-09-02T00:00:00+00:00"
    store.upsert_edges([e_old, e_new])
    got = {r["dst"] for r in store.edges_asof(_NOW)}
    assert got == {"fomc"}  # last_seen <= as_of 边界外排除


def test_edge_weight_desc_order(tmp_path) -> None:
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    store.upsert_edges([_edge("a", "b", weight=1.0), _edge("a", "c", weight=5.0)])
    rows = store.edges_asof(_NOW)
    assert [r["dst"] for r in rows] == ["c", "b"]
