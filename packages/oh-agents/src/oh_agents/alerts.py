"""预警订阅引擎（Phase 6，蓝图 M5 提案：规则阈值触发、同实体每日 1 次）。

语义（措辞纪律）：NDI 超历史分位数 = "该实体叙事分歧进入历史高位区间"的
描述性提示，不构成任何方向性判断。触发记录带证据链锚点（event_id），
用户经 /events/{id} 下钻复核原文。
独立 sqlite（与决策日志同理：订阅/触发记录不进 Silver/Gold 协议）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection

from oh_contracts.schemas import NDIPoint
from oh_storage.connection import connect
from oh_storage.protocols import GoldReader, SilverStore

_DDL = """
CREATE TABLE IF NOT EXISTS alert_rules (
    rule_id     TEXT PRIMARY KEY,
    entity_id   TEXT NOT NULL,
    percentile  REAL NOT NULL,
    window_days INTEGER NOT NULL DEFAULT 90,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id       TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    event_id      TEXT NOT NULL,
    event_title   TEXT,
    ndi           REAL NOT NULL,
    baseline      REAL NOT NULL,
    triggered_at  TEXT NOT NULL,
    triggered_date TEXT NOT NULL,
    UNIQUE(rule_id, entity_id, triggered_date)
);
CREATE INDEX IF NOT EXISTS idx_alert_events_entity ON alert_events(entity_id);
"""


def _percentile(sorted_values: list[float], p: float) -> float:
    """线性插值分位数（纯 Python，避免为单函数引 numpy）。"""
    if not sorted_values:
        raise ValueError("empty values")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


@dataclass(frozen=True)
class AlertRule:
    rule_id: str
    entity_id: str
    percentile: float
    window_days: int
    created_at: datetime


@dataclass(frozen=True)
class AlertHit:
    """一次触发（含触发电流的 NDI 与历史基线值）。"""

    rule_id: str
    entity_id: str
    event_id: str
    event_title: str
    ndi: float
    baseline: float
    triggered_at: datetime


class AlertStore:
    """订阅规则 + 触发记录（UNIQUE 约束实现同实体每日 1 次去重）。"""

    def __init__(self, db_path: Path | str | Connection) -> None:
        if isinstance(db_path, Connection):
            self._conn = db_path
        else:
            self._conn = connect(Path(db_path))
        self._conn.executescript(_DDL)
        self._conn.commit()

    def add_rule(
        self, rule_id: str, entity_id: str, percentile: float, *, window_days: int = 90
    ) -> AlertRule:
        if not 0.0 < percentile < 1.0:
            raise ValueError("percentile must be in (0, 1)")
        now = datetime.now(UTC)
        self._conn.execute(
            "INSERT OR REPLACE INTO alert_rules VALUES (?,?,?,?,?)",
            (rule_id, entity_id, percentile, window_days, now.isoformat()),
        )
        self._conn.commit()
        return AlertRule(rule_id, entity_id, percentile, window_days, now)

    def list_rules(self) -> list[AlertRule]:
        rows = self._conn.execute(
            "SELECT rule_id, entity_id, percentile, window_days, created_at"
            " FROM alert_rules ORDER BY created_at"
        ).fetchall()
        return [
            AlertRule(
                r["rule_id"],
                r["entity_id"],
                r["percentile"],
                r["window_days"],
                datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def remove_rule(self, rule_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM alert_rules WHERE rule_id = ?", (rule_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_hits(self, limit: int = 50) -> list[AlertHit]:
        rows = self._conn.execute(
            "SELECT rule_id, entity_id, event_id, event_title, ndi, baseline, triggered_at"
            " FROM alert_events ORDER BY triggered_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            AlertHit(
                r["rule_id"],
                r["entity_id"],
                r["event_id"],
                r["event_title"] or "",
                r["ndi"],
                r["baseline"],
                datetime.fromisoformat(r["triggered_at"]),
            )
            for r in rows
        ]

    def record_hit(self, hit: AlertHit) -> bool:
        """写入触发（公有供 check_alerts 调用）；同 (rule_id, entity, 当日) 已存在则忽略。"""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO alert_events"
            " (rule_id, entity_id, event_id, event_title, ndi, baseline, triggered_at,"
            "  triggered_date) VALUES (?,?,?,?,?,?,?,?)",
            (
                hit.rule_id,
                hit.entity_id,
                hit.event_id,
                hit.event_title,
                hit.ndi,
                hit.baseline,
                hit.triggered_at.isoformat(),
                hit.triggered_at.date().isoformat(),
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0


def check_alerts(
    store: SilverStore, gold: GoldReader, alerts: AlertStore, *, now: datetime
) -> list[AlertHit]:
    """运行全部规则：实体相关事件最新 ok NDI ≥ 历史分位基线 → 触发。

    基线 = 该实体**全部相关事件**的 NDI 点集合（含当前事件历史点位，
    排除当前点本身）在 window_days 窗口内的分位数；历史不足 8 点 → 弃权
    （样本门语义，与统计层 N_MIN 一致的保守取向）。
    """
    _MIN_HISTORY = 8
    hits: list[AlertHit] = []
    for rule in alerts.list_rules():
        cutoff = now.replace(microsecond=0).timestamp() - rule.window_days * 86400
        all_points: list[tuple[datetime, float]] = []
        candidates: list[tuple[str, str, NDIPoint]] = []
        for event in store.events_asof(now):
            if rule.entity_id not in event.entities:
                continue
            series = [
                p for p in gold.ndi_series(event.event_id) if p.status == "ok" and p.ndi is not None
            ]
            in_window = [p for p in series if p.ts.timestamp() >= cutoff and p.ts <= now]
            for p in in_window:
                all_points.append((p.ts, p.ndi))  # type: ignore[arg-type]
            if in_window:
                candidates.append((event.event_id, event.title, in_window[-1]))
        if len(all_points) < _MIN_HISTORY:
            continue
        values = sorted(v for _, v in all_points)
        baseline = _percentile(values, rule.percentile)
        for event_id, title, cur in candidates:
            assert cur.ndi is not None
            if cur.ndi < baseline:
                continue
            hit = AlertHit(
                rule_id=rule.rule_id,
                entity_id=rule.entity_id,
                event_id=event_id,
                event_title=title,
                ndi=cur.ndi,
                baseline=round(baseline, 4),
                triggered_at=now,
            )
            if alerts.record_hit(hit):
                hits.append(hit)
    return hits


__all__ = [
    "AlertHit",
    "AlertRule",
    "AlertStore",
    "check_alerts",
]
