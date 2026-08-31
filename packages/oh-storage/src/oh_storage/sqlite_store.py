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
    event_id    TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    entities    TEXT NOT NULL DEFAULT '[]',
    as_of       TEXT NOT NULL,
    first_seen  TEXT,
    cluster_key TEXT
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
    low_confidence INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, ts, language)
);

CREATE TABLE IF NOT EXISTS null_events (
    event_id      TEXT PRIMARY KEY,
    entity_id     TEXT NOT NULL,
    reason        TEXT NOT NULL,
    notes         TEXT NOT NULL DEFAULT '',
    distance      REAL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    item_key     TEXT PRIMARY KEY,
    payload      TEXT NOT NULL,
    engine       TEXT NOT NULL,
    annotated_at TEXT NOT NULL
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
    low_confidence INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event_id, ts, language)
);
INSERT OR IGNORE INTO ndi_series_new
    SELECT event_id, ts, ndi, ci_low, ci_high, n_sources, status,
           'all', 0 FROM ndi_series;
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


def _migrate_ndi_low_confidence(conn: Connection) -> None:
    """ndi_series 加 low_confidence 列（早期 language 迁移产物缺列，幂等 ALTER）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(ndi_series)").fetchall()}
    if not cols or "low_confidence" in cols:
        return
    conn.execute("ALTER TABLE ndi_series ADD COLUMN low_confidence INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _migrate_events_cluster_key(conn: Connection) -> None:
    """events 加 cluster_key 列（M3-S2 语义聚类，幂等 ALTER）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    if not cols or "cluster_key" in cols:
        return
    conn.execute("ALTER TABLE events ADD COLUMN cluster_key TEXT")
    conn.commit()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ndi_from_row(row: sqlite3.Row) -> NDIPoint:
    return NDIPoint(
        event_id=str(row["event_id"]),
        ts=datetime.fromisoformat(str(row["ts"])),
        ndi=None if row["ndi"] is None else float(row["ndi"]),
        ci_low=None if row["ci_low"] is None else float(row["ci_low"]),
        ci_high=None if row["ci_high"] is None else float(row["ci_high"]),
        n_sources=int(row["n_sources"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        language=str(row["language"]),
        low_confidence=bool(row["low_confidence"]),
    )


class SqliteStore:
    """SilverStore + GoldReader 的 SQLite 实现（Phase 0 默认）。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_DDL)
        self._conn.commit()
        _migrate_ndi_language(self._conn)
        _migrate_ndi_low_confidence(self._conn)
        _migrate_events_cluster_key(self._conn)

    # -- Silver -------------------------------------------------------------

    def upsert_event(self, event: EventRecord) -> None:
        self._conn.execute(
            "INSERT INTO events "
            "(event_id, title, summary, entities, as_of, first_seen, cluster_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(event_id) DO UPDATE SET title = excluded.title, "
            "summary = excluded.summary, entities = excluded.entities, as_of = excluded.as_of, "
            "cluster_key = excluded.cluster_key",
            (
                event.event_id,
                event.title,
                event.summary,
                json.dumps(event.entities, ensure_ascii=False),
                _iso(event.as_of),
                _iso(event.first_seen) if event.first_seen else None,
                event.cluster_key,
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
            "(event_id, ts, ndi, ci_low, ci_high, n_sources, status, language, low_confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                point.event_id,
                _iso(point.ts),
                point.ndi,
                point.ci_low,
                point.ci_high,
                point.n_sources,
                point.status,
                point.language,
                int(point.low_confidence),
            ),
        )
        self._conn.commit()

    def ndi_series(self, event_id: str, *, language: str | None = None) -> list[NDIPoint]:
        sql = (
            "SELECT event_id, ts, ndi, ci_low, ci_high, n_sources, status, language, "
            "low_confidence FROM ndi_series WHERE event_id = ?"
        )
        params: list[str] = [event_id]
        if language is not None:
            sql += " AND language = ?"
            params.append(language)
        cur = self._conn.execute(sql + " ORDER BY ts", params)
        return [_ndi_from_row(row) for row in cur.fetchall()]

    def ndi_first_ts(self, language: str) -> datetime | None:
        """某 within-language 管线首个 ok 点位时间（裁决 F gate 条件 1/2 的稳定天数起点）。"""
        row = self._conn.execute(
            "SELECT MIN(ts) FROM ndi_series WHERE language = ? AND status = 'ok'",
            (language,),
        ).fetchone()
        ts = row[0] if row else None
        return datetime.fromisoformat(str(ts)) if ts else None

    # -- Phase 7 跨语言门禁：null 集 -----------------------------------------

    def register_null_event(
        self,
        event_id: str,
        entity_id: str,
        reason: str,
        registered_at: datetime,
        *,
        notes: str = "",
    ) -> None:
        """登记 null 事件（无实质分歧的常规事件，裁决 F 语域基线样本）。"""
        self._conn.execute(
            "INSERT INTO null_events (event_id, entity_id, reason, notes, registered_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(event_id) DO UPDATE SET entity_id = excluded.entity_id, "
            "reason = excluded.reason, notes = excluded.notes",
            (event_id, entity_id, reason, notes, _iso(registered_at)),
        )
        self._conn.commit()

    def set_null_distance(self, event_id: str, distance: float) -> None:
        """回写 null 事件的跨语言原始距离（供 D₀ 估计）。"""
        cur = self._conn.execute(
            "UPDATE null_events SET distance = ? WHERE event_id = ?",
            (distance, event_id),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"null 事件未登记: {event_id}")

    def null_events(self) -> list[dict[str, object]]:
        cur = self._conn.execute(
            "SELECT event_id, entity_id, reason, notes, distance, registered_at "
            "FROM null_events ORDER BY registered_at"
        )
        return [
            {
                "event_id": str(r["event_id"]),
                "entity_id": str(r["entity_id"]),
                "reason": str(r["reason"]),
                "notes": str(r["notes"]),
                "distance": None if r["distance"] is None else float(r["distance"]),
                "registered_at": str(r["registered_at"]),
            }
            for r in cur.fetchall()
        ]

    def null_distances(self) -> list[float]:
        cur = self._conn.execute("SELECT distance FROM null_events WHERE distance IS NOT NULL")
        return [float(r["distance"]) for r in cur.fetchall()]

    # -- 语义标注层（M3-S1：annotations 表，payload=SemanticAnnotation JSON） ----

    def upsert_annotation(
        self,
        item_key: str,
        payload: dict[str, object],
        engine: str,
        annotated_at: datetime,
    ) -> None:
        """幂等 upsert（同 item_key 重新标注覆盖；payload 由调用方 model_dump）。"""
        self._conn.execute(
            "INSERT OR REPLACE INTO annotations (item_key, payload, engine, annotated_at) "
            "VALUES (?, ?, ?, ?)",
            (item_key, json.dumps(payload, ensure_ascii=False), engine, _iso(annotated_at)),
        )
        self._conn.commit()

    def get_annotation(self, item_key: str) -> dict[str, object] | None:
        """单条标注（payload 反序列化；未标注 → None）。"""
        cur = self._conn.execute(
            "SELECT payload, engine, annotated_at FROM annotations WHERE item_key = ?",
            (item_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            **json.loads(str(row["payload"])),
            "engine": str(row["engine"]),
            "annotated_at": str(row["annotated_at"]),
        }

    def annotations_asof(self, as_of: datetime) -> list[dict[str, object]]:
        """PIT 读取：annotated_at ≤ as_of 的标注（ISO 字符串比较即时间序）。"""
        cur = self._conn.execute(
            "SELECT item_key, payload, engine, annotated_at FROM annotations "
            "WHERE annotated_at <= ? ORDER BY item_key",
            (_iso(as_of),),
        )
        return [
            {
                "item_key": str(r["item_key"]),
                **json.loads(str(r["payload"])),
                "engine": str(r["engine"]),
                "annotated_at": str(r["annotated_at"]),
            }
            for r in cur.fetchall()
        ]

    def count_annotations(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM annotations")
        return int(cur.fetchone()["n"])

    # -- 信息流可视化（/api/flow 聚合面） ---------------------------------------

    def flow_frames(self) -> list[dict[str, object]]:
        """全部 stance 按 日期×框架 聚合流量（主题河流图数据面）。"""
        cur = self._conn.execute(
            "SELECT substr(ts, 1, 10) AS day, frame, COUNT(*) AS n "
            "FROM stances GROUP BY day, frame ORDER BY day, frame"
        )
        return [
            {"date": str(r["day"]), "frame": str(r["frame"]), "n": int(r["n"])}
            for r in cur.fetchall()
        ]

    def ndi_all(self) -> list[NDIPoint]:
        """全部 NDI 点位（时间正序，跨事件；情报大屏总览数据面）。"""
        cur = self._conn.execute(
            "SELECT event_id, ts, ndi, ci_low, ci_high, n_sources, status, language, "
            "low_confidence FROM ndi_series ORDER BY ts"
        )
        return [_ndi_from_row(row) for row in cur.fetchall()]
