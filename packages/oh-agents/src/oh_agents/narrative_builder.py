"""Narrative Builder（RECONSTRUCTION §C P4）：框架计数之上的"人们在相信什么"。

输入：某实体近窗 stance 行（调用方保证 PIT：只含 ts ≤ as_of 的行）+ 可选
前窗 baseline 行（用于主导框架迁移方向与 ΔNDI 对照）。
本模块为离线路径：确定性模板句，engine="offline" 诚实标注；LLM 路径
（strategic tier，抽 1-3 条叙事）由后续编排接入，接口返回 list 预留。

措辞纪律：NDI = 叙事分歧指数，描述性监测指标。

弃权纪律（RECONSTRUCTION §D）：近窗 stance 行 < min_samples → 不产出，
不硬凑；全部行 ABSTAIN（无框架可述）同样弃权。

确定性与幂等：同输入同参数 → narrative_id（nar-{entity}-{window}）与
全部字段逐位一致（计数平票按 FrameLabel 枚举序、item_keys 排序、
momentum 阈值固定）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from oh_contracts.constants import N_MIN_SAMPLES
from oh_contracts.enums import FrameLabel, SourceTier, StanceLabel
from oh_contracts.narrative import NarrativeMomentum, NarrativeStatement
from oh_contracts.schemas import StanceRow
from oh_pipeline.divergence import ndi_for_event

_MIN_MOMENTUM_ROWS = 4
_RISING_SHARE = 0.6
_FADING_SHARE = 0.4
_DELTA_EPS = 0.005

_CLUSTER_ZH: dict[str, str] = {
    "official": "官方",
    "financial_press": "财经媒体",
    "social": "社媒",
    "mixed": "官方与市场混合",
}
_FRAME_ZH: dict[FrameLabel, str] = {
    FrameLabel.LOSS: "损失",
    FrameLabel.GAIN: "收益",
    FrameLabel.RESPONSIBILITY: "责任",
    FrameLabel.CONFLICT: "冲突",
    FrameLabel.HUMAN_INTEREST: "人情",
    FrameLabel.OTHER: "其他",
}
_MOMENTUM_ZH: dict[NarrativeMomentum, str] = {
    NarrativeMomentum.RISING: "叙事热度上升",
    NarrativeMomentum.STEADY: "叙事热度平稳",
    NarrativeMomentum.FADING: "叙事热度回落",
}

_FRAMES: tuple[FrameLabel, ...] = tuple(FrameLabel)


def _dominant_frame(rows: Sequence[StanceRow]) -> FrameLabel | None:
    """非弃权行的主导框架；平票按枚举序取先（确定性），全弃权返回 None。"""
    counts: dict[FrameLabel, int] = {}
    for r in rows:
        if r.stance == StanceLabel.ABSTAIN:
            continue
        counts[r.frame] = counts.get(r.frame, 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda f: (-counts[f], _FRAMES.index(f)))


def _source_cluster(rows: Sequence[StanceRow], tier_map: Mapping[str, SourceTier]) -> str:
    """叙事来源簇：窗口内出现过的 tier 集合 → 契约四值。

    official=仅 L1；financial_press=仅 L2/L3（通讯社与财经媒体）；
    social=仅 L4；其余（跨 official/market 或混入 L4）= mixed。
    """
    tiers = {tier_map.get(r.source_id) for r in rows} - {None}
    if tiers <= {SourceTier.OFFICIAL}:
        return "official"
    if tiers <= {SourceTier.WIRE, SourceTier.FINANCIAL_PRESS}:
        return "financial_press"
    if tiers == {SourceTier.SOCIAL}:
        return "social"
    return "mixed"


def _momentum(rows: Sequence[StanceRow]) -> NarrativeMomentum:
    """叙事动量 v1：窗口内时间密度近似（后半帧行数占比）。

    局限（如实标注）：纯时序密度，不含语义强度与跨窗对照；样本 < 4 或
    时间跨度为 0 → STEADY。
    """
    if len(rows) < _MIN_MOMENTUM_ROWS:
        return NarrativeMomentum.STEADY
    srt = sorted(rows, key=lambda r: r.ts)
    span = srt[-1].ts - srt[0].ts
    if span <= timedelta(0):
        return NarrativeMomentum.STEADY
    cut = srt[0].ts + span / 2
    later = sum(1 for r in srt if r.ts >= cut)
    share = later / len(srt)
    if share > _RISING_SHARE:
        return NarrativeMomentum.RISING
    if share < _FADING_SHARE:
        return NarrativeMomentum.FADING
    return NarrativeMomentum.STEADY


def _narrative_confidence(n_sources: int, n_primary: int) -> float:
    """与 oh_pipeline.event_status 同式：0.5·min(n/8,1) + 0.5·min(n_primary/2,1)。"""
    return round(0.5 * min(n_sources / 8, 1.0) + 0.5 * min(n_primary / 2, 1.0), 3)


def _ndi_point(
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    as_of: datetime,
) -> float | None:
    """跨簇分歧点值；门禁不过（弃权）返回 None。n_boot=1 只取点值不采 CI。"""
    return ndi_for_event(rows, tier_map, as_of, n_boot=1).ndi


def build_narrative(
    entity_id: str,
    window: str,
    rows: Sequence[StanceRow],
    tier_map: Mapping[str, SourceTier],
    *,
    as_of: datetime,
    baseline_rows: Sequence[StanceRow] | None = None,
    min_samples: int = N_MIN_SAMPLES,
) -> list[NarrativeStatement]:
    """离线构建实体叙事（v1 单条主导叙事，接口返回 list 预留 LLM 1-3 条）。

    PIT 纪律：调用方保证 rows 与 baseline_rows 只含 ts ≤ as_of 的行；
    first_seen 取窗口内最早行 ts（必为历史，无前视）。
    """
    if len(rows) < min_samples:
        return []
    dominant = _dominant_frame(rows)
    if dominant is None:
        return []

    n_rows = len(rows)
    n_abstain = sum(1 for r in rows if r.stance == StanceLabel.ABSTAIN)
    share = (n_rows - n_abstain) / n_rows
    cluster = _source_cluster(rows, tier_map)
    momentum = _momentum(rows)

    source_ids = {r.source_id for r in rows}
    n_sources = len(source_ids)
    n_primary = sum(1 for s in source_ids if tier_map.get(s) == SourceTier.OFFICIAL)
    confidence = _narrative_confidence(n_sources, n_primary)
    ndi_measured = _ndi_point(rows, tier_map, as_of)
    divergence = ndi_measured if ndi_measured is not None else 0.0

    parts = [
        f"「{entity_id}」近窗{n_rows}行报道以{_CLUSTER_ZH[cluster]}为主，"
        f"主导框架为「{_FRAME_ZH[dominant]}」（占非弃权行 {share:.0%}）"
    ]
    if baseline_rows and len(baseline_rows) >= min_samples:
        baseline_dominant = _dominant_frame(baseline_rows)
        if baseline_dominant is not None:
            if baseline_dominant == dominant:
                parts.append(f"与前窗主导框架一致（{_FRAME_ZH[baseline_dominant]}）")
            else:
                parts.append(
                    f"较前窗由「{_FRAME_ZH[baseline_dominant]}」迁移至「{_FRAME_ZH[dominant]}」"
                )
            baseline_ndi = _ndi_point(baseline_rows, tier_map, as_of)
            if baseline_ndi is not None and ndi_measured is not None:
                delta = round(ndi_measured - baseline_ndi, 4)
                if abs(delta) >= _DELTA_EPS:
                    direction = "上升" if delta > 0 else "回落"
                    parts.append(f"叙事分歧较前窗{direction} {abs(delta):.2f}")
    if ndi_measured is not None:
        parts.append(f"官方-市场叙事分歧 NDI={divergence:.2f}")
    else:
        parts.append("官方-市场叙事分歧暂不可测（样本门未过，保守记 0）")
    statement = "；".join(parts) + f"，{_MOMENTUM_ZH[momentum]}。"

    return [
        NarrativeStatement(
            narrative_id=f"nar-{entity_id}-{window}",
            statement=statement,
            entity_id=entity_id,
            event_ids=sorted({r.event_id for r in rows}),
            supporting_item_keys=sorted(
                {r.item_key for r in rows if r.stance == StanceLabel.SUPPORTIVE}
            ),
            opposing_item_keys=sorted(
                {r.item_key for r in rows if r.stance == StanceLabel.CRITICAL}
            ),
            source_cluster=cluster,
            momentum=momentum,
            confidence=confidence,
            divergence=divergence,
            first_seen=min(r.ts for r in rows),
            window=window,
            engine="offline",
        )
    ]
