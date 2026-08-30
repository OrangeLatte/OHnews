"""Insight Generator 测试：五段强制、保守强度、备择保证、NDI 措辞纪律。"""

from datetime import UTC, datetime

from oh_agents.insight_generator import generate_insight
from oh_contracts.narrative import (
    EventAssessment,
    EventStatus,
    EvidenceStrength,
    Insight,
    NarrativeMomentum,
    NarrativeStatement,
)
from oh_contracts.signals import Signal, SignalKind

_NOW = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)
_AS_OF = datetime(2026, 8, 29, 23, 0, tzinfo=UTC)


def _signal(
    kind: SignalKind = SignalKind.NDI_ALERT,
    what_changed: str = "官方与市场源簇的叙事分歧显著升高（NDI 0.50 → 0.70）",
    **overrides,
) -> Signal:
    values: dict = {
        "signal_id": "sig-fed-ndi-20260829",
        "kind": kind,
        "entity_id": "fed",
        "title": "FED NDI Alert",
        "what_changed": what_changed,
        "why_it_matters": "源簇分歧通常先于政策沟通调整。",
        "metrics": {"intelligence_score": 72.44, "ndi": 0.7, "delta": 0.2},
        "strength": 75.0,
        "confidence": 0.8,
        "evidence_ids": ["ev-fed-20260829"],
        "detected_at": _NOW,
        "as_of": _AS_OF,
        "subject_type": "entity",
        "subject_id": "fed",
        "novelty_score": 1.0,
        "persistence_score": 0.67,
        "baseline": 0.5,
        "current_value": 0.7,
    }
    values.update(overrides)
    return Signal(**values)


def _assessment(
    status: EventStatus = EventStatus.CONTESTED,
    strength: EvidenceStrength = EvidenceStrength.MODERATE,
    event_id: str = "ev-fed-20260829",
) -> EventAssessment:
    return EventAssessment(
        event_id=event_id,
        status=status,
        confidence=0.62,
        evidence_strength=strength,
        n_independent_sources=3,
        n_primary_sources=1,
        observation="测试评估观察句，长度超过八字。",
    )


def _narrative(narrative_id: str = "nar-fed-2026-08-24/30") -> NarrativeStatement:
    return NarrativeStatement(
        narrative_id=narrative_id,
        statement="「fed」近窗报道以官方与市场混合为主，主导框架为「损失」。",
        entity_id="fed",
        event_ids=["ev-fed-20260829"],
        supporting_item_keys=["k1", "k2"],
        opposing_item_keys=["k3"],
        source_cluster="mixed",
        momentum=NarrativeMomentum.RISING,
        confidence=0.55,
        divergence=0.7,
        first_seen=_AS_OF,
        window="2026-08-24/30",
    )


def test_basic_fields_and_provenance() -> None:
    sig = _signal()
    insight = generate_insight(sig, now=_NOW)
    assert isinstance(insight, Insight)
    assert insight.insight_id == f"ins-{sig.signal_id}"
    assert insight.engine == "offline"
    assert insight.related_signal_ids == [sig.signal_id]
    assert insight.intelligence_score == 72.4  # metrics 透传并 round 1 位
    assert insight.what_changed == sig.what_changed
    assert insight.why_it_matters == sig.why_it_matters
    assert insight.as_of == sig.as_of  # PIT 锚取 signal.as_of
    assert insight.generated_at == _NOW
    assert insight.related_event_ids == []
    assert insight.related_narrative_ids == []


def test_headline_and_observation_min_length() -> None:
    insight = generate_insight(_signal(), assessments=[_assessment()], now=_NOW)
    assert len(insight.headline) >= 8
    assert len(insight.observation) >= 8
    assert "0.5" in insight.observation and "0.7" in insight.observation  # 基线→当前括注


def test_strength_is_conservative_across_assessments() -> None:
    insight = generate_insight(
        _signal(),
        assessments=[_assessment(strength=EvidenceStrength.STRONG), _assessment()],
        now=_NOW,
    )
    assert insight.evidence_strength is EvidenceStrength.MODERATE


def test_strength_insufficient_without_assessments() -> None:
    insight = generate_insight(_signal(), now=_NOW)
    assert insight.evidence_strength is EvidenceStrength.INSUFFICIENT


def test_alternative_explanations_guaranteed_for_all_kinds() -> None:
    for kind in SignalKind:
        insight = generate_insight(_signal(kind=kind), now=_NOW)
        assert len(insight.alternative_explanations) >= 1
        assert all(isinstance(a, str) and a for a in insight.alternative_explanations)


def test_contested_adds_extra_alternative() -> None:
    plain = generate_insight(_signal(), now=_NOW)
    contested = generate_insight(
        _signal(), assessments=[_assessment(status=EventStatus.CONTESTED)], now=_NOW
    )
    assert len(contested.alternative_explanations) > len(plain.alternative_explanations)
    assert any("复杂性" in a for a in contested.alternative_explanations)


def test_related_ids_dedup_and_sort() -> None:
    insight = generate_insight(
        _signal(),
        assessments=[
            _assessment(event_id="ev-b"),
            _assessment(event_id="ev-a"),
            _assessment(event_id="ev-b"),
        ],
        narratives=[_narrative(), _narrative(narrative_id="nar-fed-2026-08-17/23")],
        now=_NOW,
    )
    assert insight.related_event_ids == ["ev-a", "ev-b"]
    assert insight.related_narrative_ids == [
        "nar-fed-2026-08-17/23",
        "nar-fed-2026-08-24/30",
    ]


def test_ndi_interpretation_is_descriptive_not_predictive() -> None:
    insight = generate_insight(_signal(kind=SignalKind.NDI_ALERT), now=_NOW)
    assert "叙事分歧指数" in insight.interpretation
    assert "非预测器" in insight.interpretation
    shift = generate_insight(_signal(kind=SignalKind.NARRATIVE_SHIFT), now=_NOW)
    assert "非预测器" not in shift.interpretation  # 措辞仅挂在 NDI 类信号


def test_interpretation_cites_assessment_and_narrative() -> None:
    insight = generate_insight(
        _signal(), assessments=[_assessment()], narratives=[_narrative()], now=_NOW
    )
    assert "存争议" in insight.interpretation
    assert "叙事层观察" in insight.interpretation
    assert "主导框架" in insight.interpretation


def test_idempotent_with_fixed_now() -> None:
    sig = _signal()
    a = generate_insight(sig, assessments=[_assessment()], narratives=[_narrative()], now=_NOW)
    b = generate_insight(sig, assessments=[_assessment()], narratives=[_narrative()], now=_NOW)
    assert a.model_dump() == b.model_dump()


def test_observation_fallback_for_short_text() -> None:
    insight = generate_insight(
        _signal(what_changed="过短", baseline=None, current_value=None), now=_NOW
    )
    assert len(insight.observation) >= 8
