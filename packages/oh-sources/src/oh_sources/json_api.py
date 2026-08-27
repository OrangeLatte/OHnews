"""JsonApiAdapter：配置驱动 JSON API 适配器（Phase 1.5 中文源主通道）。

覆盖：新浪 7x24 / 华尔街见闻快讯 / 东方财富快讯 / 知乎热榜 / gov.cn 政策库 /
HN Algolia 等无 RSS 但有公开 JSON 接口的信源。

字段映射经 dot-path（如 result.data.feed.list，数组下标用整数段）；
时间解析优先级：epoch 毫秒(13位) → epoch 秒(10位) → date_formats 显式格式
（naive 按 tz_offset_hours 升 UTC）→ ISO 兜底。无 PIT 锚（解析不出时间）的条目丢弃。
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import Draft, SourceAdapter

_TAG_RE = re.compile(r"<[^>]+>")
_EPOCH_MS_RE = re.compile(r"\d{13}")
_EPOCH_S_RE = re.compile(r"\d{10}")
MIN_BODY_CHARS = 8


def strip_html(text: str | None) -> str:
    """剥掉 JSON 内嵌 HTML 标签与常见实体（gov.cn <em>、wscn <p> 等）。"""
    cleaned = _TAG_RE.sub(" ", text or "")
    return cleaned.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def dot_get(obj: Any, path: str, default: Any = None) -> Any:
    """a.b.0.c 形式的点路径取值；任一层缺失返回 default。"""
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        else:
            return default
    return cur


def parse_ts(
    raw: Any,
    date_formats: list[str] | None,
    tz_offset_hours: int,
) -> datetime | None:
    """epoch 秒/毫秒 → UTC；显式格式 naive → tz_offset 升 UTC；ISO 兜底；失败 None。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if _EPOCH_MS_RE.fullmatch(s):
        return datetime.fromtimestamp(int(s) / 1000, tz=UTC)
    if _EPOCH_S_RE.fullmatch(s):
        return datetime.fromtimestamp(int(s), tz=UTC)
    for fmt in date_formats or []:
        try:
            naive = datetime.strptime(s, fmt)
            tz = timezone(timedelta(hours=tz_offset_hours))
            return naive.replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class JsonApiAdapter(SourceAdapter):
    """params 契约（config/sources.yaml）：

    - url/params/headers/items_path 必填（items_path 指向条目数组）
    - external_id_path 缺省 → sha1(f"{title}|{published_iso}")[:16]
    - title_path/body_path/url_path 可选；body 缺省回落 title
    - url_template 支持 {external_id} 占位（如知乎 question 页）
    - params 值支持 {now_ms} 动态替换（东方财富 req_trace）
    - published_path + date_formats + tz_offset_hours：naive 时间升 UTC
    """

    def __init__(
        self,
        meta: SourceMeta,
        *,
        url: str,
        items_path: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        external_id_path: str | None = None,
        title_path: str | None = None,
        body_path: str | None = None,
        url_path: str | None = None,
        url_template: str | None = None,
        published_path: str | None = None,
        date_formats: list[str] | None = None,
        tz_offset_hours: int = 0,
        article_type: ArticleType = ArticleType.WIRE,
    ) -> None:
        super().__init__(meta)
        self._url = url
        self._params = params
        self._headers = headers
        self._items_path = items_path
        self._external_id_path = external_id_path
        self._title_path = title_path
        self._body_path = body_path
        self._url_path = url_path
        self._url_template = url_template
        self._published_path = published_path
        self._date_formats = date_formats
        self._tz_offset_hours = tz_offset_hours
        self._article_type = article_type

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        async with httpx.AsyncClient(
            headers={"User-Agent": "OHNews/0.1"}, follow_redirects=True
        ) as client:
            params = {
                k: v.replace("{now_ms}", str(int(time.time() * 1000))) if isinstance(v, str) else v
                for k, v in (self._params or {}).items()
            }
            payload = await self.get_json(client, self._url, params=params, headers=self._headers)
        items = dot_get(payload, self._items_path, []) or []
        return self.entries_to_drafts(items, since, until)

    def entries_to_drafts(
        self,
        items: list[Any],
        since: datetime,
        until: datetime,
    ) -> list[Draft]:
        """条目 → Draft（纯方法，离线可测；窗口过滤 + 无 PIT 锚丢弃 + 过短正文跳过）。"""
        out: list[Draft] = []
        for item in items:
            title = strip_html(
                str(dot_get(item, self._title_path, "") or "") if self._title_path else ""
            )[:200]
            published = parse_ts(
                dot_get(item, self._published_path) if self._published_path else None,
                self._date_formats,
                self._tz_offset_hours,
            )
            if not title or published is None or not (since <= published <= until):
                continue
            body = strip_html(
                str(dot_get(item, self._body_path, "") or "") if self._body_path else ""
            )
            if len(body) < MIN_BODY_CHARS:
                body = title
            ext_raw = (
                str(dot_get(item, self._external_id_path, "") or "")
                if self._external_id_path
                else ""
            )
            external_id = (
                ext_raw
                or hashlib.sha1(f"{title}|{published.isoformat()}".encode()).hexdigest()[:16]
            )
            url = (str(dot_get(item, self._url_path, "") or "") if self._url_path else "") or (
                self._url_template.format(external_id=external_id) if self._url_template else ""
            )
            out.append(
                Draft(
                    external_id=external_id,
                    title=title,
                    url=url,
                    published_at=published,
                    body=body,
                    lang=self.meta.language,
                    article_type=self._article_type,
                    raw={"source_kind": "json_api"},
                )
            )
        return out
