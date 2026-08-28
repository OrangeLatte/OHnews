"""intel_graph：六角色情报循环编排（超越 TradingAgents 的主动巡逻）。

Scout（异常检测，纯统计）→ Cartographer（实体网络，纯统计）
→ Red Team（ACH 竞争假设，LLM strategic/离线降级）
→ Chief Analyst（ICD 203 Key Judgments，LLM strategic/离线降级）
→ IntelReport 持久化（intel.sqlite，个人情报档案与产品数据分离）。

不走 langgraph：本轮四节点为固定顺序、无中断/回环，
直接顺序编排（langgraph 编排保留给 analysis/research/chat 三图）。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from oh_contracts.intel import IntelReport
from oh_contracts.schemas import EventRecord

from oh_agents.intel.ach import EvidenceBundle, RedTeamAgent
from oh_agents.intel.cartographer import co_occurrence_network, top_hubs
from oh_agents.intel.chief import ChiefAnalystAgent
from oh_agents.intel.scout import ScoutFinding, volume_zscores

__all__ = ["IntelLedger", "run_intel_cycle", "daily_volume_series"]

_DDL = """
CREATE TABLE IF NOT EXISTS intel_reports (
    report_id   TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    scope       TEXT NOT NULL,
    engine      TEXT NOT NULL,
    report_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intel_created ON intel_reports(created_at);
"""


class IntelLedger:
    """情报简报持久化（intel.sqlite）。"""

    def __init__(self, db_path: Path | str | Connection) -> None:
        if isinstance(db_path, Connection):
            self._conn = db_path
        else:
            from oh_storage.connection import connect

            self._conn = connect(db_path)
        self._conn.executescript(_DDL)
        self._conn.commit()

    def save(self, report: IntelReport) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO intel_reports VALUES (?,?,?,?,?)",
            (
                report.report_id,
                report.created_at,
                report.scope,
                report.engine,
                report.model_dump_json(),
            ),
        )
        self._conn.commit()

    def latest(self, n: int = 1) -> list[IntelReport]:
        rows = self._conn.execute(
            "SELECT report_json FROM intel_reports ORDER BY created_at DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [IntelReport.model_validate_json(r[0]) for r in rows]


def daily_volume_series(
    events: list[EventRecord], *, days: int = 21, now: datetime
) -> tuple[list[str], dict[str, list[int]]]:
    """实体 × 逐日事件数序列（Scout 量级突刺检测输入，右端=now 日）。"""
    start = now.date() - timedelta(days=days - 1)
    dates = [start + timedelta(days=i) for i in range(days)]
    series: dict[str, list[int]] = {}
    for ev in events:
        d = ev.as_of.date()
        if d < start or d > now.date():
            continue
        idx = (d - start).days
        for e in ev.entities:
            arr = series.setdefault(e, [0] * days)
            arr[idx] += 1
    return [d.isoformat() for d in dates], series


async def run_intel_cycle(
    *,
    events: list[EventRecord],
    stances_by_event: dict[str, int],
    official_rows: int,
    total_rows: int,
    ndi_points: list,
    ndi_percentile: float | None,
    now: datetime,
    router: Any | None = None,
    scope: str = "全库巡逻",
) -> IntelReport:
    """一轮完整情报循环（四节点顺序编排）。"""
    # 1) Scout：实体量级突刺（末端 3 日 z-score vs 14 日基线）
    _dates, series = daily_volume_series(events, now=now)
    findings: list[ScoutFinding] = []
    for ent in sorted(series):
        zs = volume_zscores(series[ent])
        for i in range(max(0, len(zs) - 3), len(zs)):
            z = zs[i]
            if z is not None and z >= 3.0:
                findings.append(
                    ScoutFinding(
                        kind="volume_spike",
                        target=ent,
                        score=round(z, 2),
                        detail=f"{_dates[i]} 事件量 z={z:.1f}",
                    )
                )
    findings.sort(key=lambda f: -f.score)
    findings = findings[:5]

    # 2) Cartographer：实体共现网络
    network = co_occurrence_network(events, min_weight=2)
    hubs = [n["id"] for n in top_hubs(network, k=5)]

    # 3) Red Team：ACH
    bundle = EvidenceBundle(
        scope=scope,
        scout_anomalies=[f"{f.kind}:{f.target}({f.detail})" for f in findings],
        top_hubs=hubs,
    )
    ok_points = [p for p in ndi_points if p.ndi is not None]
    if ok_points:
        bundle.ndi_latest = ok_points[-1].ndi
    if ndi_points:
        bundle.ndi_absent_ratio = 1 - len(ok_points) / len(ndi_points)
    if total_rows:
        bundle.official_share = official_rows / total_rows
    redteam = RedTeamAgent(router)
    ach = await redteam.run(bundle)

    # 4) Chief：Key Judgments
    chief = ChiefAnalystAgent(router)
    kjs, summary = await chief.run(bundle, ach, ndi_percentile)

    engine = "llm" if router is not None else "offline"
    report = IntelReport(
        report_id=f"intel-{now.strftime('%Y%m%dT%H%M%S')}",
        created_at=now.isoformat(),
        scope=scope,
        engine=engine,  # type: ignore[arg-type]
        scout_findings=[asdict(f) for f in findings],
        network=network,
        ach=ach,
        key_judgments=kjs,
        summary=summary,
    )
    return report
