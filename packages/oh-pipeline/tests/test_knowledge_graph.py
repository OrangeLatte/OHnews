"""KG v2 边构建器（M3-S3）：co_occurs / parent_of / SRO 极性边。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_contracts.schemas import EventRecord, StanceRow
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
from oh_pipeline.knowledge_graph import build_entity_edges, edge_key

_T1 = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
_T2 = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
_REG = EntityRegistry(DEFAULT_ENTITIES)


def _ev(eid: str, ents: list[str], ts: datetime, cluster: str) -> EventRecord:
    return EventRecord(event_id=eid, title=eid, entities=ents, as_of=ts, cluster_key=cluster)


def _stance_row(item_key: str, entity_id: str, stance: str) -> StanceRow:
    return StanceRow(
        event_id="ev-fed-20260829",
        source_id="govcn",
        entity_id=entity_id,
        frame="loss",
        stance=stance,
        confidence=0.8,
        engine="rule",
        item_key=item_key,
        ts=_T1,
    )


def test_co_occurs_within_cluster() -> None:
    evs = [
        _ev("ev-a", ["fed", "fomc"], _T1, "evt-x"),
        _ev("ev-b", ["fomc", "ecb"], _T2, "evt-x"),
    ]
    edges = build_entity_edges(events=evs, annotations=[], registry=_REG)
    cos = [e for e in edges if e.kind == "co_occurs"]
    # 同簇实体全对全（簇级共现，src/dst 字母序规范化）：ecb<fed<fomc
    pairs = {(e.src, e.dst) for e in cos}
    assert pairs == {("ecb", "fed"), ("ecb", "fomc"), ("fed", "fomc")}
    assert all(e.weight == 1.0 for e in cos)
    assert all(e.evidence_item_keys == ["evt-x"] for e in cos)


def test_co_occurs_weight_accumulates_across_clusters() -> None:
    evs = [
        _ev("ev-a", ["fed", "fomc"], _T1, "evt-x"),
        _ev("ev-b", ["fomc", "fed"], _T2, "evt-y"),
    ]
    edges = build_entity_edges(events=evs, annotations=[], registry=_REG)
    cos = [e for e in edges if e.kind == "co_occurs" and {e.src, e.dst} == {"fed", "fomc"}]
    assert len(cos) == 1
    assert cos[0].weight == 2.0
    assert cos[0].first_seen == _T1 and cos[0].last_seen == _T2
    assert cos[0].evidence_item_keys == ["evt-x", "evt-y"]


def test_parent_of_edges_from_registry() -> None:
    edges = build_entity_edges(events=[], annotations=[], registry=_REG)
    pops = [(e.src, e.dst) for e in edges if e.kind == "parent_of"]
    assert ("fed", "fomc") in pops
    # registry 无 events/annotations 时锚为 epoch
    e = next(e for e in edges if (e.src, e.dst, e.kind) == ("fed", "fomc", "parent_of"))
    assert e.weight == 1.0


def test_sro_polarity_from_stance_rows() -> None:
    ann = {
        "item_key": "k1",
        "roles": [{"subject": "Fed", "target": "FOMC", "action": "tighten"}],
        "annotated_at": _T1.isoformat(),
    }
    rows = [_stance_row("k1", "fomc", "critical")]
    edges = build_entity_edges(events=[], annotations=[ann], registry=_REG, rows=rows)
    sro = [e for e in edges if e.kind != "parent_of"]
    assert len(sro) == 1
    e = sro[0]
    assert (e.src, e.dst, e.kind) == ("fed", "fomc", "opposes")
    assert e.evidence_item_keys == ["k1"]
    # 别名已 canonical 化（非原文 "Fed"）
    assert e.src == "fed" and e.dst == "fomc"


def test_sro_supportive_and_neutral_fallback() -> None:
    anns = [
        {
            "item_key": "k1",
            "roles": [{"subject": "Fed", "target": "FOMC"}],
            "annotated_at": _T1.isoformat(),
        },
        {
            "item_key": "k2",
            "roles": [{"subject": "Fed", "target": "FOMC"}],
            "annotated_at": _T2.isoformat(),
        },
    ]
    rows = [_stance_row("k1", "fomc", "supportive")]
    edges = build_entity_edges(events=[], annotations=anns, registry=_REG, rows=rows)
    # k1 supportive → supports；k2 无 stance 行 → acts_on 兜底（不同 kind 不同键）
    kinds = {(e.src, e.dst, e.kind, e.weight) for e in edges}
    assert ("fed", "fomc", "supports", 1.0) in kinds
    assert ("fed", "fomc", "acts_on", 1.0) in kinds


def test_sro_skips_unregistered_and_self_loops() -> None:
    anns = [
        {
            "item_key": "k1",
            "roles": [
                {"subject": "Fed", "target": "Nike"},  # 未注册别名
                {"subject": "Fed", "target": "Federal Reserve"},  # 同实体自环
                {"subject": "", "target": "FOMC"},  # 空主体
            ],
            "annotated_at": _T1.isoformat(),
        }
    ]
    edges = build_entity_edges(events=[], annotations=anns, registry=_REG)
    assert [e for e in edges if e.kind != "parent_of"] == []


def test_edge_key_stable_and_kind_sensitive() -> None:
    assert edge_key("fed", "fomc", "co_occurs") == edge_key("fed", "fomc", "co_occurs")
    assert edge_key("fed", "fomc", "co_occurs") != edge_key("fed", "fomc", "opposes")
    assert edge_key("fed", "fomc", "co_occurs") != edge_key("fomc", "fed", "co_occurs")
