"""Phase 0 门禁：10 个合成事件贯通 Bronze→Silver→Gold（docs/BLUEPRINT.md §13）。

验证五件事：
1. Bronze 分区 parquet 写入 + item_key 去重回读
2. Silver 事件 upsert + 立 stance 幂等追加（UNIQUE 约束）
3. PIT 查询：as_of/ts 截断正确（day2 00:00 截面只见 day1 事件）
4. Gold NDI 点位读写（含 abstain 语义：无 ndi 数值）
5. SQLite WAL 生效（裁决 D 连接工厂）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from oh_contracts.constants import CONF_TAU_RULE
from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    SourceTier,
    StanceLabel,
)
from oh_contracts.ids import content_hash, make_item_key, url_hash
from oh_contracts.schemas import BronzeRecord, EventRecord, NDIPoint, StanceRow
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

DAY1 = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
DAY2 = DAY1 + timedelta(days=1)
EVENT_IDS = [f"E{i:02d}" for i in range(1, 11)]

#: 三个合成信源（覆盖 L1/L3/L4 三层级）
SOURCES = {
    "pbc": ("zh", SourceTier.OFFICIAL, 0.95),
    "wscn": ("zh", SourceTier.FINANCIAL_PRESS, 0.75),
    "weibo": ("zh", SourceTier.SOCIAL, 0.40),
}


def _as_of(event_id: str) -> datetime:
    """E01-E06 落在 day1；E07-E10 落在 day2（DAY2 + 2h，保证 PIT 截面区分）。"""
    index = int(event_id[1:])
    return DAY1 if index <= 6 else DAY2 + timedelta(hours=2)


def _article_source(event_id: str) -> str:
    return "pbc" if int(event_id[1:]) % 2 == 1 else "wscn"


def _synthetic_world() -> tuple[list[EventRecord], list[StanceRow], list[BronzeRecord]]:
    events: list[EventRecord] = []
    stances: list[StanceRow] = []
    articles: list[BronzeRecord] = []

    for i, event_id in enumerate(EVENT_IDS, start=1):
        ts = _as_of(event_id)
        events.append(
            EventRecord(
                event_id=event_id,
                title=f"合成事件 {event_id}：央行公开市场操作",
                summary="Phase 0 sanity 合成数据，非真实新闻。",
                entities=["中国人民银行", "OMO"],
                as_of=ts,
                first_seen=ts,
            )
        )

        # 每事件 2 条 stance：pbc(wire, 0.95, rule) + wscn(analysis, 0.62, small_model)
        stances.append(
            StanceRow(
                event_id=event_id,
                source_id="pbc",
                entity_id="中国人民银行",
                frame=FrameLabel.GAIN,
                stance=StanceLabel.NEUTRAL,
                confidence=0.95,
                engine=ExtractionEngine.RULE,  # 0.95 >= CONF_TAU_RULE → 规则层
                item_key=make_item_key("pbc", f"stance-{i}", ts.isoformat()),
                ts=ts,
            )
        )
        stances.append(
            StanceRow(
                event_id=event_id,
                source_id="wscn",
                entity_id="中国人民银行",
                frame=FrameLabel.CONFLICT,
                stance=StanceLabel.CRITICAL,
                confidence=0.62,
                engine=ExtractionEngine.SMALL_MODEL,  # CONF_TAU_SMALL <= 0.62 < TAU_RULE
                item_key=make_item_key("wscn", f"stance-{i}", ts.isoformat()),
                ts=ts,
            )
        )

        # 每事件 1 篇 bronze 文章（奇偶轮换信源，制造多源分区）
        src = _article_source(event_id)
        body = f"{event_id} 合成正文：流动性净投放 {100 * i} 亿元。"
        articles.append(
            BronzeRecord(
                source_id=src,
                item_key=make_item_key(src, f"art-{i}", ts.isoformat()),
                external_id=f"art-{i}",
                url_hash=url_hash(f"https://{src}.example/{event_id}"),
                content_hash=content_hash(body),
                fetched_at=ts,
                published_at=ts,
                raw={"title": f"合成事件 {event_id}", "body": body, "article_type": "wire"},
            )
        )

    return events, stances, articles


@pytest.mark.sanity
def test_ten_events_bronze_silver_gold(tmp_path: Path) -> None:
    events, stances, articles = _synthetic_world()
    assert len(events) == 10 and len(stances) == 20 and len(articles) == 10

    conn = connect(tmp_path / "ohnews.db")
    store = SqliteStore(conn)
    bronze = ParquetBronzeWriter(tmp_path / "bronze")

    # 1. Bronze：分区写入 + 去重回读
    assert bronze.write(articles) == 10
    parquet_files = list((tmp_path / "bronze").glob("source=*/*/*/*.parquet"))
    assert len(parquet_files) == 4, "应为 2 源 × 2 日 = 4 个分区文件"
    back = list(bronze.iter_records())
    assert {r.item_key for r in back} == {a.item_key for a in articles}

    # 重复写入同批（幂等采集模拟）→ 回读仍 10 条（item_key 去重）
    bronze.write(articles)
    assert len(list(bronze.iter_records())) == 10

    # 2. Silver：事件 upsert + stance 幂等追加
    for event in events:
        store.upsert_event(event)
    assert store.count_events() == 10
    assert store.append_stances(stances) == 20
    assert store.append_stances(stances) == 0, "UNIQUE 约束下重复追加应零新增"
    assert store.count_stances() == 20

    # 3. PIT：DAY2 截面只见 day1 的 6 个事件（12 条 stance）
    day1_ids = {e.event_id for e in events if _as_of(e.event_id) <= DAY2}
    assert len(day1_ids) == 6
    pit_events = store.events_asof(DAY2)
    assert {e.event_id for e in pit_events} == day1_ids
    assert store.stances_asof(DAY2) and len(store.stances_asof(DAY2)) == 12

    # 截面推进到 day3 → 全量可见
    assert len(store.events_asof(DAY2 + timedelta(hours=23))) == 10

    # 4. Gold：NDI 点位（E10 追加一条 abstain）
    for event in events:
        store.append_ndi(
            NDIPoint(
                event_id=event.event_id,
                ts=_as_of(event.event_id),
                ndi=0.42,
                ci_low=0.30,
                ci_high=0.55,
                n_sources=2,
                status="ok",
            )
        )
    store.append_ndi(
        NDIPoint(
            event_id="E10",
            ts=DAY2 + timedelta(hours=12),
            ndi=None,
            ci_low=None,
            ci_high=None,
            n_sources=1,
            status="abstain",
        )
    )
    series = store.ndi_series("E10")
    assert [p.status for p in series] == ["ok", "abstain"]
    assert series[0].ndi == pytest.approx(0.42)
    assert series[1].ndi is None

    # 5. WAL 生效（裁决 D）
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    # 路由阈值 sanity：0.95 走规则层、0.62 走小模型
    assert stances[0].confidence >= CONF_TAU_RULE
    assert stances[1].confidence >= 0.5
    assert SOURCES["pbc"][1] is SourceTier.OFFICIAL
