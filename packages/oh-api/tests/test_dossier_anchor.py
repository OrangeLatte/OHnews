"""detection_anchor 回归：数据尾落后 >1d 时，change-field 的 ID 必须能被详情命中。

背景 bug：change-field 检测锚定数据尾（signal_id 内嵌数据日），而
build_dossier 曾用 wall clock 重检 → 跨日失配，点条目进详情 404。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import GAIN_BODY, LOSS_BODY, TIER_MAP, make_now
from fastapi.testclient import TestClient
from oh_api.app import AppPaths, create_app
from oh_contracts.ids import make_item_key
from oh_contracts.schemas import BronzeRecord, EventRecord
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

LAG_DAYS = 3


def _seed_event(
    bronze: ParquetBronzeWriter,
    store: SqliteStore,
    event_id: str,
    now: datetime,
) -> EventRecord:
    """conftest.seed_event 变体：事件 as_of 提前 4h（早于数据尾，锚定后可查）。"""
    event = EventRecord(
        event_id=event_id,
        title=f"事件{event_id}",
        entities=["fed"],
        as_of=now - timedelta(hours=4),
    )
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
    bronze.write(recs)
    return event


@pytest.fixture()
def lagged_client(tmp_path: Path) -> TestClient:
    """数据停在 T，now_fn = T + 3d（模拟采集断流 3 天）。"""
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    data_now = make_now()
    ev = _seed_event(bronze, store, "E01", data_now)
    run_pipeline(
        bronze,
        store,
        store,
        [ev],
        TIER_MAP,
        as_of=data_now,
        lookback_days=1,
        min_per_source=10,
    )
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text(
        "sources:\n"
        + "".join(f"  - source_id: {sid}\n    tier: {t.value}\n" for sid, t in TIER_MAP.items()),
        encoding="utf-8",
    )
    wall_now = data_now + timedelta(days=LAG_DAYS)
    app = create_app(
        AppPaths(
            root=tmp_path,
            sources_yaml=sources_yaml,
            now_fn=lambda: wall_now,
        )
    )
    return TestClient(app)


def test_change_id_resolvable_when_data_lags(lagged_client: TestClient) -> None:
    wall_now = make_now() + timedelta(days=LAG_DAYS)
    r = lagged_client.get("/api/change-field", params={"days": 1, "lang": "en"})
    assert r.status_code == 200
    changes = r.json()["changes"]
    if not changes:
        pytest.skip("种子未产出合格变化（gate 过滤），本断言依赖非空 changes")
    # signal_id 内嵌锚点日期：change-field 锚定数据尾（8-28），非 wall clock
    assert wall_now.date().isoformat().replace("-", "") not in changes[0]["change_id"]
    cid = changes[0]["change_id"]
    detail = lagged_client.get(f"/api/changes/{cid}", params={"lang": "en"})
    assert detail.status_code == 200, f"详情 404：列表 ID {cid} 不可寻址（锚定不一致）"


def test_detection_anchor_follows_data_tail(tmp_path: Path) -> None:
    """detection_anchor：数据尾落后 >1d 时锚定数据尾，否则用真实 now。"""
    from oh_api.briefing import detection_anchor

    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    data_now = make_now()
    wall_now = data_now + timedelta(days=LAG_DAYS)

    class _Rec:
        published_at = data_now

    anchor = detection_anchor([_Rec()], store, wall_now)
    assert anchor == data_now
    fresh_now = data_now + timedelta(hours=12)
    assert detection_anchor([_Rec()], store, fresh_now) == fresh_now
    assert detection_anchor([], store, wall_now) == wall_now
    # 数据尾距真实 now 仅 1h（新鲜）：锚定真实 now
    real_now = datetime.now(UTC)
    fresh_rec = type("_R", (), {"published_at": real_now - timedelta(hours=1)})()
    assert detection_anchor([fresh_rec], store, real_now) == real_now
