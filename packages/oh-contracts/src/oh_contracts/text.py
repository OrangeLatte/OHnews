"""文本清洗纯函数（Bronze 展示层/入库层共用）。"""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str:
    """剥掉内嵌 HTML 标签与常见实体（gov.cn <em>、wscn <p>/<img> 等）。"""
    cleaned = _TAG_RE.sub(" ", text or "")
    return cleaned.replace("&nbsp;", " ").replace("&amp;", "&").strip()


__all__ = ["strip_html"]
