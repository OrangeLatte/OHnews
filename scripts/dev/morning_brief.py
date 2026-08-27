"""晨报 CLI：watchlist 实体 NDI 环比 + 证据链（纯只读，无 LLM）。

用法：
    uv run python scripts/dev/morning_brief.py --watchlist fed,trump,ecb [--days 1]
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from oh_agents.morning_brief import build_brief
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


def main() -> None:
    parser = argparse.ArgumentParser(description="OH!News 晨报")
    parser.add_argument("--bronze", default="data/bronze")
    parser.add_argument("--silver", default="data/silver.sqlite")
    parser.add_argument("--watchlist", default="fed,trump,ecb,boe,pboc")
    parser.add_argument("--days", type=int, default=1, help="只看最近 N 天的事件")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    now = datetime.now(UTC)
    brief = build_brief(
        ParquetBronzeWriter(args.bronze),
        SqliteStore(connect(args.silver)),
        SqliteStore(connect(args.silver)),
        [w.strip() for w in args.watchlist.split(",") if w.strip()],
        now=now,
        top_n=args.top,
    )
    cutoff = now - timedelta(days=args.days)
    items = tuple(i for i in brief.items if i.as_of >= cutoff)
    brief = type(brief)(generated_at=brief.generated_at, items=items)
    print(brief.render_text())


if __name__ == "__main__":
    main()
