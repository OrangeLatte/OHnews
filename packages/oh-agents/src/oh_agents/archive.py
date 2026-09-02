"""Phase D 档案存储：ArchiveStore（archive.sqlite，三档案库 + 报纸）。

裁决精神：旧 library.sqlite 不迁移（历史量小）；确认式存档（API 层由用户
显式动作触发，本 store 不做自动写入）。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DDL = """
CREATE TABLE IF NOT EXISTS archive_items (
  archive_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  ref_kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_archive_kind ON archive_items(kind, created_at);
CREATE TABLE IF NOT EXISTS agent_papers (
  paper_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  item_ids TEXT NOT NULL DEFAULT '[]',
  foreword TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ArchiveStore:
    def __init__(self, path: Path | str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)

    def save_item(
        self,
        *,
        kind: str,
        title: str,
        ref_kind: str,
        ref_id: str,
        payload: dict[str, Any],
        note: str = "",
    ) -> str:
        import hashlib
        import json

        aid = f"ar-{hashlib.sha1(f'{kind}|{ref_id}|{_now()}'.encode()).hexdigest()[:8]}"
        self._conn.execute(
            "INSERT INTO archive_items"
            " (archive_id,kind,title,ref_kind,ref_id,payload,note,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                aid,
                kind,
                title,
                ref_kind,
                ref_id,
                json.dumps(payload, ensure_ascii=False),
                note,
                _now(),
            ),
        )
        self._conn.commit()
        return aid

    def list_items(self, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        import json

        if kind:
            rows = self._conn.execute(
                "SELECT * FROM archive_items WHERE kind=?"
                " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM archive_items ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.get("payload") or "{}")
            out.append(d)
        return out

    def get_item(self, archive_id: str) -> dict[str, Any] | None:
        import json

        r = self._conn.execute(
            "SELECT * FROM archive_items WHERE archive_id=?", (archive_id,)
        ).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["payload"] = json.loads(d.get("payload") or "{}")
        return d

    def remove_item(self, archive_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM archive_items WHERE archive_id=?", (archive_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def save_paper(self, *, title: str, item_ids: list[str], foreword: str) -> str:
        import hashlib
        import json

        pid = f"pp-{hashlib.sha1(f'{title}|{_now()}'.encode()).hexdigest()[:8]}"
        self._conn.execute(
            "INSERT INTO agent_papers"
            " (paper_id,title,item_ids,foreword,created_at) VALUES (?,?,?,?,?)",
            (pid, title, json.dumps(item_ids), foreword, _now()),
        )
        self._conn.commit()
        return pid

    def list_papers(self, limit: int = 50) -> list[dict[str, Any]]:
        import json

        rows = self._conn.execute(
            "SELECT * FROM agent_papers ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["item_ids"] = json.loads(d.get("item_ids") or "[]")
            out.append(d)
        return out

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT kind, COUNT(*) AS n FROM archive_items GROUP BY kind"
        ).fetchall()
        return {r["kind"]: r["n"] for r in rows}
