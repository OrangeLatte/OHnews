"""TrackingStore 测试：CRUD/命中/清零重建语义。"""

import pytest
from oh_agents.tracking import TrackingStore
from oh_contracts.tracking import TrackingUnit


@pytest.fixture()
def store(tmp_path):
    return TrackingStore(tmp_path / "tracking.sqlite")


def test_add_list_remove_flow(store: TrackingStore) -> None:
    u1 = store.add(kind="entity", query="fed", label="美联储")
    u2 = store.add(kind="element", query="tone:fear", mode="alert", threshold=0.8)
    assert u1.unit_id.startswith("tu-en-")
    assert u2.mode == "alert" and u2.threshold == 0.8
    assert len(store.list()) == 2
    assert [u.kind for u in store.list(kind="entity")] == ["entity"]
    got = store.get(u1.unit_id)
    assert isinstance(got, TrackingUnit) and got.query == "fed"
    assert store.remove(u2.unit_id) is True
    assert store.remove(u2.unit_id) is False
    assert len(store.list()) == 1


def test_hits_and_mark_checked(store: TrackingStore) -> None:
    u = store.add(kind="topic", query="关税")
    store.mark_checked(u.unit_id, now="2026-09-02T08:00:00+00:00")
    assert store.get(u.unit_id).last_checked_at == "2026-09-02T08:00:00+00:00"
    store.append_hit(
        u.unit_id, "topic", "近 7 日 22 篇命中「关税」", now="2026-09-02T09:00:00+00:00"
    )
    store.append_hit(u.unit_id, "topic", "新增 3 篇", now="2026-09-02T10:00:00+00:00")
    hits = store.hits(u.unit_id)
    assert len(hits) == 2
    assert hits[0].summary == "新增 3 篇"  # id DESC 倒序
    assert store.hits(limit=1)[0].unit_id == u.unit_id
    assert store.counts() == {"units": 1, "hits": 2}
