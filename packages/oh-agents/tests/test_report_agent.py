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
    assert rep.title == "真实性与可信度核查 · 研究报告"
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


class FakeTransRouter:
    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        from oh_agents.translation_agent import TranslationOutputP

        if "rupt" in system:  # fail 哨兵
            raise RuntimeError("candidates exhausted")
        out = TranslationOutputP(
            title="Fed signals a September pause",
            body=(
                "Fed officials said on Wednesday that slowing inflation keeps"
                " room for the September decision."
            ),
            term_notes=["机构名保留原文"],
        )
        return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash")


class FakeStore2:
    """translations 收集器（真实 SqliteStore.upsert_translation 同签名）。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def upsert_translation(
        self,
        item_key: str,
        payload: dict,
        *,
        engine: str,
        source_language: str,
        target_language: str,
        translated_at: str,
    ) -> None:
        self.rows[(item_key, target_language)] = payload


def test_translation_llm_path_and_verify() -> None:
    import asyncio

    from oh_agents.translation_agent import build_translation_graph

    store = FakeStore2()
    g = build_translation_graph(
        router=FakeTransRouter(), store=store,
        now_fn=lambda: "2026-09-02T12:00:00+00:00",
    )
    out = asyncio.run(
        g.ainvoke(
            {
                "item_key": "wscn:x:2026-08-30T00:00:00+00:00",
                "title": "美联储暗示九月暂停加息",
                "text": "Fed officials said on Wednesday that inflation has slowed.",
                "source_language": "zh",
                "target_language": "en",
            }
        )
    )
    tr = out["translation"]
    assert tr["engine"] == "llm"
    assert tr["target_language"] == "en"
    assert "Fed" in tr["body_translated"]
    assert any("复核" in n or "保留" in n for n in tr["term_notes"])


def test_translation_failure_degrades_offline() -> None:
    import asyncio

    from oh_agents.translation_agent import build_translation_graph

    class BoomRouter:
        async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
            raise RuntimeError("timeout after 90s")

    store = FakeStore2()
    g = build_translation_graph(
        router=BoomRouter(), store=store,
        now_fn=lambda: "2026-09-02T12:00:00+00:00",
    )
    out = asyncio.run(
        g.ainvoke(
            {
                "item_key": "wscn:y:2026-08-30T00:00:00+00:00",
                "title": "t",
                "text": "x",
                "source_language": "zh",
                "target_language": "en",
            }
        )
    )
    tr = out["translation"]
    assert tr["engine"] == "offline"
    assert tr["body_translated"] == ""
    assert any("翻译未完成" in n for n in tr["term_notes"])
