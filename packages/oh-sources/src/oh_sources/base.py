"""SourceAdapter 框架（裁决 C）：元数据驱动 + item_key 幂等 + 统一 Bronze 出口。

子类只实现 fetch()；to_bronze() 统一构造双 hash 幂等记录。
令牌桶限速内建于 get_text()（min interval = 60/rate_limit_rpm 秒）。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from oh_contracts.enums import ArticleType
from oh_contracts.ids import content_hash, make_item_key, url_hash
from oh_contracts.schemas import BronzeRecord, SourceMeta

DEFAULT_TIMEOUT_S = 30.0
USER_AGENT = "OHNews/0.1 (+non-commercial research; local deployment)"


@dataclass(frozen=True)
class Draft:
    """适配器归一化草稿（Bronze 之前的最小公共形态）。

    published_at 必须为 tz-aware UTC（PIT 锚点；naive 时间一律视为契约违规）。
    """

    external_id: str
    title: str
    url: str
    published_at: datetime
    body: str = ""
    lang: str = "zh"
    article_type: ArticleType = ArticleType.WIRE
    raw: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """采集适配器基类。

    Attributes:
        source_id: 信源唯一 ID（= SourceMeta.source_id）。
        meta: describe() 契约面（ccxt describe 模式）。
    """

    def __init__(self, meta: SourceMeta) -> None:
        self.meta = meta
        self.source_id = meta.source_id
        self._last_request: float = 0.0

    def describe(self) -> SourceMeta:
        """返回信源元数据（裁决 C：describe 元数据驱动）。"""
        return self.meta

    @abstractmethod
    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        """拉取 [since, until] 窗口内条目（tz-aware UTC，含端点）。"""

    def to_bronze(self, draft: Draft, fetched_at: datetime) -> BronzeRecord:
        """Draft → BronzeRecord：item_key=(source, external_id, published_ts) 幂等。"""
        ts = draft.published_at.isoformat()
        content = f"{draft.title}\n{draft.body}"
        return BronzeRecord(
            source_id=self.source_id,
            item_key=make_item_key(self.source_id, draft.external_id, ts),
            external_id=draft.external_id,
            url_hash=url_hash(draft.url),
            content_hash=content_hash(content),
            fetched_at=fetched_at,
            published_at=draft.published_at,
            raw=draft.raw,
            normalized={
                "title": draft.title,
                "url": draft.url,
                "published_at": ts,
                "body": draft.body,
                "lang": draft.lang,
                "article_type": str(draft.article_type),
            },
        )

    async def get_text(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> str:
        """限速 GET 文本；非 2xx 抛 httpx.HTTPStatusError（由 runner 退避重试）。"""
        interval = 60.0 / self.meta.rate_limit_rpm
        wait = self._last_request + interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()
        resp = await client.get(url, params=params, timeout=DEFAULT_TIMEOUT_S)
        resp.raise_for_status()
        return resp.text
