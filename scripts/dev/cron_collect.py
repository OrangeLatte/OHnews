"""C1 定时采集入口（供系统 crontab 调用）：全部 enabled 源各采近 1 天。

链路：采集 bronze → 增量标注（backfill_annotations --missing，只补表内
缺失项，PIT 锚定 published_at）。

用法：uv run python scripts/dev/cron_collect.py [--days 1] [--only sid1,sid2]
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "packages" / "oh-api" / "src"))

import yaml  # noqa: E402
from oh_api.app import AppPaths  # noqa: E402

paths = AppPaths()
from oh_sources.registry import build_registry  # noqa: E402
from oh_sources.runner import run_collector  # noqa: E402
from oh_storage.bronze_parquet import ParquetBronzeWriter  # noqa: E402


def annotate_missing() -> bool:
    """采集后增量标注（复用回填入口；脚本同目录可直接导入）。"""
    try:
        import backfill_annotations

        backfill_annotations.main(["--missing"])
    except Exception as exc:
        print(f"[annotate] fail: {exc}", flush=True)
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()
    doc = yaml.safe_load(paths.sources_yaml.read_text(encoding="utf-8")) or {}
    registry = build_registry(doc)
    writer = ParquetBronzeWriter(ROOT / "data" / "bronze")
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    failures = 0
    for adapter in sorted(registry.all(), key=lambda a: a.meta.source_id):
        sid = adapter.meta.source_id
        if only and sid not in only:
            continue
        now = datetime.now(UTC)
        result = asyncio.run(
            run_collector(
                adapter,
                writer=writer,
                since=now - timedelta(days=max(1, args.days)),
                until=now,
            )
        )
        status = "ok" if result.ok else f"fail: {result.error}"
        if not result.ok:
            failures += 1
        print(f"{sid}: written={result.n_written} {status}", flush=True)
    if not annotate_missing():
        failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
