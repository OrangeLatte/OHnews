"""句级叙事光谱（展示层只读派生，裁决 A：不写回 stance_table/NDI）。

对事件关联文章逐句复用规则层线索词打标：命中句染框架色，
未命中句中性。与文章级 RuleTagger 的差异：光谱不产行、不进
NDI，仅供 /api/events/{id}/spectrum 与事件详情页渲染。

诚实边界：v0 分句不切英文句号（保护小数/缩写），句界=。！？；！?；与换行。
"""

from __future__ import annotations

import re
from typing import Any

from oh_contracts.enums import FrameLabel

from oh_pipeline.rules import FRAME_KEYWORDS, STANCE_NEGATIVE, STANCE_POSITIVE
from oh_pipeline.tagger import _count_hits

_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*|\n+")

_FRAME_ORDER: tuple[FrameLabel, ...] = tuple(FrameLabel)


def split_sentences(text: str) -> list[str]:
    """中英兼容分句：句末标点后切分并保留标点，换行强制切分。"""
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    return parts


def sentence_spectrum(text: str) -> list[dict[str, Any]]:
    """逐句框架光谱：[{i, text, frame, stance, hits, keywords}]。

    frame=None 表示该句无框架线索（中性句）；stance 仅在句内有正/负
    立场线索时给出（句级不做实体邻域限制，v0 简化并如实标注）。
    """
    out: list[dict[str, Any]] = []
    for i, sent in enumerate(split_sentences(text)):
        low = sent.lower()
        hits: dict[str, int] = {}
        keywords: list[str] = []
        for f in _FRAME_ORDER:
            words = FRAME_KEYWORDS[f]
            if not words:
                continue
            n = _count_hits(low, words)
            if n:
                hits[str(f).split(".")[-1]] = n
                for w in words:
                    if w and w in low and w not in keywords:
                        keywords.append(w)
        pos = _count_hits(low, STANCE_POSITIVE)
        neg = _count_hits(low, STANCE_NEGATIVE)
        stance: str | None = None
        if neg > pos:
            stance = "critical"
        elif pos > neg:
            stance = "supportive"
        frame: str | None = None
        if hits:
            frame = max(hits, key=lambda k: (hits[k], -_FRAME_ORDER.index(FrameLabel(k))))
        out.append(
            {
                "i": i,
                "text": sent,
                "frame": frame,
                "stance": stance,
                "hits": hits,
                "keywords": keywords,
            }
        )
    return out
