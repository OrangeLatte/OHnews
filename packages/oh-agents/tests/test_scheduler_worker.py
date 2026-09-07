"""Scheduler worker 测试：tick 纯函数（due/幂等/not due/unscheduled）+ 线程 heartbeat。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest  # noqa: F401  (fixtures 语义保留)
from oh_agents.scheduler_worker import (
    SchedulerWorker,
    run_scheduler_tick,
)
from oh_contracts.monitoring import Monitor, MonitorRun
from oh_storage.research_store import ResearchStore


def _now() -> datetime:
    return datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _mon(store: ResearchStore, monitor_id: str, schedule: str = "1h") -> Monitor:
    mon = Monitor(
        monitor_id=monitor_id,
        target_type="topic",
        target_ref="fed",
        question="q",
        trigger_conditions=[],
        window="7d",
        schedule=schedule,
        status="active",
        created_at=_iso(_now() - timedelta(days=2)),
    )
    store.create_monitor(mon)
    return mon


def _run(
    store: ResearchStore,
    monitor_id: str,
    run_id: str,
    started: datetime,
    status: str = "succeeded",
) -> None:
    store.add_monitor_run(
        MonitorRun(
            run_id=run_id,
            monitor_id=monitor_id,
            status="queued",
            started_at=_iso(started),
        )
    )
    store.finish_monitor_run(
        run_id, status=status, finished_at=_iso(started + timedelta(minutes=1))
    )


def test_tick_fires_due_monitor(tmp_path: Any) -> None:
    store = ResearchStore.open(str(tmp_path / "r.sqlite"))
    try:
        _mon(store, "mon-a", schedule="1h")
        _run(store, "mon-a", "mrun-old", _now() - timedelta(hours=2))
        fired: list[tuple[str, str]] = []

        def executor(monitor_id: str, run_id: str) -> None:
            fired.append((monitor_id, run_id))
            store.finish_monitor_run(run_id, status="succeeded", finished_at=_iso(_now()))

        result = run_scheduler_tick(store, lambda: iter(()), _now, executor=executor)
        assert [(m, r) for m, r in fired] == [("mon-a", result.fired[0]["run_id"])]
        assert result.fired[0]["overdue_seconds"] == 3600.0
        assert result.skipped_not_due == []
        # queued run 已登记
        active = store.active_monitor_run("mon-a")
        assert active is None  # executor 已终结
        assert store.monitor_runs_for("mon-a", limit=1)[0]["run_id"] == result.fired[0]["run_id"]
    finally:
        store.close()


def test_tick_idempotent_active_run(tmp_path: Any) -> None:
    store = ResearchStore.open(str(tmp_path / "r.sqlite"))
    try:
        _mon(store, "mon-a")
        # 活跃 queued run（执行器慢）→ 跳过不重复登记
        store.add_monitor_run(
            MonitorRun(
                run_id="mrun-live",
                monitor_id="mon-a",
                status="running",
                started_at=_iso(_now() - timedelta(hours=3)),
            )
        )
        calls: list[str] = []
        result = run_scheduler_tick(
            store, lambda: iter(()), _now, executor=lambda m, r: calls.append(r)
        )
        assert result.fired == []
        assert result.skipped_active == ["mon-a"]
        assert calls == []
    finally:
        store.close()


def test_tick_not_due_and_unscheduled(tmp_path: Any) -> None:
    store = ResearchStore.open(str(tmp_path / "r.sqlite"))
    try:
        _mon(store, "mon-due", schedule="1h")
        _run(store, "mon-due", "mrun-recent", _now() - timedelta(minutes=5))
        _mon(store, "mon-cron", schedule="")  # 不可解析 → unscheduled
        calls: list[str] = []
        result = run_scheduler_tick(
            store, lambda: iter(()), _now, executor=lambda m, r: calls.append(r)
        )
        assert result.fired == []
        assert result.skipped_not_due == ["mon-due"]
        assert result.skipped_unscheduled == ["mon-cron"]
        assert calls == []
    finally:
        store.close()


def test_tick_missed_run_refires_after_restart(tmp_path: Any) -> None:
    """重启继续：上次 run 远超一个周期 → 立即补跑（overdue 记录）。"""
    store = ResearchStore.open(str(tmp_path / "r.sqlite"))
    try:
        _mon(store, "mon-a", schedule="1h")
        _run(store, "mon-a", "mrun-old", _now() - timedelta(hours=30))
        fired: list[dict[str, Any]] = []

        def executor(monitor_id: str, run_id: str) -> None:
            store.finish_monitor_run(run_id, status="succeeded", finished_at=_iso(_now()))

        result = run_scheduler_tick(store, lambda: iter(()), _now, executor=executor)
        assert len(result.fired) == 1
        assert result.fired[0]["overdue_seconds"] == 29 * 3600.0
        assert fired == []  # executor 是本函数局部闭包，fired 列表未接——仅验证 fired result
    finally:
        store.close()


def test_worker_loop_heartbeat() -> None:
    """线程壳：start→ticks 递增→stop 后 alive=False。"""
    import tempfile
    import time as _time
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    worker = SchedulerWorker(
        lambda: ResearchStore.open(str(tmp / "r.sqlite")),
        lambda: iter(()),
        tick_seconds=0.05,
        clock=_now,
    )
    worker.start()
    deadline = _time.monotonic() + 5.0
    while worker.heartbeat()["ticks"] < 1 and _time.monotonic() < deadline:
        _time.sleep(0.02)
    hb = worker.heartbeat()
    assert hb["alive"] is True
    assert hb["ticks"] >= 1
    assert hb["last_tick"] != ""
    worker.stop()
    assert worker.heartbeat()["alive"] is False
