"""Library：Research Memory（REDESIGN §3 四页 IA：Library 页存储层）。

沉淀研究对象（v3 纲领 WATCH→…→REMEMBER 闭环的 REMEMBER 端）：
- analysis：Agent 产出的 AnalysisArtifact（五层结构 JSON）；
- event：收藏事件快照（event_id/title/as_of/ndi）；
- note：用户手写研究笔记。

与 watch（显式意图+定期快照）互补：library 是一次性沉淀的持久资产，
无刷新语义。item_id 幂等（lib-{uuid}），title 冗余存便于列表渲染。
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
CREATE TABLE IF NOT EXISTS library_items (
    item_id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    title TEXT NOT NULL,
    ref_kind TEXT,
    ref_id TEXT,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

ITEM_TYPES = ("analysis", "event", "note")


@dataclass(frozen=True)
class LibraryItem:
    item_id: str
    item_type: str
    title: str
    ref_kind: str | None
    ref_id: str | None
    payload: dict[str, Any]
    created_at: str


def _row_to_item(row: sqlite3.Row) -> LibraryItem:
    return LibraryItem(
        item_id=row["item_id"],
        item_type=row["item_type"],
        title=row["title"],
        ref_kind=row["ref_kind"],
        ref_id=row["ref_id"],
        payload=json.loads(row["payload"]),
        created_at=row["created_at"],
    )


class LibraryStore:
    """library_items 表 CRUD（sqlite，与 watch/chat/intel 同模式单库单写者）。"""

    def __init__(self, db_path: Path | str | sqlite3.Connection) -> None:
        if isinstance(db_path, sqlite3.Connection):
            self._conn = db_path
        else:
            from oh_storage.connection import connect

            self._conn = connect(Path(db_path))
        self._conn.executescript(_DDL)
        self._conn.commit()

    def add(
        self,
        *,
        item_type: str,
        title: str,
        payload: dict[str, Any],
        ref_kind: str | None = None,
        ref_id: str | None = None,
        now: datetime,
    ) -> LibraryItem:
        if item_type not in ITEM_TYPES:
            raise ValueError(f"unknown library item type: {item_type}")
        t = title.strip()
        if not t:
            raise ValueError("title must be non-empty")
        item_id = f"lib-{uuid.uuid4().hex[:10]}"
        self._conn.execute(
            "INSERT INTO library_items (item_id, item_type, title, ref_kind,"
            " ref_id, payload, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                item_type,
                t,
                ref_kind,
                ref_id,
                json.dumps(payload, ensure_ascii=False),
                now.isoformat(),
            ),
        )
        self._conn.commit()
        return LibraryItem(item_id, item_type, t, ref_kind, ref_id, payload, now.isoformat())

    def remove(self, item_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM library_items WHERE item_id = ?", (item_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def list(self, item_type: str | None = None) -> list[LibraryItem]:
        if item_type is None:
            rows = self._conn.execute(
                "SELECT * FROM library_items ORDER BY created_at DESC"
            ).fetchall()
        else:
            if item_type not in ITEM_TYPES:
                raise ValueError(f"unknown library item type: {item_type}")
            rows = self._conn.execute(
                "SELECT * FROM library_items WHERE item_type = ? ORDER BY created_at DESC",
                (item_type,),
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get(self, item_id: str) -> LibraryItem | None:
        row = self._conn.execute(
            "SELECT * FROM library_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return _row_to_item(row) if row else None
