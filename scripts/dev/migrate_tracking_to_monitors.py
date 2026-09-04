"""M3/M4 迁移脚本：tracking / watch / alerts 三旧库 → research.sqlite Monitor 体系。

映射（Phase 0 迁移表 M3/M4）：
- M3: tracking_units → Monitor（确定性跟踪，kind 映射到 MonitorTarget，缺省 topic）；
      tracking_hits → MonitorRun(status=succeeded) + MonitorUpdate(reviewed=False)
- M4: watches → Monitor(status=needs_review 草稿)；last_summary JSON → 一条 legacy
      MonitorRun + MonitorUpdate（数据不丢失）；alert_rules → Monitor（实体 NDI 描述性
      监测草稿，trigger_conditions 写 percentile/window）；alert_events → MonitorRun +
      MonitorUpdate（suggested_case_action 固定 none——迁移不自动升级 case 候选，留给 HITL）

幂等：新 id 由源主键确定性生成（mon-m3-{unit_id} / mon-m4w-{watch_id} / mon-m4a-{rule_id}、
mrun-m3-{hit_id} …），已存在则整条跳过；孤儿记录（hit 无 unit / event 无 rule）跳过并计数。

用法：uv run python scripts/dev/migrate_tracking_to_monitors.py [--dry-run] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from oh_contracts.monitoring import MONITOR_TARGETS, Monitor, MonitorRun, MonitorUpdate
from oh_storage.connection import connect
from oh_storage.research_store import ResearchStore

ROOT = Path(__file__).resolve().parents[2]

# 确定性 id 前缀（幂等重跑依赖 exists 检查，前缀不参与碰撞）
PFX_M3_MONITOR = "mon-m3-"
PFX_M3_RUN = "mrun-m3-"
PFX_M3_UPDATE = "mupd-m3-"
PFX_M4W_MONITOR = "mon-m4w-"
PFX_M4W_RUN = "mrun-m4w-"
PFX_M4W_UPDATE = "mupd-m4w-"
PFX_M4A_MONITOR = "mon-m4a-"
PFX_M4A_RUN = "mrun-m4a-"
PFX_M4A_UPDATE = "mupd-m4a-"


@dataclass
class MigrationReport:
    """迁移计数：dry_run 下 created 表示"将创建"。"""

    monitors_created: int = 0
    monitors_skipped: int = 0
    runs_created: int = 0
    runs_skipped: int = 0
    updates_created: int = 0
    updates_skipped: int = 0
    orphans: list[str] = field(default_factory=list)


def _target_type(kind: str, fallback: str = "topic") -> str:
    """旧 kind → MonitorTarget；未知值回落到 fallback（不编造新语义）。"""
    return kind if kind in MONITOR_TARGETS else fallback


def _monitor_ready(store: ResearchStore, known: set[str], monitor_id: str) -> bool:
    """monitor 已落库或本次已计划（dry-run 下 monitor 不写库，靠 known 集合跟踪）。"""
    return monitor_id in known or store.monitor_exists(monitor_id)


def migrate_tracking_units(
    tracking: sqlite3.Connection,
    store: ResearchStore,
    report: MigrationReport,
    known: set[str],
    *,
    dry_run: bool,
) -> None:
    """M3：tracking_units → Monitor。"""
    rows = tracking.execute("SELECT * FROM tracking_units").fetchall()
    for row in rows:
        unit = dict(row)
        monitor_id = PFX_M3_MONITOR + str(unit["unit_id"])
        if _monitor_ready(store, known, monitor_id):
            report.monitors_skipped += 1
            continue
        conditions: list[str] = []
        if unit["threshold"] is not None:
            conditions.append(f"threshold>={unit['threshold']:g}")
        monitor = Monitor(
            monitor_id=monitor_id,
            target_type=_target_type(str(unit["kind"])),
            target_ref=str(unit["query"]),
            question=str(unit["label"] or unit["query"]),
            trigger_conditions=conditions,
            status="paused" if unit["mode"] == "paused" else "active",
            last_confirmed_snapshot_at=unit["last_checked_at"],
            created_at=str(unit["created_at"]),
        )
        if not dry_run:
            store.create_monitor(monitor)
        known.add(monitor_id)
        report.monitors_created += 1


def _add_run_update(
    store: ResearchStore,
    report: MigrationReport,
    *,
    run: MonitorRun,
    update: MonitorUpdate,
    dry_run: bool,
) -> None:
    if store.monitor_run_exists(run.run_id):
        report.runs_skipped += 1
    else:
        if not dry_run:
            store.add_monitor_run(run)
        report.runs_created += 1
    if store.monitor_update_exists(update.update_id):
        report.updates_skipped += 1
    else:
        if not dry_run:
            store.add_monitor_update(update)
        report.updates_created += 1


def migrate_tracking_hits(
    tracking: sqlite3.Connection,
    store: ResearchStore,
    report: MigrationReport,
    known: set[str],
    *,
    dry_run: bool,
) -> None:
    """M3：tracking_hits → MonitorRun + MonitorUpdate（按 unit 归属）。"""
    rows = tracking.execute("SELECT * FROM tracking_hits ORDER BY id").fetchall()
    for row in rows:
        hit = dict(row)
        monitor_id = PFX_M3_MONITOR + str(hit["unit_id"])
        if not _monitor_ready(store, known, monitor_id):
            report.orphans.append(
                f"tracking_hit id={hit['id']}: unit '{hit['unit_id']}' 不存在，跳过"
            )
            continue
        run_id = PFX_M3_RUN + str(hit["id"])
        if store.monitor_run_exists(run_id):
            report.runs_skipped += 1
            if store.monitor_update_exists(PFX_M3_UPDATE + str(hit["id"])):
                report.updates_skipped += 1
            continue
        at = str(hit["triggered_at"])
        run = MonitorRun(
            run_id=run_id,
            monitor_id=monitor_id,
            status="succeeded",
            started_at=at,
            finished_at=at,
        )
        update = MonitorUpdate(
            update_id=PFX_M3_UPDATE + str(hit["id"]),
            run_id=run.run_id,
            monitor_id=monitor_id,
            summary=str(hit["summary"]),
            delta={"hit_kind": str(hit["kind"]), "legacy_unit_kind": str(hit["kind"])},
            created_at=at,
        )
        _add_run_update(store, report, run=run, update=update, dry_run=dry_run)


def migrate_watches(
    watch: sqlite3.Connection,
    store: ResearchStore,
    report: MigrationReport,
    known: set[str],
    *,
    dry_run: bool,
) -> None:
    """M4：watches → Monitor 草稿（needs_review）；last_summary → legacy run+update。"""
    rows = watch.execute("SELECT * FROM watches").fetchall()
    for row in rows:
        w = dict(row)
        monitor_id = PFX_M4W_MONITOR + str(w["watch_id"])
        if _monitor_ready(store, known, monitor_id):
            report.monitors_skipped += 1
            # 重跑时 legacy run/update 同样计入 skip（保持计数完备）
            if store.monitor_run_exists(PFX_M4W_RUN + str(w["watch_id"])):
                report.runs_skipped += 1
                has_summary = bool((w["last_summary"] or "").strip())
                if has_summary and store.monitor_update_exists(PFX_M4W_UPDATE + str(w["watch_id"])):
                    report.updates_skipped += 1
            continue
        monitor = Monitor(
            monitor_id=monitor_id,
            target_type=_target_type(str(w["type"])),
            target_ref=str(w["query"]),
            question=str(w["query"]),
            status="needs_review",
            last_confirmed_snapshot_at=w["last_checked_at"],
            created_at=str(w["created_at"]),
        )
        if not dry_run:
            store.create_monitor(monitor)
        known.add(monitor_id)
        report.monitors_created += 1

        summary_raw = (w["last_summary"] or "").strip()
        if not summary_raw:
            continue
        at = str(w["last_checked_at"] or w["created_at"])
        run_id = PFX_M4W_RUN + str(w["watch_id"])
        if store.monitor_run_exists(run_id):
            report.runs_skipped += 1
            if store.monitor_update_exists(PFX_M4W_UPDATE + str(w["watch_id"])):
                report.updates_skipped += 1
            continue
        try:
            delta = json.loads(summary_raw)
        except json.JSONDecodeError:
            delta = {"raw": summary_raw}
        if not isinstance(delta, dict):
            delta = {"raw": summary_raw}
        run = MonitorRun(
            run_id=run_id,
            monitor_id=monitor_id,
            status="succeeded",
            started_at=at,
            finished_at=at,
        )
        update = MonitorUpdate(
            update_id=PFX_M4W_UPDATE + str(w["watch_id"]),
            run_id=run_id,
            monitor_id=monitor_id,
            summary="Legacy watch snapshot (migrated M4, needs review)",
            delta=delta,
            created_at=at,
        )
        _add_run_update(store, report, run=run, update=update, dry_run=dry_run)


def migrate_alert_rules(
    alerts: sqlite3.Connection,
    store: ResearchStore,
    report: MigrationReport,
    known: set[str],
    *,
    dry_run: bool,
) -> None:
    """M4：alert_rules → 实体 NDI 描述性监测草稿（needs_review，不自动启用）。"""
    rows = alerts.execute("SELECT * FROM alert_rules").fetchall()
    for row in rows:
        rule = dict(row)
        monitor_id = PFX_M4A_MONITOR + str(rule["rule_id"])
        if _monitor_ready(store, known, monitor_id):
            report.monitors_skipped += 1
            continue
        monitor = Monitor(
            monitor_id=monitor_id,
            target_type="entity",
            target_ref=str(rule["entity_id"]),
            question=f"叙事分歧指数 (NDI) 监测：{rule['entity_id']}",
            trigger_conditions=[
                f"ndi_percentile>{rule['percentile']:g}",
                f"window_days={int(rule['window_days'])}",
            ],
            window=f"{int(rule['window_days'])}d",
            status="needs_review",
            created_at=str(rule["created_at"]),
        )
        if not dry_run:
            store.create_monitor(monitor)
        known.add(monitor_id)
        report.monitors_created += 1


def migrate_alert_events(
    alerts: sqlite3.Connection,
    store: ResearchStore,
    report: MigrationReport,
    known: set[str],
    *,
    dry_run: bool,
) -> None:
    """M4：alert_events → MonitorRun + MonitorUpdate；孤儿事件跳过并计数。"""
    known_rules = {
        str(r["rule_id"]) for r in alerts.execute("SELECT rule_id FROM alert_rules").fetchall()
    }
    rows = alerts.execute("SELECT * FROM alert_events ORDER BY id").fetchall()
    for row in rows:
        ev = dict(row)
        if str(ev["rule_id"]) not in known_rules:
            report.orphans.append(f"alert_event id={ev['id']}: rule '{ev['rule_id']}' 不存在，跳过")
            continue
        monitor_id = PFX_M4A_MONITOR + str(ev["rule_id"])
        if not _monitor_ready(store, known, monitor_id):
            report.orphans.append(f"alert_event id={ev['id']}: monitor '{monitor_id}' 未迁移，跳过")
            continue
        if store.monitor_run_exists(PFX_M4A_RUN + str(ev["id"])):
            report.runs_skipped += 1
            if store.monitor_update_exists(PFX_M4A_UPDATE + str(ev["id"])):
                report.updates_skipped += 1
            continue
        at = str(ev["triggered_at"])
        title = ev["event_title"] or ev["entity_id"]
        run = MonitorRun(
            run_id=PFX_M4A_RUN + str(ev["id"]),
            monitor_id=monitor_id,
            status="succeeded",
            started_at=at,
            finished_at=at,
        )
        update = MonitorUpdate(
            update_id=PFX_M4A_UPDATE + str(ev["id"]),
            run_id=run.run_id,
            monitor_id=monitor_id,
            summary=f"NDI {ev['ndi']:.4f} 高于基线 {ev['baseline']:.4f}：{title}",
            delta={
                "ndi": ev["ndi"],
                "baseline": ev["baseline"],
                "event_id": ev["event_id"],
                "event_title": ev["event_title"],
                "triggered_date": ev["triggered_date"],
            },
            suggested_case_action="none",
            created_at=at,
        )
        _add_run_update(store, report, run=run, update=update, dry_run=dry_run)


def print_report(report: MigrationReport, *, dry_run: bool) -> None:
    verb = "would create" if dry_run else "created"
    print(f"monitors {verb}={report.monitors_created} skipped={report.monitors_skipped}")
    print(f"runs {verb}={report.runs_created} skipped={report.runs_skipped}")
    print(f"updates {verb}={report.updates_created} skipped={report.updates_skipped}")
    if report.orphans:
        print(f"orphans={len(report.orphans)}")
        for line in report.orphans:
            print(f"  - {line}")


def run_migration(data_dir: Path, *, dry_run: bool = False, backup: bool = True) -> MigrationReport:
    """对 data_dir 下的 research/tracking/watch/alerts 四库执行 M3/M4 迁移。"""
    research_path = data_dir / "research.sqlite"
    tracking_path = data_dir / "tracking.sqlite"
    watch_path = data_dir / "watch.sqlite"
    alerts_path = data_dir / "alerts.sqlite"

    if backup and not dry_run and research_path.exists():
        stamp = f"{datetime.now(UTC):%Y%m%d%H%M%S}"
        backup_path = research_path.with_name(f"research.sqlite.bak-{stamp}")
        shutil.copy2(research_path, backup_path)
        print(f"backup -> {backup_path.name}")

    store = ResearchStore.open(research_path)
    # 已有 monitor 全集 + 本次计划集（dry-run 下 monitor 不写库，hits/events 归属检查靠它）
    known = {m.monitor_id for m in store.list_monitors()}
    report = MigrationReport()

    tracking = connect(tracking_path) if tracking_path.exists() else None
    if tracking is not None:
        migrate_tracking_units(tracking, store, report, known, dry_run=dry_run)
        migrate_tracking_hits(tracking, store, report, known, dry_run=dry_run)
        tracking.close()

    watch = connect(watch_path) if watch_path.exists() else None
    if watch is not None:
        migrate_watches(watch, store, report, known, dry_run=dry_run)
        watch.close()

    alerts = connect(alerts_path) if alerts_path.exists() else None
    if alerts is not None:
        migrate_alert_rules(alerts, store, report, known, dry_run=dry_run)
        migrate_alert_events(alerts, store, report, known, dry_run=dry_run)
        alerts.close()

    store.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT / "data", help="四库所在目录（默认 <repo>/data）"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("dry-run: no writes")
    report = run_migration(args.data_dir, dry_run=args.dry_run)
    print_report(report, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
