"""alerts 预警引擎测试：分位数/CRUD/触发/每日去重/样本门。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pytest  # noqa: E402
from conftest import make_now  # noqa: E402
from oh_agents.alerts import AlertStore, _percentile, check_alerts  # noqa: E402
from oh_contracts.schemas import EventRecord, NDIPoint  # noqa: E402
from oh_storage.connection import connect  # noqa: E402
from oh_storage.sqlite_store import SqliteStore  # noqa: E402

NOW = make_now()


def _ndi(event_id: str, ts: datetime, ndi: float) -> NDIPoint:
    return NDIPoint(
        event_id=event_id,
        ts=ts,
        ndi=ndi,
        ci_low=max(0.0, ndi - 0.05),
        ci_high=min(1.0, ndi + 0.05),
        n_sources=3,
        status="ok",
    )


def test_percentile_interpolation() -> None:
    vals = sorted([float(i) for i in range(1, 11)])  # 1..10
    assert _percentile(vals, 0.9) == pytest.approx(9.1)  # 线性插值手算
    assert _percentile([7.0], 0.5) == 7.0
    with pytest.raises(ValueError):
        _percentile([], 0.5)


def test_rule_crud(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "a.sqlite")
    store.add_rule("r1", "fed", 0.9)
    rules = store.list_rules()
    assert len(rules) == 1 and rules[0].entity_id == "fed" and rules[0].percentile == 0.9
    assert store.remove_rule("r1") is True
    assert store.remove_rule("r1") is False
    with pytest.raises(ValueError):
        store.add_rule("r2", "fed", 1.0)  # 越界拒绝


def _seed_two_events(store: SqliteStore) -> None:
    for eid, title in (("E1", "事件1"), ("E2", "事件2")):
        store.upsert_event(EventRecord(event_id=eid, title=title, entities=["fed"], as_of=NOW))


def test_check_triggers_and_daily_dedupe(tmp_path: Path) -> None:
    silver = SqliteStore(connect(tmp_path / "s.sqlite"))
    gold = SqliteStore(connect(tmp_path / "g.sqlite"))
    _seed_two_events(silver)
    # E1: 9 个低位历史点 + 最新 0.9；E2: 1 个低位点 → P90 基线 ~0.29
    for i in range(9):
        gold.append_ndi(_ndi("E1", NOW - timedelta(days=9 - i), 0.2 + 0.01 * i))
    gold.append_ndi(_ndi("E1", NOW - timedelta(hours=2), 0.9))
    gold.append_ndi(_ndi("E2", NOW - timedelta(hours=3), 0.25))

    alerts = AlertStore(tmp_path / "a.sqlite")
    alerts.add_rule("r1", "fed", 0.9)

    hits = check_alerts(silver, gold, alerts, now=NOW)
    assert len(hits) == 1
    assert hits[0].event_id == "E1" and hits[0].ndi == pytest.approx(0.9)
    assert hits[0].baseline == pytest.approx(0.28, abs=0.01)

    # 同实体每日 1 次：立即复跑不新增
    assert check_alerts(silver, gold, alerts, now=NOW) == []
    assert len(alerts.list_hits()) == 1


def test_min_history_gate(tmp_path: Path) -> None:
    silver = SqliteStore(connect(tmp_path / "s.sqlite"))
    gold = SqliteStore(connect(tmp_path / "g.sqlite"))
    silver.upsert_event(EventRecord(event_id="E1", title="t", entities=["fed"], as_of=NOW))
    for i in range(3):  # 不足 8 点 → 样本门弃权
        gold.append_ndi(_ndi("E1", NOW - timedelta(days=3 - i), 0.2))
    alerts = AlertStore(tmp_path / "a.sqlite")
    alerts.add_rule("r1", "fed", 0.5)
    assert check_alerts(silver, gold, alerts, now=NOW) == []
