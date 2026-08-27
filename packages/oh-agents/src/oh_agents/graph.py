"""analysis_graph（蓝图图2，裁决 A 拓扑）：纯统计分歧 + LLM 只读解释层。

不变量（裁决 A）：NDI 数据仅来自 stance_table（Tagger 产出），
LLM 输出（假设/解释卡）只读、永不写回分歧度量。

结构：主图 plan_batch → Send 并行分发每事件到 event_pipeline 子图
（私有 EventState：tagger → divergence → calibration → hypothesis →
interpret → gate），子图输出经 reducer 汇入主图 AnalysisState。

- tagger：规则层 + 官方源 LLM 补盲（成本受 max_llm_fills 硬约束）
- divergence：Dirichlet JSD NDI + 样本门弃权（oh_pipeline.divergence）
- calibration：历史分位对比（<5 历史点 → cold_start）
- hypothesis/interpret：strategic/execute tier 只读；router=None 时跳过
- gate：低置信 + enable_hitl → interrupt（HITL 审核队列入口）
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send
from oh_contracts.constants import PIT_LOOKBACK_DAYS
from oh_contracts.enums import SourceTier, Tier
from oh_contracts.schemas import (
    BronzeRecord,
    EventRecord,
    Hypothesis,
    NarrativeCard,
    NDIPoint,
    StanceRow,
)
from oh_pipeline.divergence import ndi_for_event, temperature_gap
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.tagger import RuleTagger
from oh_storage.protocols import BronzeWriter, GoldReader, SilverStore

from oh_agents.state import AnalysisState, CalibrationEntry
from oh_agents.tagger_llm import LLMTagger

HYPOTHESIS_PROMPT = """\\
你是叙事分析假设生成器。输入：事件 + NDI（叙事分歧指数，描述性统计）+ 各信源簇框架分布。
产出 1 条可检验的假设：claim（一句话）+ drivers（2-4 条驱动因素）+ cite（引用的信源 source_id）。
规则：只基于给定数据；NDI 弃权时如实说明数据不足；不做收益预测。
"""


@dataclass
class GraphDeps:
    """图依赖注入（仓储/路由器/可替换函数；测试用 fake 注入）。"""

    bronze: BronzeWriter
    store: SilverStore
    gold: GoldReader
    tier_map: Mapping[str, SourceTier]
    registry: EntityRegistry = field(default_factory=EntityRegistry)
    router: Any = None  # ModelRouter | None（None=纯统计图，跳过 LLM 节点）
    llm_tagger: LLMTagger | None = None
    hypothesis_fn: Callable[..., Awaitable[Hypothesis | None]] | None = None
    interpret_fn: Callable[..., Awaitable[NarrativeCard | None]] | None = None
    lookback_days: int = PIT_LOOKBACK_DAYS
    min_per_source: int = 2
    max_llm_fills_per_event: int = 4
    enable_hitl: bool = False
    low_confidence_threshold: float = 0.5
    checkpointer: Any = None
    lang_map: Mapping[str, str] | None = None  # source_id → language（within-language）
    languages: tuple[str, ...] | None = None  # None=混算单点 "all"


class EventState(TypedDict, total=False):
    """每事件子图私有 state（单事件顺序链：每 key 单写者，LastValue 覆盖即可）。

    与主图 AnalysisState 的同名 key（ndi_points/calibrations/hypotheses/
    narrative_cards/pending_interrupt）自动映射；stance_rows/event/as_of/gaps
    为子图私有，不回写主图。
    """

    event: dict[str, Any]
    as_of: str
    stance_rows: list[StanceRow]
    ndi_points: list[NDIPoint]
    calibrations: list[CalibrationEntry]
    hypotheses: list[Hypothesis]
    narrative_cards: list[dict[str, Any]]
    gaps: list[float | None]
    pending_interrupt: list[dict[str, Any]]


def _event(state: EventState) -> EventRecord:
    return EventRecord.model_validate(state["event"])


def _as_of(state: EventState) -> datetime:
    return datetime.fromisoformat(state["as_of"])


def _window_records(
    bronze: BronzeWriter, event: EventRecord, as_of: datetime, lookback_days: int
) -> list[BronzeRecord]:
    start = as_of - timedelta(days=lookback_days)
    return [
        r
        for r in bronze.iter_records()
        if r.published_at is not None and start <= r.published_at <= as_of
    ]


async def _default_hypothesis_fn(
    deps: GraphDeps, event: EventRecord, ndi: float | None, rows: Sequence[StanceRow]
) -> Hypothesis | None:
    assert deps.router is not None
    by_source: dict[str, int] = {}
    for r in rows:
        by_source[r.source_id] = by_source.get(r.source_id, 0) + 1
    user = (
        f"事件：{event.event_id} {event.title}\n"
        f"NDI：{ndi if ndi is not None else 'abstain（数据不足）'}\n"
        f"各源 stance 行数：{by_source}\n"
        f"实体：{event.entities}"
    )
    hyp, _ = await deps.router.invoke(Tier.STRATEGIC, HYPOTHESIS_PROMPT, user, Hypothesis)
    return hyp


async def _default_interpret_fn(
    deps: GraphDeps, event: EventRecord, hyps: Sequence[Hypothesis]
) -> NarrativeCard | None:
    assert deps.router is not None
    user = (
        f"事件：{event.event_id} {event.title}\n假设："
        + "; ".join(h.text for h in hyps)
        + "\n写 3-5 句叙事解释卡，标注置信度与认知状态。"
    )
    card, _ = await deps.router.invoke(
        Tier.EXECUTE,
        "你是证据解释器：只解释给定假设与数据，不做收益预测。",
        user,
        NarrativeCard,
    )
    return card


# -- 子图节点（单事件） --------------------------------------------------------


def make_tagger_node(deps: GraphDeps):
    tagger = RuleTagger(deps.registry)

    async def tagger_node(state: EventState) -> dict[str, Any]:
        event = _event(state)
        as_of = _as_of(state)
        rows: list[StanceRow] = []
        llm_fills = 0
        for rec in _window_records(deps.bronze, event, as_of, deps.lookback_days):
            text = str(rec.normalized.get("body") or rec.normalized.get("title") or "")
            if not text:
                continue
            produced = tagger.tag(
                event_id=event.event_id,
                source_id=rec.source_id,
                text=text,
                item_key=rec.item_key,
                ts=rec.published_at,
                entities=event.entities,
            )
            if produced:
                rows.extend(produced)
                continue
            # 官方源补盲：规则零行 + LLM 可用 + 配额未满（85/10/5 成本纪律）
            if (
                deps.llm_tagger is not None
                and deps.tier_map.get(rec.source_id) == SourceTier.OFFICIAL
                and llm_fills < deps.max_llm_fills_per_event
            ):
                for entity_id in event.entities:
                    filled = await deps.llm_tagger.fill(
                        event_id=event.event_id,
                        source_id=rec.source_id,
                        entity_id=entity_id,
                        text=text,
                        item_key=rec.item_key,
                        ts=rec.published_at,
                    )
                    if filled is not None:
                        rows.append(filled)
                        llm_fills += 1
        if rows:
            deps.store.append_stances(rows)
        return {"stance_rows": rows}

    return tagger_node


def make_divergence_node(deps: GraphDeps):
    async def divergence_node(state: EventState) -> dict[str, Any]:
        event = _event(state)
        as_of = _as_of(state)
        rows = [r for r in deps.store.stances_asof(as_of) if r.event_id == event.event_id]
        if not rows:
            return {}
        langs = deps.languages or ("all",)
        points: list[NDIPoint] = []
        gaps: list[float | None] = []
        for lang in langs:
            point = ndi_for_event(
                rows,
                deps.tier_map,
                as_of,
                min_per_source=deps.min_per_source,
                event_id=event.event_id,
                lang_map=deps.lang_map,
                language=lang,
            )
            deps.gold.append_ndi(point)
            points.append(point)
            gaps.append(
                temperature_gap(
                    rows,
                    deps.tier_map,
                    min_per_source=deps.min_per_source,
                    lang_map=deps.lang_map,
                    language=lang,
                )
            )
        return {"ndi_points": points, "gaps": gaps}

    return divergence_node


def make_calibration_node(deps: GraphDeps):
    async def calibration_node(state: EventState) -> dict[str, Any]:
        event = _event(state)
        as_of = _as_of(state)
        series = [
            p for p in deps.gold.ndi_series(event.event_id) if p.ndi is not None and p.ts <= as_of
        ]
        if not series:
            return {}
        current = series[-1].ndi or 0.0
        history = [p.ndi for p in series[:-1]]
        entry: CalibrationEntry
        if len(history) < 5:
            entry = {
                "event_id": event.event_id,
                "ndi": current,
                "percentile": None,
                "regime": "cold_start",
            }
        else:
            pct = sum(1 for h in history if h <= current) / len(history)
            entry = {
                "event_id": event.event_id,
                "ndi": current,
                "percentile": round(pct, 4),
                "regime": "extreme" if pct >= 0.9 else "normal",
            }
        return {"calibrations": [entry]}

    return calibration_node


def make_hypothesis_node(deps: GraphDeps):
    async def hypothesis_node(state: EventState) -> dict[str, Any]:
        event = _event(state)
        as_of = _as_of(state)
        rows = [r for r in deps.store.stances_asof(as_of) if r.event_id == event.event_id]
        points = [
            p for p in deps.gold.ndi_series(event.event_id) if p.ts <= as_of and p.ndi is not None
        ]
        ndi = points[-1].ndi if points else None
        if deps.hypothesis_fn is not None:
            hyp = await deps.hypothesis_fn(event, ndi, rows)
        elif deps.router is not None:
            hyp = await _default_hypothesis_fn(deps, event, ndi, rows)
        else:
            return {}
        return {"hypotheses": [hyp]} if hyp is not None else {}

    return hypothesis_node


def make_interpret_node(deps: GraphDeps):
    async def interpret_node(state: EventState) -> dict[str, Any]:
        event = _event(state)
        hyps = state.get("hypotheses", [])
        if deps.interpret_fn is not None:
            card = await deps.interpret_fn(event, hyps)
        elif deps.router is not None:
            card = await _default_interpret_fn(deps, event, hyps)
        else:
            return {}
        return {"narrative_cards": [card.model_dump()]} if card is not None else {}

    return interpret_node


def make_gate_node(deps: GraphDeps):
    async def gate_node(state: EventState) -> dict[str, Any] | Command:
        cards = state.get("narrative_cards", [])
        low = [c for c in cards if c.get("confidence", 1.0) < deps.low_confidence_threshold]
        if low and deps.enable_hitl:
            from langgraph.types import interrupt

            value = interrupt({"type": "confirm", "cards": low})
            return {"pending_interrupt": [value]}
        return {"pending_interrupt": []}

    return gate_node


# -- 装配 ----------------------------------------------------------------------


def _build_event_pipeline(deps: GraphDeps):
    """单事件子图：tagger → divergence → calibration → hypothesis → interpret → gate。"""
    g = StateGraph(EventState)
    g.add_node("tagger", make_tagger_node(deps))
    g.add_node("divergence", make_divergence_node(deps))
    g.add_node("calibration", make_calibration_node(deps))
    g.add_node("hypothesis", make_hypothesis_node(deps))
    g.add_node("interpret", make_interpret_node(deps))
    g.add_node("gate", make_gate_node(deps))
    g.add_edge(START, "tagger")
    g.add_edge("tagger", "divergence")
    g.add_edge("divergence", "calibration")
    g.add_edge("calibration", "hypothesis")
    g.add_edge("hypothesis", "interpret")
    g.add_edge("interpret", "gate")
    g.add_edge("gate", END)
    return g.compile()


async def _plan_batch(state: AnalysisState) -> dict[str, Any]:
    return {"event_ids": [str(e["event_id"]) for e in state.get("events_input", [])]}


def _fanout_events(state: AnalysisState) -> list[Send]:
    default_now = state.get("now") or datetime.now(UTC).isoformat()
    sends: list[Send] = []
    for ev in state.get("events_input", []):
        raw = ev.get("as_of")
        if isinstance(raw, datetime):
            as_of = raw.isoformat()
        elif raw:
            as_of = str(raw)
        else:
            as_of = default_now
        sends.append(Send("event_pipeline", {"event": ev, "as_of": as_of}))
    return sends


def build_analysis_graph(deps: GraphDeps):
    """编译 analysis_graph：plan_batch → Send 并行 event_pipeline 子图。"""
    pipeline = _build_event_pipeline(deps)
    main = StateGraph(AnalysisState)
    main.add_node("plan_batch", _plan_batch)
    main.add_node("event_pipeline", pipeline)
    main.add_edge(START, "plan_batch")
    main.add_conditional_edges("plan_batch", _fanout_events, ["event_pipeline"])
    main.add_edge("event_pipeline", END)
    return main.compile(checkpointer=deps.checkpointer)
