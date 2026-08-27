"""FredSeriesAdapter 离线测试：_parse_csv 纯函数 + 快照语义。"""

from datetime import UTC, datetime

from oh_contracts.enums import SourceTier
from oh_contracts.schemas import SourceMeta
from oh_sources.fred import FredSeriesAdapter, _parse_csv

CSV_TEXT = "observation_date,DGS10\n2026-08-25,4.20\n2026-08-26,4.18\n2026-08-27,.\n"
META = SourceMeta(
    source_id="fred_test",
    language="en",
    tier=SourceTier.OFFICIAL,
    credibility_prior=0.95,
    rate_limit_rpm=600,
)
SINCE = datetime(2026, 8, 26, tzinfo=UTC)
UNTIL = datetime(2026, 8, 27, tzinfo=UTC)


def test_parse_csv():
    rows = _parse_csv(CSV_TEXT)
    assert rows == [
        (datetime(2026, 8, 25).date(), "4.20"),
        (datetime(2026, 8, 26).date(), "4.18"),
        (datetime(2026, 8, 27).date(), "."),
    ]


def test_snapshot_semantics():
    """观察窗内有新观测 → 单条快照 Draft；published_at=窗内最后有效观测日。"""
    adapter = FredSeriesAdapter(META, series_id="DGS10")
    drafts = adapter.snapshot_drafts(_parse_csv(CSV_TEXT), SINCE, UNTIL)  # 纯函数钩子
    assert len(drafts) == 1
    d = drafts[0]
    assert d.external_id == "DGS10:20260826"
    assert d.published_at == datetime(2026, 8, 26, tzinfo=UTC)
    assert d.raw["series_id"] == "DGS10"
    assert d.raw["window_obs"] == 1  # 08-27 为缺失值 "." 不计
    assert "observation_date,value" in d.body


def test_no_new_obs_returns_empty():
    adapter = FredSeriesAdapter(META, series_id="DGS10")
    old_since = datetime(2020, 1, 1, tzinfo=UTC)
    assert (
        adapter.snapshot_drafts(_parse_csv(CSV_TEXT), old_since, datetime(2020, 1, 2, tzinfo=UTC))
        == []
    )
