"""证据层（RECONSTRUCTION §C/P7/P8）：Bronze 记录 → EvidenceItem + 强度分档。

role 标注（tier→role 一一映射，F-05）：L1 官方→primary / L2 通讯社→secondary
/ L3 财媒→commentary / L4 社媒→social。
分档规则（RECONSTRUCTION §C，纯规则可复现）：
- strong       = ≥2 primary 源 或 ≥5 独立源跨 ≥3 tier
- moderate     = ≥3 独立源跨 ≥2 tier
- limited      = 恰 2 源 或 单一 tier（含其余未达上两档的组合）
- insufficient = <2 源（= 弃权语义，IS 门禁封顶 40 的输入）

诚实边界：tier_map 未覆盖的源不进证据（不虚构 role）；published_at 缺失
的记录跳过（PIT 纪律，同 events.py 裁决 C 语义）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from oh_contracts.enums import SourceTier
from oh_contracts.narrative import EvidenceItem, EvidenceRole, EvidenceStrength
from oh_contracts.schemas import BronzeRecord

_TIER_TO_ROLE: dict[SourceTier, EvidenceRole] = {
    SourceTier.OFFICIAL: EvidenceRole.PRIMARY,
    SourceTier.WIRE: EvidenceRole.SECONDARY,
    SourceTier.FINANCIAL_PRESS: EvidenceRole.COMMENTARY,
    SourceTier.SOCIAL: EvidenceRole.SOCIAL,
}

_QUOTE_MAX = 400  # 与 EvidenceItem.quote 字段约束一致


def role_for_tier(tier: SourceTier) -> EvidenceRole:
    """tier→role 固定映射（RECONSTRUCTION F-05）。"""
    return _TIER_TO_ROLE[tier]


def build_evidence(
    records: Iterable[BronzeRecord],
    tier_map: Mapping[str, SourceTier],
) -> list[EvidenceItem]:
    """Bronze 记录流 → 证据条目（quote=title 优先，截断至 400 字符）。

    published_at 缺失或 tier 未登记的记录跳过；输出按 (published_at,
    item_key) 确定性排序，重跑幂等。
    """
    items: list[EvidenceItem] = []
    for rec in records:
        tier = tier_map.get(rec.source_id)
        if tier is None or rec.published_at is None:
            continue
        normalized = rec.normalized or {}
        text = str(normalized.get("title") or normalized.get("body") or "").strip()
        if not text:
            continue
        items.append(
            EvidenceItem(
                item_key=rec.item_key,
                source_id=rec.source_id,
                role=role_for_tier(tier),
                quote=text[:_QUOTE_MAX],
                published_at=rec.published_at,
            )
        )
    items.sort(key=lambda e: (e.published_at, e.item_key))
    return items


def assess_strength(evidence: Sequence[EvidenceItem]) -> EvidenceStrength:
    """证据强度四档纯函数（规则见模块 docstring）。

    tier 信息经 role 反推（tier↔role 一一映射），故只需证据条目本身；
    源数按 source_id 去重（独立源语义），role 覆盖按条目集合去重。
    """
    sources = {e.source_id for e in evidence}
    n_sources = len(sources)
    if n_sources < 2:
        return EvidenceStrength.INSUFFICIENT
    roles = {e.role for e in evidence}
    n_primary = len({e.source_id for e in evidence if e.role is EvidenceRole.PRIMARY})
    if n_primary >= 2 or (n_sources >= 5 and len(roles) >= 3):
        return EvidenceStrength.STRONG
    if n_sources >= 3 and len(roles) >= 2:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.LIMITED
