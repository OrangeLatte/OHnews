"""全量/增量 bronze 语义标注回填（M3-S1 接线）。

用法：
    uv run python scripts/dev/backfill_annotations.py [--missing] [--limit K]

默认全量：对 bronze 逐条 annotate_document（词典层，engine=lexicon），
upsert 进 silver.sqlite 的 annotations 表（INSERT OR REPLACE 幂等，可
重复执行）。--missing 增量：仅标注表内尚无记录的 item_key（cron 采集
链路复用同一入口）。annotated_at 取各记录 published_at（PIT：标注时
间锚定在文档自身时间而非回填时刻，重跑与增量结果一致）；无
published_at 的记录跳过（与事件构建门一致）。
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


def run_backfill(*, missing: bool = False, limit: int = 0) -> tuple[int, int, int]:
    """回填核心（供 CLI 与 cron_collect 复用）：返回 (标注数, 已标注跳过数, 跳过数)。"""
    registry = EntityRegistry(DEFAULT_ENTITIES)
    bronze = ParquetBronzeWriter(ROOT / "data" / "bronze")
    store = SqliteStore(connect(ROOT / "data" / "silver.sqlite"))

    done = already = skipped = 0
    for rec in bronze.iter_records():
        if limit and done >= limit:
            break
        if missing and store.get_annotation(rec.item_key) is not None:
            already += 1
            continue
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
            print(f"[annotate] {done} 条…", flush=True)

    print(
        f"[annotate] 完成：标注 {done} 条，跳过 {skipped} 条（无 published_at/"
        f"空文本/时间不可解析）"
        + (f"，已标注跳过 {already} 条" if missing else "")
        + f"，表内现有 {store.count_annotations()} 条"
    )
    return done, already, skipped


def main(argv: list[str] | None = None) -> int:
    """回填入口：bronze → annotate_document → annotations 表。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--missing", action="store_true", help="增量模式：仅标注表内尚无的 item_key"
    )
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 K 条（0=全量）")
    args = parser.parse_args(argv)
    run_backfill(missing=args.missing, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
