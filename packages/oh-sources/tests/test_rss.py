"""RssAdapter 离线测试：解析逻辑与 HTTP 分离（entries_to_drafts 纯方法）。"""

from datetime import UTC, datetime, timedelta

import feedparser
from oh_contracts.enums import ArticleType, SourceTier
from oh_contracts.ids import content_hash, url_hash
from oh_contracts.schemas import SourceMeta
from oh_sources.rss import RssAdapter

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>test feed</title>
<item>
  <title>央行开展逆回购操作</title>
  <link>http://example.com/a1</link>
  <pubDate>Wed, 26 Aug 2026 10:00:00 GMT</pubDate>
  <description>流动性净投放，维护季末资金面。</description>
</item>
<item>
  <title>窗口外旧闻</title>
  <link>http://example.com/a2</link>
  <pubDate>Tue, 26 Aug 2025 10:00:00 GMT</pubDate>
  <description>去年内容应被过滤。</description>
</item>
<item>
  <title>缺日期条目</title>
  <link>http://example.com/a3</link>
  <description>无 pubDate 应被过滤。</description>
</item>
</channel></rss>
"""

META = SourceMeta(
    source_id="people_test",
    language="zh",
    tier=SourceTier.WIRE,
    credibility_prior=0.85,
    bias="state_media",
    rate_limit_rpm=600,
)
SINCE = datetime(2026, 8, 26, tzinfo=UTC)
UNTIL = datetime(2026, 8, 27, tzinfo=UTC)


def _drafts() -> list:
    feed = feedparser.parse(RSS_XML)
    adapter = RssAdapter(META, url="http://example.com/rss")
    return adapter.entries_to_drafts(feed.entries, SINCE, UNTIL)


def test_window_filter():
    drafts = _drafts()
    assert len(drafts) == 1
    assert drafts[0].external_id == "http://example.com/a1"
    assert drafts[0].published_at == datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def test_to_bronze_idempotent():
    adapter = RssAdapter(META, url="http://example.com/rss")
    draft = _drafts()[0]
    fetched = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    rec = adapter.to_bronze(draft, fetched)
    assert rec.item_key.startswith("people_test:http://example.com/a1:2026-08-26T10:00:00+00:00")
    assert rec.url_hash == url_hash("http://example.com/a1")  # 域分隔输入 "u:" 内建
    assert rec.content_hash == content_hash("央行开展逆回购操作\n流动性净投放，维护季末资金面。")
    assert rec.normalized["article_type"] == str(ArticleType.WIRE)
    rec2 = adapter.to_bronze(draft, fetched)
    assert rec2 == rec


def test_date_fallback_uses_fetch_time_and_stable_item_key():
    """无日期 feed（nikkei 型）：date_fallback 以抓取时刻为 PIT 锚 + item_key 不含时间戳。"""
    feed = feedparser.parse(RSS_XML)
    adapter = RssAdapter(META, url="http://example.com/rss", date_fallback=True)
    fb = datetime(2026, 8, 26, 23, 0, tzinfo=UTC)  # 窗口内锚点
    drafts = adapter.entries_to_drafts(feed.entries, SINCE, UNTIL, fallback_dt=fb)
    # a1 有正常日期；a2 窗口外仍过滤；a3 无日期 → fallback 锚
    assert [d.external_id for d in drafts] == [
        "http://example.com/a1",
        "http://example.com/a3",
    ]
    a3 = drafts[1]
    assert a3.published_at == fb
    assert a3.raw["date_anchor"] == "fetched"
    rec = adapter.to_bronze(a3, fb)
    assert rec.item_key == "people_test:http://example.com/a3:"
    assert rec.raw["date_anchor"] == "fetched"


def test_default_drops_undated_entries():
    """未开启 date_fallback：无日期条目维持丢弃（PIT 纪律默认）。"""
    feed = feedparser.parse(RSS_XML)
    adapter = RssAdapter(META, url="http://example.com/rss")
    drafts = adapter.entries_to_drafts(feed.entries, SINCE, UNTIL)
    assert len(drafts) == 1


def test_effective_since_window_days_clamps():
    """稀疏源窗口放大：window_days=30 → since 收敛到 until-30d；None 透传。"""
    adapter = RssAdapter(META, url="http://example.com/rss", window_days=30)
    since = UNTIL - timedelta(days=90)
    eff = adapter.effective_since(since, UNTIL)
    assert timedelta(days=29) < UNTIL - eff <= timedelta(days=30)
    plain = RssAdapter(META, url="http://example.com/rss")
    assert plain.effective_since(since, UNTIL) == since
