"""KG v2 边构建器（M3-S3）：语义簇/SRL 论元/注册表 → 类型化实体边。

设计来源：REFACTOR_V2.md §3.1 EntityEdge / §4 S3。三类边（v1 确定性层）：

- co_occurs：同 cluster_key 的事件成员行跨实体共现（S2 聚类产物），
  weight=共享簇数，evidence=成员 event_id。
- acts_on / opposes / supports：annotations 的 SRL roles
  （subject→A，target→B，A≠B），kind 由该 item 中 B 实体的 stance 行极性判定
  （critical→opposes / supportive→supports / 其余→acts_on）；
  weight=独立文档数，evidence=item_key。
- parent_of：EntityRegistry 父子关系（fomc→fed 等），weight=1，
  时间锚=全局锚（图内已知最晚信息时间，不引入未来信息）。

PIT 纪律：边时间戳只取输入数据的 as_of/annotated_at（t-1 及更早）；
查询侧用 last_seen ≤ as_of 过滤。别名→canonical id 由 registry.match 解析，
未注册别名跳过（不虚构节点）。

v1 诚实边界：SRO 仅 subject→target 二元投影；object（金融宾语）不入边；
direction（涨/跌）未映射到边属性。
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from oh_contracts.semantics import EntityEdge

from oh_pipeline.entities import EntityRegistry

__all__ = ["build_entity_edges", "edge_key"]

_STANCE_KIND = {"critical": "opposes", "supportive": "supports"}


def edge_key(src: str, dst: str, kind: str) -> str:
    """内容寻址边键（同 src/dst/kind 幂等）。"""
    return hashlib.sha1(f"{src}|{dst}|{kind}".encode()).hexdigest()[:16]


def _canonical(registry: EntityRegistry, mention: str | None) -> str | None:
    """别名提及 → canonical entity_id（未注册 → None，调用方跳过）。"""
    if not mention:
        return None
    hits = registry.match(mention)
    return min(hits) if hits else None


def build_entity_edges(
    *,
    events: list[Any],
    annotations: list[dict[str, Any]],
    registry: EntityRegistry,
    rows: list[Any] = (),
) -> list[EntityEdge]:
    """从事件簇/语义标注/注册表构建类型化边（确定性，可重跑幂等）。

    events：EventRecord（含 entities/cluster_key/as_of）；
    annotations：store.annotations_asof 产出的 dict（item_key/roles/annotated_at）；
    rows：StanceRow（item_key/entity_id/stance，供边极性判定）。
    输出按 (kind, src, dst) 排序；parent_of 锚定全局锚（输入最晚时间）。
    """
    agg: dict[tuple[str, str, str], dict[str, Any]] = {}

    def _touch(src: str, dst: str, kind: str, *, at: datetime, ev_key: str) -> None:
        cell = agg.setdefault(
            (src, dst, kind),
            {"weight": 0, "first": at, "last": at, "evidence": set()},
        )
        cell["weight"] += 1
        cell["first"] = min(cell["first"], at)
        cell["last"] = max(cell["last"], at)
        cell["evidence"].add(ev_key)

    # 全局锚：输入数据内最晚时间（parent_of 无文档时间，用之；PIT 安全——
    # 锚本身来自 t-1 及更早的数据）。
    anchors = [e.as_of for e in events]
    for ann in annotations:
        try:
            anchors.append(datetime.fromisoformat(str(ann["annotated_at"])))
        except (KeyError, ValueError):
            continue
    global_anchor = max(anchors) if anchors else datetime(1970, 1, 1, tzinfo=UTC)

    # -- co_occurs：同簇跨实体（S2 cluster_key） -----------------------------
    clusters: dict[str, list[Any]] = defaultdict(list)
    for ev in events:
        if ev.cluster_key:
            clusters[ev.cluster_key].append(ev)
    for ck, members in clusters.items():
        ents = sorted({e for m in members for e in m.entities})
        for i, a in enumerate(ents):
            for b in ents[i + 1 :]:
                at = min(m.as_of for m in members)
                _touch(a, b, "co_occurs", at=at, ev_key=ck)

    # -- parent_of：注册表父子 -----------------------------------------------
    for eid in registry.ids():
        parent = registry.parent(eid)
        if parent:
            _touch(parent, eid, "parent_of", at=global_anchor, ev_key=eid)

    # -- SRO：roles subject→target（极性由 stance 行判定） --------------------
    stance_by_key_entity: dict[tuple[str, str], str] = {}
    for r in rows:
        stance_by_key_entity.setdefault((r.item_key, r.entity_id), str(r.stance))

    for ann in annotations:
        item_key = str(ann.get("item_key", ""))
        try:
            at = datetime.fromisoformat(str(ann["annotated_at"]))
        except (KeyError, ValueError):
            continue
        for role in ann.get("roles", []) or []:
            src = _canonical(registry, role.get("subject"))
            dst = _canonical(registry, role.get("target"))
            if not src or not dst or src == dst:
                continue
            raw = stance_by_key_entity.get((item_key, dst), "")
            kind = _STANCE_KIND.get(raw, "acts_on")
            _touch(src, dst, kind, at=at, ev_key=item_key)

    edges = [
        EntityEdge(
            src=src,
            dst=dst,
            kind=kind,  # type: ignore[arg-type]
            weight=1.0 * cell["weight"],
            first_seen=cell["first"],
            last_seen=cell["last"],
            evidence_item_keys=sorted(cell["evidence"]),
        )
        for (src, dst, kind), cell in agg.items()
    ]
    edges.sort(key=lambda e: (e.kind, e.src, e.dst))
    return edges
