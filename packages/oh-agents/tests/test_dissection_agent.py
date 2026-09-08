"""B1 DissectionGraph 测试：LLM 主路径 / offline 降级 / 落库与闭包注入。

长文分块（v3）：分块切分不变量 / 跨块 spans 全文坐标映射 / 部分块失败
engine=llm 留痕 / 全部块失败 offline 降级。
"""

import asyncio
import datetime as dt
import re
from typing import Any

from oh_agents.dissection_agent import (
    DissectionOutputP,
    _chunk_text,
    build_dissection_graph,
)
from oh_contracts.dissection import DissectionElement, DissectionSpan
from oh_llm.config import ModelRef

_NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)


class FakeRouter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.last_system = ""
        self.last_user = ""

    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        self.calls += 1
        self.last_system, self.last_user = system, user
        if self.fail:
            raise RuntimeError("all candidates failed")
        out = DissectionOutputP(
            elements=[
                DissectionElement(element="actor", content="美联储"),
                DissectionElement(element="tone", content="谨慎"),
            ]
        )
        return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None


class FakeStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def upsert_dissection(
        self, item_key: str, payload: dict, engine: str, dissected_at: Any, *, language: str = ""
    ) -> None:
        self.rows.append(payload)


def _base_state() -> dict:
    return {
        "item_key": "src:https://x.com/1:2026-08-30T00:00:00+00:00",
        "title": "美联储暗示九月暂停加息",
        "text": "美联储官员周三表示，通胀放缓令九月的利率决定保有空间。",
        "language": "zh",
        "hints": '{"actions": ["放缓"], "emotions": {"uncertainty": 0.3}}',
    }


def test_llm_path_persists_with_model_hint() -> None:
    router = FakeRouter()
    store = FakeStore()
    g = build_dissection_graph(router=router, store=store, now_fn=lambda: _NOW)
    out = asyncio.run(g.ainvoke(dict(_base_state())))
    d = out["dissection"]
    assert d.engine == "llm"
    assert d.model_hint == "zhipu/glm-5.3-flash"
    assert d.dissected_at == _NOW
    assert len(d.elements) == 2
    assert len(store.rows) == 1


def test_llm_failure_falls_back_offline() -> None:
    store = FakeStore()
    g = build_dissection_graph(
        router=FakeRouter(fail=True),
        store=store,
        fallback_fn=lambda s: [
            DissectionElement(element="action", content="词典命中：放缓"),
        ],
        now_fn=lambda: _NOW,
    )
    out = asyncio.run(g.ainvoke(dict(_base_state())))
    d = out["dissection"]
    assert d.engine == "offline"
    assert d.model_hint == ""
    assert d.elements[0].element == "action"
    assert any("llm_failed" in e for e in out["errors"])


def test_no_router_no_fallback_still_persists_empty() -> None:
    store = FakeStore()
    g = build_dissection_graph(store=store, now_fn=lambda: _NOW)
    out = asyncio.run(g.ainvoke(dict(_base_state())))
    assert out["dissection"].engine == "offline"
    assert out["dissection"].elements == []
    assert len(store.rows) == 1


def test_llm_empty_output_degrades_offline() -> None:
    """LLM 返回空产出（虚假成功）→ 诚实降级 offline。"""

    class EmptyRouter:
        async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
            return DissectionOutputP(elements=[]), ModelRef(provider="z", model_id="m"), None

    store = FakeStore()
    g = build_dissection_graph(
        router=EmptyRouter(),
        store=store,
        fallback_fn=lambda s: [DissectionElement(element="tone", content="词典命中")],
        now_fn=lambda: _NOW,
    )
    out = asyncio.run(g.ainvoke(dict(_base_state())))
    d = out["dissection"]
    assert d.engine == "offline"
    assert d.model_hint == ""
    assert len(d.elements) == 1
    assert any("llm_empty_output" in e for e in out["errors"])


def test_prompt_carries_publisher_and_calibration_rules() -> None:
    """P0-4 来源幻觉防线：publisher 元数据注入 + 信源纪律 + confidence 校准规则。"""
    from oh_agents.dissection_agent import _DISSECT_SYSTEM

    router = FakeRouter()
    g = build_dissection_graph(router=router, store=FakeStore(), now_fn=lambda: _NOW)
    state = dict(_base_state())
    state["publisher"] = "wsj"
    asyncio.run(g.ainvoke(state))
    # user prompt 显式注入元数据发布方（不可质疑）
    assert "wsj" in router.last_user
    assert "publisher" in router.last_user
    assert "不可质疑" in router.last_user
    # system：source_reliability 只分析文中引用来源，发布方来自元数据
    assert "publisher" in _DISSECT_SYSTEM
    assert "cited source" in _DISSECT_SYSTEM
    assert "primary evidence" in _DISSECT_SYSTEM
    assert "anonymous source" in _DISSECT_SYSTEM
    # system：confidence 校准（推断类禁止 1.0）
    assert "confidence" in _DISSECT_SYSTEM
    assert "禁止对推断类元素输出 1.0" in _DISSECT_SYSTEM
    assert router.last_system == _DISSECT_SYSTEM


def test_analysis_locale_appends_output_language_line() -> None:
    """P1-8 analysis_locale：显式指定时 user prompt 末尾追加输出语言约束行。"""
    router = FakeRouter()
    g = build_dissection_graph(router=router, store=FakeStore(), now_fn=lambda: _NOW)
    state = dict(_base_state())
    state["analysis_locale"] = "zh"
    asyncio.run(g.ainvoke(state))
    assert "分析输出语言" in router.last_user
    assert "使用 中文 书写" in router.last_user
    # 元素键名保持英文枚举的约束必须同时在
    assert "元素键名(element)保持英文枚举不变" in router.last_user


def test_no_analysis_locale_no_output_language_line() -> None:
    """analysis_locale 缺省（空）→ 不追加输出语言行（后端维持默认行为）。"""
    router = FakeRouter()
    g = build_dissection_graph(router=router, store=FakeStore(), now_fn=lambda: _NOW)
    asyncio.run(g.ainvoke(dict(_base_state())))
    assert "分析输出语言" not in router.last_user


# ---- 长文分块拆解（dissect-v3）----

_SENT = "美联储官员周三表示，通胀放缓令九月的利率决定保有空间。"


def _long_text(n: int = 300) -> str:
    """构造多块长文：逐句编号（内容不周期重复，块首片段天然互异）。"""
    return "".join(f"第{i}条：通胀放缓令九月的利率决定保有空间。" for i in range(n))


class ChunkAwareRouter:
    """按块产出元素的桩：解析 user prompt 的块区间标注，span 用块内偏移。

    fail_on 按调用序号抛错（模拟部分块失败）；content_fmt 控制各块产出
    content（含 {offset} 则跨块互异，不含则精确重复触发去重）。
    """

    def __init__(self, *, fail_on: set[int] | None = None, content_fmt: str = "块{offset}事实"):
        self.fail_on = fail_on or set()
        self.content_fmt = content_fmt
        self.calls = 0
        self.offsets: list[int] = []
        self.chunk_lens: list[int] = []

    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("all candidates failed")
        m = re.search(r"字符区间 \[(\d+), (\d+)\)", user)
        assert m is not None, f"user prompt 缺块区间标注：{user[:120]}"
        offset = int(m.group(1))
        body = user.split("正文：\n", 1)[1].split("\n（Prompt 版本：", 1)[0]
        self.offsets.append(offset)
        self.chunk_lens.append(len(body))
        out = DissectionOutputP(
            elements=[
                DissectionElement(
                    element="hard_fact",
                    content=self.content_fmt.format(offset=offset),
                    spans=[DissectionSpan(start=0, end=5, quote=body[:5])],
                )
            ]
        )
        return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None


def _run_dissect(router: Any, **kwargs: Any) -> dict:
    g = build_dissection_graph(router=router, store=FakeStore(), now_fn=lambda: _NOW, **kwargs)
    state = dict(_base_state())
    state["text"] = _long_text()
    return asyncio.run(g.ainvoke(state))


def test_chunk_text_invariants() -> None:
    """分块函数不变量：无缝覆盖全文 / 句界回退 / 硬切兜底 / 小数点保护。"""
    from oh_agents.dissection_agent import _CHUNK_SIZE

    assert _chunk_text("") == [(0, "")]
    assert _chunk_text("短文。") == [(0, "短文。")]
    chunks = _chunk_text(_SENT * 150)
    assert len(chunks) > 1
    assert "".join(c for _, c in chunks) == _SENT * 150
    assert all(len(c) <= _CHUNK_SIZE for _, c in chunks)
    assert all(c[-1] in "。！？!?\n" for _, c in chunks[:-1])  # 块界落在句界字符之后
    hard = "a" * 5000  # 无句界超长段 → 硬切仍完整覆盖
    hard_chunks = _chunk_text(hard)
    assert "".join(c for _, c in hard_chunks) == hard
    assert all(len(c) <= _CHUNK_SIZE for _, c in hard_chunks)
    dec = "结论。" * 599 + "3.14" + "。收尾正文继续。" * 50  # 小数点恰在自然切点
    dec_chunks = _chunk_text(dec)
    assert "".join(c for _, c in dec_chunks) == dec
    assert any("3.14" in c for _, c in dec_chunks)  # 数值不被切断


def test_long_text_chunked_spans_map_to_fulltext_coords() -> None:
    """长文分块：逐块调用 router，块内偏移平移为全文坐标且逐字对回原文。"""
    text = _long_text()
    expected = _chunk_text(text)
    assert len(expected) >= 3  # 测试前提：确实切成多块
    router = ChunkAwareRouter()
    out = _run_dissect(router)
    d = out["dissection"]
    assert router.calls == len(expected)  # 逐块调用，块数与分块函数一致
    assert router.offsets[0] == 0
    assert sum(router.chunk_lens) == len(text)  # 无缝覆盖全文
    for k in range(1, len(expected)):
        assert router.offsets[k] == router.offsets[k - 1] + router.chunk_lens[k - 1]
    assert d.engine == "llm"
    assert d.model_hint == "zhipu/glm-5.3-flash"
    assert len(d.elements) == router.calls  # 各块产出全保留（content 含 offset 不去重）
    second_start = router.offsets[1]  # 第二块元素 spans 已映射全文坐标
    spans = [s for el in d.elements for s in el.spans]
    assert any(s.start == second_start for s in spans)
    assert second_start >= router.chunk_lens[0]
    for s in spans:  # 全文坐标正确性：每个 span 切片与自报 quote 逐字一致
        assert text[s.start : s.end] == s.quote


def test_partial_chunk_failure_keeps_llm_engine_and_records_errors() -> None:
    """部分块失败：engine=llm（部分成功是真实状态），errors 记块序号，其余块保留。"""
    text = _long_text()
    n_chunks = len(_chunk_text(text))
    assert n_chunks >= 3
    router = ChunkAwareRouter(fail_on={2})  # 第 2 块抛错
    out = _run_dissect(router)
    d = out["dissection"]
    failed_offset = _chunk_text(text)[1][0]
    assert router.calls == n_chunks  # 失败不中断，继续调完其余块
    assert d.engine == "llm"
    assert d.model_hint == "zhipu/glm-5.3-flash"
    assert len(d.elements) == n_chunks - 1  # 仅失败块缺产出
    assert len({el.content for el in d.elements}) == len(d.elements)
    assert all(el.content != f"块{failed_offset}事实" for el in d.elements)
    assert any("llm_failed" in e and "第 2/" in e for e in out["errors"])
    for el in d.elements:  # 成功块 spans 仍为正确全文坐标
        for s in el.spans:
            assert text[s.start : s.end] == s.quote


def test_all_chunks_failure_degrades_offline() -> None:
    """全部块失败 → 整体失败语义，persist 诚实降级 offline（不冒充 LLM）。"""
    n_chunks = len(_chunk_text(_long_text()))
    router = ChunkAwareRouter(fail_on=set(range(1, 9)))
    out = _run_dissect(
        router,
        fallback_fn=lambda s: [DissectionElement(element="tone", content="词典命中")],
    )
    d = out["dissection"]
    assert router.calls == n_chunks
    assert d.engine == "offline"
    assert d.model_hint == ""
    assert [el.element for el in d.elements] == ["tone"]
    assert sum("llm_failed: 第" in e for e in out["errors"]) == n_chunks


def test_cross_chunk_exact_duplicates_deduped() -> None:
    """同 element+content 跨块精确重复只保留一条（首条产出，全文坐标）。"""
    text = _long_text(200)
    assert len(_chunk_text(text)) >= 2
    router = ChunkAwareRouter(content_fmt="美联储维持谨慎立场")  # 各块产出同名 → 精确重复
    out = _run_dissect(router)
    d = out["dissection"]
    assert d.engine == "llm"
    assert len(d.elements) == 1
    assert d.elements[0].spans[0].start == 0  # 保留首块（offset=0）的 span


def test_long_span_narrowed_by_content() -> None:
    """v5：超长 span 用 content 收窄到窄区间。"""
    from oh_agents.dissection_agent import _narrow_long_spans

    sent = "美联储主席表示，通胀正在放缓，九月可能暂停加息，市场解读为鸽派信号。"
    text = sent * 6  # >150 字符，span 覆盖全文触发收窄
    long_el = DissectionElement(
        element="actor",
        content="美联储主席表示",
        spans=[DissectionSpan(start=0, end=len(text))],
    )
    out, narrowed = _narrow_long_spans(text, [long_el])
    assert narrowed == 1
    sp = out[0].spans[0]
    assert text[sp.start : sp.end] == "美联储主席表示"


def test_short_span_untouched() -> None:
    from oh_agents.dissection_agent import _narrow_long_spans

    text = "短文内容。"
    el = DissectionElement(element="tone", content="短文", spans=[DissectionSpan(start=0, end=4)])
    out, narrowed = _narrow_long_spans(text, [el])
    assert narrowed == 0
    assert out[0].spans[0].end - out[0].spans[0].start == 4
