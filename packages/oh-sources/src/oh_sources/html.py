"""HtmlAdapter：配置驱动静态列表页抓取（政务/媒体 HTML，Phase 1.5 基建）。

Phase 1.5 全球探测结论：主流政务/央行列表页（stats.gov.cn/csrc/treasury/nyfed）
均为 JS 渲染，静态抓取 0 命中——本适配器保留为"agent 维护稳定政务源"的基建，
依赖离线单测保底；JS 渲染站点由 Phase 6 playwright 壳接管。

params 契约：list_url/params/headers/encoding/item_selector/link_attr(默认 href)/
date_regex+date_formats+tz_offset_hours/date_scope(item|parent)/
detail{content_selector, drop_selectors, max_items, title_selector}/max_items(默认 30)。
无日期条目跳过（PIT 锚点纪律）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import Draft, SourceAdapter
from oh_sources.json_api import parse_ts

_DEFAULT_DATE_RE = r"\d{4}-\d{2}-\d{2}"
_DEFAULT_DATE_FMTS = ["%Y-%m-%d"]


class HtmlAdapter(SourceAdapter):
    """静态列表页 → Draft；可选 detail 抓正文。"""

    def __init__(
        self,
        meta: SourceMeta,
        *,
        list_url: str,
        item_selector: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        encoding: str | None = None,
        link_attr: str = "href",
        date_regex: str = _DEFAULT_DATE_RE,
        date_formats: list[str] | None = None,
        tz_offset_hours: int = 8,
        date_scope: str = "parent",
        max_items: int = 30,
        detail: dict[str, Any] | None = None,
        article_type: ArticleType = ArticleType.WIRE,
    ) -> None:
        super().__init__(meta)
        self._list_url = list_url
        self._item_selector = item_selector
        self._params = params
        self._headers = headers
        self._encoding = encoding
        self._link_attr = link_attr
        self._date_regex = re.compile(date_regex)
        self._date_formats = date_formats or _DEFAULT_DATE_FMTS
        self._tz_offset_hours = tz_offset_hours
        self._date_scope = date_scope
        self._max_items = max_items
        self._detail = detail
        self._article_type = article_type

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        async with httpx.AsyncClient(
            headers={"User-Agent": "OHNews/0.1"}, follow_redirects=True
        ) as client:
            text = await self.get_text(
                client,
                self._list_url,
                params=self._params,
                headers=self._headers,
                encoding=self._encoding,
            )
            drafts = self.parse_listing(text, self._list_url, since, until)
            if self._detail:
                drafts = await self._fetch_details(client, drafts)
        return drafts

    def parse_listing(
        self,
        html: str,
        base_url: str,
        since: datetime,
        until: datetime,
    ) -> list[Draft]:
        """列表页 HTML → Draft（纯方法，离线可测）。"""
        soup = BeautifulSoup(html, "lxml")
        out: list[Draft] = []
        for el in soup.select(self._item_selector)[: self._max_items]:
            title = el.get_text(" ", strip=True)[:200]
            if not title:
                continue
            href = el.get(self._link_attr)
            if not href:
                link = el.select_one(f"[{self._link_attr}]")
                href = link.get(self._link_attr) if link else None
            if not href:
                continue
            url = urljoin(base_url, str(href))
            scope = el.parent if self._date_scope == "parent" and el.parent else el
            m = self._date_regex.search(scope.get_text(" ", strip=True))
            published = (
                parse_ts(m.group(0), self._date_formats, self._tz_offset_hours) if m else None
            )
            if published is None or not (since <= published <= until):
                continue
            out.append(
                Draft(
                    external_id=url,
                    title=title,
                    url=url,
                    published_at=published.astimezone(UTC),
                    body="",
                    lang=self.meta.language,
                    article_type=self._article_type,
                    raw={"source_kind": "html"},
                )
            )
        return out

    async def _fetch_details(
        self,
        client: httpx.AsyncClient,
        drafts: list[Draft],
    ) -> list[Draft]:
        """逐条抓正文（走 get_text 令牌桶限速；detail.max_items 上限）。"""
        cfg = self._detail or {}
        content_sel = str(cfg.get("content_selector", ""))
        drop_sels = list(cfg.get("drop_selectors", []))
        max_detail = int(cfg.get("max_items", 10))
        out: list[Draft] = []
        for draft in drafts[:max_detail]:
            if not draft.url:
                out.append(draft)
                continue
            try:
                page = await self.get_text(
                    client, draft.url, headers=self._headers, encoding=self._encoding
                )
            except httpx.HTTPError:
                out.append(draft)
                continue
            soup = BeautifulSoup(page, "lxml")
            for sel in drop_sels:
                for node in soup.select(sel):
                    node.decompose()
            node = soup.select_one(content_sel) if content_sel else None
            body = node.get_text(" ", strip=True)[:8000] if node else draft.body
            out.append(
                Draft(
                    external_id=draft.external_id,
                    title=draft.title,
                    url=draft.url,
                    published_at=draft.published_at,
                    body=body,
                    lang=draft.lang,
                    article_type=draft.article_type,
                    raw=draft.raw,
                )
            )
        return out
