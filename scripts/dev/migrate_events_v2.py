"""M3-S2 迁移脚本：既有 silver.sqlite 事件表回填 cluster_key（events.py v2）。

流程：
1. 备份 silver.sqlite（同目录 .bak-YYYYMMDDHHMMSS，已存在则跳过备份直接跑——幂等）
2. SqliteStore 初始化（自动 ALTER TABLE events ADD COLUMN cluster_key）
3. 全量 bronze 重跑 EventBuilder v2 → 簇级聚类 → upsert 全部成员事件行
   （v2 事件集 ⊇ v1：桶定义未变，合并只放宽合格门，故旧行同 event_id 重写、
   新增合并产生的新行；stances/ndi_series 外键不动）
4. 打印统计：事件数 / 簇数 / 多实体簇数 / 最大簇

用法：uv run python scripts/dev/migrate_events_v2.py [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
from oh_pipeline.events import EventBuilder
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    db_path = ROOT / "data" / "silver.sqlite"
    bronze_dir = ROOT / "data" / "bronze"
    if not db_path.exists():
        raise SystemExit(f"silver db not found: {db_path}")

    if not args.dry_run:
        backup = db_path.with_suffix(f".sqlite.bak-{datetime.now(UTC):%Y%m%d%H%M%S}")
        shutil.copy2(db_path, backup)
        print(f"backup -> {backup.name}")

    store = SqliteStore(connect(db_path))
    before = store.count_events()

    bronze = ParquetBronzeWriter(bronze_dir)
    built = EventBuilder(EntityRegistry(DEFAULT_ENTITIES)).build(bronze.iter_records())

    clusters: dict[str, set[str]] = defaultdict(set)
    for b in built:
        assert b.cluster_key is not None
        clusters[b.cluster_key].add(b.event.entities[0])

    print(f"events(before)={before} events(after upsert)={len(built)} clusters={len(clusters)}")
    multi = {k: v for k, v in clusters.items() if len(v) > 1}
    print(f"multi-entity clusters={len(multi)}")
    if multi:
        top = sorted(multi.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:5]
        for ck, ents in top:
            print(f"  {ck}: {sorted(ents)}")

    if args.dry_run:
        print("dry-run: no writes")
        return

    for b in built:
        store.upsert_event(b.event)

    # 兜底：v1 遗留行（v2 门未过或历史孤儿）cluster_key 仍为 NULL → 自成单例簇，
    # 保证下游（KG/簇级视图）无需处理 NULL；关联的 stances/ndi 不动。
    import hashlib
    import sqlite3

    raw = sqlite3.connect(db_path)
    orphans = [r[0] for r in raw.execute("SELECT event_id FROM events WHERE cluster_key IS NULL")]
    for event_id in orphans:
        digest = hashlib.sha1(event_id.encode("utf-8")).hexdigest()
        raw.execute(
            "UPDATE events SET cluster_key = ? WHERE event_id = ?",
            (f"evt-{digest[:8]}", event_id),
        )
    raw.commit()
    raw.close()
    print(
        f"upserted {len(built)} event rows; singleton fallback for {len(orphans)} legacy rows; done"
    )


if __name__ == "__main__":
    main()
