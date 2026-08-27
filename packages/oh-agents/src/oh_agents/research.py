"""research_graph（蓝图图2 子图 RG）：问诊 agent，只读自有数据资产。

两节点图：gather（结构化查询：实体/事件/NDI/证据）→ synthesize
（LLM 合成答案；无 router 时模板拼接降级，仍可用）。
工具集全部只读——查询不触发重算（成本失控防线，裁决 A）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from oh_contracts.schemas import NDIPoint
from oh_pipeline.entities import EntityRegistry
from oh_storage.protocols import BronzeWriter, GoldReader, SilverStore
from pydantic import BaseModel, Field

ANSWER_PROMPT = """\
你是 OH!News 研究问诊助手。基于给定的查询结果（事件/NDI/证据链）回答用户问题。
规则：只使用给定数据；每条论断标注来源（source_id 或 event_id）；
NDI=叙事分歧指数（EPU 式条件变量，非收益预测器）；数据不足时如实说明。
"""


@dataclass(frozen=True)
class ResearchResult:
    """问诊结果（citations 为 event_id/source_id 列表）。"""

    question: str
    answer: str
    confidence: float
    citations: tuple[str, ...]
    tool_calls: tuple[str, ...]


class _SynthOutput(BaseModel):
    """LLM 合成输出（后校验契约）。"""

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[str] = Field(default_factory=list)


class ResearchState(TypedDict, total=False):
    question: str
    now: str
    gathered: dict[str, Any]  # 单写者（LastValue 覆盖）
    answer: dict[str, Any]


def gather_node(deps: _ResearchDeps):
    async def gather(state: ResearchState) -> dict[str, Any]:
        question = state["question"]
        now = datetime.fromisoformat(state["now"])
        registry = deps.registry
        entity_ids = registry.match(question)
        tool_calls: list[str] = []
        events = deps.store.events_asof(now)
        matched_events = [e for e in events if e.entities and set(e.entities) & set(entity_ids)]
        tool_calls.append(f"search_entities:{len(entity_ids)}")
        tool_calls.append(f"query_events:{len(matched_events)}")
        ndi: list[NDIPoint] = []
        evidence: list[dict[str, Any]] = []
        for e in matched_events:
            series = deps.gold.ndi_series(e.event_id)
            ndi.extend(p for p in series if p.ts <= now)
            rows = [r for r in deps.store.stances_asof(now) if r.event_id == e.event_id]
            tool_calls.append(f"retrieve_evidence:{e.event_id}:{len(rows)}")
            for r in sorted(rows, key=lambda x: -x.confidence)[:3]:
                evidence.append(
                    {
                        "event_id": e.event_id,
                        "source_id": r.source_id,
                        "frame": str(r.frame),
                        "stance": str(r.stance),
                        "item_key": r.item_key,
                    }
                )
        return {
            "gathered": {
                "entities": entity_ids,
                "events": [e.model_dump() for e in matched_events],
                "ndi": [p.model_dump() for p in ndi],
                "evidence": evidence,
                "tool_calls": tool_calls,
            }
        }

    return gather


def _quote_map(bronze: BronzeWriter, evidence: list[dict[str, Any]]) -> dict[str, str]:
    want = {e["item_key"] for e in evidence}
    out: dict[str, str] = {}
    for rec in bronze.iter_records():
        if rec.item_key in want:
            body = str(rec.normalized.get("body") or rec.normalized.get("title") or "")
            out[rec.item_key] = body[:120].replace("\n", " ")
    return out


def synthesize_node(deps: _ResearchDeps):
    async def synthesize(state: ResearchState) -> dict[str, Any]:
        g = state["gathered"]
        quotes = _quote_map(deps.bronze, g["evidence"])
        if deps.router is not None:
            evidence_lines = "\n".join(
                f"- [{e['source_id']}] {e['event_id']} frame={e['frame']} "
                f"stance={e['stance']} | {quotes.get(e['item_key'], '')}"
                for e in g["evidence"]
            )
            ndi_lines = "\n".join(
                f"- {p['event_id']} NDI={p['ndi']} status={p['status']}" for p in g["ndi"]
            )
            user = (
                f"用户问题：{state['question']}\n实体：{g['entities']}\n"
                f"事件：{[e['event_id'] for e in g['events']]}\n"
                f"NDI 序列：\n{ndi_lines or '（无）'}\n证据链：\n{evidence_lines or '（无）'}"
            )
            out, _ref = await deps.router.invoke(deps.tier, ANSWER_PROMPT, user, _SynthOutput)
            return {
                "answer": out.model_dump(),
            }
        # 无 LLM：模板拼接降级（可用性优先，诚实标注）
        lines = [f"问题：{state['question']}", f"命中实体：{g['entities']}"]
        for p in g["ndi"]:
            lines.append(f"NDI {p['event_id']} = {p['ndi']}（{p['status']}）")
        for e in g["evidence"]:
            lines.append(
                f"[{e['source_id']}] {e['event_id']} frame={e['frame']} "
                f"| {quotes.get(e['item_key'], '')}"
            )
        if len(lines) == 2:
            lines.append("（数据不足：未命中相关事件）")
        return {
            "answer": {
                "answer": "\n".join(lines),
                "confidence": 0.3,
                "citations": sorted({e["event_id"] for e in g["evidence"]}),
            }
        }

    return synthesize


@dataclass
class _ResearchDeps:
    """问诊图依赖（全部只读仓储 + 可选 router）。"""

    bronze: BronzeWriter
    store: SilverStore
    gold: GoldReader
    registry: EntityRegistry
    router: Any = None
    tier: Any = None  # Tier.STRATEGIC 默认（import 时避免循环，运行时取）


def build_research_graph(deps: _ResearchDeps):
    if deps.tier is None:
        from oh_contracts.enums import Tier

        deps.tier = Tier.STRATEGIC
    g = StateGraph(ResearchState)
    g.add_node("gather", gather_node(deps))
    g.add_node("synthesize", synthesize_node(deps))
    g.add_edge(START, "gather")
    g.add_edge("gather", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()


async def run_research(
    question: str,
    *,
    bronze: BronzeWriter,
    store: SilverStore,
    gold: GoldReader,
    registry: EntityRegistry | None = None,
    router: Any = None,
    now: datetime | None = None,
) -> ResearchResult:
    """便捷入口：建图→invoke→ResearchResult。"""
    deps = _ResearchDeps(
        bronze=bronze,
        store=store,
        gold=gold,
        registry=registry or EntityRegistry(),
        router=router,
    )
    graph = build_research_graph(deps)
    result = await graph.ainvoke(
        {"question": question, "now": (now or datetime.now(UTC)).isoformat()}
    )
    ans = result["answer"]
    tool_calls = tuple(result.get("gathered", {}).get("tool_calls", []))
    return ResearchResult(
        question=question,
        answer=ans["answer"],
        confidence=ans["confidence"],
        citations=tuple(ans["citations"]),
        tool_calls=tool_calls,
    )


__all__ = ["ResearchResult", "build_research_graph", "run_research"]
