"""chat_graph（用户意见①核心）：多轮会话情报 Agent。

langgraph agent ⇄ tools 循环（条件边路由），ModelRouter 中心——不走
BaseChatModel 适配，统一 tier 路由/fallback/后校验。工具全只读
（裁决 A）+ 在线检索 + 制作工具。会话历史由 ChatStore（独立 sqlite）
持久化，每轮全量注入（checkpointer 留给 HITL 场景）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from oh_contracts.case import AnalysisRun
from oh_contracts.text import strip_html
from pydantic import BaseModel, Field

from .parent_planner import build_research_plan

MAX_TOOL_ROUNDS = 5
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# 消息九类型（阶段 2 对话约束：每条消息 ∈ 九类型闭集，禁止只回显）。
MessageType = Literal[
    "answer",
    "plan",
    "tool_call",
    "progress",
    "artifact",
    "challenge",
    "hitl_request",
    "abstention",
    "error",
]
MESSAGE_TYPES: tuple[MessageType, ...] = (
    "answer",
    "plan",
    "tool_call",
    "progress",
    "artifact",
    "challenge",
    "hitl_request",
    "abstention",
    "error",
)

CHAT_SYSTEM = """\
你是 OH!News 情报研究员。你本人不直接调用任何函数：所有数据查询（事件/实体/
NDI/证据链）与在线检索（GDELT）、简报制作都由外部系统代为执行。规则：
- 你的每次回复必须以名为 `ChatOutput` 的函数调用提交（这是唯一允许的调用，
  其 name 必须恰为 ChatOutput）；
- 查询意图写在 ChatOutput 的 tool_calls 字段（[{name, args}] 声明式列表，
  name 取以下之一：query_events / search_entities / get_ndi /
  retrieve_evidence / fetch_online / draft_brief），外部执行后回传结果；
- 只依据已回传的工具结果作答，每条论断标注来源（source_id/event_id）；
  无数据如实说明；
- NDI=叙事分歧指数（EPU 式条件变量，非收益预测器），禁用"预测/择时"措辞；
- 信息足够后填写 reply，tool_calls 留空。
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
        out, _ref, _usage = await deps.router.invoke(deps.tier, CHAT_SYSTEM, user, ChatOutput)
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
    context: str | None = None,
) -> dict[str, Any]:
    """单轮会话：历史+新消息 → agent⇄tools 循环 → 回复+审计。

    history 为 [{"role": "user"|"assistant", "content": ...}, ...]。
    context 为可选研究上下文（如 ContextPacket.summary_text()），
    以「研究上下文」前缀注入本轮 user 消息头部。
    返回 {reply, citations, tools_used, rounds}。
    """
    if tier is None:
        from oh_contracts.enums import Tier

        # 对话=检索+汇总（io 语义）：glm-5.3-flash 一轮 15-50s×多轮循环不可接受，
        # 默认走 deepseek-v4-flash（json_mode 后单轮 1-2s，实测全链 6.4s）。
        tier = Tier.IO
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
    full_message = f"【研究上下文】\n{context}\n\n【问题】{message}" if context else message
    result = await graph.ainvoke(
        {
            "messages": [*history, {"role": "user", "content": full_message}],
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


# ---------------------------------------------------------------- command mode


# 指挥意图闭集：chat 从「补充信息聊天」升级为可指挥工作流的对话 Agent。
ChatIntent = Literal[
    "plan",
    "dissect",
    "compare",
    "report",
    "challenge",
    "status",
    "observe",
    "question",
    "hitl",
    "answer_case_question",
]
CHAT_INTENTS: tuple[ChatIntent, ...] = (
    "plan",
    "dissect",
    "compare",
    "report",
    "challenge",
    "status",
    "observe",
    "question",
    "hitl",
    "answer_case_question",
)

# 规则兜底（高置信领域词，顺序即优先级：status/hitl 元意图先于执行意图，
# 避免「拆解状态如何」被误路由为 dissect）。中文+英文；未命中 → question。
_INTENT_RULES: tuple[tuple[ChatIntent, tuple[str, ...]], ...] = (
    ("status", ("状态", "进度", "运行记录", "执行记录", "跑到哪", "status", "progress", "runs")),
    ("hitl", ("待审批", "待审核", "待确认", "审批", "批准", "确认事项", "hitl", "approval")),
    ("plan", ("计划", "规划", "研究方案", "怎么研究", "下一步", "plan")),
    ("dissect", ("拆解", "十八元素", "18元素", "18 元素", "dissect")),
    ("compare", ("比较", "对比", "跨源", "口径", "compare", "diff")),
    ("challenge", ("挑战", "反证", "质询", "证伪", "challenge")),
    ("report", ("报告", "写一份", "生成报", "总结成", "report")),
    ("observe", ("收件箱", "观察", "变化", "信号", "最新动态", "observe", "inbox", "what's new")),
)

# Case 上下文指代词（T3）：疑问句 + 指代当前 Case 内部情况 → answer_case_question。
# 规格含裸字 "本"，为避免「成本/基本/日本」等词误命中，替换为其上下文变体。
_CASE_REF_MARKS: tuple[str, ...] = (
    "当前",
    "这个",
    "这些",
    "本案",
    "本 case",
    "本case",
    "本文",
    "本篇",
    "几篇",
    "多少",
    "哪些",
    "这篇",
    "current",
    "this case",
    "how many",
)

INTENT_SYSTEM = """\
你是 OH!News 对话路由器。把用户消息分类为以下意图之一：
- plan: 请求规划研究步骤
- dissect: 请求拆解文档（十八元素）
- compare: 请求跨源/跨版本比较
- report: 请求生成研究报告
- challenge: 请求对主张做反证质询
- status: 查询 Case 内工作流运行状态/进度
- observe: 请求观察最新变化/收件箱/信号概览
- hitl: 查询待人工确认（HITL）事项
- question: 其他问答（基于已有数据回答问题）
- answer_case_question: 询问当前 Case 内部情况（几篇文档/哪些标题/多少主张/
  最近运行），基于 Case 上下文直接回答
"""


class IntentOut(BaseModel):
    """LLM 意图分类输出契约（pattern 闭集校验，非法输出按分类失败处理）。"""

    intent: str = Field(
        pattern=(
            r"^(plan|dissect|compare|report|challenge|status|observe|question"
            r"|hitl|answer_case_question)$"
        )
    )


_INTERROGATIVE_MARKS = (
    "为什么",
    "为什么",
    "怎么",
    "如何",
    "什么意思",
    "是什么",
    "吗？",
    "呢？",
    " explain",
    " why ",
    " how ",
    " what ",
    "?",
)


def _is_interrogative(text: str) -> bool:
    """疑问语境判定：疑问词/问号命中即视为追问（回答优先于执行）。"""
    stripped = text.strip()
    return (
        stripped.endswith("?")
        or stripped.endswith("？")
        or any(m in stripped for m in _INTERROGATIVE_MARKS)
    )


# P0-1 否定约束：用户显式禁止写操作时，执行类意图一律降级为建议（最高优先级）。
_NEGATION_MARKS: tuple[str, ...] = (
    "不要创建",
    "不要保存",
    "不要修改",
    "不要执行",
    "不要动",
    "不要跑",
    "不要触发",
    "别创建",
    "别保存",
    "别修改",
    "别执行",
    "别跑",
    "禁止创建",
    "禁止保存",
    "禁止修改",
    "禁止执行",
    "不要任何",
    "don't",
    "do not ",
    "never ",
    "without ",
)
# "只/仅…判断/分析/回答/解释"型只读约束（用户要求先直接回答）。
_ONLY_MARKS: tuple[str, ...] = (
    "仅基于",
    "只基于",
    "仅根据",
    "只根据",
    "只回答",
    "仅回答",
    "只判断",
    "仅判断",
    "只分析",
    "仅分析",
    "只解释",
    "仅解释",
    "based only",
    "only based",
    "just tell",
    "just answer",
    "just analyze",
    "just judge",
)


def detect_read_only_forced(message: str) -> bool:
    """否定/只读约束解析：命中即强制只读（任何写操作不得执行，P0-1）。

    规则层保守判定：显式否定短语命中 → True；"仅/只…回答/判断/分析"型
    约束命中 → True。LLM 路由不可依赖（分类本身可能出错）。
    """
    text = message.strip().lower()
    if any(m in text for m in _NEGATION_MARKS):
        return True
    if any(m in text for m in _ONLY_MARKS):
        return True
    # 中文无空格变体："仅…判断"（约束词与动词间有间隔）
    for mark in ("仅", "只"):
        if mark in text and any(v in text for v in ("判断", "回答", "分析", "解释")):
            return True
    return False


def classify_intent(message: str) -> ChatIntent:
    """规则兜底：领域词命中即返回对应意图，未命中一律 question（不猜）。

    T3：疑问句且含 Case 上下文指代词（当前/这个/几篇/多少…）→
    answer_case_question，优先于 question/status（直接回答 Case 内部情况）。
    """
    text = message.strip().lower()
    # 多轮追问优先：疑问语境下即使出现执行类工作流关键词（"为什么要拆解…"），
    # 也应回答而非再次执行；元意图（status/observe/hitl）本身是查询，保留。
    if _is_interrogative(text):
        if any(m in text for m in _CASE_REF_MARKS):
            return "answer_case_question"
        for intent, keywords in _INTENT_RULES:
            if intent in ("status", "observe", "hitl") and any(k in text for k in keywords):
                return intent
        return "question"
    for intent, keywords in _INTENT_RULES:
        if any(k in text for k in keywords):
            return intent
    return "question"


async def classify_intent_llm(router: Any, tier: Any, message: str) -> ChatIntent | None:
    """LLM 意图分类：router 缺失/输出非法/调用失败 → None（交还规则兜底）。"""
    if router is None:
        return None
    try:
        if tier is None:
            from oh_contracts.enums import Tier

            tier = Tier.IO
        out, _ref, _usage = await router.invoke(tier, INTENT_SYSTEM, message, IntentOut)
        return out.intent  # type: ignore[return-value]
    except Exception:  # noqa: BLE001 分类失败不阻断对话主路
        return None


async def resolve_intent(
    message: str, *, router: Any = None, tier: Any = None
) -> tuple[ChatIntent, str]:
    """意图路由中间件：规则命中（高置信领域词）→ 直接采用；
    未命中且有 router → LLM 分类；再兜底 question。返回 (intent, by)。"""
    by_rule = classify_intent(message)
    if by_rule != "question" or router is None:
        return by_rule, "rule"
    by_llm = await classify_intent_llm(router, tier, message)
    if by_llm is not None:
        return by_llm, "llm"
    return "question", "fallback"


def context_injector(research: Any, case_id: str) -> str:
    """上下文注入中间件：ResearchState 摘要 → 注入 LLM prompt（question 路径锚点）。

    research 缺失或 case 不存在返回空串（诚实：不虚构 Case 上下文）。
    """
    if research is None or not case_id:
        return ""
    case = research.get_case(case_id)
    if case is None:
        return ""
    docs = research.case_documents(case_id)
    claims = research.claims_for_case(case_id)
    kinds = research.case_run_kinds(case_id)
    return "\n".join(
        [
            f"当前 Case: {case.case_id}｜{case.title}",
            f"研究问题: {case.question}",
            f"挂载文档 {len(docs)} 篇；claims {len(claims)} 条；"
            f"已跑工作流: {','.join(kinds) or '（无）'}",
        ]
    )


def hitl_gate(research: Any) -> list[dict[str, Any]]:
    """HITL 闸门中间件：有 pending HITL 时在回复前注入 hitl 卡（无则空）。"""
    if research is None:
        return []
    return [
        {
            "type": "hitl",
            "hitl_id": h.hitl_id,
            "summary": f"{h.action} · run={h.run_id} · 等待用户裁决",
        }
        for h in research.pending_hitl()
    ]


# ---- 结构化卡片构造（cards 闭集，随消息持久化）----


def _card_tool_call(tool: str, status: str, detail: str = "") -> dict[str, Any]:
    return {"type": "tool_call", "tool": tool, "status": status, "detail": detail}


def _card_progress(run_id: str, kind: str, status: str) -> dict[str, Any]:
    return {"type": "progress", "run_id": run_id, "kind": kind, "status": status}


def _card_case(case: Any) -> dict[str, Any]:
    return {"type": "case", "case_id": str(case.case_id), "question": str(case.question)}


def _observe_card(store: Any, now: datetime) -> dict[str, Any]:
    """观察摘要卡（只读派生自 Silver 事件表，不造数据）。"""
    events = store.events_asof(now)
    return {
        "type": "observe_summary",
        "n_events": len(events),
        "recent_events": [
            {"event_id": e.event_id, "title": e.title, "as_of": e.as_of.isoformat()}
            for e in events[-5:]
        ],
        "hint": "在研究台从收件箱选文建 Case，或对已有 Case 下达拆解/比较/报告指令",
    }


def _runs_summary_card(runs: list[Any]) -> dict[str, Any]:
    return {
        "type": "runs_summary",
        "runs": [
            {
                "run_id": r.run_id,
                "kind": r.kind,
                "status": r.status,
                "started_at": r.started_at,
                "error": r.error,
            }
            for r in runs[:10]
        ],
    }


_ANSWER_CASE_SYSTEM = """\
你是 OH!News 研究助理。用户在询问当前研究 Case 的内部情况。规则：
- 只依据下方给出的 Case 上下文回答，直接回答问题本身；
- 引用上下文中的证据（文档标题/信源/数量/运行记录），不虚构任何数据；
- 不创建、不修改、不保存任何数据（纯只读问答）；
- 上下文不足以回答时如实说明缺什么。
"""


def _case_question_context(research: Any, case: Any) -> str:
    """answer_case_question 只读路径：组装 Case 内部情况上下文（文档/主张/运行）。"""
    case_id = str(case.case_id)
    docs = research.case_documents(case_id)
    claims = research.claims_for_case(case_id)
    runs = [r for r in research.analysis_runs(50) if r.case_id == case_id]
    doc_lines = "\n".join(
        f"  - {str(d.get('title') or d.get('source_id') or d['document_revision_id'])}"
        f"（信源 {d.get('source_id') or '未知'}·{d.get('language') or '未知语言'}）"
        for d in docs[:20]
    )
    run_lines = "\n".join(f"  - {r.kind} {r.status}（{r.started_at}）" for r in runs[:10])
    return "\n".join(
        [
            f"Case {case_id}：{case.title or case.question}",
            f"研究问题：{case.question}",
            f"文档共 {len(docs)} 篇：",
            doc_lines or "  （无）",
            f"claims 共 {len(claims)} 条",
            f"最近分析运行共 {len(runs)} 次：",
            run_lines or "  （无）",
        ]
    )


def _optional_actions_card(actions: list[dict[str, str]]) -> dict[str, Any]:
    """只读建议卡（T3）：建议下一步可选操作，needs_confirmation=False 恒不触发执行。

    响应 schema：{"type": "optional_actions", "title": str, "needs_confirmation": False,
    "actions": [{"label": str, "message": str}]}——message 为用户可原样重发的指令。
    """
    return {
        "type": "optional_actions",
        "title": "下一步可选操作",
        "needs_confirmation": False,
        "actions": actions,
    }


_COMMAND_WORKFLOWS: dict[str, tuple[str, str]] = {
    # intent → (WORKFLOWS 闭集名, analysis_runs kind)
    "dissect": ("DissectDocument", "dissect"),
    "compare": ("CompareSources", "compare"),
    "report": ("BuildReport", "report"),
    "challenge": ("ChallengeClaim", "challenge"),
}
_LLM_RUN_KINDS = frozenset({"dissect", "report", "translate"})


def _mutation_changes(intent: str, case_id: str, p: dict[str, Any]) -> list[str]:
    """写操作预览：confirm_action 卡的 changes 列表（用户确认依据，P0-1）。"""
    head = f"Case: {case_id}"
    if intent == "dissect":
        rev = str(p.get("document_revision_id") or "自动选取第一篇文档")
        return [
            "创建 1 个拆解运行（DissectDocument）",
            "写入元素提取与证据 span",
            head,
            f"文档: {rev}",
        ]
    if intent == "compare":
        ids = list(p.get("document_revision_ids") or [])
        n = len(ids) if ids else "自动选取前 2 篇"
        return [
            "创建 1 个跨源比较运行（CompareSources）",
            "写入 ComparisonSet",
            head,
            f"文档版本: {n}",
        ]
    if intent == "report":
        rtype = str(p.get("report_type") or "structured_summary")
        return [
            f"创建 1 个报告草稿（{rtype}）+ Artifact/Revision（draft）",
            head,
            "归档仍需您在 REPORT 模式确认（HITL）",
        ]
    if intent == "challenge":
        return ["创建 1 个挑战运行（ChallengeClaim）", "写入质询问题与反证", head]
    return ["创建 1 个分析运行", head]


def _prepare_run(
    store: Any, *, kind: str, case_id: str, refs: list[str], now: str
) -> tuple[dict[str, Any] | None, Any]:
    """幂等复用或新建 queued run；返回 (existing, run)。existing 非 None = 复用。"""
    refs_json = json.dumps(list(refs), ensure_ascii=False, separators=(",", ":"))
    existing = store.active_run(kind, case_id, refs_json)
    if existing is not None:
        return existing, None
    run = AnalysisRun(
        run_id=f"run-{uuid4().hex[:14]}",
        case_id=case_id,
        kind=kind,  # type: ignore[arg-type]
        engine="llm" if kind in _LLM_RUN_KINDS else "rule",
        status="queued",
        input_refs=list(refs),
        started_at=now,
    )
    store.add_analysis_run(run)
    return None, run


def _finish_failed(research: Any, run_id: str, exc: Exception, now: str) -> None:
    """后台/内联执行失败 → run 落 failed（根因留痕，不传染会话）。"""
    try:
        research.finish_analysis_run(
            run_id,
            status="failed",
            error=str(exc) or type(exc).__name__,
            finished_at=now,
        )
    except Exception:  # noqa: BLE001 连接级失败不反噬线程
        pass


def _launch_workflow(
    *,
    kind: str,
    case_id: str,
    refs: list[str],
    call: Any,
    research: Any,
    research_factory: Any = None,
    workflows: Any = None,
    workflows_factory: Any = None,
    now: str,
) -> dict[str, Any]:
    """chat 侧异步启动（与 object_api._launch 同协议，生产主路）：

    幂等复用活跃 run → queued 落库 → 后台线程执行 → chat 只负责触发不等待。
    sqlite 连接禁止跨线程复用：后台线程内经 factory 重建线程本地连接/工作流
    （线程内无事件循环，asyncio.run 安全）。仅当 research_factory /
    workflows_factory 任一提供时进入本路径。
    """
    store = research_factory() if research_factory is not None else research
    existing, run = _prepare_run(store, kind=kind, case_id=case_id, refs=refs, now=now)
    if existing is not None:
        return {
            "run_id": str(existing["run_id"]),
            "status": str(existing["status"]),
            "reused": True,
        }

    def _exec() -> None:
        try:
            wf = workflows_factory() if workflows_factory is not None else workflows
            out = call(wf, run.run_id)
            if asyncio.iscoroutine(out):
                asyncio.run(out)  # async workflow（dissect/report/translate）
        except Exception as exc:  # noqa: BLE001
            rs = research_factory() if research_factory is not None else research
            _finish_failed(rs, run.run_id, exc, now)

    threading.Thread(target=_exec, daemon=True, name=f"chat-{kind}-{run.run_id}").start()
    return {"run_id": run.run_id, "status": "queued", "reused": False}


async def _run_workflow_inline(
    *,
    kind: str,
    case_id: str,
    refs: list[str],
    call: Any,
    research: Any,
    workflows: Any,
    now: str,
) -> dict[str, Any]:
    """无 factory 的退化路径（测试/CLI）：当前事件循环内联 await 执行。

    run_chat_command 本身是协程，调用方必在事件循环内——此处不可 asyncio.run
    （RuntimeError），改为直接 await；返回前读取 run 终态，卡片状态如实反映。
    """
    existing, run = _prepare_run(research, kind=kind, case_id=case_id, refs=refs, now=now)
    if existing is not None:
        return {
            "run_id": str(existing["run_id"]),
            "status": str(existing["status"]),
            "reused": True,
        }
    try:
        out = call(workflows, run.run_id)
        if asyncio.iscoroutine(out):
            await out
    except Exception as exc:  # noqa: BLE001
        _finish_failed(research, run.run_id, exc, now)
    final = research.get_analysis_run(run.run_id)
    return {
        "run_id": run.run_id,
        "status": str((final or {}).get("status") or "queued"),
        "reused": False,
    }


async def run_chat_command(
    message: str,
    history: list[dict[str, str]],
    *,
    bronze: Any,
    store: Any,
    gold: Any,
    registry: Any,
    research: Any = None,
    workflows: Any = None,
    research_factory: Any = None,
    workflows_factory: Any = None,
    router: Any = None,
    tier: Any = None,
    gdelt_proxy: str | None = None,
    now: datetime | None = None,
    case_id: str = "",
    params: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """指挥模式单轮会话：意图路由 → 中间件链 → 执行接线 → 结构化卡片。

    中间件链（函数链，不引框架）：resolve_intent → context_injector（question
    路径注入 ResearchState 摘要）→ hitl_gate（pending HITL 卡前置注入）。
    执行类意图（plan/dissect/compare/report/challenge）触发工作流后立即返回
    run_id（异步 202 协议，chat 不等待）；status/observe/hitl 只读汇总；
    answer_case_question 基于 Case 上下文只读直答（不建 run，响应附
    optional_actions 只读建议卡）；question 走既有 run_chat LLM 循环。返回
    {reply, message_type, intent, intent_by, cards, citations, tools_used, rounds}。

    P0-1 权限纪律：执行类意图一律 state_mutation——未经 ``confirmed=True``
    （用户在卡片上显式确认）不触发任何工作流，返回 confirm_action 预览卡；
    用户消息含否定/只读约束（detect_read_only_forced）时进一步降级为
    draft_action（只回答+建议，绝不执行，即使 confirmed 也不放行约束轮）。
    """
    now_dt = now or datetime.now(UTC)
    now_s = now_dt.isoformat()
    p = dict(params or {})
    intent, intent_by = await resolve_intent(message, router=router, tier=tier)
    cards: list[dict[str, Any]] = hitl_gate(research)
    case = research.get_case(case_id) if (research is not None and case_id) else None
    read_only_forced = detect_read_only_forced(message) and not confirmed
    base = {
        "citations": [],
        "tools_used": (),
        "rounds": 0,
        "intent": intent,
        "intent_by": intent_by,
        "cards": cards,
        "read_only_forced": read_only_forced,
    }

    def _abstain(reason: str) -> dict[str, Any]:
        reply = (
            f"请先打开一个研究 Case，再在 Case 上下文中指挥工作流执行。（无法执行根因：{reason}）"
        )
        return {**base, "reply": reply, "message_type": "abstention"}

    if intent in _COMMAND_WORKFLOWS:
        if case is None:
            reason = f"case not found: {case_id}" if case_id else "未提供 case_id"
            return _abstain(reason)
        wf_name, run_kind = _COMMAND_WORKFLOWS[intent]
        docs = research.case_documents(case_id)
        launch_args: dict[str, Any] = {"kind": run_kind, "case_id": case_id}
        if intent == "dissect":
            rev_id = str(
                p.get("document_revision_id") or (docs[0]["document_revision_id"] if docs else "")
            )
            if not rev_id:
                return _abstain("该 Case 尚未挂载任何文档（请先在收件箱入案）")
            launch_args.update(
                refs=[rev_id],
                call=lambda wf, rid: wf.dissect_document(case_id, rev_id, run_id=rid),
            )
        elif intent == "compare":
            rev_ids = [str(x) for x in (p.get("document_revision_ids") or [])]
            if len(rev_ids) < 2:
                rev_ids = [str(d["document_revision_id"]) for d in docs[:2]]
            if len(rev_ids) < 2:
                return _abstain("跨源比较需要至少 2 个文档版本，该 Case 目前不足")
            launch_args.update(
                refs=rev_ids, call=lambda wf, rid: wf.compare_sources(case_id, rev_ids, run_id=rid)
            )
        elif intent == "report":
            report_type = str(p.get("report_type") or "structured_summary")
            title = str(p.get("title") or "").strip() or (case.title or case.question)[:40]
            item_key = str(p.get("item_key") or "")
            launch_args.update(
                refs=[item_key or title],
                call=lambda wf, rid: wf.build_report(
                    case_id,
                    report_type=report_type,
                    title=title,
                    item_key=item_key,
                    run_id=rid,
                ),
            )
        else:  # challenge
            claims = research.claims_for_case(case_id)
            claim_id = str(p.get("claim_id") or (claims[-1].claim_id if claims else ""))
            if not claim_id:
                return _abstain("该 Case 尚无 claim（先从拆解元素建立可质询的主张）")
            launch_args.update(
                refs=[claim_id],
                call=lambda wf, rid: wf.challenge_claim(case_id, claim_id, run_id=rid),
            )
        if read_only_forced:
            # P0-1：用户显式禁止写操作——最高优先级，降级为建议（绝不执行）
            wf_name = _COMMAND_WORKFLOWS[intent][0]
            cards.append(
                {
                    "type": "confirm_action",
                    "action_id": "",
                    "intent": intent,
                    "title": "已按您的只读约束跳过执行",
                    "changes": [],
                    "needs_confirmation": False,
                }
            )
            return {
                **base,
                "reply": (
                    f"已遵循您的只读约束：本次不会创建、修改或保存任何数据。"
                    f"如需执行「{wf_name}」，请去掉约束表述后再发送，或在页面上手动操作。"
                ),
                "message_type": "abstention",
            }
        if not confirmed:
            # P0-1 写操作确认门：预览将产生的变更，等待用户显式确认
            changes = _mutation_changes(intent, case_id, p)
            cards.append(
                {
                    "type": "confirm_action",
                    "action_id": f"act-{intent}-{case_id}",
                    "intent": intent,
                    "title": "待确认的写操作",
                    "changes": changes,
                    "needs_confirmation": True,
                    "message": message,
                }
            )
            return {
                **base,
                "cards": cards,
                "reply": "此操作将创建分析运行（写操作）。请核对以下变更，确认后执行。",
                "message_type": "hitl_request",
            }
        use_thread = research_factory is not None or workflows_factory is not None
        if use_thread:
            launched = _launch_workflow(  # 线程模式：触发即返回，不等待
                research=research,
                research_factory=research_factory,
                workflows=workflows,
                workflows_factory=workflows_factory,
                now=now_s,
                **launch_args,
            )
        else:
            launched = await _run_workflow_inline(
                research=research,
                workflows=workflows,
                now=now_s,
                **launch_args,
            )
        cards.append(
            _card_tool_call(
                wf_name,
                str(launched["status"]),
                f"case={case_id} refs={','.join(launch_args['refs'])}",
            )
        )
        cards.append(_card_progress(str(launched["run_id"]), run_kind, str(launched["status"])))
        cards.append(_card_case(case))
        reused = "复用进行中的运行" if launched["reused"] else "已在后台执行"
        run_id = launched["run_id"]
        return {
            **base,
            "cards": cards,
            "reply": (
                f"已触发 {wf_name}（run_id={run_id}，状态 {launched['status']}，{reused}）。"
                f"可用「状态」查询进度，或轮询 GET /api/analysis-runs/{run_id}。"
            ),
            "message_type": "tool_call",
        }

    if intent == "plan":
        if case is None:
            reason = f"case not found: {case_id}" if case_id else "未提供 case_id"
            return _abstain(reason)
        result = await build_research_plan(
            case_id,
            research=research,
            router=router,
            question=str(p.get("question") or message),
            now_fn=lambda: now_s,
        )
        steps = list(result.get("steps") or [])
        status = str(result.get("status") or "")
        cards.append(_card_progress(str(result.get("run_id") or ""), "plan", status))
        cards.append(_card_case(case))
        if steps:
            titles = "；".join(f"{i + 1}. {s['title']}" for i, s in enumerate(steps[:6]))
            return {
                **base,
                "cards": cards,
                "reply": f"研究计划已生成（run {result.get('run_id')}）：{titles}",
                "message_type": "plan",
            }
        error = str(result.get("error") or "模型返回空计划（诚实弃权）")
        return {
            **base,
            "cards": cards,
            "reply": f"计划未能生成：{error}",
            "message_type": "abstention",
        }

    if intent == "status":
        if research is None:
            return {
                **base,
                "reply": "研究库上下文不可用（research 未注入）。",
                "message_type": "abstention",
            }
        runs = [r for r in research.analysis_runs(50) if not case_id or r.case_id == case_id]
        cards.append(_runs_summary_card(runs))
        if case is not None:
            cards.append(_card_case(case))
        counts = Counter(r.status for r in runs)
        summary = "、".join(f"{k}×{v}" for k, v in sorted(counts.items())) or "无运行记录"
        return {
            **base,
            "cards": cards,
            "reply": f"最近 {len(runs)} 次分析运行：{summary}。详情见 runs_summary 卡。",
            "message_type": "answer",
        }

    if intent == "observe":
        card = _observe_card(store, now_dt)
        cards.append(card)
        n = int(card["n_events"])
        latest = card["recent_events"][-1] if card["recent_events"] else None
        if latest is not None:
            lead = f"当前共 {n} 个事件；最新：{latest['event_id']}「{latest['title']}」。"
        else:
            lead = "当前窗口暂无事件。"
        return {
            **base,
            "cards": cards,
            "reply": f"{lead} {card['hint']}。",
            "message_type": "answer",
        }

    if intent == "hitl":
        if not cards:
            return {**base, "reply": "当前没有待人工确认（HITL）事项。", "message_type": "answer"}
        listing = "；".join(f"{c['hitl_id']}（{c['summary']}）" for c in cards)
        return {
            **base,
            "cards": cards,
            "reply": f"当前有 {len(cards)} 条待人工确认：{listing}。请在 HITL 队列裁决。",
            "message_type": "hitl_request",
        }

    if intent == "answer_case_question":
        # T3 只读路径：组装 Case 上下文直接回答，不创建 analysis_run/不写业务库
        # （chat 消息本身由 API 层持久化，与本分支无关）。
        if case is None:
            reason = f"case not found: {case_id}" if case_id else "未提供 case_id"
            return _abstain(reason)
        context = _case_question_context(research, case)
        reply = ""
        if router is not None:
            try:
                if tier is None:
                    from oh_contracts.enums import Tier

                    tier = Tier.IO
                out, _ref, _usage = await router.invoke(
                    tier,
                    _ANSWER_CASE_SYSTEM,
                    f"Case 上下文：\n{context}\n\n问题：{message}",
                    ChatOutput,
                )
                reply = str(out.reply or "")
            except Exception:  # noqa: BLE001 LLM 失败→规则回答兜底
                reply = ""
        if not reply:
            docs = research.case_documents(case_id)
            claims = research.claims_for_case(case_id)
            titles = "、".join(
                str(d.get("title") or d.get("source_id") or d["document_revision_id"])
                for d in docs[:20]
            )
            reply = (
                f"当前 Case 共 {len(docs)} 篇文档：{titles or '（无）'}；claims {len(claims)} 条。"
            )
        cards.append(_card_case(case))
        cards.append(
            _optional_actions_card(
                [
                    {"label": "拆解文档", "message": "拆解这篇文档"},
                    {"label": "跨源比较", "message": "比较这些版本"},
                    {"label": "生成报告", "message": "生成一份报告"},
                    {"label": "查看运行状态", "message": "看看运行状态"},
                ]
            )
        )
        return {**base, "cards": cards, "reply": reply, "message_type": "answer"}

    # question（默认）：既有 LLM⇄tools 循环 + 上下文注入
    ctx = context_injector(research, case_id)
    result = await run_chat(
        message,
        history,
        bronze=bronze,
        store=store,
        gold=gold,
        registry=registry,
        router=router,
        tier=tier,
        gdelt_proxy=gdelt_proxy,
        now=now_dt,
        context=ctx,
    )
    if case is not None:
        cards.append(_card_case(case))
    return {
        **base,
        **result,  # reply/citations/tools_used/rounds 以真实运行结果为准
        "cards": cards,
        # 无模型离线聚合=诚实弃权（与端点既有语义一致）
        "message_type": "answer" if router is not None else "abstention",
    }


# ---------------------------------------------------------------- store


class ChatStore:
    """会话历史（独立 sqlite；thread_id 会话，每轮全量注入）。

    message_type 为消息九类型（默认 'answer'）；cards_json 为结构化卡片
    （JSON 数组，默认 '[]'）。旧库缺列时打开即幂等 ALTER TABLE 补列
    （DEFAULT 值），历史消息自动归为 answer / 空卡片。
    """

    def __init__(self, path: str | Any) -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS chat_messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " thread_id TEXT NOT NULL, role TEXT NOT NULL,"
            " content TEXT NOT NULL, ts TEXT NOT NULL,"
            " message_type TEXT NOT NULL DEFAULT 'answer',"
            " cards_json TEXT NOT NULL DEFAULT '[]')"
        )
        cols = {
            str(r[1]) for r in self._conn.execute("PRAGMA table_info(chat_messages)").fetchall()
        }
        if "message_type" not in cols:
            self._conn.execute(
                "ALTER TABLE chat_messages ADD COLUMN message_type TEXT NOT NULL DEFAULT 'answer'"
            )
        if "cards_json" not in cols:
            self._conn.execute(
                "ALTER TABLE chat_messages ADD COLUMN cards_json TEXT NOT NULL DEFAULT '[]'"
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
            "SELECT role, content, ts, message_type, cards_json FROM chat_messages"
            " WHERE thread_id=? ORDER BY id",
            (thread_id,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            msg = dict(r)
            try:
                cards = json.loads(msg.pop("cards_json") or "[]")
            except (TypeError, ValueError):
                cards = []
            msg["cards"] = cards if isinstance(cards, list) else []
            out.append(msg)
        return out

    def append(
        self,
        thread_id: str,
        role: str,
        content: str,
        ts: str,
        message_type: MessageType = "answer",
        cards: list[dict[str, Any]] | None = None,
    ) -> None:
        if message_type not in MESSAGE_TYPES:
            raise ValueError(f"unknown message_type: {message_type}")
        self._conn.execute(
            "INSERT INTO chat_messages(thread_id, role, content, ts, message_type, cards_json)"
            " VALUES (?,?,?,?,?,?)",
            (
                thread_id,
                role,
                content,
                ts,
                message_type,
                json.dumps(cards or [], ensure_ascii=False),
            ),
        )
        self._conn.commit()


__all__ = [
    "CHAT_INTENTS",
    "CHAT_SYSTEM",
    "ChatOutput",
    "ChatStore",
    "ChatToolCall",
    "ChatIntent",
    "MAX_TOOL_ROUNDS",
    "MESSAGE_TYPES",
    "MessageType",
    "TOOL_NAMES",
    "build_chat_graph",
    "classify_intent",
    "classify_intent_llm",
    "context_injector",
    "execute_tool",
    "detect_read_only_forced",
    "hitl_gate",
    "resolve_intent",
    "run_chat",
    "run_chat_command",
]
