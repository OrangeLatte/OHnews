"""A0-1 agent 基座测试：AgentSessions / user_gate / absorb / interrupt 闸门。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from oh_agents.agent_base import (
    AgentSessions,
    AgentState,
    absorb_user_input,
    confirm_save,
    make_checkpointer,
    user_gate,
)


def _mk(tmp_path: Path) -> AgentSessions:
    s = AgentSessions(tmp_path / "agent_sessions.sqlite")
    return s


def test_session_lifecycle_and_kinds(tmp_path: Path) -> None:
    s = _mk(tmp_path)
    tid = s.create_session("dissection", title="拆解测试")
    assert tid.startswith("dissection:")
    s.touch(tid)
    rows = s.list_sessions("dissection")
    assert rows and rows[0]["thread_id"] == tid
    try:
        s.create_session("unknown-kind", title="x")
        raise AssertionError("should reject unknown kind")
    except ValueError:
        pass


def test_pending_queue_push_and_drain_once(tmp_path: Path) -> None:
    s = _mk(tmp_path)
    tid = s.create_session("parent", title="t")
    s.push_input(tid, "info", "补充：关注美联储")
    s.push_input(tid, "instruction", "忽略这家媒体的立场")
    items = s.drain_inputs(tid)
    assert [i["kind"] for i in items] == ["info", "instruction"]
    assert s.drain_inputs(tid) == []  # 幂等：取走即清


def test_absorb_info_and_instruction_semantics() -> None:
    state: AgentState = {
        "messages": [],
        "pending_user": {"kind": "instruction", "text": "换个口径重跑"},
    }
    update = absorb_user_input(state)
    assert update["pending_user"] is None
    assert update["revise_hint"] == "换个口径重跑"
    assert update["messages"][-1]["role"] == "user"
    assert update["absorbed"][0]["text"] == "换个口径重跑"

    info = absorb_user_input({"pending_user": {"kind": "info", "text": "补充信息"}})
    assert "revise_hint" not in info  # info 不触发 revise


def test_user_gate_routing() -> None:
    assert user_gate({"pending_user": {"kind": "info", "text": "x"}}) == "absorb"
    assert user_gate({}) == "main"


def test_demo_graph_with_user_gate(tmp_path: Path) -> None:
    """最小图验证：无 pending 直通；有 pending 先 absorb 再回主路。"""
    s = _mk(tmp_path)
    checkpointer = make_checkpointer(s)
    tid = s.create_session("dissection", title="demo")

    def work(state: AgentState) -> dict[str, Any]:
        return {"messages": [{"role": "assistant", "content": "worked"}]}

    g = StateGraph(AgentState)
    g.add_node("work", work)
    g.add_node("absorb", absorb_user_input)
    g.add_edge(START, "work")
    g.add_conditional_edges("work", user_gate, {"absorb": "absorb", "main": END})
    g.add_edge("absorb", "work")
    graph = g.compile(checkpointer=checkpointer)

    cfg = {"configurable": {"thread_id": tid}}
    out = graph.invoke({"lang": "zh", "messages": []}, cfg)
    assert [m["content"] for m in out["messages"]] == ["worked"]  # 累积语义下仍一次

    # 运行中打断（生产模式）：FastAPI 收到补充 → update_state(as_node=最后完成节点)
    # 回卷到 work 之后 → invoke(None) 续跑 → user_gate 命中 absorb → 回主路 → END
    s.push_input(tid, "info", "补充：关注欧元区")
    graph.update_state(
        cfg,
        {"pending_user": {"kind": "info", "text": "补充：关注欧元区"}},
        as_node="work",
    )
    out2 = graph.invoke(None, cfg)
    contents = [m["content"] for m in out2["messages"]]
    assert contents == ["worked", "补充：关注欧元区", "worked"]  # 累积：旧+absorb 增量+回主路
    assert out2["absorbed"][0]["text"] == "补充：关注欧元区"


def test_confirm_save_interrupt_gate(tmp_path: Path) -> None:
    """interrupt 闸门：首次 invoke 挂起等待；resume 载荷透传。"""
    s = _mk(tmp_path)
    tid = s.create_session("memory", title="confirm")
    g = StateGraph(AgentState)
    g.add_node("ask", lambda st: {})
    g.add_node("save", lambda st: {"user_confirm": True})
    g.add_edge(START, "ask")
    g.add_edge("ask", "save")
    graph = g.compile(checkpointer=make_checkpointer(s))

    def save(state: AgentState) -> dict[str, Any]:  # noqa: ARG001
        result = confirm_save("存入档案库？")
        return {"user_confirm": bool(result.get("confirmed"))}

    g2 = StateGraph(AgentState)
    g2.add_node("save", save)
    g2.add_edge(START, "save")
    graph = g2.compile(checkpointer=make_checkpointer(s))
    cfg = {"configurable": {"thread_id": tid}}

    pending = graph.invoke({}, cfg)
    assert pending["__interrupt__"]  # 挂起等确认

    resumed = graph.invoke(Command(resume={"confirmed": True}), cfg)
    assert resumed["user_confirm"] is True
