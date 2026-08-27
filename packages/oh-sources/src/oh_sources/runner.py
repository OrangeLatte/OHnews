"""采集执行器：指数退避重试 ≤3 + item_key 幂等去重 + 健康度回写与自动降级。

依赖方向：仅依赖 oh-contracts + 结构化协议（BronzeSink/FetchLogSink），
不 import oh_storage —— 采集层与存储层经协议解耦（蓝图 §10）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from oh_contracts.schemas import BronzeRecord

from oh_sources.base import Draft, SourceAdapter

MAX_RETRIES = 3
BASE_DELAY_S = 1.0
DEFAULT_MIN_HEALTH = 0.3


class BronzeSink(Protocol):
    """ParquetBronzeWriter 的结构化协议（write 返回实际写入行数）。"""

    def write(self, records: Iterable[BronzeRecord]) -> int: ...

    def iter_records(self, source_id: str | None = None) -> Iterator[BronzeRecord]: ...


class FetchLogSink(Protocol):
    """SourceHealthTracker 的结构化协议。"""

    def record(
        self,
        *,
        source_id: str,
        ok: bool,
        n_items: int = 0,
        n_written: int = 0,
        error: str | None = None,
        duration_ms: float = 0.0,
    ) -> None: ...

    def health_score(self, source_id: str) -> float | None: ...


@dataclass(frozen=True)
class FetchResult:
    """单源一次采集的结果（回填报告/SSE 的最小单元）。"""

    source_id: str
    ok: bool
    n_items: int = 0
    n_written: int = 0
    error: str | None = None
    duration_ms: int = 0


def _log(
    tracker: FetchLogSink | None,
    *,
    source_id: str,
    ok: bool,
    n_items: int,
    n_written: int,
    error: str | None,
    duration_ms: int,
) -> None:
    if tracker is not None:
        tracker.record(
            source_id=source_id,
            ok=ok,
            n_items=n_items,
            n_written=n_written,
            error=error,
            duration_ms=duration_ms,
        )


async def run_collector(
    adapter: SourceAdapter,
    writer: BronzeSink,
    *,
    since: datetime,
    until: datetime,
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY_S,
    tracker: FetchLogSink | None = None,
) -> FetchResult:
    """采集单源：失败指数退避重试；成功后按 item_key 幂等去重写入 Bronze。"""
    t0 = time.monotonic()
    error: str | None = None
    drafts: list[Draft] = []

    for attempt in range(max_retries):
        try:
            drafts = await adapter.fetch(since, until)
            error = None
            break
        except Exception as exc:  # noqa: BLE001 —— 采集失败必须退避重试而非崩溃
            error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2**attempt))

    duration_ms = int((time.monotonic() - t0) * 1000)
    if error is not None:
        _log(
            tracker,
            source_id=adapter.source_id,
            ok=False,
            n_items=0,
            n_written=0,
            error=error,
            duration_ms=duration_ms,
        )
        return FetchResult(adapter.source_id, ok=False, error=error, duration_ms=duration_ms)

    known = {r.item_key for r in writer.iter_records(source_id=adapter.source_id)}
    fetched_at = datetime.now(UTC)
    records: list[BronzeRecord] = []
    for draft in drafts:
        record = adapter.to_bronze(draft, fetched_at)
        if record.item_key not in known:
            records.append(record)

    n_written = writer.write(records) if records else 0
    _log(
        tracker,
        source_id=adapter.source_id,
        ok=True,
        n_items=len(drafts),
        n_written=n_written,
        error=None,
        duration_ms=duration_ms,
    )
    return FetchResult(
        adapter.source_id,
        ok=True,
        n_items=len(drafts),
        n_written=n_written,
        duration_ms=duration_ms,
    )


async def collect_all(
    registry,
    writer: BronzeSink,
    *,
    since: datetime,
    until: datetime,
    tracker: FetchLogSink | None = None,
    min_health: float = DEFAULT_MIN_HEALTH,
    only: set[str] | None = None,
) -> list[FetchResult]:
    """顺序采集全部注册源（确定性顺序；健康度低于阈值自动降级跳过）。

    Args:
        registry: CollectorRegistry（鸭子类型，避免循环依赖）。
        only: source_id 白名单；显式指定时跳过健康度降级检查（人工强制）。
    """
    results: list[FetchResult] = []
    for adapter in registry.all():
        if only is not None and adapter.source_id not in only:
            continue
        if tracker is not None and only is None:
            score = tracker.health_score(adapter.source_id)
            if score is not None and score < min_health:
                results.append(
                    FetchResult(
                        adapter.source_id,
                        ok=False,
                        error=f"degraded: health={score:.2f} < {min_health:.2f}",
                    )
                )
                continue
        results.append(
            await run_collector(
                adapter,
                writer,
                since=since,
                until=until,
                tracker=tracker,
            )
        )
    return results
