"""认知快照账本（阶段 2 判断闭环）。

记录用户对变化的判断（BeliefSnapshot）——仅用户主动确认写入；
独立 sqlite（belief.sqlite，不进 Silver/Gold：个人数据与产品数据分离，
对齐 DecisionLog/ProductEventStore 模式）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from oh_contracts.belief import BeliefSnapshot

_DDL = """
CREATE TABLE IF NOT EXISTS beliefs (
    snapshot_id   TEXT PRIMARY KEY,
    change_id     TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    subject_label TEXT NOT NULL DEFAULT '',
    stance        TEXT NOT NULL,
    confidence    REAL NOT NULL,
    rationale     TEXT NOT NULL DEFAULT '',
    change_type   TEXT NOT NULL,
    believed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_belief_change ON beliefs(change_id);
CREATE INDEX IF NOT EXISTS idx_belief_subject ON beliefs(subject_id, believed_at);
"""


class BeliefStore:
    """BeliefSnapshot CRUD（WAL 连接由调用方传入或自动创建）。"""

    def __init__(self, db_path: Path | str | Connection) -> None:
        if isinstance(db_path, Connection):
            self._conn = db_path
        else:
            from oh_storage.connection import connect

            self._conn = connect(db_path)
        self._conn.executescript(_DDL)
        self._conn.commit()

    def save(self, snap: BeliefSnapshot) -> BeliefSnapshot:
        """写入一条快照（INSERT OR REPLACE：snapshot_id 幂等）。"""
        self._conn.execute(
            "INSERT OR REPLACE INTO beliefs "
            "(snapshot_id, change_id, subject_id, subject_label, stance, confidence, "
            "rationale, change_type, believed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snap.snapshot_id,
                snap.change_id,
                snap.subject_id,
                snap.subject_label,
                snap.stance,
                snap.confidence,
                snap.rationale,
                snap.change_type,
                snap.believed_at.isoformat(),
            ),
        )
        self._conn.commit()
        return snap

    def for_change(self, change_id: str) -> list[BeliefSnapshot]:
        """某变化的全部快照（believed_at 升序）。"""
        rows = self._conn.execute(
            "SELECT * FROM beliefs WHERE change_id = ? ORDER BY believed_at, rowid",
            (change_id,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def latest_for_change(self, change_id: str) -> BeliefSnapshot | None:
        """某变化最新一条快照（服务端判定 change_type 用）。"""
        beliefs = self.for_change(change_id)
        return beliefs[-1] if beliefs else None

    def timeline(self, subject_id: str) -> list[BeliefSnapshot]:
        """某实体的认知时间线（跨变化，believed_at 升序）。"""
        rows = self._conn.execute(
            "SELECT * FROM beliefs WHERE subject_id = ? ORDER BY believed_at, rowid",
            (subject_id,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    @staticmethod
    def _from_row(r) -> BeliefSnapshot:  # noqa: ANN001 (sqlite3.Row)
        return BeliefSnapshot(
            snapshot_id=r["snapshot_id"],
            change_id=r["change_id"],
            subject_id=r["subject_id"],
            subject_label=r["subject_label"],
            stance=r["stance"],
            confidence=r["confidence"],
            rationale=r["rationale"],
            change_type=r["change_type"],
            believed_at=datetime.fromisoformat(r["believed_at"]),
        )


def now_utc() -> datetime:
    """服务端时间锚（believed_at 只由服务端写入）。"""
    return datetime.now(UTC)


__all__ = ["BeliefStore", "now_utc"]
