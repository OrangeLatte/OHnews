"""RSS 适配器（feedparser）：中文免费源主通道（L2 官方/通讯社 + L3 财经媒体）。"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx
from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import USER_AGENT, Draft, SourceAdapter


def _entry_dt(entry: Any) -> datetime | None:
    """feedparser 条目 → tz-aware UTC（published 优先，updated 兜底）。"""
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if st is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(st), tz=UTC)


class RssAdapter(SourceAdapter):
    """通用 RSS 源；条目过滤 [since, until] 窗口，external_id = link（无 link 用 id/title）。"""

    def __init__(
        self,
        meta: SourceMeta,
        url: str,
        article_type: ArticleType = ArticleType.WIRE,
    ) -> None:
        super().__init__(meta)
        self._url = url
        self._article_type = article_type

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            text = await self.get_text(client, self._url)
        feed = feedparser.parse(text)
        return self.entries_to_drafts(feed.get("entries", []), since, until)

    def entries_to_drafts(
        self,
        entries: list[Any],
        since: datetime,
        until: datetime,
    ) -> list[Draft]:
        """条目 → Draft（独立成方法便于离线单测；网络解析与 HTTP 分离）。"""
        out: list[Draft] = []
        for entry in entries:
            pub = _entry_dt(entry)
            if pub is None or not (since <= pub <= until):
                continue
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("link", "")).strip()
            external_id = url or str(entry.get("id", "")).strip() or title
            out.append(
                Draft(
                    external_id=external_id,
                    title=title,
                    url=url,
                    published_at=pub,
                    body=str(entry.get("summary", "")).strip(),
                    lang=self.meta.language,
                    article_type=self._article_type,
                    raw={"title": title, "link": url},
                )
            )
        return out
