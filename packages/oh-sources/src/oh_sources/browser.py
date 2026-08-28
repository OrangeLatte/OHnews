"""BrowserAdapter：playwright 渲染壳（JS 列表页，Phase 6 needs_browser 通道）。

Phase 1.5b 探测结论：BoE speeches 列表为 JS 壳（静态 0 命中），渲染后结构：
列表项 a.release-speech（href=/speech/YYYY/month/slug）+ time.release-date[datetime]
+ h3.list 标题；detail 正文在 div#output。ECB 列表由 AddSearch 索引驱动、
BIS 提供官方 ZIP（123MB 非增量友好）——均不走本壳（死源台账留档）。

params 契约：list_url/item_selector 必填；link_attr(默认 href)/
title_selector(缺省 item 文本)/date_selector+date_attr(默认 datetime，"text" 时
用 date_formats 解析)/date_formats/tz_offset_hours(默认 0)/max_items(默认 30)/
wait_ms(渲染等待毫秒，默认 3000)/scroll_rounds(默认 0)/
detail{content_selector, drop_selectors, max_items, max_chars}（复用 html.apply_detail）。
无日期条目跳过（PIT 锚点纪律）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import USER_AGENT, Draft, SourceAdapter
from oh_sources.html import apply_detail
from oh_sources.json_api import parse_ts

_DEFAULT_DATE_FMTS = ["%Y-%m-%d"]

_MISSING_PLAYWRIGHT = (
    "playwright 未安装或缺浏览器内核：uv add --package oh-sources playwright "
    "&& uv run playwright install chromium"
)


def parse_rendered_listing(
    html: str,
    base_url: str,
    *,
    item_selector: str,
    link_attr: str = "href",
    title_selector: str | None = None,
    date_selector: str | None = None,
    date_attr: str = "datetime",
    date_formats: list[str] | None = None,
    tz_offset_hours: int = 0,
    max_items: int = 30,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[tuple[str, str, datetime | None]]:
    """渲染后列表页 HTML → [(url, title, published|None)]（纯函数，离线可测）。

    无日期条目返回 published=None，由调用方按 PIT 纪律丢弃。
    """
    soup = BeautifulSoup(html, "lxml")
    fmts = date_formats or _DEFAULT_DATE_FMTS
    out: list[tuple[str, str, datetime | None]] = []
    for el in soup.select(item_selector)[:max_items]:
        title_node = el.select_one(title_selector) if title_selector else None
        title = (title_node or el).get_text(" ", strip=True)[:200]
        if not title:
            continue
        href = el.get(link_attr)
        if not href:
            link = el.select_one(f"[{link_attr}]")
            href = link.get(link_attr) if link else None
        if not href:
            continue
        url = urljoin(base_url, str(href))
        published: datetime | None = None
        if date_selector:
            node = el.select_one(date_selector)
            if node is not None:
                if date_attr == "text":
                    published = parse_ts(node.get_text(" ", strip=True), fmts, tz_offset_hours)
                else:
                    raw = node.get(date_attr)
                    if raw:
                        published = parse_ts(str(raw), fmts, tz_offset_hours)
        out.append((url, title, published))
    if since is not None and until is not None:
        out = [(u, t, p) for u, t, p in out if p is not None and since <= p <= until]
    return out


class BrowserAdapter(SourceAdapter):
    """playwright 渲染列表页 → Draft；可选渲染 detail 抓正文（JS 站点壳）。"""

    def __init__(
        self,
        meta: SourceMeta,
        *,
        list_url: str,
        item_selector: str,
        link_attr: str = "href",
        title_selector: str | None = None,
        date_selector: str | None = None,
        date_attr: str = "datetime",
        date_formats: list[str] | None = None,
        tz_offset_hours: int = 0,
        max_items: int = 30,
        wait_ms: int = 3000,
        scroll_rounds: int = 0,
        detail: dict[str, Any] | None = None,
        article_type: ArticleType = ArticleType.WIRE,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(meta, **base_kwargs)
        self._list_url = list_url
        self._item_selector = item_selector
        self._link_attr = link_attr
        self._title_selector = title_selector
        self._date_selector = date_selector
        self._date_attr = date_attr
        self._date_formats = date_formats
        self._tz_offset_hours = tz_offset_hours
        self._max_items = max_items
        self._wait_ms = wait_ms
        self._scroll_rounds = scroll_rounds
        self._detail = detail
        self._article_type = article_type

    def _listing_cfg(self) -> dict[str, Any]:
        return {
            "item_selector": self._item_selector,
            "link_attr": self._link_attr,
            "title_selector": self._title_selector,
            "date_selector": self._date_selector,
            "date_attr": self._date_attr,
            "date_formats": self._date_formats,
            "tz_offset_hours": self._tz_offset_hours,
            "max_items": self._max_items,
        }

    async def _render(self, page: Any, url: str) -> str:
        await page.goto(url, timeout=60_000, wait_until="load")
        await page.wait_for_timeout(self._wait_ms)
        for _ in range(self._scroll_rounds):
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(1200)
        return await page.content()

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        since = self.effective_since(since, until)
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - 环境缺依赖
            raise RuntimeError(_MISSING_PLAYWRIGHT) from exc
        cfg = self._listing_cfg()
        max_detail = int((self._detail or {}).get("max_items", 10))
        drafts: list[Draft] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=USER_AGENT)
            try:
                html = await self._render(page, self._list_url)
                items = parse_rendered_listing(
                    html, self._list_url, since=since, until=until, **cfg
                )
                if not self._detail:
                    max_detail = len(items)
                for url, title, published in items[:max_detail]:
                    if published is None:
                        continue
                    body = ""
                    if self._detail and url:
                        try:
                            page_html = await self._render(page, url)
                        except RuntimeError:
                            page_html = ""
                        if page_html:
                            probe = Draft(
                                external_id=url,
                                title=title,
                                url=url,
                                published_at=published,
                                lang=self.meta.language,
                                article_type=self._article_type,
                                raw={"source_kind": "browser"},
                            )
                            body = apply_detail(page_html, self._detail, probe).body
                    drafts.append(
                        Draft(
                            external_id=url,
                            title=title,
                            url=url,
                            published_at=published,
                            body=body,
                            lang=self.meta.language,
                            article_type=self._article_type,
                            raw={"source_kind": "browser"},
                        )
                    )
            finally:
                await browser.close()
        return drafts
