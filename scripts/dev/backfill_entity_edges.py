"""KG v2 全量边回填：events/annotations/stances → entity_edges 表（M3-S3）。

用法：
    uv run python scripts/dev/backfill_entity_edges.py [--dry-run]

从 silver 库读全量 events（含 S2 cluster_key）/annotations（S1）/stances，
build_entity_edges 聚合为类型化边后 upsert 进 entity_edges 表
（同 edge_key 覆盖，全量重跑幂等）。as_of 取库内最晚 NDI 点时间锚。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
from oh_pipeline.knowledge_graph import build_entity_edges, edge_key
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    """回填入口：silver 三表 → build_entity_edges → entity_edges 表。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args(argv)

    store = SqliteStore(connect(ROOT / "data" / "silver.sqlite"))
    points = store.ndi_all()
    if not points:
        print("[edges] 库内无 NDI 点，缺 as_of 锚，终止")
        return 1
    now = points[-1].ts

    events = store.events_asof(now)
    annotations = store.annotations_asof(now)
    rows = store.stances_asof(now)
    edges = build_entity_edges(
        events=events,
        annotations=annotations,
        registry=EntityRegistry(DEFAULT_ENTITIES),
        rows=rows,
    )
    by_kind: dict[str, int] = {}
    for e in edges:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
    print(
        f"[edges] as_of={now.isoformat()} events={len(events)} "
        f"annotations={len(annotations)} stances={len(rows)}"
    )
    print(f"[edges] 聚合出 {len(edges)} 条边 by_kind={by_kind}")
    if args.dry_run:
        print("[edges] dry-run：未写库")
        return 0

    payload = [
        {
            "edge_key": edge_key(e.src, e.dst, e.kind),
            "src": e.src,
            "dst": e.dst,
            "kind": e.kind,
            "weight": e.weight,
            "first_seen": e.first_seen.isoformat(),
            "last_seen": e.last_seen.isoformat(),
            "evidence": e.evidence_item_keys,
        }
        for e in edges
    ]
    n = store.upsert_edges(payload)
    print(f"[edges] upsert {n} 行，表内现有 {store.count_edges()} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
