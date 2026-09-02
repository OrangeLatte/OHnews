"""C3 跟踪预警统一存储：tracking.sqlite（清零重建，不迁移旧 watch/alerts 库）。

四类单元（entity/topic/question/element）× 两模式（track/alert）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from oh_contracts.tracking import TrackingHit, TrackingUnit

_DDL = """
CREATE TABLE IF NOT EXISTS tracking_units (
    unit_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    query TEXT NOT NULL,
    label TEXT DEFAULT '',
    mode TEXT DEFAULT 'track',
    threshold REAL,
    created_at TEXT NOT NULL,
    last_checked_at TEXT
);
CREATE TABLE IF NOT EXISTS tracking_hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    triggered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracking_hits_unit ON tracking_hits(unit_id, id);
"""

_COLS = (
    "unit_id",
    "kind",
    "query",
    "label",
    "mode",
    "threshold",
    "created_at",
    "last_checked_at",
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TrackingStore:
    def __init__(self, path: Path | str) -> None:
        import sqlite3

        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_DDL)

    def add(
        self,
        *,
        kind: str,
        query: str,
        mode: str = "track",
        label: str = "",
        threshold: float | None = None,
        now: str | None = None,
    ) -> TrackingUnit:
        uid = f"tu-{kind[:2]}-{abs(hash((kind, query, mode))) % 10**8:08d}"
        created = now or now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO tracking_units VALUES (?,?,?,?,?,?,?,NULL)",
            (uid, kind, query, label, mode, threshold, created),
        )
        self._conn.commit()
        return TrackingUnit(
            unit_id=uid,
            kind=kind,  # type: ignore[arg-type]
            query=query,
            label=label,
            mode=mode,  # type: ignore[arg-type]
            threshold=threshold,
            created_at=created,
        )

    def list(self, kind: str | None = None) -> list[TrackingUnit]:
        if kind:
            cur = self._conn.execute(
                f"SELECT {','.join(_COLS)} FROM tracking_units WHERE kind=? ORDER BY created_at",
                (kind,),
            )
        else:
            cur = self._conn.execute(
                f"SELECT {','.join(_COLS)} FROM tracking_units ORDER BY created_at"
            )
        out = []
        for r in cur.fetchall():
            d = dict(zip(_COLS, r, strict=True))
            out.append(TrackingUnit.model_validate(d))
        return out

    def get(self, unit_id: str) -> TrackingUnit | None:
        cur = self._conn.execute(
            f"SELECT {','.join(_COLS)} FROM tracking_units WHERE unit_id=?", (unit_id,)
        )
        row = cur.fetchone()
        return TrackingUnit.model_validate(dict(zip(_COLS, row, strict=True))) if row else None

    def remove(self, unit_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM tracking_units WHERE unit_id=?", (unit_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def mark_checked(self, unit_id: str, *, now: str | None = None) -> bool:
        cur = self._conn.execute(
            "UPDATE tracking_units SET last_checked_at=? WHERE unit_id=?",
            (now or now_iso(), unit_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def append_hit(
        self, unit_id: str, kind: str, summary: str, *, now: str | None = None
    ) -> TrackingHit:
        ts = now or now_iso()
        self._conn.execute(
            "INSERT INTO tracking_hits (unit_id, kind, summary, triggered_at) VALUES (?,?,?,?)",
            (unit_id, kind, summary, ts),
        )
        self._conn.commit()
        return TrackingHit(unit_id=unit_id, kind=kind, summary=summary, triggered_at=ts)  # type: ignore[arg-type]

    def hits(self, unit_id: str | None = None, *, limit: int = 50) -> list[TrackingHit]:
        if unit_id:
            cur = self._conn.execute(
                "SELECT unit_id, kind, summary, triggered_at FROM tracking_hits "
                "WHERE unit_id=? ORDER BY id DESC LIMIT ?",
                (unit_id, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT unit_id, kind, summary, triggered_at FROM tracking_hits "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        cols = ("unit_id", "kind", "summary", "triggered_at")
        return [TrackingHit.model_validate(dict(zip(cols, r, strict=True))) for r in cur.fetchall()]

    def counts(self) -> dict[str, int]:
        cur = self._conn.execute("SELECT COUNT(*) FROM tracking_units")
        n_units = int(cur.fetchone()[0])
        cur = self._conn.execute("SELECT COUNT(*) FROM tracking_hits")
        return {"units": n_units, "hits": int(cur.fetchone()[0])}
