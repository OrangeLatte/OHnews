"""websearch 工具层（M5 A0-2）：Tavily 主选 + DuckDuckGo 免费兜底。

设计（§五 用户裁决）：
- Tavily：REST API（无 SDK 依赖），search / extract 两端点；p50 ~180ms；
  PII 不得入请求（只发查询词/URL）。
- DuckDuckGo：免费兜底（HTML 即时答案接口），无 key。
- key 来源：环境变量 TAVILY_API_KEY（/api/keys 热配置写入 runtime_keys.json）。
- 纯函数 + 注入 fetcher，测试 monkeypatch HTTP，不打真实网络。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import requests

Fetch = Callable[[str, dict[str, Any] | None], requests.Response]

_TAVILY_BASE = "https://api.tavily.com"
_TIMEOUT = 10.0

WebSearchResult = dict[str, Any]  # {title,url,snippet}
WebExtractResult = dict[str, str]  # {url: text}


def _strip_pii(text: str) -> str:
    """查询词防 PII 泄漏：去邮箱/电话/长数字串。"""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "", text)
    text = re.sub(r"\+?\d[\d\s-]{7,}\d", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _tavily_fetch(path: str, payload: dict[str, Any]) -> requests.Response:
    return requests.post(f"{_TAVILY_BASE}/{path}", json=payload, timeout=_TIMEOUT)


def _ddg_fetch(path: str, payload: dict[str, Any]) -> requests.Response:
    return requests.get(
        "https://html.duckduckgo.com/html/", params={"q": payload["query"]}, timeout=_TIMEOUT
    )


def _parse_ddg(html: str, limit: int) -> list[WebSearchResult]:
    out: list[WebSearchResult] = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        url = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if url.startswith("//"):
            url = f"https:{url}"
        out.append({"title": title, "url": url, "snippet": ""})
        if len(out) >= limit:
            break
    return out


def web_search(
    query: str,
    *,
    api_key: str | None = None,
    limit: int = 5,
    fetch: Fetch | None = None,
) -> list[WebSearchResult]:
    """联网搜索：有 key 走 Tavily，无 key 降级 DuckDuckGo；空结果/异常再兜底。"""
    q = _strip_pii(query)
    if not q:
        return []
    results: list[WebSearchResult] = []
    if api_key and api_key.strip():
        r = (fetch or _tavily_fetch)(
            "search", {"api_key": api_key.strip(), "query": q, "max_results": limit}
        )
        if r.ok:
            results = [
                {
                    "title": i.get("title", ""),
                    "url": i.get("url", ""),
                    "snippet": i.get("content", ""),
                }
                for i in r.json().get("results", [])[:limit]
            ]
    if not results:
        try:
            r = (fetch or _ddg_fetch)("html", {"query": q})
            if r.ok:
                results = _parse_ddg(r.text, limit)
        except requests.RequestException:
            return []
    return results


def web_extract(
    urls: list[str],
    *,
    api_key: str | None = None,
    fetch: Fetch | None = None,
) -> WebExtractResult:
    """Tavily extract：URL → 正文文本（Tavily-only；失败/超限 url 值为空串）。"""
    if not urls or not api_key:
        return {u: "" for u in urls}
    try:
        r = (fetch or _tavily_fetch)("extract", {"api_key": api_key.strip(), "urls": urls[:10]})
        if not r.ok:
            return {u: "" for u in urls}
        data = r.json().get("results", [])
        out = {i.get("url", ""): i.get("raw_content") or "" for i in data}
        return {u: out.get(u, "") for u in urls}
    except requests.RequestException:
        return {u: "" for u in urls}


def tavily_ready(api_key: str | None) -> bool:
    """key 是否可用（布尔，不回显）。"""
    return bool(api_key and api_key.strip())
