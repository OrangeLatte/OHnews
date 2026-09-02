"""B2 ReportGraph 测试：LLM 主路径 / 空产出与失败降级 / 落库幂等。"""

import asyncio
import datetime as dt
from typing import Any

from oh_agents.report_agent import (
    ReportOutputP,
    build_report_graph,
    report_id_for,
)
from oh_contracts.reports import ReportSection
from oh_llm.config import ModelRef

_NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)


class FakeRouter:
    def __init__(self, *, fail: bool = False, empty: bool = False) -> None:
        self.fail = fail
        self.empty = empty

    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        if self.fail:
            raise RuntimeError("all candidates failed")
        sections = (
            []
            if self.empty
            else [ReportSection(title="核心判断：原文核验", body="原文显示通胀放缓。")]
        )
        return ReportOutputP(sections=sections), ModelRef(provider="zhipu", model_id="glm-5.3")


class FakeStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def upsert_report(
        self, payload: dict, *, engine: str, model_hint: str, created_at: str
    ) -> None:
        self.rows[payload["report_id"]] = payload


def _state() -> dict:
    return {
        "item_key": "src:u:2026-08-30T00:00:00+00:00",
        "kind": "truth",
        "title": "美联储暗示九月暂停加息",
        "text": "美联储官员表示通胀放缓。",
        "dissection_json": '{"elements": [{"element": "actor", "content": "美联储"}]}',
    }


def test_llm_path_persists_with_model_hint() -> None:
    store = FakeStore()
    g = build_report_graph(router=FakeRouter(), store=store, now_fn=lambda: _NOW)
    out = asyncio.run(g.ainvoke(dict(_state())))
    rep = out["report"]
    assert rep.engine == "llm"
    assert rep.model_hint == "zhipu/glm-5.3"
    assert rep.report_id == report_id_for(_state()["item_key"], "truth")
    assert rep.title == "真实性与可信度核查"
    assert len(rep.sections) == 1
    assert len(store.rows) == 1


def test_llm_failure_degrades_offline_with_reason() -> None:
    store = FakeStore()
    g = build_report_graph(router=FakeRouter(fail=True), store=store, now_fn=lambda: _NOW)
    out = asyncio.run(g.ainvoke(dict(_state())))
    rep = out["report"]
    assert rep.engine == "offline"
    assert rep.model_hint == ""
    assert "模型未在预期时间内返回有效报告" in rep.sections[-1].body
    assert rep.sections[0].title.startswith("拆解要素复述")
    assert "美联储" in rep.sections[0].body
    assert any("llm_failed" in e for e in out["errors"])


def test_llm_empty_output_degrades_offline() -> None:
    store = FakeStore()
    g = build_report_graph(router=FakeRouter(empty=True), store=store, now_fn=lambda: _NOW)
    out = asyncio.run(g.ainvoke(dict(_state())))
    rep = out["report"]
    assert rep.engine == "offline"
    assert any("llm_empty_output" in e for e in out["errors"])


def test_report_id_stable_across_calls() -> None:
    assert report_id_for("k", "truth") == report_id_for("k", "truth")
    assert report_id_for("k", "truth") != report_id_for("k", "intent")
