"""一键刷新全部订阅（定时任务入口，供 OS cron 调用；裁决 D：不引 APScheduler）。

用法：
    uv run python scripts/dev/refresh_watches.py [--url http://127.0.0.1:8787]

cron 示例（每 30 分钟）：
    */30 * * * * cd /path/to/OHnews && uv run python scripts/dev/refresh_watches.py
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8787")
    args = ap.parse_args()
    req = urllib.request.Request(
        f"{args.url}/api/watches/refresh_all",
        method="POST",
        data=b"",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:  # BLE001：CLI 顶层报告根因
        print(f"FAIL: {exc}")
        return 1
    ok = sum(1 for r in payload["results"] if r["ok"])
    print(f"refreshed {ok}/{payload['n']} watches at {payload['refreshed_at']}")
    for r in payload["results"]:
        if not r["ok"]:
            print(f"  {r['watch_id']}: {r['error']}")
    return 0 if ok == payload["n"] else 1


if __name__ == "__main__":
    sys.exit(main())
