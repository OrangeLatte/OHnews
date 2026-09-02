"""B1 拆解 agent（DissectionGraph）：单篇文章 → 18 元素结构化拆解。

流程（langgraph）：hints（词典层标注锚） → llm（Tier.EXECUTE 结构化输出） →
persist（article_dissections，engine=llm/model_hint 溯源）。

降级语义：LLM 全候选失败 → offline 兜底（调用方注入的词典 fallback elements，
engine=offline 诚实标注——不冒充 LLM 产物）。缓存幂等由 API 层负责。
依赖（router/store/fallback/now）通过 build 参数闭包注入，不进 State。
"""

import asyncio
import datetime as _dt
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from oh_contracts.dissection import ELEMENT_KEYS, ArticleDissection, DissectionElement
from oh_contracts.enums import Tier
from pydantic import BaseModel

from .agent_base import AgentSessions, make_checkpointer

_DISSECT_SYSTEM = (
    "你是新闻拆解专家。对给定文章做结构化拆解，仅输出 JSON。"
    "元素闭集："
    + ",".join(ELEMENT_KEYS)
    + "。每个元素给 content（一句中文提炼）与可选 spans（原文 start/end 字符偏移）。"
    "文中未体现的元素直接省略，禁止编造；引文必须来自原文。"
)


class DissectionOutputP(BaseModel):
    """LLM 结构化输出：逐元素提取，无则跳过（18 元素闭集校验）。"""

    elements: list[DissectionElement]


class DissectionState(TypedDict, total=False):
    item_key: str
    title: str
    text: str
    language: str
    hints: str
    elements: list[DissectionElement]
    dissection: ArticleDissection
    llm_failed: str
    _model_hint: str
    errors: Annotated[list[str], operator.add]


def build_dissection_graph(
    *,
    router: Any = None,
    store: Any = None,
    fallback_fn: Any = None,
    now_fn: Any = None,
    sessions: AgentSessions | None = None,
    llm_timeout: float = 90.0,
):
    """组装拆解图；router/store/兜底元素工厂/时钟均闭包注入。"""

    async def hints_node(state: DissectionState) -> dict[str, Any]:
        if not state.get("hints"):
            return {"hints": "（无词典标注可用）"}
        return {}

    async def llm_node(state: DissectionState) -> dict[str, Any]:
        if router is None:
            return {"errors": ["llm_unavailable: router 未配置"], "llm_failed": "router 未配置"}
        user = (
            f"标题：{state.get('title', '')}\n语言：{state.get('language', '')}\n"
            f"词典标注锚：{state.get('hints', '')}\n正文：\n{state.get('text', '')}"
        )
        try:
            async with asyncio.timeout(llm_timeout):
                parsed, ref = await router.invoke(
                    Tier.EXECUTE, _DISSECT_SYSTEM, user, DissectionOutputP
                )
        except Exception as exc:  # noqa: BLE001 —— 根因落 errors，persist 降级 offline
            return {"errors": [f"llm_failed: {exc}"], "llm_failed": str(exc)}
        return {"elements": list(parsed.elements), "_model_hint": f"{ref.provider}/{ref.model_id}"}

    async def persist_node(state: DissectionState) -> dict[str, Any]:
        now = now_fn() if now_fn else _dt.datetime.now(_dt.UTC)
        if state.get("llm_failed"):
            elements = list(fallback_fn(state) if fallback_fn else [])
            engine = "offline"
            model_hint = ""
        else:
            elements = list(state.get("elements") or [])
            if not elements:
                # LLM 返回空产出 = 虚假成功：诚实降级 offline，不冒充 LLM 结果
                elements = list(fallback_fn(state) if fallback_fn else [])
                engine = "offline"
                model_hint = ""
                state.setdefault("errors", []).append(
                    "llm_empty_output: LLM 返回空拆解，已降级为词典拆解"
                )
            else:
                engine = "llm"
                model_hint = state.get("_model_hint") or ""
        d = ArticleDissection(
            item_key=state["item_key"],
            title=state.get("title", ""),
            elements=elements,
            engine=engine,  # type: ignore[arg-type]
            language=state.get("language", ""),
            model_hint=model_hint,
            dissected_at=now,
        )
        if store is not None:
            store.upsert_dissection(
                d.item_key,
                d.model_dump(mode="json"),
                d.engine,
                d.dissected_at,
                language=d.language,
            )
        return {"dissection": d}

    g: StateGraph = StateGraph(DissectionState)
    g.add_node("hints", hints_node)
    g.add_node("llm", llm_node)
    g.add_node("persist", persist_node)
    g.set_entry_point("hints")
    g.add_edge("hints", "llm")
    g.add_edge("llm", "persist")
    g.add_edge("persist", END)
    if sessions is not None:
        return g.compile(checkpointer=make_checkpointer(sessions))
    return g.compile()


def fallback_elements_from_hints(hints: dict[str, Any]) -> list[DissectionElement]:
    """offline 兜底：S1 词典标注 → 元素（诚实降级）。

    真实 payload 结构（S1 annotations 表拍平）：roles 是逐句 SemanticRole dict 列表；
    actions 是 ActionMention dict 列表；emotions.expressed 是 label→密度 dict。
    全程防御式解析，结构不符直接跳过该项。
    """
    out: list[DissectionElement] = []

    subject = ""
    for r in hints.get("roles") or []:
        if isinstance(r, dict):
            v = r.get("subject")
            if isinstance(v, str) and v:
                subject = v
                break
    if subject:
        out.append(DissectionElement(element="actor", content=f"词典命中主体：{subject}"))

    for a in (hints.get("actions") or [])[:3]:
        verb = a.get("verb") if isinstance(a, dict) else None
        if isinstance(verb, str) and verb:
            out.append(DissectionElement(element="action", content=f"词典命中动作：{verb}"))

    emotions = hints.get("emotions")
    if isinstance(emotions, dict):
        expressed = emotions.get("expressed")
        if isinstance(expressed, dict) and expressed:
            top = max(
                expressed.items(),
                key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0,
            )
            out.append(DissectionElement(element="tone", content=f"词典情绪基调：{top[0]}"))
    return out
