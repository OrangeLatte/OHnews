"""M3/M4 迁移脚本测试：tracking/watch/alerts 三库 → research.sqlite Monitor。

脚本位于 scripts/dev/（不在 testpaths 内），通过 importlib 加载后对 tmp 沙箱库执行，
覆盖：dry-run 零写入 / 全量映射值正确 / 孤儿跳过 / 幂等重跑全 skipped / exists 三方法。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from oh_storage.research_store import ResearchStore

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "dev" / "migrate_tracking_to_monitors.py"
)


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("migrate_tracking_to_monitors", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass 注解解析要求模块已注册
    spec.loader.exec_module(mod)
    return mod


_TRACKING_DDL = """
CREATE TABLE tracking_units (
    unit_id TEXT PRIMARY KEY, kind TEXT NOT NULL, query TEXT NOT NULL,
    label TEXT DEFAULT '', mode TEXT DEFAULT 'track', threshold REAL,
    created_at TEXT NOT NULL, last_checked_at TEXT);
CREATE TABLE tracking_hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT, unit_id TEXT NOT NULL, kind TEXT NOT NULL,
    summary TEXT NOT NULL, triggered_at TEXT NOT NULL);
"""

_WATCH_DDL = """
CREATE TABLE watches (
    watch_id TEXT PRIMARY KEY, type TEXT NOT NULL, query TEXT NOT NULL,
    created_at TEXT NOT NULL, last_checked_at TEXT, last_summary TEXT);
"""

_ALERTS_DDL = """
CREATE TABLE alert_rules (
    rule_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, percentile REAL NOT NULL,
    window_days INTEGER NOT NULL DEFAULT 90, created_at TEXT NOT NULL);
CREATE TABLE alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    event_id TEXT NOT NULL, event_title TEXT, ndi REAL NOT NULL, baseline REAL NOT NULL,
    triggered_at TEXT NOT NULL, triggered_date TEXT NOT NULL,
    UNIQUE(rule_id, entity_id, triggered_date));
"""


@pytest.fixture()
def sandbox(tmp_path: Path) -> dict[str, Path]:
    """tmp 沙箱：三旧库带样例数据（含孤儿），research 空库。"""
    tracking = sqlite3.connect(tmp_path / "tracking.sqlite")
    tracking.executescript(_TRACKING_DDL)
    tracking.executemany(
        "INSERT INTO tracking_units VALUES (?,?,?,?,?,?,?,?)",
        [
            ("u-topic", "topic", "tariff", "关税跟踪", "track", 3.0, "2026-09-01T00:00:00", None),
            ("u-weird", "weird", "foo", "", "paused", None, "2026-09-01T01:00:00", None),
        ],
    )
    tracking.executemany(
        "INSERT INTO tracking_hits (unit_id, kind, summary, triggered_at) VALUES (?,?,?,?)",
        [
            ("u-topic", "topic", "关税命中 12 篇", "2026-09-02T00:00:00"),
            ("u-ghost", "topic", "孤儿命中", "2026-09-02T01:00:00"),
        ],
    )
    tracking.commit()
    tracking.close()

    watch = sqlite3.connect(tmp_path / "watch.sqlite")
    watch.executescript(_WATCH_DDL)
    watch.executemany(
        "INSERT INTO watches VALUES (?,?,?,?,?,?)",
        [
            (
                "watch-topic",
                "topic",
                "central bank,关税",
                "2026-09-01T02:00:00",
                "2026-09-02T02:00:00",
                json.dumps({"kind": "topic", "terms": ["central bank"], "n_articles": 22}),
            ),
            ("watch-q", "question", "美联储叙事有何变化？", "2026-09-01T03:00:00", None, None),
        ],
    )
    watch.commit()
    watch.close()

    alerts = sqlite3.connect(tmp_path / "alerts.sqlite")
    alerts.executescript(_ALERTS_DDL)
    alerts.execute("INSERT INTO alert_rules VALUES ('rule-war','war',0.9,90,'2026-09-01T04:00:00')")
    alerts.executemany(
        "INSERT INTO alert_events (rule_id, entity_id, event_id, event_title, ndi, baseline,"
        " triggered_at, triggered_date) VALUES (?,?,?,?,?,?,?,?)",
        [
            (
                "rule-war",
                "war",
                "evt-1",
                "升级报道",
                0.3431,
                0.3,
                "2026-09-02T05:00:00",
                "2026-09-02",
            ),
            (
                "rule-ghost",
                "war",
                "evt-2",
                None,
                0.5,
                0.3,
                "2026-09-02T06:00:00",
                "2026-09-02",
            ),
        ],
    )
    alerts.commit()
    alerts.close()

    return {"root": tmp_path}


def test_exists_methods(sandbox: dict[str, Path]) -> None:
    store = ResearchStore.open(sandbox["root"] / "research.sqlite")
    assert not store.monitor_exists("mon-x")
    assert not store.monitor_run_exists("run-x")
    assert not store.monitor_update_exists("upd-x")
    store.close()


def test_dry_run_writes_nothing(sandbox: dict[str, Path]) -> None:
    mod = _load_script()
    report = mod.run_migration(sandbox["root"], dry_run=True, backup=False)
    assert report.monitors_created == 5  # 2 tracking + 2 watches + 1 alert rule
    assert report.runs_created == 3  # 1 hit + 1 watch legacy + 1 alert event
    assert report.updates_created == 3
    assert len(report.orphans) == 2
    conn = sqlite3.connect(sandbox["root"] / "research.sqlite")
    for table in ("monitors", "monitor_runs", "monitor_updates"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    conn.close()


def test_migration_and_idempotent_rerun(sandbox: dict[str, Path]) -> None:
    mod = _load_script()
    report = mod.run_migration(sandbox["root"], dry_run=False, backup=False)
    assert report.monitors_created == 5
    assert report.runs_created == 3
    assert report.updates_created == 3
    assert len(report.orphans) == 2
    assert any("unit 'u-ghost'" in line for line in report.orphans)
    assert any("rule 'rule-ghost'" in line for line in report.orphans)

    store = ResearchStore.open(sandbox["root"] / "research.sqlite")
    monitors = {m.monitor_id: m for m in store.list_monitors()}
    assert len(monitors) == 5

    # M3 tracking unit：kind 合法直用、threshold 进 trigger_conditions、mode=paused 生效
    m3 = monitors["mon-m3-u-topic"]
    assert (m3.target_type, m3.target_ref, m3.question) == ("topic", "tariff", "关税跟踪")
    assert m3.trigger_conditions == ["threshold>=3"]
    assert m3.status == "active"
    # 未知 kind 回落 topic；paused 保留
    m3w = monitors["mon-m3-u-weird"]
    assert (m3w.target_type, m3w.status) == ("topic", "paused")
    assert m3w.question == "foo"

    # M4 watch：needs_review 草稿 + last_summary JSON 进 delta
    m4w = monitors["mon-m4w-watch-topic"]
    assert (m4w.target_type, m4w.status) == ("topic", "needs_review")
    updates = {u.update_id: u for u in store.pending_updates()}
    assert len(updates) == 3  # 全部迁移 update 均待复核（HITL 纪律）
    wu = updates["mupd-m4w-watch-topic"]
    assert wu.delta["n_articles"] == 22
    assert wu.monitor_id == "mon-m4w-watch-topic"

    # M4 alert rule：NDI 描述性措辞 + percentile/window 进 trigger_conditions
    m4a = monitors["mon-m4a-rule-war"]
    assert (m4a.target_type, m4a.target_ref) == ("entity", "war")
    assert m4a.trigger_conditions == ["ndi_percentile>0.9", "window_days=90"]
    assert m4a.window == "90d"
    assert m4a.status == "needs_review"
    au = next(u for u in updates.values() if u.monitor_id == "mon-m4a-rule-war")
    assert au.suggested_case_action == "none"  # 迁移不自动升级 case 候选
    assert au.delta["event_id"] == "evt-1"
    assert "0.3431" in au.summary

    # hit → run/update 挂到正确 monitor（hit/event run_id 用自增 int，watch 用 watch_id）
    runs = store._conn.execute("SELECT run_id, monitor_id FROM monitor_runs").fetchall()
    by_id = {dict(r)["run_id"]: dict(r)["monitor_id"] for r in runs}
    assert by_id["mrun-m3-1"] == "mon-m3-u-topic"
    assert by_id["mrun-m4w-watch-topic"] == "mon-m4w-watch-topic"
    assert by_id["mrun-m4a-1"] == "mon-m4a-rule-war"
    store.close()

    # 幂等重跑：全部 skipped，无新增
    report2 = mod.run_migration(sandbox["root"], dry_run=False, backup=False)
    assert report2.monitors_created == 0 and report2.monitors_skipped == 5
    assert report2.runs_created == 0 and report2.runs_skipped == 3
    assert report2.updates_created == 0 and report2.updates_skipped == 3
