"""B1 拆解 agent（DissectionGraph）：单篇文章 → 18 元素结构化拆解。

流程（langgraph）：hints（词典层标注锚） → llm（Tier.EXECUTE 结构化输出） →
persist（article_dissections，engine=llm/model_hint 溯源）。

长文分块：llm 节点把全文按句界切成 ≤1800 字符的块，逐块调 LLM（块内偏移
标 spans），合并时把块内坐标平移块 offset 映射为全文坐标——无论文章多长，
元素与 spans 标注完整覆盖全文，单块超时/失败只丢该块（记 errors）不整体失败。

降级语义：全部块 LLM 失败 → offline 兜底（调用方注入的词典 fallback elements，
engine=offline 诚实标注——不冒充 LLM 产物）；部分块失败 → engine=llm（部分
成功是真实状态），缺块信息落 errors。缓存幂等由 API 层负责。
依赖（router/store/fallback/now）通过 build 参数闭包注入，不进 State。
"""

import asyncio
import datetime as _dt
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from oh_contracts.dissection import (
    ELEMENT_KEYS,
    ArticleDissection,
    DissectionElement,
    DissectionSpan,
)
from oh_contracts.enums import Tier
from pydantic import BaseModel, field_validator, model_validator

from .agent_base import AgentSessions, make_checkpointer, output_language_line

# 拆解 prompt 版本（纪律改动须同步递增；run output 双写供审计）。
# v3：长文分块拆解——user prompt 注入块序号/字符区间，spans 用块内偏移；
# system prompt 注明块内坐标纪律。
DISSECT_PROMPT_VERSION = "dissect-v7-1"

_CHUNK_SIZE = 1800  # 单块字符上限：确保单块输出窗口装得下全部元素+spans 标注
_SENTENCE_BOUNDARIES = "。！？!?\n"

_DISSECT_SYSTEM = (
    "你是新闻拆解专家。对给定文章做结构化拆解，仅输出 JSON。"
    "元素闭集："
    + ",".join(ELEMENT_KEYS)
    + "。每个元素给 content（一句中文提炼）、confidence（0-1 置信度，按下方校准规则）"
    "与可选 spans（原文 start/end 字符偏移，并给 quote=该偏移切片的逐字原文用于锚点校验）。"
    "标注密度纪律（v7）：高密度全覆盖——标注必须覆盖原文的 80% 以上；纯叙述、背景交代、"
    "时间推进、立场表达、修辞渲染等句子也必须归入相应元素（timeline/context/perspective/"
    "explicit_stance/implicit_bias/tone/diction 等），不得留下大片无标注区域；"
    "文章开头的导语与背景段同样必须逐句标注——场景描写归 human_interest/perspective，"
    "历史背景归 timeline/context；宁多勿漏，"
    "同一片段可给出多个不同元素的多重短 spans。"
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
    "confidence 校准（硬性上限，逐元素类型）：1.0 仅限原文逐字直接引用的显式事实与数值"
    "（hard_fact/quant_data 且 span 命中，不含任何改写归纳）；actor/target 若为文中明确点名的主体"
    "可 0.95，经推理判定的 ≤0.85；action/causal_link/timeline/stakeholder/data_scope/"
    "argument_structure 等需要归纳或串联的元素上限 0.85；intent/perspective/implicit_bias/"
    "tone/diction 等纯分析判断上限 0.75；≤0.5 为证据不足或需外部知识的判断。"
    "对任何元素输出 1.0 前自问：原文是否逐字可引？若含一点改写即降档。禁止对推断类元素输出 1.0。"
    "长文分块纪律：user 消息的正文是全文的一个连续块（注明块序号与字符区间），"
    "只分析本块内容，spans 用块内偏移（0 起算，服务端统一映射为全文坐标），"
    "quote 仍须逐字来自本块；本块没有依据的元素直接省略。"
    "多语言细粒度纪律（v4）：文章可能是 en/zh/fr/es/de/ar 等任意语言，"
    "按文章实际语言理解与输出（content 用文章主要语言）。"
    "一句话/一段话常同时包含多种元素（如事实中嵌主体与意图）——交叠标注："
    "同一文本区间必须分别给出各元素的独立 spans（短元素嵌在长元素内），"
    "严禁用一个元素的大段覆盖吞掉其它元素；每个元素 spans 尽量分散多点，"
    "避免集中单点；无法定位的元素宁可省略 spans 交给系统回填，也不要编造偏移。"
    "span 长度纪律（v5）：每个 span 不超过 120 字符——宁短勿长，只锚定该元素最核心的"
    "词句；严禁把整段或整句标为单一元素；内容较长时拆成多个短 spans 分布在相关位置。"
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


def _chunk_text(text: str, size: int = _CHUNK_SIZE) -> list[tuple[int, str]]:
    """全文 → [(offset, chunk)]：按句界回退切分，块拼接恰为原文。

    - len(text) ≤ size（含空文本）→ 单块 [(0, text)]；
    - 优先在窗口内最后一个句界字符之后断开（句界字符归前块）；
    - 数字夹住的小数点（如 3.14 的 .）不作句界，防数值被切断；
    - 窗口内无句界 → 硬切（无标点超长段仍保证覆盖全文）。
    不变量："".join(c for _, c in out) == text，offset 单调递增无缝衔接。
    """
    if len(text) <= size:
        return [(0, text)]
    out: list[tuple[int, str]] = []
    cursor, n = 0, len(text)
    while cursor < n:
        end = min(cursor + size, n)
        if end == n:
            out.append((cursor, text[cursor:]))
            break
        cut = 0
        for i in range(end - 1, cursor, -1):
            ch = text[i]
            if ch not in _SENTENCE_BOUNDARIES:
                continue
            if ch == "." and text[i - 1].isdigit() and text[i + 1].isdigit():
                continue  # 小数点不作句界
            cut = i + 1
            break
        if not cut:
            cut = end  # 无句界 → 硬切
        out.append((cursor, text[cursor:cut]))
        cursor = cut
    return out


def _map_element_spans(el: DissectionElement, offset: int) -> DissectionElement:
    """块内 span 坐标 → 全文坐标：start/end 平移块 offset（quote 原样保留）。

    平移保持 end>start 不变，无需重校验；无 spans 或 offset=0 时原样返回。
    """
    if not el.spans or offset == 0:
        return el
    return el.model_copy(
        update={
            "spans": [
                s.model_copy(update={"start": s.start + offset, "end": s.end + offset})
                for s in el.spans
            ]
        }
    )


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
    """组装拆解图；router/store/兜底元素工厂/时钟均闭包注入。

    llm_timeout 为每块超时（长文逐块调用，单块超时只丢该块不整体失败）。
    """

    async def hints_node(state: DissectionState) -> dict[str, Any]:
        if not state.get("hints"):
            return {"hints": "（无词典标注可用）"}
        return {}

    async def llm_node(state: DissectionState) -> dict[str, Any]:
        if router is None:
            return {"errors": ["llm_unavailable: router 未配置"], "llm_failed": "router 未配置"}
        chunks = _chunk_text(state.get("text", ""))
        total = len(chunks)
        # analysis_locale 显式指定时约束输出语言；空则维持默认（不追加）
        lang_line = output_language_line(state.get("analysis_locale", ""))
        merged: list[DissectionElement] = []
        seen: set[tuple[str, str]] = set()  # (element, content) 跨块精确重复去重
        model_hint = ""
        usage_agg: dict[str, Any] = {}
        chunk_errors: list[str] = []
        sem = asyncio.Semaphore(3)  # 并发 3：防限流，12 块 ~4 批

        async def _one(idx: int, offset: int, chunk: str) -> dict[str, Any]:
            user = (
                f"标题：{state.get('title', '')}\n文章语言：{state.get('language') or 'unknown'}\n"
                f"本文档发布方（publisher，来自信源注册目录，不可质疑）："
                f"{state.get('publisher') or '（未注册，按 unknown 处理，禁止臆测）'}\n"
                f"词典标注锚：{state.get('hints', '')}\n"
                f"本块为全文第 {idx}/{total} 块，字符区间 [{offset}, {offset + len(chunk)})；"
                f"spans 用块内偏移（0 起算），服务端负责映射为全文坐标。\n正文：\n{chunk}"
            )
            if lang_line:
                user = f"{user}\n{lang_line}"
            user = f"{user}\n（Prompt 版本：{DISSECT_PROMPT_VERSION}）"
            try:
                # llm_timeout 为每块超时：单块失败/超时不拖垮其余块
                async with sem, asyncio.timeout(llm_timeout):
                    parsed, ref, usage = await router.invoke(
                        Tier.EXECUTE, _DISSECT_SYSTEM, user, DissectionOutputP
                    )
            except Exception as exc:  # noqa: BLE001 —— 单块失败记 errors 继续下一块
                msg = str(exc) or type(exc).__name__
                return {
                    "idx": idx,
                    "offset": offset,
                    "error": f"llm_failed: 第 {idx}/{total} 块（offset={offset}）失败: {msg}",
                }
            return {"idx": idx, "offset": offset, "parsed": parsed, "ref": ref, "usage": usage}

        results = await asyncio.gather(
            *(_one(idx, offset, chunk) for idx, (offset, chunk) in enumerate(chunks, start=1))
        )
        for res in sorted(results, key=lambda r: r["idx"]):  # 按块序聚合，保持确定性
            if "error" in res:
                chunk_errors.append(res["error"])
                continue
            ref, usage, offset = res["ref"], res["usage"], res["offset"]
            if not model_hint:
                model_hint = f"{ref.provider}/{ref.model_id}"
            if usage_agg:
                usage_agg["prompt_tokens"] += usage.prompt_tokens if usage else 0
                usage_agg["completion_tokens"] += usage.completion_tokens if usage else 0
                usage_agg["total_tokens"] += usage.total_tokens if usage else 0
                usage_agg["latency_ms"] += usage.latency_ms if usage else 0
            else:
                usage_agg = {
                    "provider": ref.provider,
                    "model": ref.model_id,
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                    "latency_ms": usage.latency_ms if usage else 0,
                }
            for el in res["parsed"].elements:
                key = (el.element, el.content)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(_map_element_spans(el, offset))
        if not merged:
            # 全部块失败（DissectionOutputP 保证成功块必有产出）→ 维持整体失败
            # 语义，由 persist 诚实降级 offline，不冒充 LLM 产物
            last = chunk_errors[-1] if chunk_errors else "llm_empty_output: 全部块无产出"
            return {
                "errors": chunk_errors or [last],
                "llm_failed": f"{total}/{total} 块失败: {last}",
            }
        return {
            "elements": merged,
            "_model_hint": model_hint,
            "usage": usage_agg,
            "errors": chunk_errors,  # 部分块失败：engine=llm（部分成功是真实状态），缺块留痕
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
        text = state.get("text") or ""
        unanchored = 0
        for i, el in enumerate(elements):
            if el.spans:
                continue
            needle = (el.content or "").strip()
            if len(needle) < 6:
                continue
            found = _locate_span(text, needle)
            if found:
                elements[i] = el.model_copy(
                    update={"spans": [DissectionSpan(start=found[0], end=found[1])]}
                )
            else:
                unanchored += 1
        if unanchored:
            state.setdefault("errors", []).append(
                f"unanchored_elements: {unanchored} 个元素三级查找均未定位到原文"
            )
        if engine == "llm":
            elements, narrowed = _narrow_long_spans(text, elements)
            if narrowed:
                state.setdefault("errors", []).append(
                    f"narrowed_long_spans: {narrowed} 个超长 span 已按 content 收窄"
                )

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


def _norm_index(s: str) -> tuple[str, list[int]]:
    """归一化文本 + 每个归一化字符到原文字符位置的映射表。"""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(s):
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            out.append(ch.lower())
            idx.append(i)
    return "".join(out), idx


def _locate_span(text: str, needle: str) -> tuple[int, int] | None:
    """三级递进定位：①原文 find ②归一化 find+位置映射 ③词首字符序列 find。

    任一命中返回原文 (start, end)；全部失败返回 None（调用方记 errors 留痕）。
    """
    needle = needle.strip()
    if not needle:
        return None
    # ① 原文直接 find
    pos = text.find(needle)
    if pos >= 0:
        return pos, pos + len(needle)
    # ② 归一化 find（大小写/空白/标点全归一，映射回原文区间）
    n_text, n_idx = _norm_index(text)
    n_needle, _ = _norm_index(needle)
    if len(n_needle) >= 4:
        p2 = n_text.find(n_needle)
        if p2 >= 0:
            lo, hi = n_idx[p2], n_idx[p2 + len(n_needle) - 1]
            return lo, hi + 1
    # ③ 词首字符序列 find（容忍 LLM 摘写改写：按词首字母序列定位）
    import re as _re

    words = [w.lower() for w in _re.findall(r"[\w\u4e00-\u9fff]{2,}", needle) if w]
    if len(words) >= 2:
        # 顺序词锚定：needle 各词在原文中依序出现（允许词间跳隔），span=首词头到末词尾
        cursor = 0
        lo = hi = -1
        ok = True
        for w in words:
            pos = text.lower().find(w, cursor)
            if pos < 0:
                ok = False
                break
            if lo < 0:
                lo = pos
            hi = pos + len(w)
            cursor = hi
        if ok:
            return lo, hi
    return None


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


def _narrow_long_spans(
    text: str, elements: list[DissectionElement], *, limit: int = 150
) -> tuple[list[DissectionElement], int]:
    """v5：span 过长（>limit）时用 content 在原 span 范围内重新定位收窄。

    命中→替换为 content 的窄区间（全文坐标）；未命中保持原 span。
    返回（新元素表, 收窄数）。
    """
    out: list[DissectionElement] = []
    narrowed = 0
    for el in elements:
        spans = el.spans or []
        if not spans:
            out.append(el)
            continue
        new_spans = []
        for sp in spans:
            if sp.end - sp.start <= limit or not el.content or len(el.content) < 6:
                new_spans.append(sp)
                continue
            seg = text[sp.start : sp.end]
            hit = _locate_span(seg, el.content[:100])
            if hit is not None:
                a, b = hit
                new_spans.append(DissectionSpan(start=sp.start + a, end=sp.start + b))
                narrowed += 1
            else:
                new_spans.append(sp)
        out.append(el.model_copy(update={"spans": new_spans}))
    return out, narrowed
