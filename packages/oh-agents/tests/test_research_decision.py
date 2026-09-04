"""research_graph 问诊（离线）+ 决策日志。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from conftest import TIER_MAP, make_now, seed_event
from oh_agents.decision_log import DecisionLog
from oh_agents.research import run_research
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def _setup(tmp_path: Path):
    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "s.sqlite"))
    now = make_now()
    ev = seed_event(bronze, store, "E01", now)
    run_pipeline(
        bronze, store, store, [ev], TIER_MAP, as_of=now, lookback_days=1, min_per_source=10
    )
    return bronze, store, now


def test_research_template_mode(tmp_path: Path) -> None:
    """无 router：模板拼接降级仍可用（可用性优先）。"""
    bronze, store, now = _setup(tmp_path)
    result = asyncio.run(
        run_research(
            "美联储最近的叙事分歧怎么样？",
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            now=now,
        )
    )
    assert "E01" in result.answer
    assert result.confidence == 0.3
    assert result.citations == ("E01",)
    assert any(tc.startswith("search_entities") for tc in result.tool_calls)
    assert any(tc.startswith("retrieve_evidence") for tc in result.tool_calls)


def test_research_llm_mode_with_fake_router(tmp_path: Path) -> None:
    bronze, store, now = _setup(tmp_path)

    class FakeRouter:
        async def invoke(self, tier, system, user, schema):
            out = schema(
                answer="官方与市场框架分歧显著，NDI 处于高位。",
                confidence=0.75,
                citations=["E01"],
            )
            return out, object(), None

    result = asyncio.run(
        run_research(
            "美联储的叙事分歧如何？",
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            router=FakeRouter(),
            now=now,
        )
    )
    assert result.confidence == 0.75
    assert "分歧显著" in result.answer


def test_research_no_entity_hit(tmp_path: Path) -> None:
    bronze, store, now = _setup(tmp_path)
    result = asyncio.run(
        run_research(
            "今天天气如何",
            bronze=bronze,
            store=store,
            gold=store,
            registry=EntityRegistry(),
            now=now,
        )
    )
    assert "数据不足" in result.answer


def test_decision_log_roundtrip(tmp_path: Path) -> None:
    log = DecisionLog(tmp_path / "decisions.sqlite")
    d = log.log(
        decision_id="d1",
        entity_id="fed",
        event_id="E01",
        ndi_at_decision=0.8,
        decision="据此判断官方叙事将转向",
    )
    assert d.outcome is None
    log.resolve("d1", "正确：下次会议措辞确实转向")
    items = log.list_for("fed")
    assert len(items) == 1
    assert items[0].outcome is not None
    assert items[0].ndi_at_decision == 0.8
