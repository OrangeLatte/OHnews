"""JsonApiAdapter 单测（离线：dot-path/时间解析/strip_html/条目转换/注册分发）。"""

from datetime import UTC, datetime, timedelta

import pytest
from oh_sources.json_api import JsonApiAdapter, dot_get, parse_ts, strip_html
from oh_sources.registry import build_registry


def _meta(source_id="sina_7x24"):
    from oh_contracts.enums import SourceTier
    from oh_contracts.schemas import SourceMeta

    return SourceMeta(
        source_id=source_id,
        language="zh",
        tier=SourceTier.FINANCIAL_PRESS,
        credibility_prior=0.7,
        bias="financial_press",
        rate_limit_rpm=60,
        needs_browser=False,
        paywall=False,
    )


def _adapter(**kw):
    defaults = dict(
        url="https://example.test/api",
        items_path="data.list",
        external_id_path="id",
        title_path="rich_text",
        body_path="rich_text",
        published_path="create_time",
        date_formats=["%Y-%m-%d %H:%M:%S"],
        tz_offset_hours=8,
    )
    defaults.update(kw)
    return JsonApiAdapter(_meta(), **defaults)


# ---- dot_get ----


def test_dot_get_nested_dict_and_list():
    payload = {"result": {"data": {"feed": {"list": [{"id": "a1"}]}}}}
    assert dot_get(payload, "result.data.feed.list.0.id") == "a1"


def test_dot_get_missing_returns_default():
    assert dot_get({"a": 1}, "a.b.c", default="x") == "x"
    assert dot_get(None, "a", default=0) == 0


# ---- parse_ts ----


def test_parse_ts_epoch_variants():
    assert parse_ts(1700000000, None, 0) == datetime.fromtimestamp(1700000000, tz=UTC)
    assert parse_ts("1700000000000", None, 0) == datetime.fromtimestamp(1700000000, tz=UTC)


def test_parse_ts_naive_with_tz_offset():
    got = parse_ts("2026-08-27 10:00:00", ["%Y-%m-%d %H:%M:%S"], 8)
    assert got is not None and got.utcoffset() == timedelta(hours=0)
    assert got.hour == 2  # 北京 10:00 → UTC 02:00


def test_parse_ts_iso_fallback_and_failure():
    assert parse_ts("2026-08-27T02:00:00Z", None, 0) is not None
    assert parse_ts("not-a-date", ["%Y-%m-%d"], 0) is None
    assert parse_ts(None, None, 0) is None


# ---- strip_html ----


def test_strip_html_tags_and_entities():
    assert strip_html("<em>货币</em>政策&nbsp;&amp; 利率") == "货币 政策 & 利率"


# ---- entries_to_drafts ----


def test_entries_to_drafts_window_and_mapping():
    now = datetime.now(UTC)
    inner = now + timedelta(hours=8)  # 北京时间表示
    items = [
        {
            "id": "a1",
            "rich_text": "<p>央行开展逆回购操作</p>",
            "create_time": inner.strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "id": "old",
            "rich_text": "窗口外旧闻",
            "create_time": "2020-01-01 10:00:00",
        },
        {"id": "nodate", "rich_text": "无 PIT 锚丢弃", "create_time": None},
    ]
    since, until = now - timedelta(hours=1), now + timedelta(hours=1)
    drafts = _adapter().entries_to_drafts(items, since, until)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.external_id == "a1"
    assert d.title == "央行开展逆回购操作" and d.body == d.title


def test_entries_to_drafts_fallback_external_id_and_url_template():
    now = datetime.now(UTC)
    items = [
        {
            "target": {
                "id": "123",
                "title": "热点问题",
                "excerpt": "详情摘要",
                "created": int(now.timestamp()),
            }
        }
    ]
    ad = _adapter(
        items_path="data",
        external_id_path="target.id",
        title_path="target.title",
        body_path="target.excerpt",
        published_path="target.created",
        url_template="https://www.zhihu.com/question/{external_id}",
    )
    drafts = ad.entries_to_drafts(items, now - timedelta(minutes=1), now + timedelta(minutes=1))
    assert len(drafts) == 1
    assert drafts[0].external_id == "123"
    assert drafts[0].url == "https://www.zhihu.com/question/123"


def test_entries_to_drafts_short_body_falls_back_title():
    now = datetime.now(UTC)
    item = {
        "id": "s1",
        "title": "标题即正文内容足够长",
        "summary": "短",
        "showTime": int(now.timestamp() * 1000),
    }
    ad = _adapter(
        title_path="title",
        body_path="summary",
        published_path="showTime",
    )
    drafts = ad.entries_to_drafts([item], now - timedelta(minutes=1), now + timedelta(minutes=1))
    assert drafts[0].body == "标题即正文内容足够长"


# ---- registry 分发与 enabled 开关 ----


def _spec(source_id, kind, enabled=True, **params):
    spec = {
        "source_id": source_id,
        "adapter": kind,
        "tier": "L3",
        "language": "zh",
        "rate_limit_rpm": 60,
        "enabled": enabled,
        "params": params,
    }
    return spec


def test_registry_dispatches_json_api():
    cfg = {
        "sources": [
            _spec(
                "s1",
                "json_api",
                url="https://x",
                items_path="d",
                title_path="t",
                published_path="ts",
            )
        ]
    }
    adapters = build_registry(cfg).all()
    assert len(adapters) == 1 and type(adapters[0]).__name__ == "JsonApiAdapter"


def test_registry_skips_disabled_sources():
    cfg = {
        "sources": [
            _spec("on", "json_api", url="https://x", items_path="d"),
            _spec("off", "json_api", enabled=False, url="https://x", items_path="d"),
            _spec("off2", "reddit_cdp", enabled=False, subreddits=["a"]),
        ]
    }
    reg = build_registry(cfg)
    assert [a.source_id for a in reg.all()] == ["on"]
    with pytest.raises(ValueError, match="未注册"):
        reg.get("off")
