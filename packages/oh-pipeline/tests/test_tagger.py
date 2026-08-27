"""规则层 Tagger：框架线索词 / 弃权语义 / 实体过滤 / 置信边界。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from oh_contracts.enums import ExtractionEngine, FrameLabel, StanceLabel
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.tagger import RuleTagger

TS = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


@pytest.fixture()
def tagger() -> RuleTagger:
    return RuleTagger(EntityRegistry())


def _tag(tagger: RuleTagger, text: str, **kw):
    return tagger.tag(
        event_id="E01",
        source_id="pbc",
        text=text,
        item_key="s:e:t",
        ts=TS,
        **kw,
    )


def test_loss_frame_dominates(tagger: RuleTagger) -> None:
    rows = _tag(
        tagger,
        "美联储面临衰退风险，市场损失惨重，裁员潮加剧失业压力",
    )
    assert len(rows) == 1
    assert rows[0].entity_id == "fed"
    assert rows[0].frame == FrameLabel.LOSS


def test_conflict_frame_dominates(tagger: RuleTagger) -> None:
    rows = _tag(tagger, "Trump announced new tariffs as the trade war escalates")
    assert rows[0].frame == FrameLabel.CONFLICT


def test_no_entity_hit_returns_empty(tagger: RuleTagger) -> None:
    assert _tag(tagger, "衰退风险持续，损失惨重") == []


def test_entity_hit_without_frame_signal_abstains(tagger: RuleTagger) -> None:
    """弃权语义：有实体但无框架线索 → 不产行（无意见≠中性意见）。"""
    assert _tag(tagger, "美联储今日发布了例行公告") == []


def test_single_weak_hit_emits_row(tagger: RuleTagger) -> None:
    """单个弱命中（confidence=0.33 ≥ 0.3）应产出；纯标点夹持的噪声不产行由门控兜底。"""
    rows = _tag(tagger, "美联储提到一次增长")
    assert len(rows) == 1


def test_stance_critical_in_entity_window(tagger: RuleTagger) -> None:
    rows = _tag(tagger, "市场批评美联储应对不力，质疑其政策失误")
    assert rows[0].stance == StanceLabel.CRITICAL


def test_stance_supportive(tagger: RuleTagger) -> None:
    rows = _tag(tagger, "市场称赞美联储的政策有效，欢迎其提振增长的决定")
    assert rows[0].stance == StanceLabel.SUPPORTIVE


def test_stance_neutral_default(tagger: RuleTagger) -> None:
    rows = _tag(tagger, "美联储声明：衰退风险与增长机遇并存，失业与就业数据混合")
    assert rows[0].stance == StanceLabel.NEUTRAL


def test_entities_filter_restricts_rows(tagger: RuleTagger) -> None:
    rows = _tag(
        tagger,
        "美联储与 FOMC 均警告制裁风险上升",
        entities=["fed"],
    )
    assert {r.entity_id for r in rows} == {"fed"}


def test_engine_and_confidence_bounds(tagger: RuleTagger) -> None:
    rows = _tag(tagger, "关税制裁引发争端，特朗普威胁报复")
    assert all(r.engine == ExtractionEngine.RULE for r in rows)
    assert all(0.0 <= r.confidence <= 0.75 for r in rows)


def test_empty_text_returns_empty(tagger: RuleTagger) -> None:
    assert _tag(tagger, "   ") == []
