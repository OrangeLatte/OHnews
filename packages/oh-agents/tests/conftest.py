"""oh-agents 测试共用 helper（合成极化事件：官方 LOSS vs 市场 GAIN）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oh_contracts.enums import SourceTier
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord, EventRecord
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.sqlite_store import SqliteStore

LOSS_BODY = "美联储：衰退风险上升，市场损失惨重，裁员与失业压力加剧"
GAIN_BODY = "美联储：增长复苏迹象明显，收益上涨改善，机遇反弹提振"
TIER_MAP = {
    "gov": SourceTier.OFFICIAL,
    "wscn": SourceTier.FINANCIAL_PRESS,
}


def make_now() -> datetime:
    return datetime(2026, 8, 28, 18, 0, tzinfo=UTC)


def seed_event(
    bronze: ParquetBronzeWriter,
    store: SqliteStore,
    event_id: str,
    now: datetime,
    *,
    future_rows: bool = False,
) -> EventRecord:
    """写入 1 事件 + 24 篇极化文章；future_rows 追加 as_of 之后的反转文章。"""
    event = EventRecord(event_id=event_id, title=f"事件{event_id}", entities=["fed"], as_of=now)
    store.upsert_event(event)
    recs: list[BronzeRecord] = []
    for i in range(12):
        ts = now - timedelta(hours=1)
        recs.append(
            BronzeRecord(
                source_id="gov",
                item_key=make_item_key("gov", f"{event_id}-g{i}", ts),
                external_id=f"{event_id}-g{i}",
                url_hash="u",
                content_hash="c",
                fetched_at=ts,
                published_at=ts,
                raw={},
                normalized={"body": LOSS_BODY},
            )
        )
    for i in range(12):
        ts = now - timedelta(hours=2)
        recs.append(
            BronzeRecord(
                source_id="wscn",
                item_key=make_item_key("wscn", f"{event_id}-w{i}", ts),
                external_id=f"{event_id}-w{i}",
                url_hash="u",
                content_hash="c",
                fetched_at=ts,
                published_at=ts,
                raw={},
                normalized={"body": GAIN_BODY},
            )
        )
    if future_rows:
        for i in range(12):
            ts = now + timedelta(hours=1)
            recs.append(
                BronzeRecord(
                    source_id="wscn",
                    item_key=make_item_key("wscn", f"{event_id}-f{i}", ts),
                    external_id=f"{event_id}-f{i}",
                    url_hash="u",
                    content_hash="c",
                    fetched_at=ts,
                    published_at=ts,
                    raw={},
                    normalized={"body": LOSS_BODY},
                )
            )
    bronze.write(recs)
    return event
