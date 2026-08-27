"""Reddit 登录态采集（用户指示：OAuth 不可行 → CDP 导出 cookies 方案）。

前置（一次性，用户配合）：
1. 本地 Chrome 以 --remote-debugging-port=9222 启动并登录 reddit.com；
2. 运行 scripts/dev/export_reddit_cookies.py → 导出 .opencode/cookies/reddit.json
   （gitignored，永不入库）。
未配置时 fail-fast ValueError（run_collector 记录为 error 结果并汇报）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oh_contracts.enums import ArticleType
from oh_contracts.schemas import SourceMeta

from oh_sources.base import Draft, SourceAdapter

DEFAULT_COOKIES_FILE = ".opencode/cookies/reddit.json"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_EXPORT_HINT = (
    "Reddit cookies 未配置。前置步骤：①本地 Chrome 加 "
    "--remote-debugging-port=9222 启动并登录 reddit.com；"
    "②运行 uv run python scripts/dev/export_reddit_cookies.py 导出 "
    f"{DEFAULT_COOKIES_FILE}（gitignored）。"
)


class RedditCdpAdapter(SourceAdapter):
    """cookies 文件驱动的 Reddit JSON API 采集（r/<sub>/new.json）。"""

    def __init__(
        self,
        meta: SourceMeta,
        *,
        subreddits: list[str],
        cookies_file: str = DEFAULT_COOKIES_FILE,
        limit: int = 25,
        article_type: ArticleType = ArticleType.OPINION,
        **base_kwargs: Any,
    ) -> None:
        super().__init__(meta, **base_kwargs)
        self._subreddits = subreddits
        self._cookies_file = cookies_file
        self._limit = limit
        self._article_type = article_type

    def _cookie_header(self) -> str:
        path = Path(self._cookies_file)
        if not path.exists():
            raise ValueError(_EXPORT_HINT)
        cookies = json.loads(path.read_text())
        pairs = [
            f"{c['name']}={c['value']}" for c in cookies if "reddit" in str(c.get("domain", ""))
        ]
        if not pairs:
            raise ValueError(f"cookies 文件无 reddit.com 域条目: {path}")
        return "; ".join(pairs)

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        headers = {"User-Agent": BROWSER_UA, "Cookie": self._cookie_header()}
        out: list[Draft] = []
        async with self.make_client(headers=headers, follow_redirects=True) as client:
            for sub in self._subreddits:
                text = await self.get_text(
                    client,
                    f"https://www.reddit.com/r/{sub}/new.json",
                    params={"limit": str(self._limit), "raw_json": "1"},
                )
                out.extend(self.parse_entries(json.loads(text), sub, since, until))
        return out

    def parse_entries(
        self,
        payload: dict,
        sub: str,
        since: datetime,
        until: datetime,
    ) -> list[Draft]:
        """new.json → Draft（纯方法，离线可测）。"""
        out: list[Draft] = []
        for child in (payload.get("data") or {}).get("children") or []:
            d = child.get("data") or {}
            created = datetime.fromtimestamp(d.get("created_utc", 0), tz=UTC)
            if not (since <= created <= until):
                continue
            title = str(d.get("title", "")).strip()[:200]
            if not title:
                continue
            permalink = f"https://www.reddit.com{d.get('permalink', '')}"
            out.append(
                Draft(
                    external_id=f"{sub}:{d.get('id', '')}",
                    title=title,
                    url=permalink,
                    published_at=created,
                    body=str(d.get("selftext", "")).strip(),
                    lang=self.meta.language,
                    article_type=self._article_type,
                    raw={"source_kind": "reddit_cdp", "subreddit": sub},
                )
            )
        return out
