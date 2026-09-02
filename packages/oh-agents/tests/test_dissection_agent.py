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

    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        self.calls += 1
        if self.fail:
            raise RuntimeError("all candidates failed")
        out = DissectionOutputP(
            elements=[
                DissectionElement(element="actor", content="美联储"),
                DissectionElement(element="tone", content="谨慎"),
            ]
        )
        return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash")


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
            return DissectionOutputP(elements=[]), ModelRef(provider="z", model_id="m")

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
