"""M5-A3 拆解契约测试。"""

from datetime import UTC, datetime

import pytest
from oh_contracts.dissection import (
    ELEMENT_KEYS,
    ArticleDissection,
    DissectionElement,
    DissectionSpan,
)
from pydantic import ValidationError


def test_element_keys_closed_set_18() -> None:
    assert len(ELEMENT_KEYS) == 18
    assert ELEMENT_KEYS[0] == "actor" and ELEMENT_KEYS[-1] == "context"


def test_element_requires_content_and_valid_key() -> None:
    with pytest.raises(ValidationError):
        DissectionElement(element="actor", content="")  # 空内容拒绝
    with pytest.raises(ValidationError):
        DissectionElement(element="mood", content="x")  # 闭集外拒绝
    ok = DissectionElement(
        element="actor",
        content="美联储",
        spans=[DissectionSpan(start=0, end=3)],
    )
    assert ok.spans[0].end == 3


def test_span_end_must_exceed_start() -> None:
    with pytest.raises(ValidationError):
        DissectionSpan(start=5, end=5)


def test_article_dissection_roundtrip_and_defaults() -> None:
    d = ArticleDissection(
        item_key="k1",
        title="美联储声明",
        elements=[DissectionElement(element="hard_fact", content="维持利率不变")],
        dissected_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert d.engine == "llm" and d.language == "" and d.model_hint == ""
    dumped = d.model_dump(mode="json")
    assert ArticleDissection.model_validate(dumped) == d


def test_dissection_requires_item_key_and_time() -> None:
    with pytest.raises(ValidationError):
        ArticleDissection(item_key="", dissected_at=datetime.now(UTC))
    with pytest.raises(ValidationError):
        ArticleDissection(item_key="k1", dissected_at="not-a-date")  # type: ignore[arg-type]
