"""Intent/Artifact/ContextPacket 契约测试。"""

from __future__ import annotations

import pytest
from oh_contracts.intents import (
    AnalysisArtifact,
    ArtifactKind,
    ContextPacket,
    Intent,
    IntentKind,
    TargetKind,
)
from pydantic import ValidationError


def test_intent_valid_and_defaults() -> None:
    i = Intent(intent=IntentKind.EXPLAIN_SIGNAL, target_kind=TargetKind.SIGNAL, target_id="sig-1")
    assert i.intent is IntentKind.EXPLAIN_SIGNAL
    assert i.created_at.tzinfo is not None
    assert i.message is None


def test_intent_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        Intent(intent="nope", target_kind="event", target_id="e1")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Intent(intent=IntentKind.SHOW_EVIDENCE, target_kind="unknown", target_id="e1")  # type: ignore[arg-type]


def test_analysis_artifact_five_layers_and_empty_observation_gate() -> None:
    a = AnalysisArtifact(
        target_id="e1",
        intent=IntentKind.EXPLAIN_CAUSE,
        observation="观察",
        interpretation="解读",
        evidence=["s1"],
        alternative="替代解释",
        uncertainty="不确定",
    )
    assert a.kind is ArtifactKind.ANALYSIS and a.engine == "offline"
    with pytest.raises(ValidationError):
        AnalysisArtifact(
            target_id="e1", intent=IntentKind.EXPLAIN_CAUSE, observation="  ", interpretation="x"
        )


def test_context_packet_summary_render() -> None:
    p = ContextPacket(
        intent=IntentKind.COMPARE_NARRATIVES,
        target_kind=TargetKind.EVENT,
        target_id="e1",
        entity_id="fed",
        signal={"title": "T", "strength": 90, "what_changed": "wc", "why_it_matters": "wm"},
        event={"title": "Event", "as_of": "2026-08-27"},
        ndi_points=[{"ndi": 0.5, "status": "ok", "n_sources": 12}],
        stances=[{"tier": "L1"}, {"tier": "L3"}],
        notes=["note1"],
    )
    text = p.summary_text()
    assert "Intent: compare_narratives" in text
    assert "What changed: wc" in text
    assert "NDI latest: 0.5" in text
    assert "official=1" in text
    assert "Note: note1" in text
