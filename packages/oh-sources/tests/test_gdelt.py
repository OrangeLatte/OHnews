"""GDELTDocAdapter 离线测试：_parse_articles 纯函数。"""

from datetime import UTC, datetime

from oh_sources.gdelt import _parse_articles

PAYLOAD = {
    "articles": [
        {
            "url": "http://a.com/1",
            "title": "央行宣布降准 0.5 个百分点",
            "seendate": "20260826T100000Z",
            "domain": "a.com",
            "sourcecountry": "China",
            "language": "Chinese",
        },
        {"url": "", "title": "无 URL 应丢弃", "seendate": "20260826T100000Z"},
        {"url": "http://a.com/2", "title": "非法时间应丢弃", "seendate": "garbage"},
    ]
}


def test_parse_articles_filters():
    drafts = _parse_articles(PAYLOAD, lang="zh")
    assert len(drafts) == 1
    d = drafts[0]
    assert d.external_id == "http://a.com/1"
    assert d.published_at == datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    assert d.raw["domain"] == "a.com"
    assert d.lang == "zh"


def test_parse_articles_empty():
    assert _parse_articles({}) == []
    assert _parse_articles({"articles": []}) == []
