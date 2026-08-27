"""事件生成器（Phase 2 收尾）：Bronze 文章流 → 确定性事件聚合。

v0 规则（诚实边界）：
- 事件 = 实体 × UTC 日窗的聚类，event_id = "ev-{entity}-{YYYYMMDD}" 幂等
- 合格门：窗口内去重文章数 ≥ min_articles 且涉及源数 ≥ min_sources
- title = 窗口内最早文章的标题（确定性，重跑不漂移）
- as_of = 日末（PIT 锚：下游只用 ts ≤ as_of 的 stance 行）

已知局限（如实标注）：
- 无语义聚类：同日同实体的多议题会被并为一事件（v1 接受，规则可复现）
- 实体命中靠别名子串匹配，误报会带入事件
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from oh_contracts.schemas import BronzeRecord, EventRecord

from oh_pipeline.entities import EntityRegistry

EventId = str


@dataclass(frozen=True)
class BuiltEvent:
    """聚合出的候选事件及其覆盖统计。"""

    event: EventRecord
    n_articles: int
    n_sources: int


def _utc_day(ts: datetime) -> date:
    return ts.astimezone(UTC).date()


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


class EventBuilder:
    """实体×日窗聚合器（规则层，无 LLM 参与，可复现）。"""

    def __init__(self, registry: EntityRegistry | None = None) -> None:
        self._registry = registry or EntityRegistry()

    def build(
        self,
        records: Iterable[BronzeRecord],
        *,
        min_articles: int = 3,
        min_sources: int = 2,
    ) -> list[BuiltEvent]:
        """聚合合格事件；输出按 (day, entity_id) 确定性排序。"""
        groups: dict[tuple[date, str], dict[str, tuple[datetime, str]]] = defaultdict(dict)
        for rec in records:
            published = rec.published_at
            if published is None:
                continue  # PIT 锚缺失：不进事件（裁决 C 语义）
            text = " ".join(
                str(rec.normalized.get(k) or "")
                for k in ("title", "body")
            )
            for entity_id in self._registry.match(text):
                bucket = groups[(_utc_day(published), entity_id)]
                bucket.setdefault(rec.item_key, (published, str(rec.normalized.get("title") or "")))

        built: list[BuiltEvent] = []
        for (day, entity_id), articles in groups.items():
            if len(articles) < min_articles:
                continue
            n_sources = len({key.split(":", 1)[0] for key in articles})
            if n_sources < min_sources:
                continue
            ordered = sorted(articles.items(), key=lambda kv: (kv[1][0], kv[0]))
            built.append(
                BuiltEvent(
                    event=EventRecord(
                        event_id=f"ev-{entity_id}-{day:%Y%m%d}",
                        title=ordered[0][1][1] or f"{entity_id} @ {day}",
                        entities=[entity_id],
                        as_of=_day_end(day),
                    ),
                    n_articles=len(articles),
                    n_sources=n_sources,
                )
            )
        built.sort(key=lambda b: (b.event.as_of, b.event.entities[0]))
        return built
