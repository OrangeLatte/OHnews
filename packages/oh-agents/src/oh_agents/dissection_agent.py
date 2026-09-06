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
from pydantic import BaseModel, field_validator, model_validator

from .agent_base import AgentSessions, make_checkpointer, output_language_line

# 拆解 prompt 版本（纪律改动须同步递增；run output 双写供审计）
DISSECT_PROMPT_VERSION = "dissect-v1"

_DISSECT_SYSTEM = (
    "你是新闻拆解专家。对给定文章做结构化拆解，仅输出 JSON。"
    "元素闭集："
    + ",".join(ELEMENT_KEYS)
    + "。每个元素给 content（一句中文提炼）、confidence（0-1 置信度，按下方校准规则）"
    "与可选 spans（原文 start/end 字符偏移，并给 quote=该偏移切片的逐字原文用于锚点校验）。"
    "span 覆盖纪律：每个元素的 spans 必须标注支撑它的完整原文片段——"
    "覆盖整句或完整短语（通常 20-120 字符），不要只标最小词组；"
    "元素结论若综合了文中某一段叙述，就把该段完整标注；"
    "一个元素可给多个 spans（不同位置的支撑片段各标一个）；"
    "目标是让读者通过色块读懂全文结构，而非零散点缀。"
    "坐标与 quote 必须精确对应原文（偏移漂移或引文改写的 span 会被丢弃）；"
    "文中未体现的元素直接省略，禁止编造；引文必须来自原文；"
    "禁止输出文中不存在的实体、机构、数字（禁造证据；找不到就诚实缺该元素）。"
    "信源纪律：source_reliability 只分析文中引用了哪些来源（cited sources），"
    "不得据此推断发布方身份——发布方（publisher）来自元数据注入（见用户消息），不可质疑；"
    "严格区分 publisher（元数据）/cited source（文中引用）/primary evidence（一手证据）/"
    "anonymous source（匿名信源），分析哪个写哪个，不得混同。"
    "confidence 校准：1.0 仅限原文逐字可直接引用的显式事实（hard_fact/actor 等且 span 命中）；"
    "0.6-0.85 为推断类（intent/perspective/implicit_bias/tone 等分析判断）；"
    "≤0.5 为证据不足或需外部知识的判断；禁止对推断类元素输出 1.0。"
)


class DissectionOutputP(BaseModel):
    """LLM 结构化输出：逐元素提取，无则跳过（18 元素闭集校验）。

    空产出在 schema 层拒绝：空列表是合法 JSON 但几乎必为模型输出问题，
    在此抛错可触发 router 退避重试，而非静默降级 offline。
    """

    elements: list[DissectionElement]

    @field_validator("elements", mode="before")
    @classmethod
    def _drop_bad_spans(cls, v: object) -> object:
        """剔除退化 span 而非整次拒绝：deepseek 等模型会偶发输出
        end<=start 或负偏移的坏 span（实测 18 个 validation error 全是
        spans.0.end=0），元素内容才是主要产物，span 是可选增强。"""
        if not isinstance(v, list):
            return v
        for el in v:
            if isinstance(el, dict) and el.get("spans"):
                good = [
                    s
                    for s in el["spans"]
                    if isinstance(s, dict)
                    and isinstance(s.get("start"), int)
                    and isinstance(s.get("end"), int)
                    and 0 <= s["start"] < s["end"]
                ]
                el["spans"] = good or None
        return v

    @model_validator(mode="after")
    def _non_empty(self) -> "DissectionOutputP":
        if not self.elements:
            raise ValueError("llm_empty_output: 模型未产出任何拆解元素")
        return self


class DissectionState(TypedDict, total=False):
    item_key: str
    title: str
    text: str
    language: str
    publisher: str
    analysis_locale: str
    hints: str
    elements: list[DissectionElement]
    dissection: ArticleDissection
    llm_failed: str
    _model_hint: str
    errors: Annotated[list[str], operator.add]
    usage: dict[str, Any]


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
            f"本文档发布方（publisher，来自信源注册目录，不可质疑）："
            f"{state.get('publisher') or '（未注册，按 unknown 处理，禁止臆测）'}\n"
            f"词典标注锚：{state.get('hints', '')}\n正文：\n{state.get('text', '')}"
        )
        # analysis_locale 显式指定时约束输出语言；空则维持默认（不追加）
        lang_line = output_language_line(state.get("analysis_locale", ""))
        if lang_line:
            user = f"{user}\n{lang_line}"
        user = f"{user}\n（Prompt 版本：{DISSECT_PROMPT_VERSION}）"
        try:
            async with asyncio.timeout(llm_timeout):
                parsed, ref, usage = await router.invoke(
                    Tier.EXECUTE, _DISSECT_SYSTEM, user, DissectionOutputP
                )
        except Exception as exc:  # noqa: BLE001 —— 根因落 errors，persist 降级 offline
            msg = str(exc) or type(exc).__name__
            return {"errors": [f"llm_failed: {msg}"], "llm_failed": msg}
        return {
            "elements": list(parsed.elements),
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


_QUEUE_TIER_SCORE = {"L1": 1.0, "L2": 0.8, "L3": 0.6, "L4": 0.4}


def build_queue_suggestions(
    records: list[Any],
    *,
    tier_map: dict[str, Any],
    registry: Any,
    now: _dt.datetime,
    store: Any = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """B0 确定性筛选：可靠性(0.5)+时效(0.3)+实体相关性(0.2) → 推荐入队。

    已拆解或已在队列的跳过；store 提供时写入 dissection_queue（幂等）。
    """
    import math

    out: list[dict[str, Any]] = []
    for r in records:
        norm = r.normalized or {}
        title = str(norm.get("title") or "")[:200]
        if not title:
            continue
        if store is not None and store.get_dissection(r.item_key) is not None:
            continue
        tier = tier_map.get(r.source_id)
        tier_v = str(getattr(tier, "value", tier) or "")
        reliability = _QUEUE_TIER_SCORE.get(tier_v, 0.3)
        pub = r.published_at
        if pub is None:
            continue
        days_ago = max(0.0, (now - pub).total_seconds() / 86400)
        freshness = math.exp(-days_ago / 7)
        hits = registry.match(title) if registry is not None else []
        hit = hits[0] if hits else None
        relevance = 1.0 if hit else 0.0
        score = round(0.5 * reliability + 0.3 * freshness + 0.2 * relevance, 4)
        reasons: list[str] = []
        if tier_v == "L1":
            reasons.append("官方一手来源")
        elif tier_v == "L2":
            reasons.append("权威通讯社")
        reasons.append(f"发布于 {days_ago:.1f} 天前" if days_ago >= 1 else "24 小时内发布")
        if hit:
            reasons.append(f"命中已关注实体：{hit}")
        item = {
            "item_key": r.item_key,
            "title": title,
            "source_id": r.source_id,
            "score": score,
            "reasons": reasons,
        }
        out.append(item)
        if store is not None:
            store.queue_upsert(
                r.item_key,
                score=score,
                reasons=reasons,
                created_at=now.isoformat(),
            )
    out.sort(key=lambda x: (-x["score"], x["item_key"]))
    return out[:limit]
