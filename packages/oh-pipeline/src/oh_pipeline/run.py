"""全链编排：Bronze 文章 → 规则 Tagger → Silver 立场行 → Gold NDI 点位。

PIT 纪律（蓝图 §5 / qlib 教训）：
- 文章侧：只消费 published_at ≤ as_of 的记录
- 指标侧：NDI 只从 store.stances_asof(as_of) 计算
- 审计：同一 as_of 重复运行幂等；as_of 之后的数据不影响同 as_of 结果
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from oh_contracts.constants import PIT_LOOKBACK_DAYS
from oh_contracts.enums import SourceTier
from oh_contracts.schemas import EventRecord
from oh_storage.protocols import BronzeWriter, GoldReader, SilverStore

from oh_pipeline.divergence import ndi_for_event, temperature_gap
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.tagger import RuleTagger


@dataclass(frozen=True)
class PipelineReport:
    """一次全链运行的结构化结果。"""

    events_processed: int
    rows_written: int
    ndi_ok: int
    ndi_abstain: int
    temperature_gaps: dict[str, float | None]


@dataclass(frozen=True)
class EventNDI:
    """单事件的 NDI 点位 + 温差（写入 Gold 前的中间产物）。"""

    event_id: str
    ndi_status: str
    ndi: float | None
    temperature: float | None


def run_pipeline(
    bronze: BronzeWriter,
    store: SilverStore,
    gold: GoldReader,
    events: Sequence[EventRecord],
    tier_map: dict[str, SourceTier],
    *,
    registry: EntityRegistry | None = None,
    as_of: datetime | None = None,
    lookback_days: int = PIT_LOOKBACK_DAYS,
    min_per_source: int = 2,
    write_gold: bool = True,
) -> PipelineReport:
    """对一批事件跑 Tagger + 分歧统计。

    min_per_source 默认 2（开发态）；测量效度验证与对外数字必须用
    N_MIN_SAMPLES=10（数据科学家样本门），此处参数化以便分层使用。
    """
    reg = registry or EntityRegistry()
    tagger = RuleTagger(reg)
    now = as_of or datetime.now(UTC)
    window_start = now - timedelta(days=lookback_days)
    rows_written = 0

    for event in events:
        window = [
            r
            for r in bronze.iter_records()
            if r.published_at is not None and window_start <= r.published_at <= now
        ]
        for rec in window:
            text = str(rec.normalized.get("body") or rec.normalized.get("title") or "")
            if not text:
                continue
            rows = tagger.tag(
                event_id=event.event_id,
                source_id=rec.source_id,
                text=text,
                item_key=rec.item_key,
                ts=rec.published_at,
                entities=event.entities,
            )
            if rows:
                rows_written += store.append_stances(rows)

    ndi_ok = 0
    ndi_abstain = 0
    gaps: dict[str, float | None] = {}
    for event in events:
        rows = [r for r in store.stances_asof(now) if r.event_id == event.event_id]
        if not rows:
            continue
        point = ndi_for_event(rows, tier_map, now, min_per_source=min_per_source)
        gaps[event.event_id] = temperature_gap(rows, tier_map, min_per_source=min_per_source)
        if write_gold:
            gold.append_ndi(point)
        if point.status == "ok":
            ndi_ok += 1
        else:
            ndi_abstain += 1

    return PipelineReport(
        events_processed=len(events),
        rows_written=rows_written,
        ndi_ok=ndi_ok,
        ndi_abstain=ndi_abstain,
        temperature_gaps=gaps,
    )
