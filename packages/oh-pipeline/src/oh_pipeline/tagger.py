"""规则层 Tagger（裁决 A：tagger 产出 stance_table，NDI 唯一数据源）。

分层路由的 v0 实现：仅规则层（ExtractionEngine.RULE，目标占比 85%）。
小模型/LLM 层在 Phase 3 接入 oh-llm 后挂入同一接口。

弃权语义：文章对某实体无框架信号（命中置信 < MIN_ROW_CONFIDENCE）时不产行——
"没有意见"不允许伪装成中性意见（ai-hedge-fund 弃权语义的行级移植）。
"""

from __future__ import annotations

from datetime import datetime

from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    StanceLabel,
)
from oh_contracts.schemas import StanceRow

from oh_pipeline.entities import EntityRegistry
from oh_pipeline.rules import (
    _CONF_MAP_K,
    FRAME_KEYWORDS,
    MIN_ROW_CONFIDENCE,
    STANCE_NEGATIVE,
    STANCE_POSITIVE,
    STANCE_WINDOW_CHARS,
)

_FRAME_ORDER: tuple[FrameLabel, ...] = tuple(FrameLabel)


def _count_hits(text_lower: str, words: tuple[str, ...]) -> int:
    """子串命中计数：同一起始位置只计一次（防 loss/losses 双计）。"""
    positions: set[int] = set()
    for w in words:
        if not w:
            continue
        start = 0
        while (i := text_lower.find(w, start)) != -1:
            positions.add(i)
            start = i + len(w)
    return len(positions)


def _confidence(top_count: int) -> float:
    """保守置信映射 n/(n+K)：1→0.33、3→0.60、5→0.71，规则层封顶 <0.75。"""
    return top_count / (top_count + _CONF_MAP_K)


class RuleTagger:
    """文章文本 × 实体 → StanceRow 列表（每命中实体一行）。"""

    def __init__(self, registry: EntityRegistry) -> None:
        self._registry = registry

    def tag(
        self,
        *,
        event_id: str,
        source_id: str,
        text: str,
        item_key: str,
        ts: datetime,
        entities: list[str] | None = None,
    ) -> list[StanceRow]:
        """对文本做实体匹配与框架/立场标注。

        entities: 限定产出行的实体集合（事件关联时传入该事件的实体清单）；
        None 表示对全部命中实体产行。
        """
        if not text or not text.strip():
            return []
        low = text.lower()
        matched = self._registry.match(text)
        if entities is not None:
            allowed = set(entities)
            matched = [e for e in matched if e in allowed]
        rows: list[StanceRow] = []
        for entity_id in matched:
            row = self._tag_entity(
                event_id=event_id,
                source_id=source_id,
                entity_id=entity_id,
                text=text,
                low=low,
                item_key=item_key,
                ts=ts,
            )
            if row is not None:
                rows.append(row)
        return rows

    def _tag_entity(
        self,
        *,
        event_id: str,
        source_id: str,
        entity_id: str,
        text: str,
        low: str,
        item_key: str,
        ts: datetime,
    ) -> StanceRow | None:
        counts = {f: _count_hits(low, FRAME_KEYWORDS[f]) for f in _FRAME_ORDER}
        total = sum(counts.values())
        if total == 0:
            return None
        top_frame = max(_FRAME_ORDER, key=lambda f: (counts[f], -_FRAME_ORDER.index(f)))
        frame_conf = _confidence(counts[top_frame])
        if frame_conf < MIN_ROW_CONFIDENCE:
            return None

        stance = self._stance_for(entity_id, low)
        return StanceRow(
            event_id=event_id,
            source_id=source_id,
            entity_id=entity_id,
            frame=top_frame,
            stance=stance,
            confidence=round(frame_conf, 4),
            engine=ExtractionEngine.RULE,
            item_key=item_key,
            ts=ts,
        )

    def _stance_for(self, entity_id: str, low: str) -> StanceLabel:
        """实体邻域内的正负线索计数 → 立场；无差异为 NEUTRAL。"""
        spec = self._registry.get(entity_id)
        window_text = self._entity_windows(low, spec.aliases)
        pos = _count_hits(window_text, STANCE_POSITIVE)
        neg = _count_hits(window_text, STANCE_NEGATIVE)
        if neg > pos:
            return StanceLabel.CRITICAL
        if pos > neg:
            return StanceLabel.SUPPORTIVE
        return StanceLabel.NEUTRAL

    @staticmethod
    def _entity_windows(low: str, aliases: tuple[str, ...]) -> str:
        pieces: list[str] = []
        for alias in aliases:
            a = alias.lower()
            start = 0
            while (i := low.find(a, start)) != -1:
                begin = max(0, i - STANCE_WINDOW_CHARS)
                pieces.append(low[begin : i + len(a) + STANCE_WINDOW_CHARS])
                start = i + len(a)
        return "\n".join(pieces)
