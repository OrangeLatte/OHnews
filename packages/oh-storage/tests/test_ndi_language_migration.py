"""ndi_series language 维度迁移：老库（PK 无 language）重建后旧数据归 'all'。"""

from __future__ import annotations

import sqlite3

from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def test_migrate_legacy_ndi_series(tmp_path) -> None:
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE ndi_series (
            event_id  TEXT NOT NULL,
            ts        TEXT NOT NULL,
            ndi       REAL,
            ci_low    REAL,
            ci_high   REAL,
            n_sources INTEGER NOT NULL,
            status    TEXT NOT NULL,
            PRIMARY KEY (event_id, ts)
        );
        INSERT INTO ndi_series VALUES ('E01', '2026-08-26T18:00:00+00:00', 0.5, 0.4, 0.6, 3, 'ok');
        """
    )
    conn.commit()
    conn.close()

    # 用项目 connect（WAL 等 PRAGMA）重开 → SqliteStore 触发迁移
    store = SqliteStore(connect(db))
    cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(ndi_series)").fetchall()}
    assert "language" in cols
    series = store.ndi_series("E01")
    assert len(series) == 1
    assert series[0].language == "all"
    assert series[0].ndi == 0.5

    # 迁移后可写入带 language 的新点（不同语言不互覆）
    from datetime import UTC, datetime

    from oh_contracts.schemas import NDIPoint

    ts = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
    store.append_ndi(
        NDIPoint(
            event_id="E01",
            ts=ts,
            ndi=0.7,
            ci_low=None,
            ci_high=None,
            n_sources=2,
            status="ok",
            language="zh",
        )
    )
    assert len(store.ndi_series("E01", language="zh")) == 1
    assert len(store.ndi_series("E01", language="all")) == 1


def test_migrate_idempotent(tmp_path) -> None:
    """新库（已含 language）二次打开不触发重建、数据不丢。"""
    db = tmp_path / "fresh.sqlite"
    store1 = SqliteStore(connect(db))
    from datetime import UTC, datetime

    from oh_contracts.schemas import NDIPoint

    ts = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)
    store1.append_ndi(
        NDIPoint(
            event_id="E01",
            ts=ts,
            ndi=0.7,
            ci_low=None,
            ci_high=None,
            n_sources=2,
            status="ok",
            language="zh",
        )
    )
    store2 = SqliteStore(connect(db))
    assert len(store2.ndi_series("E01", language="zh")) == 1
