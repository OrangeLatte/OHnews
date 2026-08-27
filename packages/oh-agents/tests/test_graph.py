"""analysis_graph 端到端（FakeRouter 离线）：Send 并行/PIT/幂等/HITL interrupt。"""

from __future__ import annotations

import asyncio

from conftest import TIER_MAP, make_now, seed_event
from oh_agents.graph import GraphDeps, build_analysis_graph
from oh_contracts.schemas import EventRecord, Hypothesis, NarrativeCard
from oh_pipeline.entities import EntityRegistry
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def _deps(bronze, store, **kw) -> GraphDeps:
    return GraphDeps(
        bronze=bronze,
        store=store,
        gold=store,
        tier_map=TIER_MAP,
        registry=EntityRegistry(),
        min_per_source=10,
        **kw,
    )


def _invoke(deps: GraphDeps, events: list[EventRecord], now):
    g = build_analysis_graph(deps)
    return asyncio.run(
        g.ainvoke(
            {
                "events_input": [e.model_dump() for e in events],
                "now": now.isoformat(),
            }
        )
    )


def test_pure_statistics_graph(tmp_path) -> None:
    """router=None：纯统计图产出 NDI 并落 Gold。"""
    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev = seed_event(bronze, store, "E01", now)
    result = _invoke(_deps(bronze, store), [ev], now)
    assert result["event_ids"] == ["E01"]
    points = result["ndi_points"]
    assert len(points) == 1
    assert points[0].status == "ok"
    assert points[0].ndi > 0.7
    assert store.ndi_series("E01")[0].ndi == points[0].ndi


def test_send_parallel_two_events(tmp_path) -> None:
    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev1 = seed_event(bronze, store, "E01", now)
    ev2 = seed_event(bronze, store, "E02", now)
    result = _invoke(_deps(bronze, store), [ev1, ev2], now)
    assert sorted(result["event_ids"]) == ["E01", "E02"]
    assert len(result["ndi_points"]) == 2


def test_pit_future_articles_ignored(tmp_path) -> None:
    """as_of 之后到达的反转文章不得影响同 as_of 的 NDI。"""
    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev = seed_event(bronze, store, "E01", now)
    first = _invoke(_deps(bronze, store), [ev], now)
    seed_event(bronze, store, "E01", now, future_rows=True)
    second = _invoke(_deps(bronze, store), [ev], now)
    assert first["ndi_points"][0].ndi == second["ndi_points"][0].ndi


def test_fanout_uses_event_own_asof(tmp_path) -> None:
    """Send 并行时各事件用自身 as_of：早事件不得看到晚事件窗口的文章。

    回归：_fanout_events 曾把 state['now'] 传给所有事件，导致所有事件共享同一
    滚动窗口——同一文章 stance 重复计入多个事件（PIT 违规 + NDI 跨日同值）。
    """
    from datetime import timedelta

    now = make_now()
    day1 = now - timedelta(days=1)
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev1 = seed_event(bronze, store, "E01", day1)
    ev2 = seed_event(bronze, store, "E02", now)
    _invoke(_deps(bronze, store), [ev1, ev2], now)
    k1 = {r.item_key for r in store.stances_asof(now) if r.event_id == "E01"}
    k2 = {r.item_key for r in store.stances_asof(now) if r.event_id == "E02"}
    assert k1, "早事件应有自己窗口内的 stance 行"
    assert k2, "晚事件应有自己窗口内的 stance 行"
    assert not (k1 & k2), "两事件文章窗口不得重叠（PIT）"


def test_rerun_idempotent(tmp_path) -> None:
    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev = seed_event(bronze, store, "E01", now)
    deps = _deps(bronze, store)
    _invoke(deps, [ev], now)
    n1 = len(store.stances_asof(now))
    _invoke(deps, [ev], now)
    assert len(store.stances_asof(now)) == n1


def test_llm_layers_with_fakes(tmp_path) -> None:
    """注入 fake hypothesis/interpret：只读 LLM 层产出假设与解释卡。"""

    async def fake_hyp(event, ndi, rows):
        return Hypothesis(
            event_id=event.event_id,
            text="官方与市场对同一政策的框架解读存在系统性分歧",
            drivers=["官方强调风险", "市场强调机遇"],
            cite=["gov", "wscn"],
        )

    async def fake_interp(event, hyps):
        return NarrativeCard(
            event_id=event.event_id,
            confidence=0.8,
            epistemic_status="inferred",
            narrative="叙事分歧显著，来自信源数据而非模型辩论。",
        )

    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev = seed_event(bronze, store, "E01", now)
    deps = _deps(bronze, store, hypothesis_fn=fake_hyp, interpret_fn=fake_interp)
    result = _invoke(deps, [ev], now)
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0].cite == ["gov", "wscn"]
    assert result["narrative_cards"][0]["confidence"] == 0.8


def test_hitl_interrupt_on_low_confidence(tmp_path) -> None:
    """enable_hitl + 低置信卡 → interrupt（LangGraph __interrupt__ 语义）。"""

    async def fake_hyp(event, ndi, rows):
        return Hypothesis(event_id=event.event_id, text="h", cite=[])

    async def fake_interp(event, hyps):
        return NarrativeCard(
            event_id=event.event_id,
            confidence=0.2,
            epistemic_status="speculative",
            narrative="低置信解释",
        )

    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev = seed_event(bronze, store, "E01", now)
    deps = _deps(
        bronze,
        store,
        hypothesis_fn=fake_hyp,
        interpret_fn=fake_interp,
        enable_hitl=True,
    )
    result = _invoke(deps, [ev], now)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "confirm"
    # interrupt 挂起时 gate 未完成：pending_interrupt 的写回发生在 Command(resume) 之后


def test_hitl_resume_writes_back(tmp_path) -> None:
    """Command(resume) → gate 完成 → pending_interrupt 写回（HITL 审批闭环）。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    async def fake_hyp(event, ndi, rows):
        return Hypothesis(event_id=event.event_id, text="h", cite=[])

    async def fake_interp(event, hyps):
        return NarrativeCard(
            event_id=event.event_id,
            confidence=0.2,
            epistemic_status="speculative",
            narrative="低置信解释",
        )

    now = make_now()
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    ev = seed_event(bronze, store, "E01", now)
    deps = _deps(
        bronze,
        store,
        hypothesis_fn=fake_hyp,
        interpret_fn=fake_interp,
        enable_hitl=True,
        checkpointer=InMemorySaver(),
    )
    g = build_analysis_graph(deps)
    config = {"configurable": {"thread_id": "t1"}}
    state = {"events_input": [ev.model_dump()], "now": now.isoformat()}
    suspended = asyncio.run(g.ainvoke(state, config))
    assert "__interrupt__" in suspended

    resumed = asyncio.run(g.ainvoke(Command(resume={"approved": True}), config))
    assert "__interrupt__" not in resumed
    assert resumed["pending_interrupt"] == [{"approved": True}]
