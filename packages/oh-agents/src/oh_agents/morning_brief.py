"""晨报（Morning Brief，业务专家提案：留存引擎）。

watchlist 实体 × 近窗事件 → NDI 环比变化 TopN + 每事件 3 条证据链回溯
（StanceRow.item_key → Bronze 原文摘录）。纯只读，无 LLM（纯排名+引用）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from oh_contracts.schemas import NDIPoint
from oh_storage.protocols import BronzeWriter, GoldReader, SilverStore

EVIDENCE_COUNT = 3


@dataclass(frozen=True)
class BriefItem:
    """单事件晨报条目：NDI 现值/环比 + 证据链摘录。"""

    entity_ids: tuple[str, ...]
    event_id: str
    title: str
    as_of: datetime
    ndi: float
    prev_ndi: float | None
    delta: float | None
    regime: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class MorningBrief:
    """晨报聚合（items 按 |delta| 或 ndi 降序）。"""

    generated_at: datetime
    items: tuple[BriefItem, ...]

    def render_text(self) -> str:
        """纯文本渲染（IM 推送/邮件预览用）。"""
        if not self.items:
            return "OH!News 晨报：关注列表近窗无 NDI 事件。"
        lines = [f"OH!News 晨报（{self.generated_at:%Y-%m-%d %H:%M} UTC）"]
        for i, it in enumerate(self.items, 1):
            delta = f"Δ{it.delta:+.3f}" if it.delta is not None else "cold_start"
            lines.append(
                f"{i}. [{it.regime}] {it.title}（{','.join(it.entity_ids)}）"
                f" NDI={it.ndi:.3f} {delta}"
            )
            for ev in it.evidence:
                lines.append(f"   - {ev}")
        lines.append("（NDI=叙事分歧指数，EPU 式条件变量，非收益预测器）")
        return "\n".join(lines)


def _evidence_for(
    bronze: BronzeWriter,
    rows_by_key: Mapping[str, tuple[str, str]],
    event_id: str,
) -> tuple[str, ...]:
    """从 Bronze 回溯 item_key → 原文摘录（source_id + 前 120 字）。"""
    out: list[str] = []
    for rec in bronze.iter_records():
        hit = rows_by_key.get(rec.item_key)
        if hit is None:
            continue
        source_id, quote_src = hit
        body = str(rec.normalized.get("body") or "")
        quote = (body or quote_src)[:120].replace("\n", " ")
        out.append(f"[{source_id}] {quote}")
        if len(out) >= EVIDENCE_COUNT:
            break
    return tuple(out)


def build_brief(
    bronze: BronzeWriter,
    store: SilverStore,
    gold: GoldReader,
    watchlist: Sequence[str],
    *,
    now: datetime,
    top_n: int = 5,
) -> MorningBrief:
    """构建晨报：watchlist 实体相关事件，NDI 环比排序 TopN。"""
    watch = set(watchlist)
    rows_by_key: dict[str, tuple[str, str]] = {}
    items: list[BriefItem] = []
    for event in store.events_asof(now):
        hit_entities = tuple(e for e in event.entities if e in watch)
        if not hit_entities:
            continue
        rows = [r for r in store.stances_asof(now) if r.event_id == event.event_id]
        if not rows:
            continue
        for r in sorted(rows, key=lambda x: -x.confidence):
            rows_by_key.setdefault(r.item_key, (r.source_id, event.title))
        series: list[NDIPoint] = [
            p for p in gold.ndi_series(event.event_id) if p.ndi is not None and p.ts <= now
        ]
        if not series:
            continue
        cur = series[-1]
        prev = series[-2] if len(series) > 1 else None
        delta = (cur.ndi - prev.ndi) if prev and prev.ndi is not None else None
        items.append(
            BriefItem(
                entity_ids=hit_entities,
                event_id=event.event_id,
                title=event.title,
                as_of=cur.ts,
                ndi=cur.ndi or 0.0,
                prev_ndi=prev.ndi if prev else None,
                delta=round(delta, 4) if delta is not None else None,
                regime="cold_start" if prev is None else "tracked",
                evidence=_evidence_for(bronze, rows_by_key, event.event_id),
            )
        )
    items.sort(key=lambda it: -(abs(it.delta) if it.delta is not None else it.ndi))
    return MorningBrief(generated_at=now, items=tuple(items[:top_n]))


__all__ = ["BriefItem", "MorningBrief", "build_brief"]
