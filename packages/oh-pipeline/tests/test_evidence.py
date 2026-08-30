"""证据层测试：role 映射 / provenance 构建 / 强度四档。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oh_contracts.enums import SourceTier
from oh_contracts.ids import make_item_key
from oh_contracts.narrative import EvidenceItem, EvidenceRole, EvidenceStrength
from oh_contracts.schemas import BronzeRecord
from oh_pipeline.evidence import assess_strength, build_evidence, role_for_tier

T0 = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
TIER_MAP = {
    "gov": SourceTier.OFFICIAL,
    "gov2": SourceTier.OFFICIAL,
    "wire": SourceTier.WIRE,
    "press": SourceTier.FINANCIAL_PRESS,
    "social": SourceTier.SOCIAL,
}


def _rec(
    source: str,
    idx: int,
    *,
    title: str = "央行宣布下调政策利率",
    published: datetime | None = T0,
) -> BronzeRecord:
    return BronzeRecord(
        source_id=source,
        item_key=make_item_key(source, f"{source}-{idx}", str(published)),
        external_id=f"{source}-{idx}",
        url_hash="u:t",
        content_hash="c:t",
        fetched_at=T0 + timedelta(hours=1),
        published_at=published,
        raw={},
        normalized={"title": title, "body": "正文内容"},
    )


def _item(source: str, role: EvidenceRole, *, idx: int = 0) -> EvidenceItem:
    return EvidenceItem(
        item_key=f"{source}:{idx}",
        source_id=source,
        role=role,
        quote="quote",
        published_at=T0,
    )


def test_role_for_tier_mapping() -> None:
    assert role_for_tier(SourceTier.OFFICIAL) is EvidenceRole.PRIMARY
    assert role_for_tier(SourceTier.WIRE) is EvidenceRole.SECONDARY
    assert role_for_tier(SourceTier.FINANCIAL_PRESS) is EvidenceRole.COMMENTARY
    assert role_for_tier(SourceTier.SOCIAL) is EvidenceRole.SOCIAL


def test_build_evidence_skips_unanchored_and_unknown_tier() -> None:
    empty = _rec("wire", 4, title="")
    empty.normalized["body"] = ""
    records = [
        _rec("gov", 1),
        _rec("unknown", 2),  # tier_map 未登记
        _rec("press", 3, published=None),  # PIT 锚缺失
        empty,  # 无可用文本
        _rec("social", 5),
    ]
    items = build_evidence(records, TIER_MAP)
    assert [e.source_id for e in items] == ["gov", "social"]


def test_build_evidence_truncates_quote_and_sorts_deterministically() -> None:
    long_title = "长" * 900
    records = [
        _rec("social", 2, published=T0 + timedelta(hours=1)),
        _rec("gov", 1, title=long_title),
    ]
    items = build_evidence(records, TIER_MAP)
    assert [e.source_id for e in items] == ["gov", "social"]  # (published_at, item_key) 序
    assert len(items[0].quote) == 400
    assert items[0].item_key == make_item_key("gov", "gov-1", str(T0))
    # 重跑幂等
    assert build_evidence(records, TIER_MAP) == items


def test_strength_insufficient_below_two_sources() -> None:
    items = [_item("gov", EvidenceRole.PRIMARY)]
    assert assess_strength(items) is EvidenceStrength.INSUFFICIENT
    assert assess_strength([]) is EvidenceStrength.INSUFFICIENT


def test_strength_limited_two_sources_or_single_tier() -> None:
    two_sources = [_item("gov", EvidenceRole.PRIMARY), _item("press", EvidenceRole.COMMENTARY)]
    assert assess_strength(two_sources) is EvidenceStrength.LIMITED
    single_tier = [_item(f"press{i}", EvidenceRole.COMMENTARY) for i in range(4)]
    assert assess_strength(single_tier) is EvidenceStrength.LIMITED


def test_strength_moderate_three_sources_two_tiers() -> None:
    items = [
        _item("gov", EvidenceRole.PRIMARY),
        _item("press1", EvidenceRole.COMMENTARY),
        _item("press2", EvidenceRole.COMMENTARY),
    ]
    assert assess_strength(items) is EvidenceStrength.MODERATE


def test_strength_strong_two_primary() -> None:
    items = [_item("gov", EvidenceRole.PRIMARY), _item("gov2", EvidenceRole.PRIMARY)]
    assert assess_strength(items) is EvidenceStrength.STRONG


def test_strength_strong_five_sources_three_tiers() -> None:
    items = [
        _item("press1", EvidenceRole.COMMENTARY),
        _item("press2", EvidenceRole.COMMENTARY),
        _item("press3", EvidenceRole.COMMENTARY),
        _item("wire", EvidenceRole.SECONDARY),
        _item("social", EvidenceRole.SOCIAL),
    ]
    assert assess_strength(items) is EvidenceStrength.STRONG


def test_strength_score_mapping() -> None:
    assert EvidenceStrength.STRONG.score == 1.0
    assert EvidenceStrength.MODERATE.score == 0.7
    assert EvidenceStrength.LIMITED.score == 0.4
    assert EvidenceStrength.INSUFFICIENT.score == 0.0
