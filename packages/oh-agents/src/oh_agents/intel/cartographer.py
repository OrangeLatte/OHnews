"""Cartographer（制图师）：实体共现网络情报（SNA v0）。

输入事件清单（实体×事件），输出共现图：节点=实体，边=同事件共现
（权重=共现事件数）。指标：度数/强度（加权重）/top 邻居。
纯统计无 LLM（六角色中与 Scout 同属确定性层）。

v0 诚实边界：无方向、无时序切片（未来可按窗口对比网络演化）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from oh_contracts.schemas import EventRecord

__all__ = ["co_occurrence_network", "top_hubs"]


def co_occurrence_network(
    events: list[EventRecord],
    *,
    min_weight: int = 1,
    max_nodes: int = 30,
) -> dict[str, Any]:
    """事件实体共现 → {nodes, edges, centrality}（确定性排序）。"""
    pairs: dict[tuple[str, str], int] = defaultdict(int)
    latest: dict[tuple[str, str], str] = {}
    for ev in events:
        ents = sorted(set(ev.entities))
        for i, a in enumerate(ents):
            for b in ents[i + 1 :]:
                key = (a, b)
                pairs[key] += 1
                prev = latest.get(key)
                if prev is None or ev.as_of > prev:
                    latest[key] = ev.as_of
    strength: dict[str, int] = defaultdict(int)
    neighbors: dict[str, set[str]] = defaultdict(set)
    edges: list[dict[str, Any]] = []
    for (a, b), w in pairs.items():
        if w < min_weight:
            continue
        strength[a] += w
        strength[b] += w
        neighbors[a].add(b)
        neighbors[b].add(a)
        edges.append(
            {
                "source": a,
                "target": b,
                "weight": w,
                "latest_event_at": latest[(a, b)].isoformat(),
            }
        )
    edges.sort(key=lambda e: (-e["weight"], e["source"], e["target"]))
    nodes = sorted(strength, key=lambda n: (-strength[n], n))[:max_nodes]
    keep = set(nodes)
    return {
        "nodes": [
            {
                "id": n,
                "strength": strength[n],
                "degree": len(neighbors[n]),
                "top_neighbors": sorted(
                    neighbors[n], key=lambda x: -pairs.get((min(n, x), max(n, x)), 0)
                )[:5],
            }
            for n in nodes
        ],
        "edges": [e for e in edges if e["source"] in keep and e["target"] in keep],
    }


def top_hubs(network: dict[str, Any], *, k: int = 5) -> list[dict[str, Any]]:
    """按强度取前 k 枢纽实体（供 Chief/晨报引用）。"""
    return sorted(network["nodes"], key=lambda n: -n["strength"])[:k]
