"""Monitor 调度 worker：真实后台 tick 循环 + 幂等触发 + 重启补跑。

第十一轮 P0-D 要求：worker heartbeat / last fire / next fire / missed run /
重启继续 / 幂等键 / 自动化测试。设计：

- ``run_scheduler_tick`` 为纯函数核心：对每个 active monitor 按
  ``last_run.started_at + schedule`` 推算 next fire，到期且无活跃 run
  （幂等键=``active_monitor_run``）才登记 queued run 并交执行器；
  重启后同一逻辑自然补跑逾期任务（missed run → 立即触发）。
- ``SchedulerWorker`` 为守护线程壳：定期 tick，维护内存 heartbeat
  （重启后从零计数——诚实反映"当前进程"的 worker 状态）。
- 调度解析与 :func:`oh_api.object_api.parse_schedule_seconds` 语义一致
  （此处独立实现，避免 agent 层反向依赖 api 层）。
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from oh_contracts.monitoring import Monitor, MonitorRun
from oh_storage.research_store import ResearchStore

_TICK_DEFAULT_SECONDS = 60.0

_SCHEDULE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"": 60.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def _parse_schedule_seconds(schedule: str) -> int | None:
    """``"14d"/"6h"/"30m"/"90s"`` → 秒；空/不可解析/≤0 → None（诚实不过滤）。"""
    m = _SCHEDULE_RE.match(schedule or "")
    if m is None:
        return None
    secs = float(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]
    return int(secs) if secs > 0 else None


def _parse_dt(value: str | None) -> datetime | None:
    """isoformat 容错解析；空/非法 → None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class TickResult:
    """单次 tick 的触发账本（可测试断言用）。"""

    fired: list[dict[str, Any]] = field(default_factory=list)
    skipped_active: list[str] = field(default_factory=list)
    skipped_not_due: list[str] = field(default_factory=list)
    skipped_unscheduled: list[str] = field(default_factory=list)


def run_scheduler_tick(
    store: ResearchStore,
    bronze_iter_factory: Callable[[], Iterable[Any]],
    now: Callable[[], datetime],
    *,
    executor: Callable[[str, str], None] | None = None,
) -> TickResult:
    """扫描 active monitors，对到期者登记 queued run 并触发执行。

    幂等：活跃 run（queued/running）存在 → 跳过。重启继续：锚点取
    最近一次 run 的 ``started_at``（无历史则用 monitor.created_at），
    进程重启不影响到期判定。executor 默认同步调用
    ``oh_agents.monitor_executor.run_monitor``（线程内重取连接由
    store_factory 语义保证——本函数收到的 store 即当前线程连接）。
    """

    def _default_executor(monitor_id: str, run_id: str) -> None:
        from oh_agents.monitor_executor import run_monitor

        run_monitor(
            monitor_id,
            run_id,
            bronze_iter_factory=bronze_iter_factory,
            store_factory=lambda: store,
            now=now,
        )

    run_one = executor or _default_executor
    result = TickResult()
    for monitor in store.list_monitors(status="active"):
        assert isinstance(monitor, Monitor)
        secs = _parse_schedule_seconds(monitor.schedule)
        if secs is None:
            result.skipped_unscheduled.append(monitor.monitor_id)
            continue
        runs = store.monitor_runs_for(monitor.monitor_id, limit=1)
        anchor = (_parse_dt(runs[0].get("started_at")) if runs else None) or _parse_dt(
            monitor.created_at
        )
        if anchor is None:
            result.skipped_not_due.append(monitor.monitor_id)
            continue
        next_fire = anchor + timedelta(seconds=secs)
        current = now()
        if current < next_fire:
            result.skipped_not_due.append(monitor.monitor_id)
            continue
        if store.active_monitor_run(monitor.monitor_id) is not None:
            result.skipped_active.append(monitor.monitor_id)
            continue
        run_id = f"mrun-{current.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:6]}"
        store.add_monitor_run(
            MonitorRun(
                run_id=run_id,
                monitor_id=monitor.monitor_id,
                status="queued",
                started_at=current.isoformat(),
            )
        )
        run_one(monitor.monitor_id, run_id)
        result.fired.append(
            {
                "monitor_id": monitor.monitor_id,
                "run_id": run_id,
                "next_fire_was": next_fire.isoformat(),
                "overdue_seconds": max(0.0, (current - next_fire).total_seconds()),
            }
        )
    return result


class SchedulerWorker:
    """守护线程调度器：定期 tick + 内存 heartbeat（进程级真值）。"""

    def __init__(
        self,
        store_factory: Callable[[], ResearchStore],
        bronze_iter_factory: Callable[[], Iterable[Any]],
        *,
        tick_seconds: float = _TICK_DEFAULT_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store_factory = store_factory
        self._bronze = bronze_iter_factory
        self._tick_seconds = max(0.01, tick_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "alive": False,
            "started_at": "",
            "last_tick": "",
            "ticks": 0,
            "fired_total": 0,
            "last_error": "",
        }
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            self._state.update(
                alive=True,
                started_at=self._clock().isoformat(),
                last_error="",
            )
        self._thread = threading.Thread(target=self._loop, daemon=True, name="monitor-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        with self._lock:
            self._state["alive"] = False

    def heartbeat(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _loop(self) -> None:
        # 首轮立即 tick（重启补跑不等第一个周期）。
        while not self._stop.is_set():
            try:
                store = self._store_factory()
                try:
                    result = run_scheduler_tick(store, self._bronze, self._clock)
                finally:
                    store.close()
                with self._lock:
                    self._state["last_tick"] = self._clock().isoformat()
                    self._state["ticks"] += 1
                    self._state["fired_total"] += len(result.fired)
                    self._state["last_error"] = ""
            except Exception as exc:  # noqa: BLE001 - worker 循环必须自愈
                with self._lock:
                    self._state["last_error"] = str(exc)[:200]
            if self._stop.wait(self._tick_seconds):
                break
