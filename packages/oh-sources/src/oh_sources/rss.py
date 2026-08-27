"""RSS 适配器（feedparser）：中文免费源主通道（L2 官方/通讯社 + L3 财经媒体）。"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from typing import Any

import feedparser
from oh_contracts.enums import ArticleType
from oh_contracts.ids import content_hash, make_item_key, url_hash
from oh_contracts.schemas import BronzeRecord, SourceMeta

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
        *,
        date_fallback: bool = False,
        detail: dict[str, Any] | None = None,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(meta, **base_kwargs)
        self._url = url
        self._article_type = article_type
        # 无日期 feed（如 nikkei_asia RDF）：以抓取时刻作 PIT 锚并打标（可审计）
        self._date_fallback = date_fallback
        # 详情页正文抓取（央行演讲稿等长文本源）：content_selector/drop_selectors/max_items
        self._detail = detail

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        since = self.effective_since(since, until)
        async with self.make_client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            text = await self.get_text(client, self._url)
            feed = feedparser.parse(text)
            # 锚点=until（本次采集窗末端）：fallback_dt 若取实时 now 会晚于 until 被窗口过滤
            fallback_dt = until if self._date_fallback else None
            drafts = self.entries_to_drafts(feed.get("entries", []), since, until, fallback_dt)
            if self._detail:
                drafts = await self._fetch_details(client, drafts)
        return drafts

    async def _fetch_details(self, client: Any, drafts: list[Draft]) -> list[Draft]:
        """逐条抓正文（html.apply_detail 共享逻辑；失败保留摘要不丢数据）。"""
        from httpx import HTTPError

        from oh_sources.html import apply_detail

        cfg = self._detail or {}
        max_detail = int(cfg.get("max_items", 5))
        out: list[Draft] = []
        for draft in drafts[:max_detail]:
            if not draft.url:
                out.append(draft)
                continue
            try:
                page = await self.get_text(client, draft.url)
            except HTTPError:
                out.append(draft)
                continue
            out.append(apply_detail(page, cfg, draft))
        return out

    def to_bronze(self, draft: Draft, fetched_at: datetime) -> BronzeRecord:
        """date_anchor=fetched 的条目 item_key 不含抓取时间戳（幂等：同条目跨次采集去重）。"""
        if draft.raw.get("date_anchor") == "fetched":
            content = f"{draft.title}\n{draft.body}"
            return BronzeRecord(
                source_id=self.source_id,
                item_key=make_item_key(self.source_id, draft.external_id, ""),
                external_id=draft.external_id,
                url_hash=url_hash(draft.url),
                content_hash=content_hash(content),
                fetched_at=fetched_at,
                published_at=draft.published_at,
                raw=draft.raw,
                normalized={
                    "title": draft.title,
                    "url": draft.url,
                    "published_at": draft.published_at.isoformat(),
                    "body": draft.body,
                    "lang": draft.lang,
                    "article_type": str(draft.article_type),
                },
            )
        return super().to_bronze(draft, fetched_at)

    def entries_to_drafts(
        self,
        entries: list[Any],
        since: datetime,
        until: datetime,
        fallback_dt: datetime | None = None,
    ) -> list[Draft]:
        """条目 → Draft（独立成方法便于离线单测；网络解析与 HTTP 分离）。

        fallback_dt 非 None 时：无日期条目以抓取时刻为 PIT 锚（raw.date_anchor=fetched）。
        """
        out: list[Draft] = []
        for entry in entries:
            pub = _entry_dt(entry)
            anchor = "published"
            if pub is None and fallback_dt is not None:
                pub = fallback_dt
                anchor = "fetched"
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
                    raw={"title": title, "link": url, "date_anchor": anchor},
                )
            )
        return out
