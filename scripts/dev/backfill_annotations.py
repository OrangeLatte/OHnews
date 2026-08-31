"""全量 bronze 语义标注回填（M3-S1 接线）。

用法：
    uv run python scripts/dev/backfill_annotations.py [--limit K]

对 bronze 全量记录逐条 annotate_document（词典层，engine=lexicon），
upsert 进 silver.sqlite 的 annotations 表（INSERT OR REPLACE 幂等，
可重复执行）。annotated_at 取各记录 published_at（PIT：标注时间锚
定在文档自身时间而非回填时刻，重跑与增量结果一致）；无 published_at
的记录跳过（与事件构建门一致）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
from oh_pipeline.semantics import annotate_document
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    """回填入口：全量 bronze → annotate_document → annotations 表。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 K 条（0=全量）")
    args = parser.parse_args(argv)

    registry = EntityRegistry(DEFAULT_ENTITIES)
    bronze = ParquetBronzeWriter(ROOT / "data" / "bronze")
    store = SqliteStore(connect(ROOT / "data" / "silver.sqlite"))

    done = skipped = 0
    for rec in bronze.iter_records():
        if args.limit and done >= args.limit:
            break
        n = rec.normalized
        ts_raw = n.get("published_at")
        if not ts_raw:
            skipped += 1
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw))
        except ValueError:
            skipped += 1
            continue
        text = f"{n.get('title') or ''}\n{n.get('body') or ''}".strip()
        if not text:
            skipped += 1
            continue
        ann = annotate_document(rec.item_key, text, registry, annotated_at=ts)
        store.upsert_annotation(
            ann.item_key,
            ann.model_dump(mode="json"),
            engine="lexicon",
            annotated_at=ts,
        )
        done += 1
        if done % 1000 == 0:
            print(f"[annotate] {done} 条…")

    print(
        f"[annotate] 完成：标注 {done} 条，跳过 {skipped} 条（无 published_at/"
        f"空文本/时间不可解析），表内现有 {store.count_annotations()} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
