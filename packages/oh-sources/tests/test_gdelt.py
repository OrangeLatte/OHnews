"""GDELTDocAdapter 离线测试：_parse_articles 纯函数 + 切片回填。"""

from datetime import UTC, datetime, timedelta

from oh_contracts.enums import ArticleType, SourceTier
from oh_contracts.schemas import SourceMeta
from oh_sources.gdelt import Draft, GDELTDocAdapter, _parse_articles, _slice_ranges

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


def _meta() -> SourceMeta:
    return SourceMeta(
        source_id="gdelt_en",
        language="en",
        tier=SourceTier.WIRE,
        credibility_prior=0.6,
    )


def test_slice_ranges_boundaries():
    since = datetime(2026, 6, 1, tzinfo=UTC)
    until = since + timedelta(days=90)
    ranges = _slice_ranges(since, until, 7)
    assert len(ranges) == 13  # 12 整片 + 6 天余片
    assert ranges[0][0] == since
    assert ranges[-1][1] == until
    for (_, e0), (s1, _) in zip(ranges, ranges[1:], strict=False):
        assert e0 == s1  # 无缝衔接
    # 不足一片
    single = [(since, since + timedelta(days=3))]
    assert _slice_ranges(since, since + timedelta(days=3), 7) == single
    # 精确整除
    assert len(_slice_ranges(since, until, 30)) == 3


def test_fetch_slices_merge_dedup(monkeypatch):
    import asyncio

    calls: list[tuple[datetime, datetime]] = []

    async def fake_range(self, since, until):
        calls.append((since, until))
        url = f"http://a.com/{until.day}"
        return [
            Draft(
                external_id=url,
                title="t",
                url=url,
                published_at=until,
                body="",
                lang="en",
                article_type=ArticleType.WIRE,
                raw={},
            ),
            # 跨片重复：两片都返回同一 fixed url
            Draft(
                external_id="http://fixed.example/x",
                title="dup",
                url="http://fixed.example/x",
                published_at=until,
                body="",
                lang="en",
                article_type=ArticleType.WIRE,
                raw={},
            ),
        ]

    adapter = GDELTDocAdapter(
        _meta(),
        query="q",
        max_records=250,
        slice_days=7,
        proxy_fallback=True,
        proxy_url="http://127.0.0.1:9674",
    )
    monkeypatch.setattr(GDELTDocAdapter, "_fetch_range", fake_range)
    since = datetime(2026, 6, 1, tzinfo=UTC)
    until = since + timedelta(days=14)
    drafts = asyncio.run(adapter.fetch(since, until))
    assert len(calls) == 2  # 14 天 / 7 天片 = 2 次请求
    # 2 片 × (1 片内 + 1 fixed 重复) → 去重后 3 条
    assert len(drafts) == 3
    assert len({d.external_id for d in drafts}) == 3


def test_fetch_slice_failure_strict(monkeypatch):
    import asyncio

    async def boom(self, since, until):
        raise RuntimeError("ssl down")

    adapter = GDELTDocAdapter(_meta(), query="q", slice_days=7)
    monkeypatch.setattr(GDELTDocAdapter, "_fetch_range", boom)
    since = datetime(2026, 6, 1, tzinfo=UTC)
    until = since + timedelta(days=7)
    try:
        asyncio.run(adapter.fetch(since, until))
        raised = False
    except RuntimeError:
        raised = True
    assert raised  # 任一片失败即抛（严格，交 run_collector 退避重试）
