"""GDELT DOC 2.0 适配器（回填主通道）。

蓝图定位（研究员 P2 + 数据科学家）：GDELT 仅作覆盖度信号（什么在被报），
不作 tone/frame 信号。DOC 2.0 ArtList 免 key；正文不在 ArtList 中（body 空，
后续如需正文经 L3 源回查）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import USER_AGENT, Draft, SourceAdapter

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


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


class GDELTDocAdapter(SourceAdapter):
    """GDELT DOC 2.0 ArtList：query 例 "sourcelang:chinese (央行 OR 货币政策)"。

    网络回退（2026-08-27 探测：直连 SSL 握手被阻断，代理间歇可达）：
    先直连 → 失败且配置 proxy_url 时经代理重试一次；两段皆败抛最后异常。
    """

    def __init__(
        self,
        meta: SourceMeta,
        *,
        query: str,
        max_records: int = 75,
        proxy_fallback: bool = False,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(meta, **base_kwargs)
        self._query = query
        self._max_records = max_records
        self._proxy_fallback = proxy_fallback

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
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
            try:
                async with self.make_client(
                    proxy=route, headers={"User-Agent": USER_AGENT}
                ) as client:
                    text = await self.get_text(client, GDELT_DOC_URL, params=params)
                return _parse_articles(json.loads(text), lang=self.meta.language)
            except Exception as exc:  # noqa: BLE001 —— 回退链逐段尝试
                last_exc = exc
        assert last_exc is not None
        raise last_exc
