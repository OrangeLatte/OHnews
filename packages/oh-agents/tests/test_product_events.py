"""ProductEventStore（阶段 1-e）测试：闭集校验/计数/时序。"""

from pathlib import Path

import pytest
from oh_agents.product_events import ProductEventStore


@pytest.fixture()
def store(tmp_path: Path) -> ProductEventStore:
    return ProductEventStore(tmp_path / "product_events.sqlite")


def test_append_and_counts(store: ProductEventStore) -> None:
    store.append("briefing_viewed", "s1")
    store.append("change_opened", "s1", object_id="sig-x", from_page="/")
    store.append("change_opened", "s2", object_id="sig-y")
    counts = store.counts()
    assert counts == {"briefing_viewed": 1, "change_opened": 2}


def test_untracked_event_rejected(store: ProductEventStore) -> None:
    with pytest.raises(ValueError, match="untracked"):
        store.append("page_view", "s1")


def test_recent_order_and_meta(store: ProductEventStore) -> None:
    store.append("briefing_viewed", "s1", meta={"top": 5})
    store.append("evidence_opened", "s1", object_id="sig-x", meta={"bucket": "context"})
    events = store.recent()
    assert [e.event for e in events] == ["evidence_opened", "briefing_viewed"]
    assert events[0].meta == {"bucket": "context"}
    assert events[0].object_id == "sig-x"
    assert events[0].ts.tzinfo is not None


def test_persistence_across_instances(tmp_path: Path) -> None:
    db = tmp_path / "pe.sqlite"
    ProductEventStore(db).append("change_opened", "s1", object_id="sig-a")
    again = ProductEventStore(db)
    assert again.counts() == {"change_opened": 1}
