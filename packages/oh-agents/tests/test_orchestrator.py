"""Orchestrator 测试：ContextPacket 组装 + Intent 消息 + 离线 Artifact。"""

from __future__ import annotations

import pytest
from conftest import TIER_MAP, make_now, seed_event
from oh_agents.orchestrator import (
    build_context_packet,
    intent_message,
    run_intent,
)
from oh_contracts.intents import Intent, IntentKind, TargetKind
from oh_pipeline.detect import detect_signals
from oh_pipeline.run import run_pipeline


@pytest.fixture()
def env(tmp_path):
    from oh_pipeline.entities import EntityRegistry
    from oh_storage.bronze_parquet import ParquetBronzeWriter
    from oh_storage.connection import connect
    from oh_storage.sqlite_store import SqliteStore

    bronze = ParquetBronzeWriter(tmp_path / "bronze")
    store = SqliteStore(connect(tmp_path / "silver.sqlite"))
    now = make_now()
    ev = seed_event(bronze, store, "E01", now)
    run_pipeline(
        bronze, store, store, [ev], TIER_MAP, as_of=now, lookback_days=1, min_per_source=10
    )
    return {
        "bronze": bronze,
        "store": store,
        "gold": store,
        "registry": EntityRegistry(),
        "now": now,
    }


def _first_signal_id(env) -> str:
    sigs = detect_signals(
        env["bronze"].iter_records(),
        env["store"],
        env["registry"],
        TIER_MAP,
        env["now"],
        min_per_source=1,
        top_n=5,
    )
    assert sigs, "seeded event should produce signals"
    return sigs[0].signal_id


def test_packet_from_signal(env) -> None:
    sid = _first_signal_id(env)
    intent = Intent(intent=IntentKind.EXPLAIN_SIGNAL, target_kind=TargetKind.SIGNAL, target_id=sid)
    p = build_context_packet(
        intent,
        bronze=env["bronze"],
        store=env["store"],
        gold=env["gold"],
        registry=env["registry"],
        tier_map=TIER_MAP,
        now=env["now"],
        min_per_source=1,
    )
    assert p.signal is not None and p.signal["signal_id"] == sid
    assert p.entity_id == "fed"
    assert p.event is not None and p.event["event_id"] == "E01"
    assert p.ndi_points and p.ndi_points[-1]["status"] == "ok"
    assert p.stances and {"gov", "wscn"} <= {s["source_id"] for s in p.stances}
    assert "L1" in {s["tier"] for s in p.stances}
    assert not p.notes


def test_packet_from_event_and_missing_signal_note(env) -> None:
    intent = Intent(intent=IntentKind.SHOW_EVIDENCE, target_kind=TargetKind.EVENT, target_id="E01")
    p = build_context_packet(
        intent,
        bronze=env["bronze"],
        store=env["store"],
        gold=env["gold"],
        registry=env["registry"],
        tier_map=TIER_MAP,
        now=env["now"],
    )
    assert p.event and p.stances and not p.notes

    miss = Intent(
        intent=IntentKind.EXPLAIN_SIGNAL, target_kind=TargetKind.SIGNAL, target_id="sig-x-y-z"
    )
    p2 = build_context_packet(
        miss,
        bronze=env["bronze"],
        store=env["store"],
        gold=env["gold"],
        registry=env["registry"],
        tier_map=TIER_MAP,
        now=env["now"],
        min_per_source=1,
    )
    assert p2.signal is None
    assert any("not found" in n for n in p2.notes)


def test_intent_message_contains_hint_and_packet(env) -> None:
    intent = Intent(
        intent=IntentKind.COMPARE_NARRATIVES, target_kind=TargetKind.EVENT, target_id="E01"
    )
    p = build_context_packet(
        intent,
        bronze=env["bronze"],
        store=env["store"],
        gold=env["gold"],
        registry=env["registry"],
        tier_map=TIER_MAP,
        now=env["now"],
    )
    msg = intent_message(p)
    assert "Intent: compare_narratives" in msg
    assert "ContextPacket" in msg


def test_offline_artifact_and_run_intent(env) -> None:
    intent = Intent(
        intent=IntentKind.START_INVESTIGATION, target_kind=TargetKind.EVENT, target_id="E01"
    )
    p = build_context_packet(
        intent,
        bronze=env["bronze"],
        store=env["store"],
        gold=env["gold"],
        registry=env["registry"],
        tier_map=TIER_MAP,
        now=env["now"],
    )
    out = run_intent(
        p,
        bronze=env["bronze"],
        store=env["store"],
        gold=env["gold"],
        registry=env["registry"],
        router=None,
        now=env["now"],
    )
    assert out["offline"] is True and out["reply"] is None
    art = out["artifact"]
    assert art["engine"] == "offline"
    assert art["observation"] and art["interpretation"]
    assert art["intent"] == "start_investigation"
    # 极化种子含官方 gov 行 → alternative 不触发"无官方对照"分支
    assert art["alternative"] is None
