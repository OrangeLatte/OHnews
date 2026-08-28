"""分歧构成解剖测试（anatomy）。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_contracts.enums import (
    ExtractionEngine,
    FrameLabel,
    SourceTier,
    StanceLabel,
)
from oh_contracts.schemas import StanceRow
from oh_pipeline.anatomy import cluster_distributions, cluster_pairwise, entity_opposition

TS = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
TIER = {"gov": SourceTier.OFFICIAL, "wire": SourceTier.WIRE, "press": SourceTier.FINANCIAL_PRESS}


def row(src: str, entity: str, frame: FrameLabel, stance: StanceLabel) -> StanceRow:
    return StanceRow(
        event_id="E1",
        source_id=src,
        entity_id=entity,
        frame=frame,
        stance=stance,
        confidence=0.9,
        engine=ExtractionEngine.RULE,
        item_key=f"k-{src}-{entity}-{stance.value}",
        ts=TS,
    )


def _rows() -> list[StanceRow]:
    rows: list[StanceRow] = []
    # 官方簇：全 loss/neutral（程式化），市场簇：混 stance
    for _i in range(4):
        rows.append(row("gov", "fed", FrameLabel.LOSS, StanceLabel.NEUTRAL))
    rows.append(row("wire", "fed", FrameLabel.GAIN, StanceLabel.SUPPORTIVE))
    rows.append(row("wire", "fed", FrameLabel.GAIN, StanceLabel.SUPPORTIVE))
    rows.append(row("press", "fed", FrameLabel.LOSS, StanceLabel.CRITICAL))
    rows.append(row("press", "trump", FrameLabel.CONFLICT, StanceLabel.CRITICAL))
    rows.append(row("gov", "trump", FrameLabel.OTHER, StanceLabel.NEUTRAL))
    return rows


def test_cluster_distributions_by_tier() -> None:
    dist = cluster_distributions(_rows(), TIER)
    assert set(dist) == {"L1", "L2", "L3"}
    assert dist["L1"]["loss"] > dist["L1"]["gain"]  # 官方程式化 loss 主导
    assert dist["L2"]["gain"] > dist["L2"]["loss"]


def test_cluster_pairwise_official_market_top() -> None:
    pairs = cluster_pairwise(_rows(), TIER)
    assert pairs, "有 3 簇应产生 3 个簇对"
    top = pairs[0]
    assert top["official_vs_market"] is True  # 官方-市场温差排在最前
    assert all({"a", "b", "jsd", "n_a", "n_b"} <= set(p) for p in pairs)


def test_entity_opposition_gap_ranking() -> None:
    opp = entity_opposition(_rows(), TIER)
    assert opp and opp[0]["entity_id"] == "fed"  # fed 双侧有样本且对立最大
    top = opp[0]
    assert top["n_official"] == 4 and top["n_market"] == 3
    assert top["gap"] > 0
    # trump 两侧也有样本（1 vs 1）
    assert any(o["entity_id"] == "trump" for o in opp)
