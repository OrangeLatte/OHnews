"""chat_graph（用户意见①核心）：多轮会话情报 Agent。

langgraph agent ⇄ tools 循环（条件边路由），ModelRouter 中心——不走
BaseChatModel 适配，统一 tier 路由/fallback/后校验。工具全只读
（裁决 A）+ 在线检索 + 制作工具。会话历史由 ChatStore（独立 sqlite）
持久化，每轮全量注入（checkpointer 留给 HITL 场景）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from oh_contracts.text import strip_html
from pydantic import BaseModel, Field

MAX_TOOL_ROUNDS = 5
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

CHAT_SYSTEM = """\
你是 OH!News 情报研究员。可调用工具查询本地数据资产（事件/实体/NDI/证据链）、
在线检索（GDELT）与制作简报。规则：
- 只依据工具结果作答，每条论断标注来源（source_id/event_id）；无数据如实说明；
- NDI=叙事分歧指数（EPU 式条件变量，非收益预测器），禁用"预测/择时"措辞；
- 需要多类信息时可在一次回复中声明多个工具调用；信息足够后给出 reply。
"""

TOOL_HELP = """\
- query_events({days=7})：近 N 天事件列表（id/标题/实体）
- search_entities({text})：文本匹配实体
- get_ndi({event_id?})：NDI 点位（不传=全部；abstain=官方簇样本不足）
- retrieve_evidence({event_id})：事件证据链（stance+原文摘录）
- fetch_online({query})：GDELT 在线新闻检索（网络受限时降级本地）
- draft_brief({watchlist="fed,trump,ecb"})：制作晨报简报文本
"""


class ChatToolCall(BaseModel):
    """LLM 声明的工具调用（args 为自由 dict，执行器按工具名解释）。"""

    name: str = Field(pattern=r"^[a-z_]+$")
    args: dict[str, Any] = Field(default_factory=dict)


class ChatOutput(BaseModel):
    """agent 节点输出契约（后校验）。"""

    reply: str = ""
    tool_calls: list[ChatToolCall] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class ChatState(TypedDict, total=False):
    messages: list[dict[str, str]]  # 对话历史（只读注入，不回写）
    now: str
    tool_feedback: str  # 上一轮工具结果（单写者）
    pending_calls: list[dict[str, Any]]  # agent 声明待执行的工具调用
    rounds: int
    reply: str
    citations: list[str]
    done: bool


# ---------------------------------------------------------------- tools


def _tool_query_events(deps: _ChatDeps, args: dict[str, Any], now: datetime) -> str:
    events = deps.store.events_asof(now)
    days = int(args.get("days", 7))
    cutoff = now.timestamp() - days * 86400
    hits = [e for e in events if e.as_of.timestamp() >= cutoff]
    if not hits:
        return "（无事件）"
    return "\n".join(
        f"- {e.event_id} | {e.title[:60]} | as_of={e.as_of:%Y-%m-%d} | {e.entities}"
        for e in hits[-30:]
    )


def _tool_search_entities(deps: _ChatDeps, args: dict[str, Any], now: datetime) -> str:
    text = str(args.get("text", ""))
    ids = deps.registry.match(text)
    return f"命中实体：{sorted(ids) or '（无）'}"


def _tool_get_ndi(deps: _ChatDeps, args: dict[str, Any], now: datetime) -> str:
    event_id = args.get("event_id")
    points = deps.gold.ndi_series(str(event_id)) if event_id else deps.gold.ndi_all()
    lines = [
        f"{p.event_id} NDI="
        + (f"{p.ndi:.3f}" if p.ndi is not None else "abstain")
        + f" ts={p.ts} lang={p.language}"
        + (" [low_confidence]" if p.low_confidence else "")
        for p in points
        if p.ts <= now
    ]
    return "\n".join(lines[-40:]) or "（无 NDI 点位）"


def _tool_retrieve_evidence(deps: _ChatDeps, args: dict[str, Any], now: datetime) -> str:
    event_id = str(args.get("event_id", ""))
    rows = [r for r in deps.store.stances_asof(now) if r.event_id == event_id]
    if not rows:
        return f"（事件 {event_id} 无 stance 行）"
    want = {r.item_key for r in sorted(rows, key=lambda x: -x.confidence)[:8]}
    quotes: dict[str, str] = {}
    for rec in deps.bronze.iter_records():
        if rec.item_key in want:
            body = str(rec.normalized.get("body") or rec.normalized.get("title") or "")
            quotes[rec.item_key] = strip_html(body)[:120].replace("\n", " ")
    return "\n".join(
        f"- [{r.source_id}] frame={r.frame} stance={r.stance} conf={r.confidence:.2f}"
        f" | {quotes.get(r.item_key, '（原文不在 Bronze 窗口）')}"
        for r in sorted(rows, key=lambda x: -x.confidence)[:8]
    )


def _tool_fetch_online(deps: _ChatDeps, args: dict[str, Any], now: datetime) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "（需要 query 参数）"
    try:
        import httpx

        kw: dict[str, Any] = {"timeout": 15.0}
        if deps.gdelt_proxy:
            kw["proxy"] = deps.gdelt_proxy
        resp = httpx.get(
            GDELT_DOC_URL,
            params={
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 10,
                "sort": "DateDesc",
            },
            **kw,
        )
        resp.raise_for_status()
        arts = resp.json().get("articles", [])
        if not arts:
            return "（GDELT 无结果）"
        return "\n".join(
            f"- [{a.get('domain', '?')}] {a.get('title', '')[:80]} {a.get('url', '')}" for a in arts
        )
    except Exception as exc:  # noqa: BLE001 工具层吞异常转述给 LLM
        return f"（在线检索失败：{exc.__class__.__name__}；网络受限时请改用本地资产）"


def _tool_draft_brief(deps: _ChatDeps, args: dict[str, Any], now: datetime) -> str:
    from oh_agents.morning_brief import build_brief

    watchlist = str(args.get("watchlist", "fed,trump,ecb"))
    entities = [w.strip() for w in watchlist.split(",") if w.strip()]
    brief = build_brief(deps.bronze, deps.store, deps.gold, entities, now=now)
    return brief.render_text()


TOOL_NAMES = (
    "query_events",
    "search_entities",
    "get_ndi",
    "retrieve_evidence",
    "fetch_online",
    "draft_brief",
)


def execute_tool(deps: _ChatDeps, name: str, args: dict[str, Any], now: datetime) -> str:
    """工具分派（未知工具/执行失败返回说明字符串，不传染图）。"""
    impl = {
        "query_events": _tool_query_events,
        "search_entities": _tool_search_entities,
        "get_ndi": _tool_get_ndi,
        "retrieve_evidence": _tool_retrieve_evidence,
        "fetch_online": _tool_fetch_online,
        "draft_brief": _tool_draft_brief,
    }.get(name)
    if impl is None:
        return f"（未知工具 {name}；可用：{','.join(TOOL_NAMES)}）"
    try:
        return impl(deps, args, now)
    except Exception as exc:  # noqa: BLE001
        return f"（工具 {name} 执行失败：{exc.__class__.__name__}: {exc}）"


# ---------------------------------------------------------------- graph


@dataclass
class _ChatDeps:
    bronze: Any
    store: Any
    gold: Any
    registry: Any
    router: Any = None
    tier: Any = None
    gdelt_proxy: str | None = None
    tools_used: list[str] = field(default_factory=list)


def _history_text(messages: list[dict[str, str]]) -> str:
    return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages[-12:])


def _agent_node(deps: _ChatDeps):
    async def agent(state: ChatState) -> dict[str, Any]:
        now = datetime.fromisoformat(state["now"])
        rounds = state.get("rounds", 0)
        if deps.router is None:
            # 无 LLM 降级：一次性聚合只读工具（可用性优先，诚实标注）
            body = "\n\n".join(
                f"[{n}]\n{execute_tool(deps, n, {}, now)}"
                for n in ("query_events", "get_ndi", "draft_brief")
            )
            return {
                "reply": f"（离线模式：只读工具聚合）\n{body}",
                "citations": [],
                "done": True,
                "rounds": rounds + 1,
            }
        user = (
            f"对话历史：\n{_history_text(list(state.get('messages', [])))}\n\n"
            f"上一轮工具结果：\n{state.get('tool_feedback', '（无）')}\n\n"
            f"当前时间 {state['now']}；工具轮次 {rounds}/{MAX_TOOL_ROUNDS}。"
            "信息足够请给 reply，否则声明 tool_calls。可用工具：\n"
            f"{TOOL_HELP}"
        )
        out, _ref = await deps.router.invoke(deps.tier, CHAT_SYSTEM, user, ChatOutput)
        payload: dict[str, Any] = {"rounds": rounds + 1}
        if out.tool_calls and rounds < MAX_TOOL_ROUNDS:
            payload["pending_calls"] = [tc.model_dump() for tc in out.tool_calls]
        elif rounds >= MAX_TOOL_ROUNDS and not out.reply:
            payload.update(
                reply="（工具轮次达上限：请缩小问题范围重试）",
                citations=out.citations,
                done=True,
                pending_calls=[],
            )
        else:
            payload.update(reply=out.reply, citations=out.citations, done=True, pending_calls=[])
        return payload

    return agent


def _tools_node(deps: _ChatDeps):
    async def tools(state: ChatState) -> dict[str, Any]:
        now = datetime.fromisoformat(state["now"])
        results: list[str] = []
        for tc in state.get("pending_calls", []):
            deps.tools_used.append(str(tc.get("name")))
            results.append(
                f"[{tc.get('name')}({json.dumps(tc.get('args', {}), ensure_ascii=False)})]\n"
                + execute_tool(deps, str(tc.get("name")), dict(tc.get("args", {})), now)
            )
        prev = state.get("tool_feedback", "")
        merged = (prev + "\n\n" if prev else "") + "\n\n".join(results)
        return {"tool_feedback": merged, "pending_calls": []}

    return tools


def _route_after_agent(state: ChatState) -> str:
    if state.get("done"):
        return END
    if state.get("pending_calls"):
        return "tools"
    return END


def build_chat_graph(deps: _ChatDeps):
    g = StateGraph(ChatState)
    g.add_node("agent", _agent_node(deps))
    g.add_node("tools", _tools_node(deps))
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


async def run_chat(
    message: str,
    history: list[dict[str, str]],
    *,
    bronze: Any,
    store: Any,
    gold: Any,
    registry: Any,
    router: Any = None,
    tier: Any = None,
    gdelt_proxy: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """单轮会话：历史+新消息 → agent⇄tools 循环 → 回复+审计。

    history 为 [{"role": "user"|"assistant", "content": ...}, ...]。
    返回 {reply, citations, tools_used, rounds}。
    """
    if tier is None:
        from oh_contracts.enums import Tier

        tier = Tier.EXECUTE
    deps = _ChatDeps(
        bronze=bronze,
        store=store,
        gold=gold,
        registry=registry,
        router=router,
        tier=tier,
        gdelt_proxy=gdelt_proxy,
    )
    graph = build_chat_graph(deps)
    result = await graph.ainvoke(
        {
            "messages": [*history, {"role": "user", "content": message}],
            "now": (now or datetime.now(UTC)).isoformat(),
            "rounds": 0,
            "tool_feedback": "",
        }
    )
    return {
        "reply": result.get("reply", ""),
        "citations": result.get("citations", []),
        "tools_used": tuple(deps.tools_used),
        "rounds": result.get("rounds", 0),
    }


# ---------------------------------------------------------------- store


class ChatStore:
    """会话历史（独立 sqlite；thread_id 会话，每轮全量注入）。"""

    def __init__(self, path: str | Any) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " thread_id TEXT NOT NULL, role TEXT NOT NULL,"
            " content TEXT NOT NULL, ts TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_thread ON chat_messages(thread_id, id)"
        )
        self._conn.commit()

    def threads(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT thread_id, COUNT(*) AS n, MAX(ts) AS last FROM chat_messages"
            " GROUP BY thread_id ORDER BY MAX(ts) DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def messages(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT role, content, ts FROM chat_messages WHERE thread_id=? ORDER BY id",
            (thread_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def append(self, thread_id: str, role: str, content: str, ts: str) -> None:
        self._conn.execute(
            "INSERT INTO chat_messages(thread_id, role, content, ts) VALUES (?,?,?,?)",
            (thread_id, role, content, ts),
        )
        self._conn.commit()


__all__ = [
    "CHAT_SYSTEM",
    "ChatOutput",
    "ChatStore",
    "ChatToolCall",
    "MAX_TOOL_ROUNDS",
    "TOOL_NAMES",
    "build_chat_graph",
    "execute_tool",
    "run_chat",
]
