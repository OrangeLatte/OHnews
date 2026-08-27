"""采集源健康探针（dry-run：不写 Bronze，只跑 fetch 并报告）。

用途：agent 维护循环（用户指示：不稳定源由 agent 维护脚本）——
逐源执行 collect_all + NullSink，输出 存活/条目数/错误，供人工或 agent
修订 sources.yaml（换 URL/调参/下线）。

用法：uv run python scripts/probe_sources.py [--only sina_7x24,wscn_lives]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from oh_sources.registry import build_registry
from oh_sources.runner import collect_all


class NullSink:
    """探针专用：write 丢弃、无日志（不污染 source_fetch_logs 健康度）。"""

    def write(self, records) -> int:  # noqa: ANN001
        return 0

    def iter_records(self, source_id=None):  # noqa: ANN001
        return iter(())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--only", default=None, help="逗号分隔 source_id 白名单")
    ap.add_argument("--hours", type=int, default=6, help="探测窗口小时数")
    args = ap.parse_args()

    config = yaml.safe_load(Path(args.config).read_text())
    registry = build_registry(config)
    only = set(args.only.split(",")) if args.only else None

    until = datetime.now(UTC)
    since = until - timedelta(hours=args.hours)
    results = asyncio.run(collect_all(registry, NullSink(), since=since, until=until, only=only))
    for r in results:
        status = "OK " if r.ok else "ERR"
        detail = f"{r.n_items} items" if r.ok else r.error
        print(f"{status} {r.source_id:20} {detail}")


if __name__ == "__main__":
    main()
