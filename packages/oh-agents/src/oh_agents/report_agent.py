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
from pydantic import BaseModel, model_validator

from .agent_base import AgentSessions, make_checkpointer, output_language_line

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
    "每个分节必须给出 evidence_refs：只能引用输入材料中真实出现的 id"
    "（extraction_id/claim_id/document_revision_id），禁止虚构 id；"
    "某分节找不到任何可引用证据时，evidence_refs 留空并在 body 写明「证据不足」。"
    "审核纪律：默认只引用 human_status=confirmed 的元素；"
    "若引用未审核（unreviewed）元素，必须在 section 正文中逐项注明『（未审核）』，"
    "不得混用不标注。"
)

# Prompt 版本标注：随 revision content / run output 落库（版本保留 Prompt 版本，P0-C T2）。
# 修改 _REPORT_SYSTEM 注入纪律时必须同步递增（report-v2, report-v3, ...）。
REPORT_PROMPT_VERSION = "report-v3"


class ReportOutputP(BaseModel):
    """LLM 结构化输出：2-4 个分节；空产出 schema 层拒绝以触发重试。"""

    sections: list[ReportSection]

    @model_validator(mode="after")
    def _non_empty(self) -> "ReportOutputP":
        if not self.sections:
            raise ValueError("llm_empty_output: 模型未产出任何报告分节")
        return self


class ReportState(TypedDict, total=False):
    item_key: str
    kind: str
    title: str
    text: str
    dissection_json: str
    evidence_json: str
    analysis_locale: str
    feedback: str
    sections: list[ReportSection]
    report: AgentReport
    llm_failed: str
    _model_hint: str
    usage: dict[str, Any]
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
    llm_timeout: float = 120.0,
):
    """组装报告图；router/store/时钟闭包注入。"""

    async def llm_node(state: ReportState) -> dict[str, Any]:
        if router is None:
            return {"errors": ["llm_unavailable: router 未配置"], "llm_failed": "router 未配置"}
        if state.get("evidence_json"):
            # Case 工作流路径：完整证据包（原文/逐元素提取/主张/挑战/比较）
            user = (
                f"报告视角：{REPORT_KIND_ZH.get(state['kind'], state['kind'])}\n"
                f"文章标题：{state.get('title', '')}\n"
                "Case 证据包（全部为该案例库内真实材料，id 可直接引用）：\n"
                f"{state['evidence_json']}"
            )
        else:
            user = (
                f"报告视角：{REPORT_KIND_ZH.get(state['kind'], state['kind'])}\n"
                f"文章标题：{state.get('title', '')}\n"
                f"拆解结果（18 元素闭集：{','.join(ELEMENT_KEYS)}）：\n"
                f"{state.get('dissection_json', '{}')}\n"
                f"原文摘录：\n{(state.get('text') or '')[:_MAX_SOURCE_CHARS]}"
            )
        # 用户反馈修订（P0-C T3）：非空时注入逐条回应纪律（与普通报告同一校验路径）
        if state.get("feedback"):
            user = (
                f"{user}\n用户对上一版草稿的反馈（生成修订版时必须逐条回应）：{state['feedback']}"
            )
        # analysis_locale 显式指定时约束输出语言；空则维持默认（不追加）
        lang_line = output_language_line(state.get("analysis_locale", ""))
        if lang_line:
            user = f"{user}\n{lang_line}"
        # Prompt 版本标注随请求注入（溯源：产出版本可对回确切 prompt 纪律）
        user = f"{user}\n（Prompt 版本：{REPORT_PROMPT_VERSION}）"
        try:
            # 报告曾走 Strategic（GLM 长结构化输出）并被 90 秒外层抢先取消，
            # fallback 根本没有机会执行。Execute 链优先走已验证的 JSON 路径；
            # timeout 仅包住完整路由调用，失败仍会留下明确 abstention 根因。
            async with asyncio.timeout(max(1.0, llm_timeout)):
                parsed, ref, usage = await router.invoke(
                    Tier.EXECUTE, _REPORT_SYSTEM, user, ReportOutputP
                )
        except Exception as exc:  # noqa: BLE001 —— 根因落 errors，persist 降级
            msg = str(exc) or type(exc).__name__
            return {"errors": [f"llm_failed: {msg}"], "llm_failed": msg}
        return {
            "sections": list(parsed.sections),
            "_model_hint": f"{ref.provider}/{ref.model_id}",
            "usage": {
                "provider": ref.provider,
                "model": ref.model_id,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "latency_ms": usage.latency_ms if usage else 0,
            },
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
