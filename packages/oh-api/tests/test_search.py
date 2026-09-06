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


def test_latin_query_uses_word_boundaries() -> None:
    """实体短词不能误召回同前缀的普通英文单词。"""
    recs = [
        _rec("s1", "fed", title="Fed signals a policy shift"),
        _rec("s1", "federal", title="Federal Register publishes a notice"),
        _rec("s1", "federer", title="Federer enters the hall of fame"),
    ]
    out = search_bronze(recs, "Fed")
    assert [row["item_key"] for row in out] == [recs[0].item_key]


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
    assert out[0]["entity"] == "fed"  # P1-A：事件携带主实体供前端跳时间线
    assert out[1]["kind"] == "article"


def test_event_without_entity_returns_none() -> None:
    """P1-A：无实体事件诚实回 entity=None，不造假不裸跳依据。"""
    from oh_api.search import search_events
    from oh_contracts.schemas import EventRecord

    events = [EventRecord(event_id="ev-x", title="美联储纪要", summary="", entities=[], as_of=NOW)]
    assert search_events(events, "美联储")[0]["entity"] is None


def test_entity_search_by_id_and_alias() -> None:
    """实体：entity_id 或任一别名 casefold 子串命中；未命中空列表。"""
    from oh_api.search import search_entities

    entities = [
        {"entity_id": "fed", "aliases": ("美联储", "Federal Reserve")},
        {"entity_id": "pboc", "aliases": ("中国人民银行",)},
        {"entity_id": "ecb", "aliases": ()},
    ]
    assert search_entities(entities, "不存在的词") == []
    assert [r["id"] for r in search_entities(entities, "美联储")] == ["fed"]
    assert [r["id"] for r in search_entities(entities, "FED")] == ["fed"]  # casefold
    assert [r["id"] for r in search_entities(entities, "人民银行")] == ["pboc"]  # 别名子串
    # entity_id 命中；空别名时 title 降级为 entity_id
    row = search_entities(entities, "ecb")[0]
    assert row["kind"] == "entity" and row["id"] == "ecb" and row["title"] == "ecb"
    hit = search_entities(entities, "联储")[0]
    assert hit["title"] == "美联储" and hit["snippet"] == "entity"
    # 短 q / limit<=0 拦截
    assert search_entities(entities, "联") == []
    assert search_entities(entities, "美联储", limit=0) == []


def test_case_and_monitor_search_hit_miss() -> None:
    """案例/监测器子串检索：title/question/id/target_ref 命中，未命中空列表。"""
    from oh_api.search import search_cases, search_monitors

    cases = [
        {
            "case_id": "case-1",
            "title": "利率路径研究",
            "question": "美联储加息影响？",
            "status": "open",
        },
        {"case_id": "case-2", "title": "", "question": "非农数据解读", "status": "closed"},
    ]
    out = search_cases(cases, "利率")
    assert [r["id"] for r in out] == ["case-1"]
    assert out[0]["kind"] == "case" and out[0]["title"] == "利率路径研究"
    assert out[0]["snippet"] == "美联储加息影响？" and out[0]["status"] == "open"
    assert [r["id"] for r in search_cases(cases, "case-2")] == ["case-2"]  # case_id 命中
    no_title = search_cases(cases, "非农")[0]
    assert no_title["title"] == "非农数据解读"  # 空标题降级 question
    assert search_cases(cases, "不存在的词") == []

    monitors = [
        {
            "monitor_id": "mon-1",
            "question": "监测美联储表态",
            "target_ref": "entity:fed",
            "status": "active",
        },
        {
            "monitor_id": "mon-2",
            "question": "监测非农数据",
            "target_ref": "topic:jobs",
            "status": "paused",
        },
    ]
    mout = search_monitors(monitors, "美联储")
    assert [r["id"] for r in mout] == ["mon-1"]
    assert mout[0]["kind"] == "monitor" and mout[0]["title"] == "监测美联储表态"
    assert mout[0]["snippet"] == "entity:fed" and mout[0]["status"] == "active"
    assert [r["id"] for r in search_monitors(monitors, "topic:jobs")] == ["mon-2"]
    assert search_monitors(monitors, "不存在的词") == []


def test_router_five_kinds_order_and_limits() -> None:
    """P1-A 合并语义：entity/case/monitor/event 前置各限 2（累计扣减）+ 文章填满。"""
    from oh_contracts.schemas import EventRecord

    entities = [
        {"entity_id": "fed", "aliases": ("美联储",)},
        {"entity_id": "fed2", "aliases": ("美联储二号",)},
    ]
    cases = [
        {"case_id": "case-a", "title": "", "question": "美联储问题1", "status": "open"},
        {"case_id": "case-b", "title": "", "question": "美联储问题2", "status": "open"},
    ]
    monitors = [
        {
            "monitor_id": "mon-a",
            "question": "美联储监测1",
            "target_ref": "entity:fed",
            "status": "active",
        },
        {
            "monitor_id": "mon-b",
            "question": "美联储监测2",
            "target_ref": "entity:fed2",
            "status": "active",
        },
    ]
    events = [
        EventRecord(
            event_id=f"ev-{i}",
            title=f"美联储事件{i}",
            summary="",
            entities=["fed"],
            as_of=NOW - timedelta(minutes=i),
        )
        for i in range(3)
    ]
    recs = [_rec("s1", f"a{i}", title=f"美联储文章{i}") for i in range(5)]
    app = FastAPI()
    app.include_router(
        build_router(
            lambda: iter(recs),
            events_fn=lambda: events,
            cases_fn=lambda: cases,
            monitors_fn=lambda: monitors,
            entities_fn=lambda: entities,
        )
    )
    client = TestClient(app)

    out = client.get("/api/search", params={"q": "美联储", "limit": 10}).json()
    assert [r["kind"] for r in out] == [
        "entity",
        "entity",
        "case",
        "case",
        "monitor",
        "monitor",
        "event",
        "event",
        "article",
        "article",
    ]
    assert all(r.get("id") or r.get("item_key") for r in out)  # 全部携带稳定 ID

    # 边界：limit=5 → 对象类型累计扣减，event/article 诚实让位
    out5 = client.get("/api/search", params={"q": "美联储", "limit": 5}).json()
    assert [r["kind"] for r in out5] == ["entity", "entity", "case", "case", "monitor"]

    # 单类型注入（其余 fn 缺省）：既有 event→article 语义不回归
    app2 = FastAPI()
    app2.include_router(build_router(lambda: iter(recs), events_fn=lambda: events))
    out2 = TestClient(app2).get("/api/search", params={"q": "美联储", "limit": 4}).json()
    assert [r["kind"] for r in out2] == ["event", "event", "article", "article"]


def test_event_title_dedupe_and_router_total_limit() -> None:
    """重复事件只展示一次，limit 约束事件与文章合并后的总数。"""
    from oh_api.search import search_events
    from oh_contracts.schemas import EventRecord

    events = [
        EventRecord(
            event_id=f"ev-fed-{i}",
            title="Fed signals a policy shift" if i < 2 else f"Fed event {i}",
            summary="Fed update",
            entities=["fed"],
            as_of=NOW - timedelta(minutes=i),
        )
        for i in range(5)
    ]
    assert len(search_events(events, "Fed", limit=5)) == 4

    recs = [_rec("s1", f"article-{i}", title=f"Fed article {i}") for i in range(5)]
    app = FastAPI()
    app.include_router(build_router(lambda: iter(recs), events_fn=lambda: events))
    out = TestClient(app).get("/api/search", params={"q": "Fed", "limit": 3}).json()
    # P1-A：事件前置条目上限 2，剩余名额由文章填满（不再吃满整个 limit）
    assert [row["kind"] for row in out] == ["event", "event", "article"]
