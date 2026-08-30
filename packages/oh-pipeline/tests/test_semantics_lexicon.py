"""词典语义层测试（M3-S1）：动作/双层情绪/SRL 论元/确定性幂等。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_pipeline.entities import EntityRegistry
from oh_pipeline.semantics import annotate_document, emotion_vector

R = EntityRegistry()
_NOW = datetime(2026, 8, 31, tzinfo=UTC)


def test_action_mentions_from_svo_lexicon() -> None:
    a = annotate_document(
        "k-1",
        "The Fed is expected to cut rates as inflation cools.",
        R,
        annotated_at=_NOW,
    )
    assert any(m.direction == "easing" and m.domain == "monetary" for m in a.actions)
    assert all(m.engine if False else m.strength == 0.5 for m in a.actions)


def test_emotion_expressed_and_audience() -> None:
    v = emotion_vector("市场恐慌情绪蔓延，官员警告风险显著上升。")
    assert v.expressed.get("fear", 0) > 0
    # audience 由风险触发词驱动
    assert sum(v.audience.values()) > 0
    assert v.engine == "lexicon"
    assert v.confidence <= 0.6


def test_emotion_english_hits() -> None:
    v = emotion_vector("Investors remain optimistic as tensions ease and markets rebound.")
    assert v.expressed.get("optimism", 0) > 0
    assert v.expressed.get("relief", 0) > 0


def test_srl_roles_heuristics() -> None:
    a = annotate_document(
        "k-2",
        "美联储2026年8月在华盛顿宣布降息25个基点。",
        R,
        annotated_at=_NOW,
    )
    role = next(r for r in a.roles if r.subject)
    assert role.subject is not None and "美联储" in role.subject
    assert role.action == "easing"
    assert role.time is not None
    assert role.location == "华盛顿"
    assert role.causality is None  # 词典层不产 causality
    assert role.engine == "lexicon"


def test_srl_object_financial_window() -> None:
    a = annotate_document(
        "k-3",
        "Washington plans new tariffs on imports next month.",
        R,
        annotated_at=_NOW,
    )
    role = next(r for r in a.roles if r.action == "escalate")
    # 动作词本身（tariffs）不算宾语；宾语=其后窗内金融词表命中
    assert role.object == "imports"


def test_srl_target_entity_after_action() -> None:
    # 动作词后窗内出现实体别名 → target 命中（取离动作最近者）
    a = annotate_document(
        "k-3b",
        "New tariffs could rattle the Fed's rate path, officials said.",
        R,
        annotated_at=_NOW,
    )
    role = next(r for r in a.roles if r.action == "escalate")
    assert role.target is not None and "Fed" in role.target


def test_deterministic_idempotent() -> None:
    text = "央行降息，市场反弹，投资者乐观。"
    a1 = annotate_document("k-9", text, R, annotated_at=_NOW)
    a2 = annotate_document("k-9", text, R, annotated_at=_NOW)
    assert a1 == a2


def test_empty_text_safe() -> None:
    a = annotate_document("k-0", "", R, annotated_at=_NOW)
    assert a.actions == []
    assert a.emotions is not None and a.emotions.intensity == 0.0
    assert a.emotions.confidence == 0.1
