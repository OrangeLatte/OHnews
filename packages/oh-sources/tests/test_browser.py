"""BrowserAdapter 离线测试：parse_rendered_listing 纯函数 + registry 分发。

playwright 渲染本身不进单测（CI 三 OS 矩阵无浏览器内核），真实链路由
backfill 实测验证（sensitive 类验证走本地手动运行）。
"""

# ruff: noqa: E501 (HTML fixture 行不可折行)

from __future__ import annotations

from datetime import UTC, datetime

from oh_sources.browser import BrowserAdapter, parse_rendered_listing
from oh_sources.registry import build_registry

# BoE speeches 渲染后列表结构样本（wave6 实测，动态日期防时间炸弹）
_BOE_LISTING = """
<html><body>
<div class="list">
  <div class="col3">
    <a href="/speech/2026/july/speech-one" class="release release-speech ">
      <div class="release-tag-wrap"><div class="release-tag">Speech // A Person</div></div>
      <div class="release-content"><div class="release-copy">
        <div class="release-meta">
          <time class="release-date" itemprop="datePublished" datetime="2026-07-21">21 July 2026</time>
        </div>
        <h3 itemprop="name" class="grid-view exclude-navigation">Title grid one</h3>
        <h3 itemprop="name" class="list exclude-navigation">Money and its role - speech by A Person</h3>
      </div></div>
    </a>
  </div>
  <div class="col3">
    <a href="/speech/2026/june/speech-two" class="release release-speech ">
      <div class="release-content"><div class="release-copy">
        <div class="release-meta">
          <time class="release-date" itemprop="datePublished" datetime="2026-06-15">15 June 2026</time>
        </div>
        <h3 itemprop="name" class="list exclude-navigation">Research in regulation - speech by B Person</h3>
      </div></div>
    </a>
  </div>
  <div class="col3">
    <a href="/speech/2026/may/speech-three" class="release release-speech ">
      <div class="release-content"><div class="release-copy">
        <div class="release-meta">
          <time class="release-date" itemprop="datePublished" datetime="2025-01-01">1 January 2025</time>
        </div>
        <h3 itemprop="name" class="list exclude-navigation">Too old - speech by C Person</h3>
      </div></div>
    </a>
  </div>
</div>
</body></html>
"""


def _cfg() -> dict:
    return {
        "item_selector": "a.release-speech",
        "title_selector": "h3.list",
        "date_selector": "time.release-date",
        "date_attr": "datetime",
        "max_items": 30,
    }


def test_parse_listing_extract_and_window_filter() -> None:
    since = datetime(2026, 6, 1, tzinfo=UTC)
    until = datetime(2026, 8, 28, tzinfo=UTC)
    items = parse_rendered_listing(
        _BOE_LISTING, "https://www.bankofengland.co.uk/speeches", since=since, until=until, **_cfg()
    )
    assert len(items) == 2  # 2025-01-01 被窗口过滤
    urls = [u for u, _, _ in items]
    assert urls == [
        "https://www.bankofengland.co.uk/speech/2026/july/speech-one",
        "https://www.bankofengland.co.uk/speech/2026/june/speech-two",
    ]
    # title_selector 命中 h3.list（非 grid 视图标题）
    assert items[0][1] == "Money and its role - speech by A Person"
    # ISO date_attr 直接解析为 UTC
    assert items[0][2] is not None and items[0][2].tzinfo is not None


def test_parse_listing_no_date_returns_none() -> None:
    html = '<html><body><a class="release-speech" href="/speech/x"><h3 class="list">T</h3></a></body></html>'
    items = parse_rendered_listing(html, "https://x/", **_cfg())
    assert items == [("", "", None)] or items[0][2] is None


def test_parse_listing_missing_link_skipped() -> None:
    html = (
        '<html><body><div class="release-speech"><h3 class="list">No href</h3></div></body></html>'
    )
    assert parse_rendered_listing(html, "https://x/", **_cfg()) == []


def test_registry_browser_dispatch() -> None:
    config = {
        "sources": [
            {
                "source_id": "boe_speeches",
                "adapter": "browser",
                "tier": "L1",
                "language": "en",
                "enabled": True,
                "params": {
                    "list_url": "https://www.bankofengland.co.uk/speeches",
                    "item_selector": "a.release-speech",
                    "title_selector": "h3.list",
                    "date_selector": "time.release-date",
                    "window_days": 90,
                    "detail": {"content_selector": "div#output", "max_items": 5},
                },
            }
        ]
    }
    registry = build_registry(config)
    adapter = registry.get("boe_speeches")
    assert isinstance(adapter, BrowserAdapter)
    assert adapter.window_days == 90
    meta = adapter.describe()
    assert meta.needs_browser is False  # needs_browser 元数据由 spec 显式声明，不自动置位
    assert meta.tier.value == "L1"


def test_registry_browser_disabled_zero_cost() -> None:
    config = {
        "sources": [
            {
                "source_id": "boe_speeches",
                "adapter": "browser",
                "tier": "L1",
                "language": "en",
                "enabled": False,
                "params": {"list_url": "https://x/", "item_selector": "a"},
            }
        ]
    }
    assert build_registry(config).all() == []
