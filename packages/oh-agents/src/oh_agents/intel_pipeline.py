"""Daily Intel 编排（RECONSTRUCTION §D 管道顺序，M2f 接线层）。

Event Status（纯规则）→ Signal Detection + 增强（M2c）→ Narrative
Modeling（M2d）→ Insight Generation（M2e）。本模块只做编排与关联，
不新增任何指标计算；落位 oh-agents 因依赖方向单向
（oh-agents → oh-pipeline → oh-contracts）。

PIT 纪律：一切输入经 store.stances_asof/ events_asof（as_of 截断）；
bronze 侧仅消费 published_at ≤ as_of 的 provenance 反查。
generated_at = as_of（同 as_of 重跑逐位幂等，审计纪律）；
LLM 路径接入时由编排层传实际时钟替代。

关联语义：Signal.evidence_ids 混含 item_key（narrative_shift，P8 修复后）
与 event_id（ndi_alert / expectation_gap）；Insight 关联事件 = 直接命中
evidence_ids 的评估 ∪ 实体同窗共现（EventRecord.entities 与 stance 行）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from oh_contracts.constants import N_MIN_SAMPLES, PIT_LOOKBACK_DAYS
from oh_contracts.enums import SourceTier
from oh_contracts.narrative import EventAssessment, Insight, NarrativeStatement
from oh_contracts.schemas import BronzeRecord, StanceRow
from oh_contracts.signals import Signal
from oh_pipeline.detect import detect_signals
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.event_status import assess_event
from oh_pipeline.evidence import build_evidence

from oh_agents.insight_generator import generate_insight
from oh_agents.narrative_builder import build_narrative


@dataclass(frozen=True)
class DailyIntel:
    """一次日频情报产出的全部中间层与顶层对象（顺序即展示序）。"""

    as_of: datetime
    assessments: tuple[EventAssessment, ...]
    signals: tuple[Signal, ...]
    narratives: tuple[NarrativeStatement, ...]
    insights: tuple[Insight, ...]


def build_daily_intel(
    bronze_iter: Sequence[BronzeRecord],
    store: Mapping[str, object],
    registry: EntityRegistry,
    tier_map: Mapping[str, SourceTier],
    *,
    as_of: datetime,
    lookback_days: int = PIT_LOOKBACK_DAYS,
    min_per_source: int = 2,
    top_n: int = 10,
    narrative_min_samples: int = N_MIN_SAMPLES,
) -> DailyIntel:
    """对 as_of 截断的世界状态跑完整 M2 情报层，产出确定性 DailyIntel。

    弃权语义逐层保留：样本不足的事件 → unverified 评估；不足样本门的
    实体 → 无叙事；无证据的信号 → IS 封顶 40 的 Insight。
    """
    bronze_list = list(bronze_iter)
    bronze_index = {rec.item_key: rec for rec in bronze_list}
    rows: list[StanceRow] = list(store.stances_asof(as_of))
    events = list(store.events_asof(as_of))

    signals = detect_signals(
        bronze_list,
        store,
        registry,
        tier_map,
        as_of,
        min_per_source=min_per_source,
        top_n=top_n,
    )

    rows_by_entity: dict[str, list[StanceRow]] = {}
    rows_by_event: dict[str, list[StanceRow]] = {}
    for r in rows:
        rows_by_entity.setdefault(r.entity_id, []).append(r)
        rows_by_event.setdefault(r.event_id, []).append(r)

    # —— Event Status 层：事件证据 = stance provenance item_key 反查 bronze ——
    assessments: list[EventAssessment] = []
    for eid in sorted({e.event_id for e in events} | set(rows_by_event)):
        ev_rows = rows_by_event.get(eid, [])
        records = [
            bronze_index[k] for k in dict.fromkeys(r.item_key for r in ev_rows) if k in bronze_index
        ]
        assessments.append(
            assess_event(eid, build_evidence(records, tier_map), stance_rows=ev_rows)
        )

    # —— Narrative 层：实体近窗 vs 等长前窗（框架迁移 + ΔNDI 对照）——
    window_start = as_of - timedelta(days=lookback_days)
    base_start = window_start - timedelta(days=lookback_days)
    window_label = f"{window_start:%Y-%m-%d}/{as_of:%Y-%m-%d}"
    narratives: list[NarrativeStatement] = []
    for entity in sorted(rows_by_entity):
        cur = [r for r in rows_by_entity[entity] if r.ts >= window_start]
        base = [r for r in rows_by_entity[entity] if base_start <= r.ts < window_start]
        narratives += build_narrative(
            entity,
            window_label,
            cur,
            tier_map,
            as_of=as_of,
            baseline_rows=base,
            min_samples=narrative_min_samples,
        )
    narratives.sort(key=lambda n: n.narrative_id)

    # —— Insight 层：Top-N 信号 ×（evidence_ids 命中 ∪ 实体同窗共现）评估/叙事 ——
    event_entities: dict[str, set[str]] = {}
    for e in events:
        event_entities.setdefault(e.event_id, set()).update(e.entities)
    for r in rows:
        event_entities.setdefault(r.event_id, set()).add(r.entity_id)

    insights: list[Insight] = []
    for sig in signals:
        related = [
            a
            for a in assessments
            if a.event_id in sig.evidence_ids
            or sig.entity_id in event_entities.get(a.event_id, set())
        ]
        rel_narrs = [n for n in narratives if n.entity_id == sig.entity_id]
        insights.append(generate_insight(sig, assessments=related, narratives=rel_narrs, now=as_of))

    return DailyIntel(
        as_of=as_of,
        assessments=tuple(assessments),
        signals=tuple(signals),
        narratives=tuple(narratives),
        insights=tuple(insights),
    )
