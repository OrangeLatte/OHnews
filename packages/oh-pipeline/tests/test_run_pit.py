"""全链编排 + PIT 审计：as_of 之后的数据不得影响同 as_of 的 NDI。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_contracts.enums import SourceTier
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord, EventRecord
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

AS_OF = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
DAY = AS_OF.date()
TIER_MAP = {
    "gov": SourceTier.OFFICIAL,
    "wscn": SourceTier.FINANCIAL_PRESS,
}

LOSS_BODY = "美联储：衰退风险上升，市场损失惨重，裁员与失业压力加剧，经济萎缩恶化"
GAIN_BODY = "美联储：增长复苏迹象明显，收益上涨改善，机遇反弹提振，扩张盈利走强"


def _bronze(source: str, body: str, ts: datetime, idx: int) -> BronzeRecord:
    external_id = f"{source}-{idx}"
    return BronzeRecord(
        source_id=source,
        item_key=make_item_key(source, external_id, ts),
        external_id=external_id,
        url_hash="u:test",
        content_hash="c:test",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={"title": body[:20], "body": body},
    )


def _seed(bronze: ParquetBronzeWriter, store: SqliteStore) -> None:
    store.upsert_event(
        EventRecord(
            event_id="E01",
            title="央行决议",
            entities=["fed"],
            as_of=AS_OF,
        )
    )
    bronze.write([_bronze("gov", LOSS_BODY, AS_OF - timedelta(hours=1), i) for i in range(12)])
    bronze.write(
        [_bronze("wscn", GAIN_BODY, AS_OF - timedelta(hours=2), 100 + i) for i in range(12)]
    )


def test_full_chain_and_pit(tmp_path: Path) -> None:
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    _seed(bronze, store)

    report = run_pipeline(
        bronze,
        store,
        store,
        [EventRecord(event_id="E01", title="t", entities=["fed"], as_of=AS_OF)],
        TIER_MAP,
        as_of=AS_OF,
        lookback_days=1,
        min_per_source=10,
    )
    assert report.rows_written == 24
    assert report.ndi_ok == 1
    assert report.temperature_gaps["E01"] is not None and report.temperature_gaps["E01"] > 1.0

    series = store.ndi_series("E01")
    assert len(series) == 1
    first = series[0]
    assert first.status == "ok" and first.ndi is not None and first.ndi > 0.7

    # --- PIT 审计：as_of 之后到达的反转文章不得影响同 as_of 的 NDI ---
    bronze.write(
        [_bronze("wscn", LOSS_BODY, AS_OF + timedelta(hours=1), 200 + i) for i in range(12)]
    )
    report2 = run_pipeline(
        bronze,
        store,
        store,
        [EventRecord(event_id="E01", title="t", entities=["fed"], as_of=AS_OF)],
        TIER_MAP,
        as_of=AS_OF,
        lookback_days=1,
        min_per_source=10,
    )
    assert report2.rows_written == 0  # 未来文章被窗口过滤，不产 stance 行
    after = store.ndi_series("E01")
    assert len(after) == 1  # INSERT OR REPLACE 覆盖同点位
    assert after[0].ndi == first.ndi  # PIT：数值不变

    # --- 幂等：同窗口重跑不新增行 ---
    report3 = run_pipeline(
        bronze,
        store,
        store,
        [EventRecord(event_id="E01", title="t", entities=["fed"], as_of=AS_OF)],
        TIER_MAP,
        as_of=AS_OF,
        lookback_days=1,
        min_per_source=10,
    )
    assert report3.rows_written == 0


def test_asof_uses_only_prior_data(tmp_path: Path) -> None:
    """as_of 推进前只有部分数据时，NDI 用截面正确弃权/计算。"""
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    early = AS_OF - timedelta(days=3)
    store.upsert_event(EventRecord(event_id="E01", title="t", entities=["fed"], as_of=early))
    bronze.write([_bronze("gov", LOSS_BODY, early - timedelta(hours=1), i) for i in range(12)])
    report = run_pipeline(
        bronze,
        store,
        store,
        [EventRecord(event_id="E01", title="t", entities=["fed"], as_of=early)],
        TIER_MAP,
        as_of=early,
        lookback_days=1,
        min_per_source=10,
    )
    # 只有官方簇合格 → NDI 弃权（诚实语义）
    assert report.ndi_abstain == 1 and report.ndi_ok == 0
