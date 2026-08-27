"""日运行编排：Bronze → 事件 → Tagger → NDI → Gold（Phase 2 全链）。

用法：
    uv run python scripts/dev/run_daily.py [--days N] [--min-articles K]
        [--min-sources K] [--min-per-source K] [--limit K]

开发态默认 min_per_source=2（测量效度验证与对外数字必须用 10）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from oh_contracts.enums import SourceTier
from oh_pipeline.events import EventBuilder
from oh_pipeline.run import run_pipeline
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

ROOT = Path(__file__).resolve().parents[2]
SOURCES_YAML = ROOT / "config" / "sources.yaml"


def load_tier_map(path: Path) -> dict[str, SourceTier]:
    """sources.yaml → {source_id: SourceTier}（enabled 与否不影响 tier 归属）。"""
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    tier_map: dict[str, SourceTier] = {}
    for spec in doc.get("sources", []):
        sid = spec.get("source_id")
        tier = spec.get("tier")
        if sid and tier:
            tier_map[sid] = SourceTier(tier)
    return tier_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="事件聚合窗口（天）")
    parser.add_argument("--min-articles", type=int, default=3)
    parser.add_argument("--min-sources", type=int, default=2)
    parser.add_argument(
        "--min-per-source", type=int, default=2, help="NDI 源级样本门：开发态 2 / 对外数字 10"
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 K 个事件（0=全部）")
    args = parser.parse_args(argv)

    bronze = ParquetBronzeWriter(ROOT / "data" / "bronze")
    records = list(bronze.iter_records())
    if not records:
        print("[EMPTY] Bronze 无数据——先运行 scripts/backfill.py", file=sys.stderr)
        return 1

    now = datetime.now(UTC)
    window_start = now - timedelta(days=args.days)
    records = [r for r in records if r.published_at is not None and r.published_at >= window_start]
    print(f"[bronze] 窗口内 {len(records)} 条（{args.days} 天）")

    built = EventBuilder().build(
        records,
        min_articles=args.min_articles,
        min_sources=args.min_sources,
    )
    if args.limit:
        built = built[: args.limit]
    if not built:
        print("[EMPTY] 无合格事件（提高窗口或放宽 --min-articles/--min-sources）")
        return 0
    print(
        f"[events] 合格事件 {len(built)} 个（门：≥{args.min_articles} 篇 × ≥{args.min_sources} 源）"
    )

    store = SqliteStore(connect(ROOT / "data" / "silver.sqlite"))
    for b in built:
        store.upsert_event(b.event)

    tier_map = load_tier_map(SOURCES_YAML)
    report = run_pipeline(
        bronze,
        store,
        store,
        [b.event for b in built],
        tier_map,
        as_of=now,
        lookback_days=args.days,
        min_per_source=args.min_per_source,
    )

    print(
        f"[pipeline] rows_written={report.rows_written} "
        f"ndi_ok={report.ndi_ok} ndi_abstain={report.ndi_abstain}"
    )
    print("\n== 事件 NDI 概览（NDI=叙事分歧指数，描述性监测）==")
    print(f"{'event_id':<28} {'articles':>8} {'sources':>7} {'NDI':>8} {'ΔT':>8}")
    for b in built:
        eid = b.event.event_id
        ndi = report.temperature_gaps.get(eid)
        series = store.ndi_series(eid)
        point = series[-1] if series else None
        ndi_s = f"{point.ndi:.3f}" if point and point.ndi is not None else "abstain"
        gap_s = f"{ndi:.2f}" if isinstance(ndi, float) else "-"
        print(f"{eid:<28} {b.n_articles:>8} {b.n_sources:>7} {ndi_s:>8} {gap_s:>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
