"""LangGraph agent 基座（M5 A0-1）。

提供四图（02 拆解 / 03 跟踪 / 04 档案 / 07 parent）共享的：
- AgentState：同构状态，含 pending_user（用户随时打断通道）；
- AgentSessions：agent_sessions.sqlite（SqliteSaver checkpoints + pending 输入队列 +
  会话元数据），thread_id 命名空间 ``{agent_kind}:{uuid}``；
- user_gate / absorb_user_input：横切条件边——任何节点完成后检查 pending_user，
  有则先吸收（补充信息 / 修改指令 / 紧急跳转）再继续；
- make_checkpointer：SqliteSaver 封装（每节点自动 checkpoint，interrupt 与
  user_gate 均落在检查点边界）。

设计文档：docs/FEATURE_PLAN_M5.md §五。
v1 使用同步 SqliteSaver（FastAPI 端点在线程池中 invoke）；并发量上来后可换
AsyncSqliteSaver，接口不变。
"""

from __future__ import annotations

import json
import operator
import uuid
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt
from oh_contracts.strict import _StrictBase

UserInputKind = Literal["info", "instruction", "redirect"]

_PENDING_DDL = """
CREATE TABLE IF NOT EXISTS pending_user_inputs (
    input_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pending_thread ON pending_user_inputs(thread_id, consumed);
CREATE TABLE IF NOT EXISTS agent_sessions (
    thread_id TEXT PRIMARY KEY,
    agent_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);
"""

AGENT_KINDS = ("dissection", "tracking", "memory", "parent")  # 02/03/04/07


class AgentState(TypedDict, total=False):
    """四图同构状态。subgraph 与父图透传；未设键读侧必须用 .get。

    messages/absorbed/errors 为增量 channel（operator.add）：节点只返回新增项，
    框架负责累积——否则并行/回跑节点会互相覆盖（LastValue 语义陷阱）。
    """

    messages: Annotated[list[dict[str, str]], operator.add]  # {"role", "content"}
    article_ids: list[str]
    dissection: dict[str, Any] | None
    reports: list[dict[str, Any]]
    queue: list[dict[str, Any]]
    lang: str  # BCP-47，i18n 与翻译学家 prompt 选择锚
    user_confirm: bool
    pending_user: dict[str, Any] | None  # {"kind": UserInputKind, "text": str}
    absorbed: Annotated[list[dict[str, Any]], operator.add]  # 已吸收（UI 回显「已采纳」）
    revise_hint: str  # absorb(instruction) 设置，报告/拆解 revise 消费
    errors: list[str]


class UserInput(_StrictBase):
    kind: UserInputKind
    text: str


class AgentSessions:
    """agent_sessions.sqlite：checkpoints（SqliteSaver 自管表）+ pending 队列 + 会话表。"""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Connection | None = None

    def _connect(self) -> Connection:
        if self._conn is None:
            import sqlite3

            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.executescript(_PENDING_DDL)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---- 会话元数据 ----

    def create_session(self, agent_kind: str, *, title: str) -> str:
        """新会话；thread_id = {agent_kind}:{uuid8}（checkpoint 命名空间）。"""
        if agent_kind not in AGENT_KINDS:
            raise ValueError(f"unknown agent kind: {agent_kind}")
        thread_id = f"{agent_kind}:{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC).isoformat()
        self._connect().execute(
            "INSERT INTO agent_sessions VALUES (?,?,?,?,?)",
            (thread_id, agent_kind, title, now, now),
        )
        self._conn.commit()
        return thread_id

    def touch(self, thread_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._connect().execute(
            "UPDATE agent_sessions SET last_active_at=? WHERE thread_id=?", (now, thread_id)
        )
        self._conn.commit()

    def list_sessions(self, agent_kind: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT thread_id,agent_kind,title,created_at,last_active_at FROM agent_sessions"
        params: tuple = ()
        if agent_kind:
            sql += " WHERE agent_kind=?"
            params = (agent_kind,)
        sql += " ORDER BY last_active_at DESC"
        rows = self._connect().execute(sql, params).fetchall()
        return [
            dict(
                zip(
                    ["thread_id", "agent_kind", "title", "created_at", "last_active_at"],
                    r,
                    strict=True,
                )
            )
            for r in rows
        ]

    # ---- pending 输入队列（用户随时打断的注入点）----

    def push_input(self, thread_id: str, kind: UserInputKind, text: str) -> str:
        """前端 AgentDock 任意时刻调用；图在下一个节点边界经 user_gate 消费。"""
        input_id = f"ui-{uuid.uuid4().hex[:12]}"
        self._connect().execute(
            "INSERT INTO pending_user_inputs VALUES (?,?,?,?,?,0)",
            (input_id, thread_id, kind, text, datetime.now(UTC).isoformat()),
        )
        self._conn.commit()
        return input_id

    def drain_inputs(self, thread_id: str) -> list[dict[str, Any]]:
        """取走该 thread 全部未消费输入（按 created_at 序），标记 consumed。"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT input_id,kind,text FROM pending_user_inputs"
            " WHERE thread_id=? AND consumed=0 ORDER BY created_at,input_id",
            (thread_id,),
        ).fetchall()
        if not rows:
            return []
        conn.execute(
            "UPDATE pending_user_inputs SET consumed=1 WHERE thread_id=? AND consumed=0",
            (thread_id,),
        )
        conn.commit()
        return [{"input_id": r[0], "kind": r[1], "text": r[2]} for r in rows]


def make_checkpointer(sessions: AgentSessions) -> SqliteSaver:
    """SqliteSaver（sync）：conn 生命周期随 sessions；关闭由 AgentSessions.close 负责。"""
    return SqliteSaver(sessions._connect())  # noqa: SLF001 — 同包基座共享连接


# ---- analysis_locale 输出语言约束（P1-8 多语言审计）----

_LOCALE_NAMES: dict[str, str] = {"zh": "中文", "en": "English"}

_OUTPUT_LANGUAGE_LINE = (
    "分析输出语言：所有 normalized_value/summary/section 正文使用 {locale} 书写；"
    "元素键名(element)保持英文枚举不变"
)


def output_language_line(locale: str) -> str:
    """analysis_locale 非空时返回追加到 user prompt 末尾的输出语言约束行；空则空串。"""
    if not locale:
        return ""
    name = _LOCALE_NAMES.get(locale, locale)
    return _OUTPUT_LANGUAGE_LINE.format(locale=name)


# ---- user_gate 横切机制 ----


def drain_pending(sessions: AgentSessions, thread_id: str) -> dict[str, Any] | None:
    """把 sqlite pending 队列合并为单条注入 state（多输入按序拼接 text）。"""
    items = sessions.drain_inputs(thread_id)
    if not items:
        return None
    if len(items) == 1:
        return {"kind": items[0]["kind"], "text": items[0]["text"]}
    return {"kind": "info", "text": "\n".join(i["text"] for i in items)}


def user_gate(state: AgentState) -> str:
    """条件边路由函数：有 pending_user → absorb，否则按图各自主路（absorb 完也回主路）。

    用法：graph.add_conditional_edges("work", user_gate,
    {"absorb": "absorb_user_input", "main": "next_node"})；absorb 节点固定回主路。
    """
    return "absorb" if state.get("pending_user") else "main"


def absorb_user_input(state: AgentState) -> dict[str, Any]:
    """吸收用户输入：info→记录；instruction→设 revise_hint；redirect→仅记录待路由。

    不做业务决策（重跑/重路由由各图的 main 路由读取 absorbed/revise_hint 决定），
    保证四图共享同一语义。
    """
    pending = state.get("pending_user")
    if not pending:
        return {}
    update: dict[str, Any] = {
        "pending_user": None,
        "absorbed": [pending],
        "messages": [{"role": "user", "content": pending["text"]}],
    }
    if pending["kind"] == "instruction":
        update["revise_hint"] = pending["text"]
    return update


def confirm_save(prompt: str) -> dict[str, Any]:
    """interrupt() 封装：确认式存档闸门（02 存报告 / 04 定报纸 / 03 复核）。

    resume 时 Command(resume={...}) 的载荷原样返回；取消约定载荷 {"confirmed": False}。
    """
    payload = interrupt(prompt)
    return payload if isinstance(payload, dict) else {"confirmed": bool(payload)}


def state_brief(state: AgentState) -> str:
    """供日志/埋点的状态摘要（不含原文，只含形状）。"""
    return json.dumps(
        {
            "n_messages": len(state.get("messages", [])),
            "n_articles": len(state.get("article_ids", [])),
            "n_absorbed": len(state.get("absorbed", [])),
            "lang": state.get("lang", ""),
            "revise": bool(state.get("revise_hint")),
        },
        ensure_ascii=False,
    )
