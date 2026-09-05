"""B1 DissectionGraph 测试：LLM 主路径 / offline 降级 / 落库与闭包注入。"""

import asyncio
import datetime as dt
from typing import Any

from oh_agents.dissection_agent import DissectionOutputP, build_dissection_graph
from oh_contracts.dissection import DissectionElement
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
