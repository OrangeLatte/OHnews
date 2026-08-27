"""Phase 1 冷启动回填编排（蓝图 §13）：采集源 → Bronze parquet + 健康度台账。

仅显式运行时发起网络请求；pytest 全程离线。day-1 首屏真实 NDI 基线的数据入口。

用法：
    uv run python scripts/backfill.py --days 3
    uv run python scripts/backfill.py --days 30 --only gdelt_zh,fred_dgs10
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from oh_sources.health import SourceHealthTracker
from oh_sources.registry import build_registry
from oh_sources.runner import collect_all
from oh_storage.bronze_parquet import ParquetBronzeWriter

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="OH!News 回填编排（Phase 1）")
    parser.add_argument("--config", default=str(ROOT / "config" / "sources.yaml"))
    parser.add_argument("--bronze", default=str(ROOT / "data" / "bronze"))
    parser.add_argument("--health-db", default=str(ROOT / "data" / "health.sqlite"))
    parser.add_argument("--days", type=int, default=3, help="回看窗口天数")
    parser.add_argument("--only", default=None, help="逗号分隔 source_id 白名单（跳过降级检查）")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    registry = build_registry(config)
    writer = ParquetBronzeWriter(args.bronze)
    tracker = SourceHealthTracker(args.health_db)

    until = datetime.now(UTC)
    since = until - timedelta(days=args.days)
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    results = asyncio.run(
        collect_all(
            registry,
            writer,
            since=since,
            until=until,
            tracker=tracker,
            only=only,
        )
    )
    report = [
        {
            "source_id": r.source_id,
            "ok": r.ok,
            "items": r.n_items,
            "written": r.n_written,
            "error": r.error,
            "duration_ms": r.duration_ms,
        }
        for r in results
    ]
    out = ROOT / "data" / "backfill_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"since": since.isoformat(), "until": until.isoformat(), "results": report},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tracker.close()
    for r in report:
        status = "OK  " if r["ok"] else "FAIL"
        print(
            f"[{status}] {r['source_id']:<18} items={r['items']:<5} "
            f"written={r['written']:<5} {r['error'] or ''}"
        )
    print(f"report -> {out}")
    return 0 if report and all(r["ok"] for r in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
