"""Silver + Gold 的 SQLite 实现（单写者；DDL 幂等；PIT 以 ISO 字符串比较为锚）。

时间统一 isoformat（tz-aware UTC）存储；同格式下字符串比较即时间序比较。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlite3 import Connection

from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    StanceLabel,
)
from oh_contracts.schemas import EventRecord, NDIPoint, StanceRow

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id   TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    entities   TEXT NOT NULL DEFAULT '[]',
    as_of      TEXT NOT NULL,
    first_seen TEXT
);

CREATE TABLE IF NOT EXISTS stances (
    stance_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL REFERENCES events(event_id),
    source_id  TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    frame      TEXT NOT NULL,
    stance     TEXT NOT NULL,
    confidence REAL NOT NULL,
    engine     TEXT NOT NULL,
    item_key   TEXT NOT NULL,
    ts         TEXT NOT NULL,
    UNIQUE (event_id, source_id, entity_id, frame, item_key)
);
CREATE INDEX IF NOT EXISTS idx_stances_ts ON stances (ts);

CREATE TABLE IF NOT EXISTS ndi_series (
    event_id  TEXT NOT NULL,
    ts        TEXT NOT NULL,
    ndi       REAL,
    ci_low    REAL,
    ci_high   REAL,
    n_sources INTEGER NOT NULL,
    status    TEXT NOT NULL,
    language  TEXT NOT NULL DEFAULT 'all',
    PRIMARY KEY (event_id, ts, language)
);
"""

_MIGRATE_NDI_LANGUAGE = """
CREATE TABLE IF NOT EXISTS ndi_series_new (
    event_id  TEXT NOT NULL,
    ts        TEXT NOT NULL,
    ndi       REAL,
    ci_low    REAL,
    ci_high   REAL,
    n_sources INTEGER NOT NULL,
    status    TEXT NOT NULL,
    language  TEXT NOT NULL DEFAULT 'all',
    PRIMARY KEY (event_id, ts, language)
);
INSERT OR IGNORE INTO ndi_series_new
    SELECT event_id, ts, ndi, ci_low, ci_high, n_sources, status,
           'all' FROM ndi_series;
DROP TABLE ndi_series;
ALTER TABLE ndi_series_new RENAME TO ndi_series;
"""


def _migrate_ndi_language(conn: Connection) -> None:
    """ndi_series 加 language 维度（老库 PK 无 language → 重建，幂等）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(ndi_series)").fetchall()}
    if not cols or "language" in cols:
        return
    conn.executescript(_MIGRATE_NDI_LANGUAGE)
    conn.commit()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class SqliteStore:
    """SilverStore + GoldReader 的 SQLite 实现（Phase 0 默认）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_DDL)
        self._conn.commit()
        _migrate_ndi_language(self._conn)

    # -- Silver -------------------------------------------------------------

    def upsert_event(self, event: EventRecord) -> None:
        self._conn.execute(
            "INSERT INTO events (event_id, title, summary, entities, as_of, first_seen) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(event_id) DO UPDATE SET title = excluded.title, "
            "summary = excluded.summary, entities = excluded.entities, as_of = excluded.as_of",
            (
                event.event_id,
                event.title,
                event.summary,
                json.dumps(event.entities, ensure_ascii=False),
                _iso(event.as_of),
                _iso(event.first_seen) if event.first_seen else None,
            ),
        )
        self._conn.commit()

    def append_stances(self, rows: Sequence[StanceRow]) -> int:
        before = self._conn.total_changes
        self._conn.executemany(
            "INSERT OR IGNORE INTO stances "
            "(event_id, source_id, entity_id, frame, stance, confidence, engine, item_key, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r.event_id,
                    r.source_id,
                    r.entity_id,
                    r.frame.value,
                    r.stance.value,
                    r.confidence,
                    r.engine.value,
                    r.item_key,
                    _iso(r.ts),
                )
                for r in rows
            ],
        )
        self._conn.commit()
        return self._conn.total_changes - before

    def events_asof(self, as_of: datetime) -> list[EventRecord]:
        cur = self._conn.execute(
            "SELECT event_id, title, summary, entities, as_of, first_seen "
            "FROM events WHERE as_of <= ? ORDER BY as_of",
            (_iso(as_of),),
        )
        return [self._event_from_row(row) for row in cur.fetchall()]

    def stances_asof(self, as_of: datetime) -> list[StanceRow]:
        cur = self._conn.execute(
            "SELECT event_id, source_id, entity_id, frame, stance, "
            "confidence, engine, item_key, ts "
            "FROM stances WHERE ts <= ? ORDER BY ts",
            (_iso(as_of),),
        )
        return [self._stance_from_row(row) for row in cur.fetchall()]

    def count_events(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def count_stances(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM stances").fetchone()[0])

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> EventRecord:
        first_seen = row["first_seen"]
        return EventRecord(
            event_id=str(row["event_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            entities=json.loads(str(row["entities"])),
            as_of=datetime.fromisoformat(str(row["as_of"])),
            first_seen=datetime.fromisoformat(first_seen) if first_seen else None,
        )

    @staticmethod
    def _stance_from_row(row: sqlite3.Row) -> StanceRow:
        return StanceRow(
            event_id=str(row["event_id"]),
            source_id=str(row["source_id"]),
            entity_id=str(row["entity_id"]),
            frame=FrameLabel(str(row["frame"])),
            stance=StanceLabel(str(row["stance"])),
            confidence=float(row["confidence"]),
            engine=ExtractionEngine(str(row["engine"])),
            item_key=str(row["item_key"]),
            ts=datetime.fromisoformat(str(row["ts"])),
        )

    # -- Gold ---------------------------------------------------------------

    def append_ndi(self, point: NDIPoint) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ndi_series "
            "(event_id, ts, ndi, ci_low, ci_high, n_sources, status, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                point.event_id,
                _iso(point.ts),
                point.ndi,
                point.ci_low,
                point.ci_high,
                point.n_sources,
                point.status,
                point.language,
            ),
        )
        self._conn.commit()

    def ndi_series(self, event_id: str, *, language: str | None = None) -> list[NDIPoint]:
        sql = (
            "SELECT event_id, ts, ndi, ci_low, ci_high, n_sources, status, language "
            "FROM ndi_series WHERE event_id = ?"
        )
        params: list[str] = [event_id]
        if language is not None:
            sql += " AND language = ?"
            params.append(language)
        cur = self._conn.execute(sql + " ORDER BY ts", params)
        return [
            NDIPoint(
                event_id=str(row["event_id"]),
                ts=datetime.fromisoformat(str(row["ts"])),
                ndi=None if row["ndi"] is None else float(row["ndi"]),
                ci_low=None if row["ci_low"] is None else float(row["ci_low"]),
                ci_high=None if row["ci_high"] is None else float(row["ci_high"]),
                n_sources=int(row["n_sources"]),
                status=str(row["status"]),  # type: ignore[arg-type]
                language=str(row["language"]),
            )
            for row in cur.fetchall()
        ]
