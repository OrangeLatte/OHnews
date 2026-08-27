"""Within-language NDI（裁决 F）：lang_map 过滤后逐语言独立计算。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_contracts.enums import ExtractionEngine, FrameLabel, SourceTier, StanceLabel
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord, EventRecord, StanceRow
from oh_pipeline.divergence import ndi_for_event, temperature_gap
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

AS_OF = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
TIER_MAP = {
    "gov_zh": SourceTier.OFFICIAL,
    "wscn": SourceTier.FINANCIAL_PRESS,
    "gov_en": SourceTier.OFFICIAL,
    "bbc": SourceTier.WIRE,
}
LANG_MAP = {"gov_zh": "zh", "wscn": "zh", "gov_en": "en", "bbc": "en"}

LOSS = "美联储：衰退风险上升，损失惨重"
GAIN = "美联储：增长复苏，收益上涨"


def _stance(source: str, frame: FrameLabel, ts: datetime, idx: int) -> StanceRow:
    external_id = f"{source}-{idx}"
    return StanceRow(
        event_id="E01",
        source_id=source,
        entity_id="fed",
        frame=frame,
        stance=StanceLabel.NEUTRAL,
        confidence=0.9,
        engine=ExtractionEngine.RULE,
        item_key=make_item_key(source, external_id, ts),
        ts=ts,
    )


def test_within_language_filters_sources() -> None:
    """lang_map+language=zh 时 en 源不参与；n_sources 只算该语言。"""
    t0 = AS_OF - timedelta(hours=1)
    rows = [_stance("gov_zh", FrameLabel.LOSS, t0, i) for i in range(6)]
    rows += [_stance("wscn", FrameLabel.GAIN, t0, 100 + i) for i in range(6)]
    rows += [_stance("gov_en", FrameLabel.CONFLICT, t0, 200 + i) for i in range(6)]

    point_zh = ndi_for_event(
        rows, TIER_MAP, AS_OF, min_per_source=2, lang_map=LANG_MAP, language="zh"
    )
    point_all = ndi_for_event(rows, TIER_MAP, AS_OF, min_per_source=2, language="all")
    assert point_zh.language == "zh"
    assert point_all.language == "all"
    # zh 簇只含 2 个有效源（gov_en 被过滤）
    assert point_zh.n_sources == 2
    assert point_all.n_sources == 3
    assert point_zh.status == "ok" and point_zh.ndi is not None

    gap_zh = temperature_gap(rows, TIER_MAP, min_per_source=2, lang_map=LANG_MAP, language="zh")
    gap_all = temperature_gap(rows, TIER_MAP, min_per_source=2, language="all")
    assert gap_zh is not None and gap_all is not None
    # 过滤生效的直接证据：zh 官方簇纯 loss、all 官方簇混入 en 的 conflict → NDI 不同
    assert point_zh.ndi != point_all.ndi


def test_run_pipeline_per_language_points(tmp_path: Path) -> None:
    """run_pipeline 逐语言出点：E01@zh 与 E01@en 独立键，en 弃权落库。"""
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    store.upsert_event(EventRecord(event_id="E01", title="t", entities=["fed"], as_of=AS_OF))
    t0 = AS_OF - timedelta(hours=1)
    bronze.write([_bronze("gov_zh", LOSS, t0, i) for i in range(6)])
    bronze.write([_bronze("wscn", GAIN, t0, 100 + i) for i in range(6)])

    report = run_pipeline(
        bronze,
        store,
        store,
        [EventRecord(event_id="E01", title="t", entities=["fed"], as_of=AS_OF)],
        TIER_MAP,
        as_of=AS_OF,
        lookback_days=1,
        min_per_source=2,
        lang_map=LANG_MAP,
        languages=("zh", "en"),
    )
    assert "E01@zh" in report.temperature_gaps
    assert "E01@en" in report.temperature_gaps
    series_zh = store.ndi_series("E01", language="zh")
    series_en = store.ndi_series("E01", language="en")
    assert len(series_zh) == 1 and len(series_en) == 1
    # en 簇无行 → NDI 弃权
    assert series_zh[0].status == "ok" and series_zh[0].ndi is not None
    assert series_en[0].status == "abstain" and series_en[0].ndi is None


def _bronze(source: str, body: str, ts: datetime, idx: int) -> BronzeRecord:
    external_id = f"{source}-{idx}"
    return BronzeRecord(
        source_id=source,
        item_key=make_item_key(source, external_id, ts),
        external_id=external_id,
        url_hash="u:t",
        content_hash="c:t",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={"title": body[:12], "body": body},
    )
