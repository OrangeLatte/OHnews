"""watching.py 契约测试（阶段 3）。"""

from __future__ import annotations

import pytest
from oh_contracts.watching import WatchKind, WatchReview, WatchUpdate
from pydantic import ValidationError


def _update(**over: object) -> WatchUpdate:
    base: dict[str, object] = {
        "watch_id": "watch-abc",
        "kind": "entity",
        "query": "fed",
        "since": "2026-08-30T00:00:00+00:00",
        "has_changes": True,
        "summary": "自上次查看以来有 2 件新变化",
    }
    base.update(over)
    return WatchUpdate(**base)  # type: ignore[arg-type]


def test_watch_kinds_closed() -> None:
    assert set(WatchKind.__args__) == {"entity", "topic", "question"}


def test_update_minimal_roundtrip() -> None:
    u = _update()
    assert u.new_changes == []
    assert u.review_hint == ""
    assert WatchUpdate.model_validate(u.model_dump()) == u


def test_update_requires_summary() -> None:
    with pytest.raises(ValidationError):
        _update(summary="")


def test_review_roundtrip() -> None:
    r = WatchReview(watch_id="watch-abc", reviewed_at="2026-09-01T00:00:00+00:00")
    assert WatchReview.model_validate(r.model_dump()) == r


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        _update(kind="keyword")
