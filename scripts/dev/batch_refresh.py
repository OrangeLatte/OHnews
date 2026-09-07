"""批量采集：刷新全部 enabled 信源，跨语言补齐 NOW 数据新鲜度。

用法：uv run python scripts/dev/batch_refresh.py [--days 1] [--limit 0] [--only src1,src2]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# 绕过 mac 系统代理（可能指向已死进程）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _req(method: str, url: str, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, method=method)
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="最多刷新 N 个信源，0=全部")
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    srcs = _req("GET", "http://localhost:8787/api/sources")["sources"]
    enabled = [s["source_id"] for s in srcs if s.get("enabled")]
    if args.only:
        picks = [s for s in args.only.split(",") if s]
    else:
        picks = enabled[: args.limit] if args.limit else enabled
    print(f"refreshing {len(picks)}/{len(enabled)} enabled sources, days={args.days}", flush=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {
            ex.submit(
                _req, "POST", f"http://localhost:8787/api/sources/{sid}/refresh?days={args.days}"
            ): sid
            for sid in picks
        }
        for fut in as_completed(futs):
            sid = futs[fut]
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                r = {"source_id": sid, "ok": False, "error": str(e)[:120]}
            results.append(r)
            print(
                f"{sid}: ok={r.get('ok')} written={r.get('n_written')} err={r.get('error')}",
                flush=True,
            )
            time.sleep(0.4)

    ok = [r for r in results if r.get("ok")]
    written = sum(r.get("n_written", 0) for r in ok)
    summary = json.dumps({"total": len(results), "ok": len(ok), "written": written})
    print(summary, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
