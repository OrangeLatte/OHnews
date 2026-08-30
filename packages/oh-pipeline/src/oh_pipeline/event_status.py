"""事件状态推导（RECONSTRUCTION §C/D）：纯规则，无 LLM。

四态判定（保守默认，P6）：
- confirmed  = ≥1 primary 源 + ≥3 独立源（且 primary 间无高分歧）
- contested  = ≥2 primary 源的框架分布冲突（JSD ≥ 阈值）
- developing = ≥3 独立源但无 primary 佐证
- unverified = 独立源 < 3（样本不足，默认保守态）

contested 用官方（primary）源间框架分布的 JSD 距离度量"立场冲突"：
复用 divergence 的 Dirichlet 平滑 + JS 距离；primary 源中有立场行的
不足两个时无法判定冲突，落回 confirmed（诚实弃权，不猜）。

PIT 纪律：调用方必须保证 evidence 与 stance_rows 只含 ts ≤ as_of 的数据。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from oh_contracts.enums import FrameLabel
from oh_contracts.narrative import (
    EventAssessment,
    EventStatus,
    EvidenceItem,
    EvidenceRole,
    EvidenceStrength,
)
from oh_contracts.schemas import StanceRow

from oh_pipeline.divergence import dirichlet_smooth, js_divergence
from oh_pipeline.evidence import assess_strength

CONTESTED_JSD_THRESHOLD = 0.5
"""官方源间框架分布 JSD 距离的冲突判定门（≥ 判 contested）。"""

_COVERAGE_SOURCES = 8
"""源覆盖饱和点（同 §H 的 min(n_sources/8, 1)）。"""


def _official_conflict(
    stance_rows: Sequence[StanceRow],
    primary_sources: set[str],
) -> float | None:
    """primary 源间两两 JSD 的最大值；有立场行的 primary 源不足 2 个时弃权。"""
    by_source: dict[str, list[StanceRow]] = defaultdict(list)
    for row in stance_rows:
        if row.source_id in primary_sources:
            by_source[row.source_id].append(row)
    dists: list[dict[FrameLabel, float]] = []
    for rows in by_source.values():
        counts: dict[FrameLabel, int] = defaultdict(int)
        for row in rows:
            counts[row.frame] += 1
        dists.append(dirichlet_smooth(counts))
    if len(dists) < 2:
        return None
    return max(
        js_divergence(dists[i], dists[j])
        for i in range(len(dists))
        for j in range(i + 1, len(dists))
    )


def derive_status(
    evidence: Sequence[EvidenceItem],
    stance_rows: Sequence[StanceRow] = (),
) -> tuple[EventStatus, float | None]:
    """四态推导：返回 (status, contested_jsd)。纯规则可复现。"""
    sources = {e.source_id for e in evidence}
    primary = {e.source_id for e in evidence if e.role is EvidenceRole.PRIMARY}
    if len(sources) < 3:
        return EventStatus.UNVERIFIED, None
    if not primary:
        return EventStatus.DEVELOPING, None
    jsd = _official_conflict(stance_rows, primary)
    if jsd is not None and jsd >= CONTESTED_JSD_THRESHOLD:
        return EventStatus.CONTESTED, jsd
    return EventStatus.CONFIRMED, jsd


def _confidence(n_sources: int, n_primary: int) -> float:
    """评估置信度 = 源覆盖与 primary 佐证覆盖的等权组合（确定性、可复现）。"""
    coverage = min(n_sources / _COVERAGE_SOURCES, 1.0)
    primary_coverage = min(n_primary / 2, 1.0)
    return round(0.5 * coverage + 0.5 * primary_coverage, 3)


def assess_event(
    event_id: str,
    evidence: Sequence[EvidenceItem],
    stance_rows: Sequence[StanceRow] = (),
) -> EventAssessment:
    """事件级情报评估（Event 页 07 段 + 首页卡同源；engine=offline 诚实标注）。"""
    sources = {e.source_id for e in evidence}
    primary = {e.source_id for e in evidence if e.role is EvidenceRole.PRIMARY}
    status, jsd = derive_status(evidence, stance_rows)
    strength: EvidenceStrength = assess_strength(evidence)
    if status is EventStatus.CONFIRMED:
        observation = f"事件经 {len(sources)} 个独立源报道，其中 {len(primary)} 个官方一手源佐证"
    elif status is EventStatus.CONTESTED:
        observation = f"{len(primary)} 个官方一手源对事件的框架存在分歧（官方簇 JSD={jsd:.2f}）"
    elif status is EventStatus.DEVELOPING:
        observation = f"事件获 {len(sources)} 个独立源报道，但暂无官方一手源佐证"
    else:
        observation = f"独立源不足（{len(sources)} 个），事件处于默认保守态"
    return EventAssessment(
        event_id=event_id,
        status=status,
        confidence=_confidence(len(sources), len(primary)),
        evidence_strength=strength,
        n_independent_sources=len(sources),
        n_primary_sources=len(primary),
        observation=observation,
        engine="offline",
    )
