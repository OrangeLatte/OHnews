"""契约行为测试：双 hash、严格 schema、冻结不可变。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from oh_contracts import (
    BronzeRecord,
    NDIPoint,
    SSEEvent,
    SSEMessage,
    content_hash,
    make_item_key,
    url_hash,
)
from pydantic import ValidationError


def test_hashes_deterministic_and_short() -> None:
    assert url_hash("https://example.com/a") == url_hash("https://example.com/a")
    assert url_hash("https://example.com/a") != content_hash("https://example.com/a")
    assert len(url_hash("x")) == 16
    int(url_hash("x"), 16)  # 必须是十六进制


def test_item_key_composition() -> None:
    assert make_item_key("pbc", "art-1", "2026-08-26T10:00:00+00:00") == (
        "pbc:art-1:2026-08-26T10:00:00+00:00"
    )


def _bronze(**overrides: object) -> BronzeRecord:
    base: dict[str, object] = {
        "source_id": "pbc",
        "item_key": "pbc:art-1:2026-08-26T10:00:00+00:00",
        "external_id": "art-1",
        "url_hash": url_hash("https://pbc.example/1"),
        "content_hash": content_hash("正文"),
        "fetched_at": datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
        "raw": {"title": "t"},
    }
    base.update(overrides)
    return BronzeRecord.model_validate(base)


def test_bronze_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _bronze(unknown_field=1)


def test_bronze_is_frozen() -> None:
    rec = _bronze()
    with pytest.raises(ValidationError):
        rec.source_id = "wscn"  # type: ignore[misc]


def test_sse_message_accepts_enum_event() -> None:
    msg = SSEMessage(run_id="r1", seq=0, event=SSEEvent.NODE_UPDATE, node="tagger_node")
    assert msg.event is SSEEvent.NODE_UPDATE
    with pytest.raises(ValidationError):
        SSEMessage(run_id="r1", seq=-1, event=SSEEvent.DONE)


def test_ndi_abstain_cannot_carry_value() -> None:
    with pytest.raises(ValidationError):
        NDIPoint.model_validate(
            {
                "event_id": "E01",
                "ts": datetime(2026, 8, 26, 10, 0, tzinfo=UTC),
                "ndi": 0.4,
                "n_sources": 1,
                "status": "abstain",
            }
        )
