"""Monitor 执行器（P0-B 真实执行闭环）：零 LLM 规则引擎。

语义：按 target_ref（空则 question）关键词在 bronze 全量记录中做
标题+正文子串匹配（大小写不敏感）；增量 = published_at > monitor.
last_confirmed_snapshot_at 的命中文档（无快照 → 全部为增量；
published_at 缺失在已有快照时不计入增量——PIT 纪律：未知时间不得声称"新"）。

产出：MonitorUpdate（相对上次确认快照的变化陈述）+ run 终态 output_json
（阶段/计数）。执行有界：检索超时 → failed（timeout 报根因），不无限等待。
线程模型：本函数设计为在后台线程内执行；store_factory 必须按线程重取
连接（sqlite 连接禁止跨线程共享），bronze_iter_factory 同理按线程构建。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from oh_contracts.monitoring import MonitorUpdate

if TYPE_CHECKING:
    from oh_contracts.monitoring import Monitor
    from oh_contracts.schemas import BronzeRecord
    from oh_storage.research_store import ResearchStore

_EVIDENCE_CAP = 10


def _parse_iso(ts: str | None) -> datetime | None:
    """ISO 时间串解析（容忍 Z 后缀）；非法输入返回 None，不抛异常。"""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _window_start(window: str, now_dt: datetime) -> tuple[datetime | None, bool]:
    """监测窗口起点解析：\"14d\"/\"7d\"/\"12h\"/\"30d\" → now - 时长。

    返回 (起点, 是否生效)。不可解析（含空串）→ (None, False)——调用方
    必须诚实标记 window_applied=False 并全量检索，不得假装过滤过。
    """
    w = (window or "").strip().lower()
    if not w:
        return None, False
    try:
        if w.endswith("d"):
            days = float(w[:-1])
        elif w.endswith("h"):
            days = float(w[:-1]) / 24.0
        else:
            return None, False
    except ValueError:
        return None, False
    if days <= 0:
        return None, False
    return now_dt - timedelta(days=days), True


def _monitor_terms(monitor: Monitor) -> list[str]:
    """检索词：target_ref 按逗号/顿号/分号拆分（任一命中即算）；
    entity 无别名数据则按字面匹配。target_ref 为空 → 退回 question 文本。
    都为空 → 空表（诚实 0 命中）。"""
    ref = monitor.target_ref.strip()
    raw = ref or monitor.question.strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,，、;；]+", raw) if p.strip()]
    return parts or [raw]


def _record_text(rec: BronzeRecord) -> str:
    """标题+正文拼接（normalized dict；缺失字段视为空串）。"""
    normalized = rec.normalized if isinstance(rec.normalized, dict) else {}
    title = str(normalized.get("title") or "")
    body = str(normalized.get("body") or "")
    return f"{title}\n{body}".casefold()


def run_monitor(
    monitor_id: str,
    run_id: str,
    *,
    bronze_iter_factory: Callable[[], Iterable[BronzeRecord]],
    store_factory: Callable[[], ResearchStore],
    now: Callable[[], datetime],
    timeout_s: float = 60.0,
) -> None:
    """执行一次 Monitor 检查并落 MonitorUpdate + run 终态（不抛异常，自愈为 failed）。

    Args:
        monitor_id: 监测器 id。
        run_id: 本次 run id（POST /runs 已落 queued 行）。
        bronze_iter_factory: 每线程惰性构建的 bronze 记录迭代器工厂。
        store_factory: 每线程重取的 ResearchStore 工厂（sqlite 禁止跨线程连接）。
        now: 时钟（可注入，测试 PIT 控制）。
        timeout_s: 检索时限；超限 → TimeoutError → run failed（有界执行）。
    """
    try:
        store = store_factory()
        monitor = store.get_monitor(monitor_id)
        if monitor is None:
            raise ValueError(f"monitor not found: {monitor_id}")
        store.finish_monitor_run(run_id, status="running")

        terms = [t.casefold() for t in _monitor_terms(monitor)]
        snapshot_at = _parse_iso(monitor.last_confirmed_snapshot_at)
        now_dt = now()
        window_start, window_applied = _window_start(monitor.window, now_dt)
        deadline = time.monotonic() + timeout_s

        hits: list[BronzeRecord] = []
        new_hits: list[BronzeRecord] = []
        records = iter(bronze_iter_factory())  # Iterable → Iterator（list 注入也可用）
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(f"monitor retrieval exceeded {timeout_s:g}s")
            try:
                rec = next(records)
            except StopIteration:
                break
            if window_applied:
                # 窗口语义：严格按设置窗口过滤。published_at 缺失 → 无法声称
                # 在窗口内（PIT 纪律，未知时间不参与窗口统计）。
                if rec.published_at is None or rec.published_at < window_start:
                    continue
            text = _record_text(rec)
            if not any(term in text for term in terms):
                continue
            hits.append(rec)
            if snapshot_at is None:
                new_hits.append(rec)
            else:
                published = rec.published_at
                if published is not None and published > snapshot_at:
                    new_hits.append(rec)

        total, n_new = len(hits), len(new_hits)
        win_note = f"窗口 {monitor.window} 内" if window_applied else "窗口不可解析，已全量检索"
        store.add_monitor_update(
            MonitorUpdate(
                update_id=f"mupd-{uuid4().hex[:12]}",
                run_id=run_id,
                monitor_id=monitor_id,
                summary=(
                    f"相对上次确认快照：新增 {n_new} 篇相关文档（{win_note}共命中 {total} 篇）"
                    if snapshot_at is not None
                    else f"首次运行：{win_note}命中 {total} 篇相关文档"
                ),
                delta={
                    "new_articles": n_new,
                    "total_hits": total,
                    "window": monitor.window,
                    "window_applied": window_applied,
                },
                evidence_refs=[r.item_key for r in new_hits[:_EVIDENCE_CAP]],
                suggested_case_action="new_candidate" if n_new > 0 else "none",
                reviewed=False,
                created_at=now_dt.isoformat(),
            )
        )
        output = {
            "stage": "succeeded",
            "hits": total,
            "new_articles": n_new,
            "window": monitor.window,
            "window_applied": window_applied,
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": now_dt.isoformat(),
        }
        store.finish_monitor_run(
            run_id,
            status="succeeded",
            finished_at=now().isoformat(),
            output_json=json.dumps(output, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001 - 任何异常落 failed（诚实根因，不悬空非终态）
        try:
            store_factory().finish_monitor_run(
                run_id,
                status="failed",
                finished_at=now().isoformat(),
                error=str(exc) or type(exc).__name__,
            )
        except Exception:  # noqa: BLE001 - 连接级失败不反噬调用线程
            pass
