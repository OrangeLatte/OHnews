"""RssAdapter 离线测试：解析逻辑与 HTTP 分离（entries_to_drafts 纯方法）。"""

from datetime import UTC, datetime

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
