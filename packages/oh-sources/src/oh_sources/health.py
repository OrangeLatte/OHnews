"""源健康度四维追踪（蓝图 §6 GOV）：覆盖率/时滞/重复率/失败率 → 自动降级。

依赖方向：oh-sources 仅依赖 oh-contracts（蓝图 §10），故自带连接工厂，
PRAGMA 与 oh_storage.connection 保持一致（WAL / busy_timeout=5000 / NORMAL）。

健康分 health_score = 0.5*success_rate + 0.3*produced_rate + 0.2*(1-duplicate_rate)；
freshness > 48h 时减半。低于 min_health（默认 0.3）→ collect_all 自动跳过。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_fetch_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    n_items INTEGER NOT NULL DEFAULT 0,
    n_written INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    duration_ms REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sfl_source ON source_fetch_logs(source_id, started_at);
"""

FRESHNESS_PENALTY_HOURS = 48.0


class SourceHealthTracker:
    """FetchLogSink 协议实现（runner 结构化调用，无导入耦合）。"""

    def __init__(self, db_path: Path | str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA_SQL)

    def record(
        self,
        *,
        source_id: str,
        ok: bool,
        n_items: int = 0,
        n_written: int = 0,
        error: str | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        """记录一次采集结果（runner 每源每轮一次）。"""
        self._conn.execute(
            "INSERT INTO source_fetch_logs"
            "(source_id, started_at, ok, n_items, n_written, error, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                datetime.now(UTC).isoformat(),
                int(ok),
                n_items,
                n_written,
                error,
                duration_ms,
            ),
        )
        self._conn.commit()

    def stats(self, source_id: str, window_days: int = 7) -> dict[str, float | int | None]:
        """窗口内四维统计：成功率/产出率/重复率/新鲜度（小时）。"""
        since = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
        rows = self._conn.execute(
            "SELECT ok, n_items, n_written, started_at FROM source_fetch_logs "
            "WHERE source_id = ? AND started_at >= ?",
            (source_id, since),
        ).fetchall()
        runs = len(rows)
        ok_rows = [r for r in rows if r["ok"]]
        success_rate = len(ok_rows) / runs if runs else 0.0
        produced_rate = (
            sum(1 for r in ok_rows if r["n_items"] > 0) / len(ok_rows) if ok_rows else 0.0
        )
        total_items = sum(r["n_items"] for r in ok_rows)
        total_written = sum(r["n_written"] for r in ok_rows)
        duplicate_rate = 1.0 - (total_written / total_items) if total_items else 0.0
        last_ok = max((str(r["started_at"]) for r in ok_rows), default=None)
        freshness_hours: float | None = None
        if last_ok is not None:
            delta = datetime.now(UTC) - datetime.fromisoformat(last_ok)
            freshness_hours = delta.total_seconds() / 3600.0
        return {
            "runs": runs,
            "success_rate": round(success_rate, 4),
            "produced_rate": round(produced_rate, 4),
            "duplicate_rate": round(duplicate_rate, 4),
            "freshness_hours": (None if freshness_hours is None else round(freshness_hours, 2)),
        }

    def health_score(self, source_id: str) -> float | None:
        """健康分 ∈ [0,1]；无记录返回 None（新源不降级）。"""
        s = self.stats(source_id)
        if s["runs"] == 0:
            return None
        score = (
            0.5 * float(s["success_rate"])
            + 0.3 * float(s["produced_rate"])
            + 0.2 * (1.0 - float(s["duplicate_rate"]))
        )
        freshness = s["freshness_hours"]
        if freshness is not None and freshness > FRESHNESS_PENALTY_HOURS:
            score *= 0.5
        return round(score, 4)

    def degraded_sources(self, min_score: float = 0.3) -> list[str]:
        """列出低于阈值的源（运维报告用；collect_all 逐源即时判断）。"""
        rows = self._conn.execute("SELECT DISTINCT source_id FROM source_fetch_logs").fetchall()
        return [
            str(r["source_id"])
            for r in rows
            if (score := self.health_score(str(r["source_id"]))) is not None and score < min_score
        ]

    def close(self) -> None:
        self._conn.close()
