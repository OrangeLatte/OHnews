"""埋点指标看板后端——轻量本地指标层（产品纲领：可替换，无第三方平台）。

纯函数 compute_metrics 直接消费 ProductEventStore.recent(10_000) 读回的
ProductEvent 列表，在进程内计算主路径漏斗指标并落成 JSON；不建新表、
不引入分析平台——未来换后端只换本模块的实现。

主线挂载（app.py create_app 内一行接线，本模块不修改 app.py）：

    from oh_api.metrics import build_router
    app.include_router(build_router(lambda: _product_events()))

指标口径（阶段 1-e/2/3 闭环验收）：
- evidence_drill_rate = evidence_opened / change_opened（证据下钻率）
- judgment_rate = judgment_saved / change_opened（判断保存率）
- watch_review_rate = watch_update_reviewed / watch_created（订阅复核率）
- time_to_first_change_median_sec = 按 session 分组，组内最早 briefing_viewed →
  最早 change_opened 的秒差（仅正数）取中位数；即 Time to First Meaningful Change。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import median
from typing import Any

from fastapi import APIRouter
from oh_agents.product_events import (
    _TRACKED_EVENTS as TRACKED_EVENTS,
)
from oh_agents.product_events import (
    ProductEvent,
    ProductEventStore,
)


def _ratio(numerator: int, denominator: int) -> float | None:
    """两数之比（round 3 位）；分母为 0 → None（无样本，不虚构 0%）。"""
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _time_to_first_change(events: list[ProductEvent]) -> float | None:
    """最早简报→最早变化的秒差中位数（仅正数，round 1 位）；无样本 → None。"""
    first_brief: dict[str, datetime] = {}
    first_change: dict[str, datetime] = {}
    for ev in events:
        if ev.event == "briefing_viewed":
            prev = first_brief.get(ev.session)
            if prev is None or ev.ts < prev:
                first_brief[ev.session] = ev.ts
        elif ev.event == "change_opened":
            prev = first_change.get(ev.session)
            if prev is None or ev.ts < prev:
                first_change[ev.session] = ev.ts
    gaps = [
        (first_change[s] - first_brief[s]).total_seconds()
        for s in first_brief.keys() & first_change.keys()
        if (first_change[s] - first_brief[s]).total_seconds() > 0
    ]
    return round(median(gaps), 1) if gaps else None


def compute_metrics(events: list[ProductEvent], *, now: datetime) -> dict[str, Any]:
    """从事件列表计算主路径指标快照（纯函数，无 IO）。

    Args:
        events: ProductEventStore.recent(10_000) 读回的事件（时间倒序均可，内部自排）。
        now: 当前时间（UTC；当前仅锚定生成语义，预留未来窗口过滤）。

    Returns:
        counters（12 事件闭集，缺失补 0）、三项比率（round 3，分母 0 → None）、
        time_to_first_change_median_sec（round 1 或 None）、n_sessions（去重，
        排除 'ssr' 服务端会话）、data_window（first_ts/last_ts ISO 或 None）。
    """
    counted = Counter(ev.event for ev in events)
    counters: dict[str, int] = {name: int(counted.get(name, 0)) for name in TRACKED_EVENTS}

    n_sessions = len({ev.session for ev in events if ev.session and ev.session != "ssr"})
    ts_sorted = sorted(ev.ts for ev in events)
    return {
        "counters": counters,
        "evidence_drill_rate": _ratio(counters["evidence_opened"], counters["change_opened"]),
        "judgment_rate": _ratio(counters["judgment_saved"], counters["change_opened"]),
        "watch_review_rate": _ratio(counters["watch_update_reviewed"], counters["watch_created"]),
        "time_to_first_change_median_sec": _time_to_first_change(events),
        "n_sessions": n_sessions,
        "data_window": {
            "first_ts": ts_sorted[0].isoformat() if ts_sorted else None,
            "last_ts": ts_sorted[-1].isoformat() if ts_sorted else None,
        },
    }


def build_router(
    store_fn: Callable[[], ProductEventStore],
    now_fn: Callable[[], datetime] | None = None,
) -> APIRouter:
    """构建 /api/metrics 路由（store/时钟均惰性注入，便于测试隔离）。

    Args:
        store_fn: 返回 ProductEventStore 的工厂（主线 _product_events()）。
        now_fn: 时钟注入；None = datetime.now(UTC)。

    Returns:
        APIRouter——app.include_router(build_router(lambda: _product_events()))。
    """

    def _now() -> datetime:
        return now_fn() if now_fn else datetime.now(UTC)

    router = APIRouter()

    @router.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        """主路径埋点指标快照（只读派生，每次现算不缓存）。"""
        return compute_metrics(store_fn().recent(10_000), now=_now())

    return router
