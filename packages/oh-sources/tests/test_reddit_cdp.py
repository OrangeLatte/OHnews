"""RedditCdpAdapter 单测（离线：cookies 门禁/条目解析/注册分发）。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from oh_sources.reddit_cdp import DEFAULT_COOKIES_FILE, RedditCdpAdapter
from oh_sources.registry import build_registry


def _meta():
    from oh_contracts.enums import SourceTier
    from oh_contracts.schemas import SourceMeta

    return SourceMeta(
        source_id="reddit_cdp",
        language="en",
        tier=SourceTier.SOCIAL,
        credibility_prior=0.4,
        bias="social_media",
        rate_limit_rpm=60,
        needs_browser=True,
        paywall=False,
    )


def _adapter(tmp_path, cookies=True):
    cf = str(tmp_path / "reddit.json")
    if cookies:
        (tmp_path / "reddit.json").write_text(
            json.dumps(
                [
                    {"name": "token", "value": "v1", "domain": ".reddit.com"},
                    {"name": "other", "value": "x", "domain": ".example.com"},
                ]
            )
        )
    return RedditCdpAdapter(_meta(), subreddits=["Economics"], cookies_file=cf, limit=25)


def test_missing_cookies_fails_fast_with_hint(tmp_path):
    with pytest.raises(ValueError, match="export_reddit_cookies"):
        _adapter(tmp_path, cookies=False)._cookie_header()


def test_cookie_header_filters_reddit_domain(tmp_path):
    header = _adapter(tmp_path)._cookie_header()
    assert header == "token=v1"


def test_parse_entries_mapping_and_window(tmp_path):
    now = datetime.now(UTC)
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "abc123",
                        "title": "Fed holds rates steady",
                        "selftext": "Discussion body text",
                        "permalink": "/r/Economics/comments/abc123/",
                        "created_utc": now.timestamp(),
                    }
                },
                {
                    "data": {
                        "id": "old1",
                        "title": "Old post",
                        "created_utc": (now - timedelta(days=30)).timestamp(),
                    }
                },
            ]
        }
    }
    ad = _adapter(tmp_path)
    drafts = ad.parse_entries(
        payload, "Economics", now - timedelta(hours=1), now + timedelta(hours=1)
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert d.external_id == "Economics:abc123"
    assert d.url == "https://www.reddit.com/r/Economics/comments/abc123/"
    assert d.article_type.value == "opinion"


def test_default_cookies_file_constant():
    assert DEFAULT_COOKIES_FILE == ".opencode/cookies/reddit.json"


def test_registry_dispatches_reddit_cdp():
    cfg = {
        "sources": [
            {
                "source_id": "r1",
                "adapter": "reddit_cdp",
                "tier": "L4",
                "language": "en",
                "rate_limit_rpm": 60,
                "params": {"subreddits": ["Economics"]},
            }
        ]
    }
    adapters = build_registry(cfg).all()
    assert len(adapters) == 1 and type(adapters[0]).__name__ == "RedditCdpAdapter"
