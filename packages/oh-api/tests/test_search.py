"""全局搜索测试：search_bronze 纯函数 + build_router 挂载冒烟（内存记录，无 IO）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from oh_api.search import build_router, search_bronze
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord

NOW = datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def _rec(
    source_id: str,
    external_id: str,
    *,
    title: str = "",
    body: str = "",
    published_at: datetime | None = NOW,
) -> BronzeRecord:
    ts = published_at or NOW
    return BronzeRecord(
        source_id=source_id,
        item_key=make_item_key(source_id, external_id, ts),
        external_id=external_id,
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=published_at,
        raw={},
        normalized={
            "title": title,
            "body": body,
            "url": f"https://example.com/{external_id}",
        },
    )


def test_title_hit_ranks_before_body_hit() -> None:
    """title 命中优先于 body 命中，同 rank 内 published_at 降序。"""
    recs = [
        _rec("gov", "b-new", title="市场综述", body="美联储暗示宽松", published_at=NOW),
        _rec(
            "gov",
            "t-old",
            title="美联储宣布利率决议",
            body="",
            published_at=NOW - timedelta(days=3),
        ),
        _rec(
            "gov",
            "b-old",
            title="市场综述",
            body="美联储暗示宽松",
            published_at=NOW - timedelta(days=1),
        ),
    ]
    out = search_bronze(recs, "美联储")
    assert [r["item_key"] for r in out] == [
        recs[1].item_key,  # title 命中唯一
        recs[0].item_key,  # body 命中，更新
        recs[2].item_key,
    ]


def test_limit_truncates() -> None:
    recs = [_rec("gov", f"k{i}", body=f"第{i}条提到美联储政策") for i in range(5)]
    out = search_bronze(recs, "美联储", limit=3)
    assert len(out) == 3


def test_short_or_blank_q_returns_empty() -> None:
    recs = [_rec("gov", "k", title="美联储决议")]
    assert search_bronze(recs, "") == []
    assert search_bronze(recs, "   ") == []
    assert search_bronze(recs, "美") == []
    assert search_bronze(recs, "f") == []


def test_case_insensitive_matching() -> None:
    recs = [_rec("wscn", "en", title="", body="Fed Signals Rate Path Shift")]
    out = search_bronze(recs, "fed")
    assert len(out) == 1
    assert out[0]["title"] == ""  # title 未命中 → 空
    assert "Fed Signals" in out[0]["snippet"]  # snippet 保留原大小写
    assert search_bronze(recs, "FED") == search_bronze(recs, "fed")


def test_snippet_window_and_word_boundary() -> None:
    """snippet=命中词前后各 60 字符；不截断词，优先句号边界。"""
    filler = "前" * 80
    tail = "后" * 80
    recs = [
        _rec("gov", "zh", body=f"{filler}。随后市场波动明显，投资者转向避险。{tail}"),
    ]
    out = search_bronze(recs, "市场波动")
    assert len(out) == 1
    snip = out[0]["snippet"].strip("…")
    # 左边界取到句号之后：完整词组与句末标点保留
    assert snip.startswith("随后")
    assert snip.endswith("。")
    assert "市场波动明显" in snip
    assert len(snip) <= 60 + len("市场波动") + 60
    # 尾部长填充被截断标注
    assert out[0]["snippet"].endswith("…")


def test_snippet_from_title_when_title_hit() -> None:
    recs = [_rec("gov", "t", title="美联储按兵不动", body="无关正文内容")]
    out = search_bronze(recs, "美联储")
    assert out[0]["snippet"].startswith("美联储")


def test_published_at_none_sorts_last_and_iso() -> None:
    recs = [
        _rec("gov", "none", body="美联储会议纪要", published_at=None),
        _rec("gov", "dated", body="美联储会议纪要", published_at=NOW),
    ]
    out = search_bronze(recs, "美联储")
    assert [r["item_key"] for r in out] == [recs[1].item_key, recs[0].item_key]
    assert out[0]["published_at"] == NOW.isoformat()
    assert out[1]["published_at"] is None


def test_no_hit_and_url_passthrough() -> None:
    recs = [_rec("gov", "k1", title="就业报告", body="非农超预期")]
    assert search_bronze(recs, "美联储") == []
    out = search_bronze(recs, "非农")
    assert out[0]["url"] == "https://example.com/k1"
    assert out[0]["source_id"] == "gov"


def test_router_mounted() -> None:
    """build_router 挂到临时 FastAPI：200/422/空 q 语义齐全。"""
    recs = [_rec("gov", "k1", title="美联储决议", body="利率维持不变")]
    app = FastAPI()
    app.include_router(build_router(lambda: iter(recs)))
    client = TestClient(app)

    r = client.get("/api/search", params={"q": "美联储"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["item_key"] == recs[0].item_key
    assert data[0]["url"] == "https://example.com/k1"
    assert data[0]["published_at"] == NOW.isoformat()

    # q 必填 + limit 值域校验
    assert client.get("/api/search", params={"limit": 5}).status_code == 422
    assert client.get("/api/search", params={"q": "美联储", "limit": 51}).status_code == 422
    assert client.get("/api/search", params={"q": "美联储", "limit": 0}).status_code == 422

    # 短 q 空结果、无命中空列表
    assert client.get("/api/search", params={"q": "美"}).json() == []
    assert client.get("/api/search", params={"q": "不存在的词"}).json() == []


def test_multi_term_and_semantics() -> None:
    """T5 分词 AND：两词分别命中才算；只命中一词不算。"""
    recs = [
        _rec("s1", "both", title="美联储发布利率决议", body="声明全文"),
        _rec("s1", "only-one", title="美联储例行会议", body="无关正文"),
    ]
    out = search_bronze(recs, "美联储 利率")
    assert len(out) == 1
    assert out[0]["item_key"].startswith("s1:both")


def test_alias_boost_and_url_dedupe() -> None:
    """T5 别名提升排序；相同 URL 去重保留最前一条。"""
    old = NOW - timedelta(days=2)
    recs = [
        # 同 URL 重复：别名命中但更旧 vs 新且无别名
        _rec("s1", "dup-old", title="美联储 outlook", body="x", published_at=old),
        _rec("s2", "dup-new", title="议息决议发布", body="美联储相关表态", published_at=NOW),
        # 让两条 URL 相同
    ]
    recs[1].normalized["url"] = recs[0].normalized["url"]  # type: ignore[index]
    out = search_bronze(recs, "美联储", boost_terms=["fed", "美联储"])
    assert len(out) == 1  # 去重
    assert out[0]["source_id"] == "s1"  # 别名提升的旧记录胜出
    plain = search_bronze(recs, "美联储")
    assert plain[0]["source_id"] == "s1"  # 无提升时 title 命中仍优先（既有语义）


def test_search_events_kind_and_router_merge() -> None:
    """T5 事件分类：events_fn 提供时 kind=event 前置，router 合并返回。"""
    from oh_contracts.schemas import EventRecord

    events = [
        EventRecord(
            event_id="ev-fed-20260828",
            title="美联储利率决议",
            summary="声明",
            entities=["fed"],
            as_of=NOW,
        )
    ]
    recs = [_rec("s1", "a1", title="美联储相关报道", body="")]
    app = FastAPI()
    app.include_router(
        build_router(
            lambda: iter(recs),
            events_fn=lambda: events,
            alias_fn=lambda: ["fed", "美联储"],
        )
    )
    client = TestClient(app)
    out = client.get("/api/search", params={"q": "美联储"}).json()
    assert out[0]["kind"] == "event" and out[0]["id"] == "ev-fed-20260828"
    assert out[1]["kind"] == "article"
