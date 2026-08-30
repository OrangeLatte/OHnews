"""语义层契约测试（M3-S1）：构造门禁 + 字段校验 + 枚举空间。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from oh_contracts.semantics import (
    ActionMention,
    EmotionLabel,
    EmotionVector,
    EntityEdge,
    SemanticAnnotation,
    SemanticRole,
)
from pydantic import ValidationError

_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def test_emotion_label_space() -> None:
    assert {e.value for e in EmotionLabel} == {
        "fear",
        "anger",
        "optimism",
        "uncertainty",
        "confidence",
        "urgency",
        "concern",
        "relief",
    }


def test_emotion_vector_rejects_out_of_range() -> None:
    # dict 值域不逐键校验（pydantic dict[float] 语义）；顶层标量强制 [0,1]
    with pytest.raises(ValidationError):
        EmotionVector(
            expressed={"fear": 0.2},
            audience={},
            intensity=1.5,
            confidence=0.0,
            engine="lexicon",
        )


def test_action_mention_defaults_strength() -> None:
    m = ActionMention(
        verb="rate cut", domain="monetary", direction="easing", certainty=0.8, start=0, end=8
    )
    assert m.strength == 0.5
    assert m.certainty == 0.8


def test_semantic_role_defaults_all_none() -> None:
    r = SemanticRole()
    assert r.subject is None and r.causality is None and r.engine == "lexicon"


def test_semantic_annotation_roundtrip() -> None:
    a = SemanticAnnotation(
        item_key="k-1",
        roles=[SemanticRole(subject="美联储", action="easing")],
        emotions=EmotionVector(
            expressed={"fear": 0.2}, audience={}, intensity=0.2, confidence=0.2, engine="lexicon"
        ),
        annotated_at=_NOW,
    )
    d = a.model_dump(mode="json")
    assert d["roles"][0]["engine"] == "lexicon"
    assert SemanticAnnotation.model_validate(d) == a


def test_entity_edge_kind_closed() -> None:
    with pytest.raises(ValidationError):
        EntityEdge(
            src="fed", dst="fomc", kind="married_to", weight=1.0, first_seen=_NOW, last_seen=_NOW
        )
    e = EntityEdge(
        src="fed",
        dst="fomc",
        kind="parent_of",
        weight=1.0,
        first_seen=_NOW,
        last_seen=_NOW,
        evidence_item_keys=["k"],
    )
    assert e.evidence_item_keys == ["k"]
