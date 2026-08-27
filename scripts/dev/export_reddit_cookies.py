"""CDP 导出 Reddit cookies（一次性；用户已在本地 Chrome 登录 reddit.com）。

用法：
1. Chrome 以 --remote-debugging-port=9222 启动并登录 reddit.com；
2. uv run python scripts/dev/export_reddit_cookies.py

输出 .opencode/cookies/reddit.json（gitignored，永不入库）。
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(".opencode/cookies/reddit.json")
CDP_URL = "http://localhost:9222"


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "缺 playwright 可选依赖：uv add --package oh-sources playwright "
            "&& uv run playwright install chromium"
        ) from None

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        cookies: list[dict] = []
        for ctx in browser.contexts:
            cookies.extend(ctx.cookies("https://www.reddit.com"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cookies, ensure_ascii=False, indent=1))
    print(f"导出 {len(cookies)} 条 cookies → {OUT}")


if __name__ == "__main__":
    main()
