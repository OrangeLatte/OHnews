"""Watch 订阅中心（REDESIGN §3 四页 IA：Watch 页存储层）。

三类订阅（v3 纲领）：
- entity：实体订阅（复用 detect_signals 的 entity_id 过滤）；
- topic：主题关键词订阅（Bronze 标题/正文命中计数）；
- question：研究问题订阅（保存问题句 + 事件关联，Agent 化在 R4）。

与 alerts（NDI 分位预警）互补：watch 是用户显式意图的持久化，
refresh 产出的 last_summary 是确定性快照（无 LLM）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS watches (
    watch_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_summary TEXT
)
"""

WATCH_TYPES = ("entity", "topic", "question")


@dataclass(frozen=True)
class Watch:
    watch_id: str
    type: str
    query: str
    created_at: str
    last_checked_at: str | None
    last_summary: dict[str, Any] | None


def _row_to_watch(row: sqlite3.Row) -> Watch:
    raw = row["last_summary"]
    return Watch(
        watch_id=row["watch_id"],
        type=row["type"],
        query=row["query"],
        created_at=row["created_at"],
        last_checked_at=row["last_checked_at"],
        last_summary=json.loads(raw) if raw else None,
    )


class WatchStore:
    """watches 表 CRUD（sqlite，与 alerts/chat/intel 同模式单库单写者）。"""

    def __init__(self, db_path: Path | str | sqlite3.Connection) -> None:
        if isinstance(db_path, sqlite3.Connection):
            self._conn = db_path
        else:
            from oh_storage.connection import connect

            self._conn = connect(Path(db_path))
        self._conn.executescript(_DDL)
        self._conn.commit()

    def add(self, *, type: str, query: str, now: datetime) -> Watch:
        if type not in WATCH_TYPES:
            raise ValueError(f"unknown watch type: {type}")
        q = query.strip()
        if not q:
            raise ValueError("query must be non-empty")
        watch_id = f"watch-{uuid.uuid4().hex[:10]}"
        self._conn.execute(
            "INSERT INTO watches (watch_id, type, query, created_at,"
            " last_checked_at, last_summary) VALUES (?, ?, ?, ?, ?, ?)",
            (watch_id, type, q, now.isoformat(), None, None),
        )
        self._conn.commit()
        return Watch(watch_id, type, q, now.isoformat(), None, None)

    def remove(self, watch_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM watches WHERE watch_id = ?", (watch_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def list(self) -> list[Watch]:
        rows = self._conn.execute("SELECT * FROM watches ORDER BY created_at DESC").fetchall()
        return [_row_to_watch(r) for r in rows]

    def get(self, watch_id: str) -> Watch | None:
        row = self._conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
        return _row_to_watch(row) if row else None

    def save_summary(self, watch_id: str, *, now: datetime, summary: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE watches SET last_checked_at = ?, last_summary = ? WHERE watch_id = ?",
            (now.isoformat(), json.dumps(summary, ensure_ascii=False), watch_id),
        )
        self._conn.commit()

    def mark_reviewed(self, watch_id: str, *, now: datetime) -> bool:
        """显式复核（阶段 3 Review Judgment）：仅推进 last_checked_at，不写 summary。"""
        cur = self._conn.execute(
            "UPDATE watches SET last_checked_at = ? WHERE watch_id = ?",
            (now.isoformat(), watch_id),
        )
        self._conn.commit()
        return cur.rowcount > 0
