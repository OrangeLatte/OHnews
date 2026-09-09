"""E3 图表组聚合器测试：G1 信息流/G3 分歧榜/G4 情绪密度。"""

import datetime as dt

from oh_api.charts import build_emotion_density, build_flow_daily, build_ndi_rank
from oh_contracts.schemas import NDIPoint
from oh_pipeline.entities import EntitySpec

NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)


def _rec(item_key: str, ts: dt.datetime, language: str = "zh"):
    from oh_contracts.schemas import BronzeRecord

    return BronzeRecord(
        source_id=f"src_{language}",
        item_key=item_key,
        external_id=item_key,
        url_hash="u",
        content_hash="c",
        fetched_at=ts,
        published_at=ts,
        raw={},
        normalized={},
    )


def test_flow_daily_counts_by_language_and_pit() -> None:
    recs = [
        _rec("k1", NOW - dt.timedelta(days=1, hours=2), "zh"),
        _rec("k2", NOW - dt.timedelta(days=1, hours=3), "zh"),
        _rec("k3", NOW - dt.timedelta(days=2), "en"),
        _rec("future", NOW + dt.timedelta(days=1)),  # PIT 排除
        _rec("no_ts", NOW),  # 无 published_at
    ]
    recs[-1] = _rec("no_ts", NOW).model_copy(update={"published_at": None})
    rows = build_flow_daily(recs, lang_by_source={"src_zh": "zh", "src_en": "en"}, now=NOW, days=7)
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    yesterday = (NOW - dt.timedelta(days=1)).date().isoformat()
    y = next(r for r in rows if r["date"] == yesterday)
    assert y["zh"] == 2 and y["total"] == 2


def test_ndi_rank_top_and_entity_labels() -> None:
    def _pt(ev: str, ndi: float | None, ts: dt.datetime | None = None):
        return NDIPoint(
            event_id=ev,
            ts=ts or NOW - dt.timedelta(days=1),
            ndi=ndi,
            n_sources=3,
            status="ok",
        )

    pts = [
        _pt("ev-fed-20260901", 0.61),
        _pt("ev-fed-20260901", 0.55, NOW - dt.timedelta(days=2)),  # 旧点不覆盖
        _pt("ev-boj-20260901", 0.72),
        _pt("ev-x-20260901", None),  # 弃权不计
    ]

    class _Reg:
        def get(self, eid: str):
            if eid == "fed":
                return EntitySpec(entity_id="fed", aliases=["Fed", "美联储"])
            return None

    rows = build_ndi_rank(pts, registry=_Reg(), now=NOW, limit=8)
    assert rows[0]["entity"] == "boj" and rows[0]["ndi"] == 0.72
    assert rows[1]["entity"] == "fed" and rows[1]["ndi"] == 0.61
    assert rows[1]["label"] == "美联储"
    assert all(r["entity"] != "x" for r in rows)

    # lang=en：拉丁别名优先；zh：CJK 别名优先，无 CJK 别名回退首别名
    rows_en = build_ndi_rank(pts, registry=_Reg(), now=NOW, limit=8, lang="en")
    assert rows_en[1]["label"] == "Fed"
    rows_zh = build_ndi_rank(pts, registry=_Reg(), now=NOW, limit=8, lang="zh")
    assert rows_zh[0]["label"] == "boj"  # 无注册表 → 回退 entity id
    assert rows_zh[1]["label"] == "美联储"


def test_emotion_density_daily_mean() -> None:
    anns = [
        {
            "annotated_at": (NOW - dt.timedelta(days=1)).isoformat(),
            "emotions": {"expressed": {"fear": 0.5, "optimism": 0.2}},
        },
        {
            "annotated_at": (NOW - dt.timedelta(days=1)).isoformat(),
            "emotions": {"expressed": {"fear": 0.1}},
        },
        {"annotated_at": None, "emotions": {"expressed": {"fear": 9.9}}},  # 无时间跳过
        {  # 闭集外跳过
            "annotated_at": (NOW - dt.timedelta(days=1)).isoformat(),
            "emotions": {"expressed": {"bogus": 1.0}},
        },
    ]
    rows = build_emotion_density(anns, now=NOW, days=7)
    # 日期连续化 + 缺测日 carry-forward：全部 8 天都有值（唯一有效值前后填充）
    assert len(rows) == 8
    assert all(r["fear"] is not None for r in rows)
    assert all(abs(r["fear"] - 0.3) < 1e-6 for r in rows)
    d1 = rows[0]
    # fear 均值 = (0.5+0.1)/2
    assert abs(d1["fear"] - 0.3) < 1e-6
    # optimism 只有一篇文档出现，不应被当天其它情绪键错误稀释。
    assert abs(d1["optimism"] - 0.2) < 1e-6 and "bogus" not in d1
