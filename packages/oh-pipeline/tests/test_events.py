"""事件生成器：实体×日窗聚合规则 / 合格门 / 幂等 / 边界。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord
from oh_pipeline.events import EventBuilder

DAY = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


def _rec(
    source: str,
    idx: int,
    title: str,
    body: str = "",
    ts: datetime | None = None,
) -> BronzeRecord:
    published = ts or DAY + timedelta(minutes=idx)
    return BronzeRecord(
        source_id=source,
        item_key=make_item_key(source, f"{source}-{idx}", published),
        external_id=f"{source}-{idx}",
        url_hash="u:t",
        content_hash="c:t",
        fetched_at=published,
        published_at=published,
        raw={},
        normalized={"title": title, "body": body},
    )


def test_aggregates_entity_day_window() -> None:
    records = [
        _rec("gov", i, f"美联储声明 {i}", "关税制裁争端风险") for i in range(3)
    ] + [
        _rec("wscn", 100 + i, f"市场解读美联储 {i}", "衰退风险与损失") for i in range(2)
    ]
    built = EventBuilder().build(records)
    assert len(built) == 1
    b = built[0]
    assert b.event.event_id == "ev-fed-20260826"
    assert b.event.entities == ["fed"]
    assert b.n_articles == 5
    assert b.n_sources == 2
    assert b.event.title == "美联储声明 0"  # 最早文章标题（确定性）
    assert b.event.as_of.date() == DAY.date()


def test_below_min_articles_no_event() -> None:
    records = [_rec("gov", i, f"美联储 {i}") for i in range(2)]
    assert EventBuilder().build(records, min_articles=3) == []


def test_below_min_sources_no_event() -> None:
    records = [_rec("gov", i, f"美联储 {i}") for i in range(5)]
    assert EventBuilder().build(records, min_sources=2) == []


def test_idempotent_event_id() -> None:
    records = [_rec("gov", i, f"美联储 {i}", "关税") for i in range(3)]
    records += [_rec("wscn", 10 + i, f"美联储 {i}", "关税") for i in range(2)]
    a = EventBuilder().build(records)
    b = EventBuilder().build(list(reversed(records)))
    assert [x.event.event_id for x in a] == [x.event.event_id for x in b]


def test_missing_pit_anchor_skipped() -> None:
    rec = _rec("gov", 0, "美联储声明")
    rec = rec.model_copy(update={"published_at": None})
    assert EventBuilder().build([rec] * 5) == []


def test_days_split_into_separate_events() -> None:
    next_day = DAY + timedelta(days=1)
    records = [_rec("gov", i, "美联储", "关税") for i in range(3)]
    records += [_rec("wscn", 10 + i, "美联储", "关税") for i in range(3)]
    records += [
        _rec("gov", 100 + i, "美联储", "关税", ts=next_day) for i in range(3)
    ]
    records += [
        _rec("wscn", 200 + i, "美联储", "关税", ts=next_day) for i in range(3)
    ]
    built = EventBuilder().build(records)
    ids = {b.event.event_id for b in built}
    assert ids == {"ev-fed-20260826", "ev-fed-20260827"}


def test_multi_entity_articles_counted_per_entity() -> None:
    records = [
        _rec("gov", i, "美联储与特朗普在关税问题上冲突", "制裁争端") for i in range(3)
    ]
    records += [
        _rec("wscn", 10 + i, "市场关注美联储与特朗普", "关税摩擦") for i in range(2)
    ]
    built = EventBuilder().build(records)
    entities = {b.event.entities[0] for b in built}
    assert entities == {"fed", "trump"}
    assert all(b.n_articles == 5 for b in built)


def test_output_deterministic_order() -> None:
    records = [_rec("gov", i, "美联储", "关税") for i in range(3)]
    records += [_rec("wscn", 10 + i, "美联储", "关税") for i in range(2)]
    records += [
        _rec("gov", 50 + i, "欧洲央行", "关税") for i in range(3)
    ]
    records += [_rec("wscn", 60 + i, "欧洲央行", "关税") for i in range(2)]
    built = EventBuilder().build(records)
    keys = [(b.event.as_of, b.event.entities[0]) for b in built]
    assert keys == sorted(keys)
