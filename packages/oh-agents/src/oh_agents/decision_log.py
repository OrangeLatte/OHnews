"""决策日志（业务专家提案：护城河候选 = 个人资产 + 校准数据）。

记录"据此判断 X"→ 事后回填结果 Y——累积个人决策资产，
同时产出"信号→判断→结果"标注数据（未来唯一可私有化的校准数据）。
独立 sqlite 表（不进 Silver/Gold 协议：个人数据与产品数据分离）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

_DDL = """
CREATE TABLE IF NOT EXISTS decision_log (
    decision_id TEXT PRIMARY KEY,
    entity_id   TEXT NOT NULL,
    event_id    TEXT,
    ndi_at_decision REAL,
    decision    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    outcome     TEXT,
    outcome_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_decision_entity ON decision_log(entity_id);
"""


@dataclass(frozen=True)
class Decision:
    """一条决策记录（outcome 未回填时为 None）。"""

    decision_id: str
    entity_id: str
    event_id: str | None
    ndi_at_decision: float | None
    decision: str
    created_at: datetime
    outcome: str | None = None
    outcome_at: datetime | None = None


class DecisionLog:
    """决策日志 CRUD（WAL 连接由调用方传入或自动创建）。"""

    def __init__(self, db_path: Path | str | Connection) -> None:
        if isinstance(db_path, Connection):
            self._conn = db_path
        else:
            from oh_storage.connection import connect

            self._conn = connect(db_path)
        self._conn.executescript(_DDL)
        self._conn.commit()

    def log(
        self,
        *,
        decision_id: str,
        entity_id: str,
        decision: str,
        event_id: str | None = None,
        ndi_at_decision: float | None = None,
        created_at: datetime | None = None,
    ) -> Decision:
        """记录一次判断（decision_id 由调用方生成，如 uuid4）。"""
        ts = (created_at or datetime.now(UTC)).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO decision_log "
            "(decision_id, entity_id, event_id, ndi_at_decision, decision, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (decision_id, entity_id, event_id, ndi_at_decision, decision, ts),
        )
        self._conn.commit()
        return Decision(
            decision_id=decision_id,
            entity_id=entity_id,
            event_id=event_id,
            ndi_at_decision=ndi_at_decision,
            decision=decision,
            created_at=datetime.fromisoformat(ts),
        )

    def resolve(self, decision_id: str, outcome: str, *, at: datetime | None = None) -> None:
        """事后回填结果（校准数据的关键一步）。"""
        self._conn.execute(
            "UPDATE decision_log SET outcome = ?, outcome_at = ? WHERE decision_id = ?",
            (outcome, (at or datetime.now(UTC)).isoformat(), decision_id),
        )
        self._conn.commit()

    def list_for(self, entity_id: str) -> list[Decision]:
        rows = self._conn.execute(
            "SELECT * FROM decision_log WHERE entity_id = ? ORDER BY created_at",
            (entity_id,),
        ).fetchall()
        return [
            Decision(
                decision_id=r["decision_id"],
                entity_id=r["entity_id"],
                event_id=r["event_id"],
                ndi_at_decision=r["ndi_at_decision"],
                decision=r["decision"],
                created_at=datetime.fromisoformat(r["created_at"]),
                outcome=r["outcome"],
                outcome_at=(datetime.fromisoformat(r["outcome_at"]) if r["outcome_at"] else None),
            )
            for r in rows
        ]


__all__ = ["Decision", "DecisionLog"]
