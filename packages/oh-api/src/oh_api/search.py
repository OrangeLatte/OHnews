"""全局搜索（v1 简化版）：bronze 子串匹配检索，无状态无索引。

v1 简化声明：子串 casefold 匹配，非全文倒排索引（FTS5/向量）。
1.3 万条 bronze 线性扫描单次请求在百毫秒量级，可接受；数据量再增两个
数量级时应迁移 SQLite FTS5 或外部索引，本模块纯函数签名可保持不变。

匹配语义：q 归一（strip + casefold）后对 title / body 做子串命中，
title 命中优先排序，同 rank 内 published_at 降序（None 靠后）。

挂载说明（主线在 create_app 内执行，本模块不自行接线）：

    from oh_api.search import build_router

    app.include_router(build_router(lambda: _bronze().iter_records()))
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from oh_contracts.schemas import BronzeRecord

__all__ = ["build_router", "search_bronze"]

_SNIPPET_WINDOW = 60
_MIN_QUERY_LEN = 2


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


def _sort_key(rank: int, published_at: datetime | None) -> tuple[int, float]:
    """排序键：rank 升序（title 优先），published_at 降序，None 靠后。"""
    if published_at is None:
        return (rank, float("inf"))
    return (rank, -published_at.timestamp())


def search_bronze(
    records: Iterable[BronzeRecord],
    q: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """在 bronze 记录上做子串检索（纯函数，无 IO）。

    Args:
        records: bronze 记录流（调用方负责来源，如 ``iter_records()``）。
        q: 用户查询词；strip + casefold 归一，长度 <2 返回空列表。
        limit: 返回条数上限。

    Returns:
        命中结果列表，每条形如::

            {
                "item_key": str,
                "source_id": str,
                "title": str,
                "url": str,
                "published_at": str | None,  # isoformat
                "snippet": str,
            }

        title 命中优先，其次 published_at 降序；snippet 为 body（title
        命中时为 title 片段）中命中词前后各 60 字符窗口。
    """
    needle = q.strip().casefold()
    if len(needle) < _MIN_QUERY_LEN:
        return []

    hits: list[tuple[tuple[int, float], dict[str, Any]]] = []
    for rec in records:
        n = rec.normalized
        title = str(n.get("title") or "")
        body = str(n.get("body") or "")

        title_idx = _match_window(title, needle)
        body_idx = _match_window(body, needle)
        if title_idx is None and body_idx is None:
            continue

        if title_idx is not None:
            rank, snippet = 0, _snippet(title, title_idx, len(needle))
        elif body_idx is not None:
            rank, snippet = 1, _snippet(body, body_idx, len(needle))
        else:
            continue

        hits.append(
            (
                _sort_key(rank, rec.published_at),
                {
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
    return [item for _, item in hits[:limit]]


def build_router(bronze_iter_fn: Callable[[], Iterable[BronzeRecord]]) -> APIRouter:
    """构造搜索路由（依赖注入 bronze 迭代器工厂，避免本模块持有 IO 单例）。

    Args:
        bronze_iter_fn: 每次请求调用，返回 bronze 记录流
            （主线传 ``lambda: _bronze().iter_records()``）。

    Returns:
        挂载 ``GET /api/search?q=&limit=`` 的 APIRouter。
    """

    router = APIRouter()

    @router.get("/api/search")
    def search(q: str = Query(...), limit: int = Query(20, ge=1, le=50)) -> list[dict[str, Any]]:
        """子串检索 bronze 文章；limit 超界与缺失 q 由 FastAPI 校验 422。"""
        return search_bronze(bronze_iter_fn(), q, limit=limit)

    return router
