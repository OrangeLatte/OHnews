"""全局搜索（v2，T5 升级）：分词 AND + 实体别名提升 + URL 去重 + 事件分类。

v2 语义（对 v1 子串整串匹配的升级）：
1. 查询按空白分词，全部词命中（AND）才算结果——「美联储 利率」不再要求整串出现。
2. 实体别名命中（title/body）的记录排序提升（rank -1 档，仍保持 title 优先）。
3. 相同 URL 的文章去重（保留排序最前的一条）。
4. 可选 events_fn：事件 title/summary 命中时前置返回 kind="event" 条目
   （事件数 ~百级，线性扫描无压力）；change 分类需要轻量信号索引，留 v2+。

仍非全文倒排索引：1.3 万条 bronze 线性扫描单次请求在百毫秒量级；数据量再增
两个数量级时应迁移 SQLite FTS5 或外部索引，本模块纯函数签名可保持不变。

挂载说明（主线在 create_app 内执行，本模块不自行接线）：

    from oh_api.search import build_router

    app.include_router(build_router(
        lambda: _bronze().iter_records(),
        events_fn=lambda: _store().events_asof(_now()),
        alias_fn=lambda: [a for eid in _registry().ids() for a in _registry().get(eid).aliases],
    ))
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from oh_contracts.schemas import BronzeRecord, EventRecord

__all__ = ["build_router", "search_bronze", "search_events"]

_SNIPPET_WINDOW = 60
_MIN_QUERY_LEN = 2
_EVENT_LIMIT = 5


def _snippet(text: str, hit_start: int, hit_len: int, *, width: int = _SNIPPET_WINDOW) -> str:
    """取命中词前后各 ``width`` 字符窗口，词中不截断（优先句号/空格边界）。

    Args:
        text: 原文（未 casefold，保留原大小写用于展示）。
        hit_start: 命中词在原文中的起始下标。
        hit_len: 命中词长度。
        width: 命中词前后各保留的字符数。

    Returns:
        截取后的片段；被截断一侧以「…」标注。
    """
    raw_start = max(0, hit_start - width)
    raw_end = min(len(text), hit_start + hit_len + width)
    boundaries = "。！？.!?:：；;"

    start = raw_start
    for i in range(hit_start - 1, raw_start - 1, -1):
        if text[i] in boundaries or text[i].isspace():
            start = i + 1
            break

    end = raw_end
    for i in range(raw_end - 1, hit_start + hit_len - 1, -1):
        if text[i] in boundaries or text[i].isspace():
            end = i + 1
            break

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def _match_window(text: str, needle: str) -> int | None:
    """casefold 子串定位；返回命中下标（-1 视为未命中）。

    注意：casefold 极少数场景（如 ß→ss）会改变串长，导致下标无法映射回
    原文——此时直接以折叠文本截取 snippet（展示层面可接受的妥协）。
    """
    idx = text.casefold().find(needle)
    return None if idx < 0 else idx


def _terms(q: str) -> list[str]:
    """查询分词：空白切分，保留长度 >=1 的词（整串 <2 字符由调用方拦截）。"""
    return [t for t in q.strip().casefold().split() if t]


def _sort_key(rank: tuple[int, int], published_at: datetime | None) -> tuple[int, int, float]:
    """排序键：复合 rank 升序（提升档, title 档），published_at 降序，None 靠后。"""
    if published_at is None:
        return (*rank, float("inf"))
    return (*rank, -published_at.timestamp())


def search_bronze(
    records: Iterable[BronzeRecord],
    q: str,
    *,
    limit: int = 20,
    boost_terms: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """在 bronze 记录上做分词 AND 检索（纯函数，无 IO）。

    Args:
        records: bronze 记录流（调用方负责来源，如 ``iter_records()``）。
        q: 用户查询词；整串 strip+casefold 后 <2 字符返回空列表。
        limit: 返回条数上限。
        boost_terms: 排序提升词表（实体别名，原始大小写，内部 casefold）；
            title/body 命中任一别名的记录 rank 提前一档。

    Returns:
        命中结果列表，每条形如::

            {
                "kind": "article",
                "item_key": str,
                "source_id": str,
                "title": str,
                "url": str,
                "published_at": str | None,  # isoformat
                "snippet": str,
            }

        排序：别名提升 > title 命中 > published_at 降序；相同 URL（非空）
        去重保留最前一条；snippet 为命中词前后各 60 字符窗口。
    """
    needle = q.strip().casefold()
    if len(needle) < _MIN_QUERY_LEN:
        return []
    terms = _terms(q) or [needle]
    boosts = [b.strip().casefold() for b in boost_terms if b.strip()]

    hits: list[tuple[tuple[int, float], dict[str, Any]]] = []
    for rec in records:
        n = rec.normalized
        title = str(n.get("title") or "")
        body = str(n.get("body") or "")
        title_cf, body_cf = title.casefold(), body.casefold()

        if not all(t in title_cf or t in body_cf for t in terms):
            continue

        # snippet 取第一个在 title 命中的词（title 优先展示），否则 body 命中词
        snippet = ""
        for t in terms:
            idx = _match_window(title, t)
            if idx is not None:
                snippet = _snippet(title, idx, len(t))
                break
        if not snippet:
            for t in terms:
                idx = _match_window(body, t)
                if idx is not None:
                    snippet = _snippet(body, idx, len(t))
                    break

        in_title = any(t in title_cf for t in terms)
        # 别名提升分层：title 命中别名 > body 命中别名 > 无别名（T5）
        title_boost = any(b in title_cf for b in boosts)
        body_boost = any(b in body_cf for b in boosts)
        boost_rank = 0 if title_boost else (1 if body_boost else 2)
        rank = (boost_rank, 0 if in_title else 1)

        hits.append(
            (
                _sort_key(rank, rec.published_at),
                {
                    "kind": "article",
                    "item_key": rec.item_key,
                    "source_id": rec.source_id,
                    "title": title,
                    "url": str(n.get("url") or ""),
                    "published_at": (rec.published_at.isoformat() if rec.published_at else None),
                    "snippet": snippet,
                },
            )
        )

    hits.sort(key=lambda pair: pair[0])
    out: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for _, item in hits:
        url = item["url"]
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def search_events(
    events: Iterable[EventRecord],
    q: str,
    *,
    limit: int = _EVENT_LIMIT,
) -> list[dict[str, Any]]:
    """事件 title/summary 检索（kind="event" 前置条目，点击跳事件详情）。"""
    needle = q.strip().casefold()
    if len(needle) < _MIN_QUERY_LEN:
        return []
    terms = _terms(q) or [needle]

    hits: list[tuple[tuple[int, float], dict[str, Any]]] = []
    for ev in events:
        title = ev.title or ""
        summary = ev.summary or ""
        title_cf, summary_cf = title.casefold(), summary.casefold()
        if not all(t in title_cf or t in summary_cf for t in terms):
            continue
        snippet = ""
        for t in terms:
            idx = _match_window(title, t)
            if idx is not None:
                snippet = _snippet(title, idx, len(t))
                break
        if not snippet:
            for t in terms:
                idx = _match_window(summary, t)
                if idx is not None:
                    snippet = _snippet(summary, idx, len(t))
                    break
        hits.append(
            (
                _sort_key((0, 0), ev.as_of),
                {
                    "kind": "event",
                    "id": ev.event_id,
                    "title": title,
                    "url": "",
                    "published_at": ev.as_of.isoformat(),
                    "snippet": snippet,
                },
            )
        )
    hits.sort(key=lambda pair: pair[0])
    return [item for _, item in hits[:limit]]


def build_router(
    bronze_iter_fn: Callable[[], Iterable[BronzeRecord]],
    *,
    events_fn: Callable[[], Iterable[EventRecord]] | None = None,
    alias_fn: Callable[[], list[str]] | None = None,
) -> APIRouter:
    """构造搜索路由（依赖注入，避免本模块持有 IO 单例）。

    Args:
        bronze_iter_fn: 每次请求调用，返回 bronze 记录流
            （主线传 ``lambda: _bronze().iter_records()``）。
        events_fn: 可选，返回事件流（主线 ``lambda: _store().events_asof(_now())``）；
            提供时命中事件以 kind="event" 前置。
        alias_fn: 可选，返回实体别名列表（用于排序提升）。

    Returns:
        挂载 ``GET /api/search?q=&limit=`` 的 APIRouter。
    """

    router = APIRouter()

    @router.get("/api/search")
    def search(q: str = Query(...), limit: int = Query(20, ge=1, le=50)) -> list[dict[str, Any]]:
        """分词 AND 检索（事件前置 + 文章）；limit 超界与缺失 q 由 FastAPI 校验 422。"""
        events = search_events(events_fn(), q) if events_fn is not None else []
        articles = search_bronze(
            bronze_iter_fn(),
            q,
            limit=limit,
            boost_terms=alias_fn() if alias_fn is not None else (),
        )
        return [*events, *articles]

    return router
