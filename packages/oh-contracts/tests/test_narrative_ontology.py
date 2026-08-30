"""RECONSTRUCTION M1：本体契约层测试。"""

from datetime import UTC, datetime

import pytest
from oh_contracts import (
    EventAssessment,
    EventStatus,
    EvidenceItem,
    EvidenceRole,
    EvidenceStrength,
    Insight,
    NarrativeMomentum,
    NarrativeStatement,
    Signal,
    SignalKind,
    entity_importance,
    impact_factor,
    intelligence_score,
    novelty_factor,
)
from pydantic import ValidationError


def _sig(**kw) -> Signal:
    now = datetime.now(UTC)
    base = dict(
        signal_id="sig-test",
        kind=SignalKind.NARRATIVE_SHIFT,
        entity_id="fed",
        title="FED Narrative Shift",
        what_changed="x",
        strength=50.0,
        confidence=0.5,
        detected_at=now,
        as_of=now,
    )
    base.update(kw)
    return Signal(**base)


def test_event_status_enum_values():
    assert EventStatus.UNVERIFIED.value == "unverified"
    assert EventStatus.CONTESTED.value == "contested"


def test_evidence_strength_scores():
    assert EvidenceStrength.STRONG.score == 1.0
    assert EvidenceStrength.INSUFFICIENT.score == 0.0


def test_evidence_item_role_required():
    e = EvidenceItem(
        item_key="u:abc|c:def|s:s|e:1|t:0",
        source_id="wallstreetcn",
        role=EvidenceRole.SECONDARY,
        quote="某声明全文节选",
        published_at=datetime.now(UTC),
    )
    assert e.role == EvidenceRole.SECONDARY
    with pytest.raises(ValidationError):
        EvidenceItem(
            item_key="x", source_id="s", role="bogus", quote="q", published_at=datetime.now(UTC)
        )


def test_event_assessment_conservative_default():
    a = EventAssessment(
        event_id="ev-fed-20260827",
        status=EventStatus.DEVELOPING,
        confidence=0.6,
        evidence_strength=EvidenceStrength.MODERATE,
        n_independent_sources=4,
        n_primary_sources=1,
        observation="多源报道同一声明。",
    )
    assert a.engine == "offline"
    assert a.interpretation is None


def test_narrative_statement_minimum():
    n = NarrativeStatement(
        narrative_id="nar-fed-2026-W35",
        statement="市场评论开始强调降息路径的不确定性。",
        entity_id="fed",
        source_cluster="financial_press",
        confidence=0.6,
        divergence=0.3,
        first_seen=datetime.now(UTC),
        window="2026-08-24/30",
    )
    assert n.momentum == NarrativeMomentum.STEADY
    assert n.engine == "offline"
    with pytest.raises(ValidationError):
        NarrativeStatement(
            narrative_id="x",
            statement="短",
            entity_id="fed",
            source_cluster="mixed",
            confidence=0.5,
            divergence=0.1,
            first_seen=datetime.now(UTC),
            window="w",
        )


def test_insight_requires_alternative_and_headline():
    now = datetime.now(UTC)
    base = dict(
        insight_id="ins-1",
        headline="围绕 OpenAI 的报道正从扩张转向竞争压力",
        observation="近一周报道框架从产品增长转向竞争失利。",
        interpretation="信息环境对 OpenAI 的讲述方式在改变。",
        evidence_strength=EvidenceStrength.MODERATE,
        what_changed="叙事迁移",
        intelligence_score=62.5,
        generated_at=now,
        as_of=now,
    )
    Insight(**{**base, "alternative_explanations": ["竞争加剧的行业叙事外溢。"]})
    with pytest.raises(ValidationError):
        Insight(**{**base, "alternative_explanations": []})


def test_signal_subject_semantics_optional():
    s = _sig(
        subject_type="entity",
        novelty_score=0.9,
        persistence_score=0.4,
        baseline=23.0,
        current_value=94.0,
    )
    assert s.subject_type == "entity"
    assert s.baseline == 23.0
    # 老代码零改动兼容：不传新字段照样构造
    assert _sig().subject_id is None


def test_ranking_weights_and_floor():
    assert abs(sum(entity_importance(k) for k in [])) == 0
    assert entity_importance("central_bank") == 1.0
    assert novelty_factor(0.0) == 1.0
    assert 0.0 < novelty_factor(7.0) < 1.0
    assert impact_factor(None) == 0.5
    assert impact_factor(2.0) == 1.0
    # 满因子 = 100
    assert intelligence_score(importance=1, novelty=1, evidence=1, persistence=1, impact=1) == 100.0
    # 证据不足 → 封顶 40
    s = intelligence_score(importance=1, novelty=1, evidence=0.0, persistence=1, impact=1)
    assert s == 40.0
    # 证据有限 → 降权不湮灭
    s2 = intelligence_score(importance=0.8, novelty=0.8, evidence=0.4, persistence=0.5, impact=0.6)
    assert 40.0 < s2 < 100.0


def test_ranking_clamps():
    assert (
        intelligence_score(importance=5, novelty=-1, evidence=0.5, persistence=0.5, impact=0.5)
        >= 0.0
    )
    v = intelligence_score(importance=1, novelty=1, evidence=1, persistence=1, impact=1)
    assert v <= 100.0


def test_signal_new_fields_reject_bad_values():
    with pytest.raises(ValidationError):
        _sig(novelty_score=1.5)
    with pytest.raises(ValidationError):
        _sig(subject_type="galaxy")
