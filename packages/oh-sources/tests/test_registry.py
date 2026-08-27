"""CollectorRegistry / build_registry 测试（gdelt/fred 分支在 test_gdelt/test_fred 覆盖构造）。"""

import pytest
from oh_contracts.enums import SourceTier
from oh_contracts.schemas import SourceMeta
from oh_sources.registry import CollectorRegistry, build_registry
from oh_sources.rss import RssAdapter

CONFIG = {
    "sources": [
        {
            "source_id": "rss_a",
            "adapter": "rss",
            "tier": "L2",
            "language": "zh",
            "credibility_prior": 0.8,
            "bias": "state_media",
            "rate_limit_rpm": 12,
            "params": {"url": "http://example.com/a.xml"},
        },
        {
            "source_id": "rss_b",
            "adapter": "rss",
            "tier": "L3",
            "params": {"url": "http://example.com/b.xml"},
        },
    ]
}


def test_build_registry_defaults():
    registry = build_registry(CONFIG)
    assert len(registry.all()) == 2
    a = registry.get("rss_a")
    assert a.meta.tier == SourceTier.WIRE
    assert a.meta.rate_limit_rpm == 12
    b = registry.get("rss_b")
    assert b.meta.credibility_prior == 0.7
    assert b.meta.language == "zh"


def test_build_registry_unknown_kind():
    with pytest.raises(ValueError, match="未知适配器类型"):
        build_registry(
            {"sources": [{"source_id": "x", "adapter": "weibo", "tier": "L4", "params": {}}]}
        )


def test_register_duplicate_rejected():
    registry = CollectorRegistry()
    adapter = RssAdapter(
        SourceMeta(source_id="dup", language="zh", tier=SourceTier.WIRE, credibility_prior=0.5),
        url="http://example.com/d.xml",
    )
    registry.register(adapter)
    with pytest.raises(ValueError, match="重复注册"):
        registry.register(adapter)


def _spec(source_id: str, **extra) -> dict:
    spec = {
        "source_id": source_id,
        "adapter": "rss",
        "tier": "L3",
        "rate_limit_rpm": 30,
        "params": {"url": f"http://example.com/{source_id}.xml"},
    }
    spec.update(extra)
    return spec


def test_fallbacks_reference_inline_and_disabled():
    """备用链解析：引用源 / 内联 spec / 禁用引用跳过（降级不报错）。"""
    cfg = {
        "sources": [
            _spec(
                "a",
                fallbacks=[
                    "b",
                    {
                        "source_id": "c_inline",
                        "adapter": "rss",
                        "tier": "L4",
                        "params": {"url": "http://example.com/c.xml"},
                    },
                    "dead_ref",
                ],
            ),
            _spec("b"),
            _spec("dead_ref", enabled=False),
        ]
    }
    reg = build_registry(cfg)
    assert [f.source_id for f in reg.fallbacks("a")] == ["b", "c_inline"]
    assert reg.fallbacks("b") == []
    assert reg.fallbacks("不存在") == []


def test_registry_passthrough_window_proxy_and_date_fallback():
    cfg = {
        "sources": [
            _spec(
                "a",
                params={
                    "url": "http://example.com/a.xml",
                    "window_days": 30,
                    "proxy_url": "http://127.0.0.1:9674",
                    "date_fallback": True,
                },
            )
        ]
    }
    ad = build_registry(cfg).get("a")
    assert ad.window_days == 30
    assert ad.proxy_url == "http://127.0.0.1:9674"
    assert ad._date_fallback is True
