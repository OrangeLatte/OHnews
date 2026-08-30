"""Insight Generator（RECONSTRUCTION §C P5）：五段强制，永不把指标当结论。

输入：一个增强后 Signal（M2c detect_signals 产物，metrics 含
"intelligence_score"）+ 可选关联 EventAssessment（M2a）与
NarrativeStatement（M2d）。本模块为离线路径：确定性模板句，
engine="offline" 诚实标注；LLM 路径由后续编排接入。

措辞纪律：NDI = 叙事分歧指数，描述性监测指标——解释层明确标注
"非预测器"，禁止任何前瞻性断言。

保守纪律：evidence_strength 取关联评估中最保守的一档；无关联评估时
诚实记 INSUFFICIENT，不借用 signal 强度冒充证据强度。

备择纪律：alternative_explanations 强制 ≥1 条（契约门禁），离线模板
按信号种类给出确定性备择解释，保证永不空。

确定性与幂等：同输入同 now → 全部字段逐位一致；备择解释顺序固定。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from oh_contracts.narrative import EventAssessment, EvidenceStrength, Insight, NarrativeStatement
from oh_contracts.signals import Signal, SignalKind

_STRENGTH_BY_CONSERVATISM: tuple[EvidenceStrength, ...] = (
    EvidenceStrength.INSUFFICIENT,
    EvidenceStrength.LIMITED,
    EvidenceStrength.MODERATE,
    EvidenceStrength.STRONG,
)

_KIND_ZH: dict[SignalKind, str] = {
    SignalKind.ATTENTION_SPIKE: "注意力聚集",
    SignalKind.NARRATIVE_SHIFT: "叙事转变",
    SignalKind.NDI_ALERT: "叙事分歧升高",
    SignalKind.EXPECTATION_GAP: "官方与市场预期错位",
}

_STATUS_ZH: dict[str, str] = {
    "confirmed": "已证实",
    "contested": "存争议",
    "developing": "进展中",
    "unverified": "未证实",
}

_FALLBACK_OBSERVATION = "信号触发的量化指标变化已记录，等待更多上下文。"
_WATCH_NEXT = "关注下一窗内该指标是否延续当前方向，以及官方一手源是否跟进报道。"


def _conservative_strength(assessments: Sequence[EventAssessment]) -> EvidenceStrength:
    """取关联评估中最保守的 evidence_strength；无评估 → INSUFFICIENT（诚实保守）。"""
    if not assessments:
        return EvidenceStrength.INSUFFICIENT
    present = {a.evidence_strength for a in assessments}
    for strength in _STRENGTH_BY_CONSERVATISM:
        if strength in present:
            return strength
    return EvidenceStrength.INSUFFICIENT


def _alternative_explanations(signal: Signal, contested: bool) -> list[str]:
    """按信号种类给确定性备择解释；通用条兜底，永不空（契约 ≥1 门禁）。"""
    alternatives: list[str] = []
    if signal.kind is SignalKind.NDI_ALERT:
        alternatives.append("叙事分歧升高可能来自各源簇措辞风格差异，而非实质性立场对立。")
    elif signal.kind is SignalKind.EXPECTATION_GAP:
        alternatives.append(
            "官方与市场的表述差异可能源于官方措辞一贯稳健或刻意模糊，而非真实预期错位。"
        )
    elif signal.kind is SignalKind.NARRATIVE_SHIFT:
        alternatives.append("主导框架迁移可能由少数新增源驱动，样本结构变化未必代表整体叙事转向。")
    elif signal.kind is SignalKind.ATTENTION_SPIKE:
        alternatives.append("报道量聚集可能由例行发布或转载潮驱动，而非实体重要性的真实变化。")
    if contested:
        alternatives.append("官方源之间的框架分歧可能反映事件本身复杂性与多方立场，而非信息不实。")
    alternatives.append("信号可能源于短期数据波动（小样本噪声），观察窗延长后可能自行消退。")
    return alternatives


def _interpretation(
    signal: Signal, assessments: Sequence[EventAssessment], narratives: Sequence[NarrativeStatement]
) -> str:
    """解释层模板：评估状态 + 叙事摘引 + NDI 措辞纪律（描述性、非预测器）。"""
    parts: list[str] = []
    if assessments:
        counts: dict[str, int] = {}
        for a in assessments:
            key = a.status.value if hasattr(a.status, "value") else str(a.status)
            counts[key] = counts.get(key, 0) + 1
        summary = "、".join(
            f"{_STATUS_ZH.get(status, status)} {n} 个" for status, n in sorted(counts.items())
        )
        parts.append(f"关联事件评估：{summary}。")
    if narratives:
        parts.append(f"当前叙事层观察：{narratives[0].statement}")
    if signal.kind is SignalKind.NDI_ALERT:
        parts.append(
            "该指标为叙事分歧指数（NDI），仅描述当期信息源之间的讲述分歧程度，非预测器，不构成方向性判断。"
        )
    return " ".join(parts) if parts else "暂无关联评估与叙事层信息，仅记录信号本身。"


def generate_insight(
    signal: Signal,
    *,
    assessments: Sequence[EventAssessment] = (),
    narratives: Sequence[NarrativeStatement] = (),
    now: datetime,
) -> Insight:
    """由增强 Signal（+关联评估/叙事）生成一条 Insight（离线模板路径）。

    PIT 纪律：内容仅消费 signal.as_of 及更早信息；generated_at=now 仅是
    生成时间戳，不参与任何计算。
    """
    is_score = signal.metrics.get("intelligence_score", float(signal.strength))
    is_score = round(min(100.0, max(0.0, float(is_score))), 1)
    kind_zh = _KIND_ZH.get(signal.kind, str(signal.kind))

    baseline = signal.baseline
    current = signal.current_value
    observation = signal.what_changed
    if baseline is not None and current is not None:
        observation = f"{observation}（基线 {baseline:g} → 当前 {current:g}）"
    if len(observation) < 8:
        observation = _FALLBACK_OBSERVATION

    headline = f"「{signal.entity_id}」{kind_zh}信号（智能分 {is_score:g}）"

    contested = any(
        (a.status.value if hasattr(a.status, "value") else str(a.status)) == "contested"
        for a in assessments
    )

    return Insight(
        insight_id=f"ins-{signal.signal_id}",
        headline=headline,
        observation=observation,
        interpretation=_interpretation(signal, assessments, narratives),
        evidence_strength=_conservative_strength(assessments),
        alternative_explanations=_alternative_explanations(signal, contested),
        what_changed=signal.what_changed,
        why_it_matters=signal.why_it_matters,
        what_to_watch_next=_WATCH_NEXT,
        related_signal_ids=[signal.signal_id],
        related_event_ids=sorted({a.event_id for a in assessments}),
        related_narrative_ids=sorted({n.narrative_id for n in narratives}),
        intelligence_score=is_score,
        engine="offline",
        generated_at=now,
        as_of=signal.as_of,
    )
