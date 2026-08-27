"""HtmlAdapter 单测（离线 fixture：列表解析/日期作用域/注册分发）。"""

from datetime import UTC, datetime, timedelta

from oh_sources.html import HtmlAdapter
from oh_sources.registry import build_registry


def _list_html() -> str:
    """动态日期 fixture（防时间炸弹：硬编码日期会被窗口过滤）。"""
    from datetime import timedelta

    today = (datetime.now(UTC) + timedelta(hours=8)).strftime("%Y-%m-%d")
    return f"""
<html><body><ul class="news-list">
  <li><a href="/news/a.html">央行发布货币政策执行报告</a><span class="date">{today}</span></li>
  <li><a href="/news/b.html">财政政策加力提效</a><span class="date">2020-01-01</span></li>
  <li><span>无链接条目</span></li>
</ul></body></html>
"""


def _adapter():
    from oh_contracts.enums import SourceTier
    from oh_contracts.schemas import SourceMeta

    meta = SourceMeta(
        source_id="gov_html_test",
        language="zh",
        tier=SourceTier.OFFICIAL,
        credibility_prior=0.95,
        bias="state_media",
        rate_limit_rpm=60,
        needs_browser=False,
        paywall=False,
    )
    return HtmlAdapter(
        meta,
        list_url="https://example.test/news/",
        item_selector="ul.news-list li a",
        date_scope="parent",
    )


def test_parse_listing_window_and_absolute_url():
    now = datetime.now(UTC)
    drafts = _adapter().parse_listing(
        _list_html(),
        "https://example.test/news/",
        now - timedelta(days=1),
        now + timedelta(days=1),
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert d.url == "https://example.test/news/a.html"
    assert d.title.startswith("央行发布货币政策执行报告")
    assert d.published_at.tzinfo is not None


def test_parse_listing_stale_item_filtered():
    drafts = _adapter().parse_listing(
        _list_html(),
        "https://example.test/news/",
        datetime(2026, 8, 1, tzinfo=UTC),
        datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert drafts == []


def test_registry_dispatches_html():
    cfg = {
        "sources": [
            {
                "source_id": "h1",
                "adapter": "html",
                "tier": "L1",
                "language": "zh",
                "rate_limit_rpm": 60,
                "params": {
                    "list_url": "https://x.test/list",
                    "item_selector": "li a",
                },
            }
        ]
    }
    adapters = build_registry(cfg).all()
    assert len(adapters) == 1 and type(adapters[0]).__name__ == "HtmlAdapter"
