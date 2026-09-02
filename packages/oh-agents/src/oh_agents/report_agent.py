"""B2 研究报告 agent（ReportGraph）：拆解结果 × 六视角 → 结构化报告。

流程（langgraph）：source（装配拆解+原文摘录） → llm（Tier.STRATEGIC 结构化） →
persist（agent_reports，engine=llm/model_hint 溯源）。

降级语义：LLM 失败/空产出 → offline 模板（基于拆解元素诚实复述，engine=offline）。
依赖（router/store/now）闭包注入。report_id=rp-{sha1(item_key|kind)[:8]} 幂等。
"""

import asyncio
import datetime as _dt
import hashlib
import json
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from oh_contracts.dissection import ELEMENT_KEYS, ArticleDissection
from oh_contracts.enums import Tier
from oh_contracts.reports import AgentReport, ReportSection
from pydantic import BaseModel

from .agent_base import AgentSessions, make_checkpointer

REPORT_KIND_ZH: dict[str, str] = {
    "truth": "真实性与可信度核查",
    "intent": "意图与动机判定",
    "causal": "归因与因果推演",
    "narrative": "叙事与框架分析",
    "trend": "动态趋势与时序分析",
    "summary": "综合结构化摘要",
}

_MAX_SOURCE_CHARS = 6000

_REPORT_SYSTEM = (
    "你是资深财经分析师。基于给定的文章拆解结果与原文摘录撰写研究报告，仅输出 JSON。"
    "sections 为 2-4 个分节（title 一句 + body 一段）；所有论断必须引用拆解元素或原文，"
    "禁止编造数据与外部事实；证据不足时分节内明确写明「证据不足」，不得硬凑结论。"
)


class ReportOutputP(BaseModel):
    """LLM 结构化输出：2-4 个分节。"""

    sections: list[ReportSection]


class ReportState(TypedDict, total=False):
    item_key: str
    kind: str
    title: str
    text: str
    dissection_json: str
    sections: list[ReportSection]
    report: AgentReport
    llm_failed: str
    _model_hint: str
    errors: Annotated[list[str], operator.add]


def report_id_for(item_key: str, kind: str) -> str:
    return "rp-" + hashlib.sha1(f"{item_key}|{kind}".encode()).hexdigest()[:8]


def _source_node(state: ReportState) -> dict[str, Any]:
    if not state.get("text"):
        return {"text": "（原文未提供，仅基于拆解元素）"}
    return {}


def build_report_graph(
    *,
    router: Any = None,
    store: Any = None,
    now_fn: Any = None,
    sessions: AgentSessions | None = None,
):
    """组装报告图；router/store/时钟闭包注入。"""

    async def llm_node(state: ReportState) -> dict[str, Any]:
        if router is None:
            return {"errors": ["llm_unavailable: router 未配置"], "llm_failed": "router 未配置"}
        user = (
            f"报告视角：{REPORT_KIND_ZH.get(state['kind'], state['kind'])}\n"
            f"文章标题：{state.get('title', '')}\n"
            f"拆解结果（18 元素闭集：{','.join(ELEMENT_KEYS)}）：\n"
            f"{state.get('dissection_json', '{}')}\n"
            f"原文摘录：\n{(state.get('text') or '')[:_MAX_SOURCE_CHARS]}"
        )
        try:
            async with asyncio.timeout(90.0):
                parsed, ref = await router.invoke(
                    Tier.STRATEGIC, _REPORT_SYSTEM, user, ReportOutputP
                )
        except Exception as exc:  # noqa: BLE001 —— 根因落 errors，persist 降级
            return {"errors": [f"llm_failed: {exc}"], "llm_failed": str(exc)}
        return {
            "sections": list(parsed.sections),
            "_model_hint": f"{ref.provider}/{ref.model_id}",
        }

    async def persist_node(state: ReportState) -> dict[str, Any]:
        now = now_fn() if now_fn else _dt.datetime.now(_dt.UTC)
        if state.get("llm_failed") or not state.get("sections"):
            reason = state.get("llm_failed") or "llm_empty_output: LLM 返回空报告"
            if not state.get("llm_failed") and not state.get("sections"):
                state = {**state, "errors": [*state.get("errors", []), reason]}
            sections = _offline_sections(state, reason)
            engine = "offline"
            model_hint = ""
        else:
            sections = list(state["sections"])
            engine = "llm"
            model_hint = state.get("_model_hint") or ""
        rid = report_id_for(state["item_key"], state["kind"])
        rep = AgentReport(
            report_id=rid,
            item_key=state["item_key"],
            kind=state["kind"],  # type: ignore[arg-type]
            title=f"{REPORT_KIND_ZH.get(state['kind'], state['kind'])} · 研究报告",
            sections=sections,
            engine=engine,  # type: ignore[arg-type]
            model_hint=model_hint,
            created_at=now.isoformat(),
        )
        if store is not None:
            store.upsert_report(
                rep.model_dump(mode="json"),
                engine=rep.engine,
                model_hint=rep.model_hint,
                created_at=rep.created_at,
            )
        out: dict[str, Any] = {"report": rep}
        if not state.get("llm_failed") and not state.get("sections"):
            out["errors"] = [reason]
        return out

    g: StateGraph = StateGraph(ReportState)
    g.add_node("source", _source_node)
    g.add_node("llm", llm_node)
    g.add_node("persist", persist_node)
    g.set_entry_point("source")
    g.add_edge("source", "llm")
    g.add_edge("llm", "persist")
    g.add_edge("persist", END)
    if sessions is not None:
        return g.compile(checkpointer=make_checkpointer(sessions))
    return g.compile()


def _offline_sections(state: ReportState, reason: str) -> list[ReportSection]:
    """offline 降级：基于拆解元素诚实复述，不冒充分析。"""
    els: list[dict] = []
    try:
        dj = json.loads(state.get("dissection_json") or "{}")
        els = list(dj.get("elements") or [])
    except Exception:  # noqa: BLE001
        els = []
    lines = [
        f"- {e.get('element', '?')}：{e.get('content', '')}"
        for e in els[:10]
        if isinstance(e, dict)
    ]
    body = "\n".join(lines) if lines else "拆解元素为空，无可用素材。"
    return [
        ReportSection(title="拆解要素复述（诚实降级）", body=body),
        ReportSection(
            title="降级说明：为什么没有完整报告",
            body=f"模型未在预期时间内返回有效报告（{reason}），本节为词典拆解要素的诚实复述，"
            "不包含超出原文的推断。可稍后重试生成完整报告。",
        ),
    ]


def report_user_text(item_key: str, dissection: ArticleDissection, text: str) -> dict[str, Any]:
    """API 层装配入参 state 的便捷函数。"""
    return {
        "item_key": item_key,
        "kind": "",
        "title": dissection.title,
        "text": text,
        "dissection_json": json.dumps(
            dissection.model_dump(mode="json", exclude={"report_id"}), ensure_ascii=False
        ),
    }
