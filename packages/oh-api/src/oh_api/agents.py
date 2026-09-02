"""Agent 会话 API（A4）：会话创建/列表/随时补充输入（user_gate 生产入口）。

真实 graph 运行与流式事件在 Phase B 接入；本路由只管会话账本与 pending 输入通道。
"""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from oh_agents.agent_base import UserInputKind
from pydantic import BaseModel

AgentKind = Literal["dissection", "tracking", "memory", "parent"]


class SessionCreate(BaseModel):
    kind: AgentKind
    title: str = ""


class SessionInput(BaseModel):
    kind: UserInputKind = "info"
    text: str


def build_router(sessions_fn) -> APIRouter:
    """sessions_fn: () -> AgentSessions（惰性单例由主线注入）。"""

    router = APIRouter(prefix="/api/agent")

    @router.post("/sessions", status_code=201)
    def create_session(body: SessionCreate) -> dict[str, Any]:
        s = sessions_fn()
        title = body.title.strip() or f"{body.kind} 会话"
        thread_id = s.create_session(body.kind, title=title)
        return {"thread_id": thread_id, "kind": body.kind}

    @router.get("/sessions")
    def list_sessions(kind: str | None = None) -> dict[str, Any]:
        return {"sessions": sessions_fn().list_sessions(kind)}

    @router.post("/sessions/{thread_id}/inputs", status_code=202)
    def push_input(thread_id: str, body: SessionInput) -> dict[str, Any]:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="text 必填")
        s = sessions_fn()
        known = any(x["thread_id"] == thread_id for x in s.list_sessions())
        if not known:
            raise HTTPException(status_code=404, detail="会话不存在")
        input_id = s.push_input(thread_id, body.kind, text)
        s.touch(thread_id)
        return {"queued": True, "input_id": input_id}

    return router


__all__ = ["build_router"]
