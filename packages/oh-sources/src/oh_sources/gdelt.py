"""GDELT DOC 2.0 适配器（回填主通道）。

蓝图定位（研究员 P2 + 数据科学家）：GDELT 仅作覆盖度信号（什么在被报），
不作 tone/frame 信号。DOC 2.0 ArtList 免 key；正文不在 ArtList 中（body 空，
后续如需正文经 L3 源回查）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import USER_AGENT, Draft, SourceAdapter

# 2026-08-30 实测：443 HTTPS 在本地网络环境被墙（TLS ClientHello 黑洞，直连与代理出口皆然），
# 80 HTTP 直连 4s 稳定返回合法 JSON——默认走 http（公开聚合 API，无敏感载荷）。
GDELT_DOC_URL = "http://api.gdeltproject.org/api/v2/doc/doc"


def _parse_seendate(value: str) -> datetime | None:
    """GDELT seendate（"20260826T100000Z"）→ tz-aware UTC；非法返回 None。"""
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_articles(payload: dict[str, Any], *, lang: str = "zh") -> list[Draft]:
    """ArtList JSON → Draft（纯函数，离线可测；无 url/无时间条目丢弃）。"""
    out: list[Draft] = []
    for article in payload.get("articles", []):
        url = str(article.get("url", "")).strip()
        if not url:
            continue
        pub = _parse_seendate(str(article.get("seendate", "")))
        if pub is None:
            continue
        title = str(article.get("title", "")).strip()
        out.append(
            Draft(
                external_id=url,
                title=title,
                url=url,
                published_at=pub,
                body="",
                lang=lang,
                article_type=ArticleType.WIRE,
                raw={
                    "domain": article.get("domain"),
                    "sourcecountry": article.get("sourcecountry"),
                    "language": article.get("language"),
                },
            )
        )
    return out


def _slice_ranges(
    since: datetime, until: datetime, slice_days: int
) -> list[tuple[datetime, datetime]]:
    """[since, until) 按 slice_days 切片（纯函数；末片不足 slice_days 取余量）。"""
    step = timedelta(days=slice_days)
    out: list[tuple[datetime, datetime]] = []
    cur = since
    while cur < until:
        nxt = min(cur + step, until)
        out.append((cur, nxt))
        cur = nxt
    return out


class GDELTDocAdapter(SourceAdapter):
    """GDELT DOC 2.0 ArtList：query 例 "sourcelang:chinese (央行 OR 货币政策)"。

    网络回退（2026-08-27 探测：直连 SSL 握手被阻断，代理间歇可达）：
    先直连 → 失败且配置 proxy_url 时经代理重试一次；两段皆败抛最后异常。

    历史回填（2026-08-28）：DOC API 单请求上限 maxrecords（≤250）且 sort=DateDesc，
    长窗口单请求只回最新一页——slice_days=N 时把 [since, until] 切成 N 天片逐片
    请求再按 external_id 去重合并；任一片失败即抛出（严格语义，交由
    run_collector 退避重试），不做部分静默。
    """

    def __init__(
        self,
        meta: SourceMeta,
        *,
        query: str,
        max_records: int = 75,
        slice_days: int | None = None,
        proxy_fallback: bool = False,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(meta, **base_kwargs)
        self._query = query
        self._max_records = max_records
        self._slice_days = slice_days
        self._proxy_fallback = proxy_fallback

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        ranges = (
            _slice_ranges(since, until, self._slice_days) if self._slice_days else [(since, until)]
        )
        seen: set[str] = set()
        out: list[Draft] = []
        for idx, (start, end) in enumerate(ranges):
            if idx > 0:
                # GDELT ArtList 限流严格（429）：分片间隔退避，回溯批量时保命
                await asyncio.sleep(min(6.0, 1.5 * idx))
            for draft in await self._fetch_range(start, end):
                if draft.external_id not in seen:
                    seen.add(draft.external_id)
                    out.append(draft)
        return out

    # 连接被墙时 TCP SYN 黑洞会吃满默认 30s——connect 收紧让回退链快速失败
    _TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=5.0)

    async def _fetch_range(self, since: datetime, until: datetime) -> list[Draft]:
        params = {
            "query": self._query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(self._max_records),
            "sort": "DateDesc",
            "startdatetime": since.strftime("%Y%m%d%H%M%S"),
            "enddatetime": until.strftime("%Y%m%d%H%M%S"),
        }
        # 回退链：直连 → 代理（proxy_fallback 且配置了 proxy_url 时）
        routes: list[str | None] = [None]
        if self._proxy_fallback and self.proxy_url:
            routes.append(self.proxy_url)
        last_exc: Exception | None = None
        for route in routes:
            for attempt in range(3):  # 429 限流退避：1s/4s/9s
                try:
                    async with self.make_client(
                        proxy=route, headers={"User-Agent": USER_AGENT}, timeout=self._TIMEOUT
                    ) as client:
                        text = await self.get_text(client, GDELT_DOC_URL, params=params)
                    return _parse_articles(json.loads(text), lang=self.meta.language)
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    if exc.response.status_code == 429 and attempt < 2:
                        await asyncio.sleep(1.0 * (attempt + 1) ** 2)
                        continue
                    break
                except Exception as exc:  # noqa: BLE001 —— 回退链逐段尝试
                    last_exc = exc
                    break
        assert last_exc is not None
        raise last_exc
