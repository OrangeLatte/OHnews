"""产品事件层（阶段 1-e）：认知闭环主路径埋点，本地 SQLite 落盘。

设计约束（产品纲领 §11）：
- 轻量、可替换：独立 sqlite（product_events.sqlite），不引入第三方分析平台；
  换后端时只换 ProductEventStore 的实现。
- 隐私：只记匿名 session（前端自生成 UUID，无设备指纹）、对象 ID、来源页、
  时间与数据新鲜度；不记 API key、完整私密问题或敏感原文。
- 指标可计算：briefing_viewed/change_opened 时间差 = Time to First Meaningful
  Change；evidence_opened/change_opened 比率 = 证据下钻率；judgment_saved 属
  阶段 2 增量，此处闭集仅主路径 7 事件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from oh_storage.connection import connect

_DDL = """
CREATE TABLE IF NOT EXISTS product_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event      TEXT NOT NULL,
    session    TEXT NOT NULL,
    object_id  TEXT NOT NULL DEFAULT '',
    from_page  TEXT NOT NULL DEFAULT '',
    freshness  TEXT NOT NULL DEFAULT '',
    meta       TEXT NOT NULL DEFAULT '{}',
    ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_events_event ON product_events(event);
CREATE INDEX IF NOT EXISTS idx_product_events_session ON product_events(session);
"""

_TRACKED_EVENTS = (
    "briefing_viewed",
    "change_opened",
    "change_dismissed_as_noise",
    "evidence_opened",
    "source_opened",
    "counter_evidence_requested",
    "insufficient_evidence_seen",
)


@dataclass(frozen=True)
class ProductEvent:
    """一条匿名产品事件。"""

    event: str
    session: str
    object_id: str
    from_page: str
    freshness: str
    meta: dict[str, object]
    ts: datetime


class ProductEventStore:
    """主路径事件账本（append-only，无更新语义）。"""

    def __init__(self, db_path: Path | str | Connection) -> None:
        if isinstance(db_path, Connection):
            self._conn = db_path
        else:
            self._conn = connect(Path(db_path))
        self._conn.executescript(_DDL)
        self._conn.commit()

    def append(
        self,
        event: str,
        session: str,
        *,
        object_id: str = "",
        from_page: str = "",
        freshness: str = "",
        meta: dict[str, object] | None = None,
        ts: datetime | None = None,
    ) -> None:
        """记录一条事件；ts 服务端锚定（UTC），meta 必须可 JSON 序列化。"""
        if event not in _TRACKED_EVENTS:
            raise ValueError(f"untracked event: {event}")
        now = ts or datetime.now(UTC)
        self._conn.execute(
            "INSERT INTO product_events(event, session, object_id, from_page, freshness, meta, ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                event,
                session,
                object_id,
                from_page,
                freshness,
                json.dumps(meta or {}, ensure_ascii=False),
                now.isoformat(),
            ),
        )
        self._conn.commit()

    def counts(self) -> dict[str, int]:
        """按事件名聚合计数（指标计算入口）。"""
        rows = self._conn.execute(
            "SELECT event, COUNT(*) FROM product_events GROUP BY event ORDER BY event"
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    def recent(self, limit: int = 100) -> list[ProductEvent]:
        """最近事件（时间倒序），供调试与指标脚本使用。"""
        rows = self._conn.execute(
            "SELECT event, session, object_id, from_page, freshness, meta, ts"
            " FROM product_events ORDER BY id DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
        return [
            ProductEvent(
                event=str(r[0]),
                session=str(r[1]),
                object_id=str(r[2]),
                from_page=str(r[3]),
                freshness=str(r[4]),
                meta=json.loads(str(r[5])),
                ts=datetime.fromisoformat(str(r[6])),
            )
            for r in rows
        ]
