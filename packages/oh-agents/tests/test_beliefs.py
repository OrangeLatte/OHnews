"""BeliefStore 认知快照账本测试（阶段 2）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from oh_agents.beliefs import BeliefStore
from oh_contracts.belief import BeliefSnapshot
from pydantic import ValidationError


@pytest.fixture()
def store(tmp_path):
    return BeliefStore(tmp_path / "belief.sqlite")


def _snap(
    snapshot_id: str,
    change_id: str = "sig-x",
    stance: str = "maintain",
    confidence: float = 0.6,
    believed_at: datetime | None = None,
    change_type: str = "new",
) -> BeliefSnapshot:
    return BeliefSnapshot(
        snapshot_id=snapshot_id,
        change_id=change_id,
        subject_id="fed",
        subject_label="美联储",
        stance=stance,  # type: ignore[arg-type]
        confidence=confidence,
        rationale="官方与市场口径一致",
        change_type=change_type,  # type: ignore[arg-type]
        believed_at=believed_at or datetime.now(UTC),
    )


def test_save_and_for_change_roundtrip(store):
    at = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    store.save(_snap("bs-1", believed_at=at))
    rows = store.for_change("sig-x")
    assert len(rows) == 1
    assert rows[0].stance == "maintain"
    assert rows[0].subject_label == "美联储"
    assert rows[0].believed_at == at


def test_stance_and_confidence_gates(store):
    with pytest.raises(ValidationError):
        _snap("bs-bad", stance="agree")
    with pytest.raises(ValidationError):
        _snap("bs-bad", confidence=1.5)


def test_change_type_ordering_and_latest(store):
    t0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    store.save(_snap("bs-1", believed_at=t0, change_type="new"))
    store.save(
        _snap(
            "bs-2",
            stance="reverse",
            confidence=0.3,
            believed_at=t0 + timedelta(hours=2),
            change_type="revised",
        )
    )
    rows = store.for_change("sig-x")
    assert [r.snapshot_id for r in rows] == ["bs-1", "bs-2"]
    latest = store.latest_for_change("sig-x")
    assert latest is not None and latest.stance == "reverse"
    assert latest.diff_from(rows[0]) == "立场由「维持原判」变为「反转看法」；信心下降 30%"
    assert store.latest_for_change("nope") is None


def test_diff_identical(store):
    a = _snap("bs-1", stance="maintain", confidence=0.6)
    b = _snap("bs-2", stance="maintain", confidence=0.62)
    assert b.diff_from(a) == "与前一版本一致"


def test_timeline_across_changes_and_persistence(store):
    t0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    store.save(_snap("bs-1", change_id="sig-a", believed_at=t0))
    store.save(_snap("bs-2", change_id="sig-b", believed_at=t0 + timedelta(hours=1)))
    reopened = BeliefStore(store._conn)
    tl = reopened.timeline("fed")
    assert [b.change_id for b in tl] == ["sig-a", "sig-b"]
