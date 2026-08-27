"""LLM 补盲抽取：fake router（鸭子类型，只要求 async invoke）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from oh_agents.tagger_llm import LLMFrameOutput, LLMTagger
from oh_contracts.enums import FrameLabel, StanceLabel, Tier
from oh_llm.committee import FrameDist

TS = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
DIST = FrameDist(
    loss=0.6, gain=0.1, responsibility=0.1, conflict=0.1, human_interest=0.05, other=0.05
)


def _fake_router():
    async def invoke(tier, system, user, schema):
        assert tier == Tier.IO
        out = LLMFrameOutput(frame_dist=DIST, stance=StanceLabel.CRITICAL, confidence=0.7)
        return out, SimpleNamespace(provider="deepseek", model_id="deepseek-v4-flash")

    return SimpleNamespace(invoke=invoke)


def test_fill_produces_llm_stance_row() -> None:
    tagger = LLMTagger(_fake_router())
    row = asyncio.run(
        tagger.fill(
            event_id="E01",
            source_id="gov",
            entity_id="fed",
            text="央行程式化文本无线索词命中",
            item_key="gov:x:ts",
            ts=TS,
        )
    )
    assert row is not None
    assert row.engine == "llm"
    assert row.frame == FrameLabel.LOSS  # argmax(dist)
    assert row.stance == StanceLabel.CRITICAL
    assert row.confidence == 0.7


def test_fill_propagates_router_failure() -> None:
    async def invoke(tier, system, user, schema):
        raise RuntimeError("all candidates exhausted")

    tagger = LLMTagger(SimpleNamespace(invoke=invoke))
    try:
        asyncio.run(
            tagger.fill(
                event_id="E01",
                source_id="gov",
                entity_id="fed",
                text="t",
                item_key="k",
                ts=TS,
            )
        )
        raise AssertionError("should raise")
    except RuntimeError as e:
        assert "exhausted" in str(e)
