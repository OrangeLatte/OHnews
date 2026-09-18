"""将 demo 数据包还原到 data/（fresh install 一步到位）。

zip 布局由 demo_snapshot.py 产出：data/*.sqlite + data/bronze/** +
DEMO_MANIFEST.json。data/ 非空时拒绝执行（--force 覆盖）。还原后对
每个库执行 integrity_check。

用法：uv run python scripts/dev/demo_restore.py [zip_path] [--force]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _verify(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise SystemExit(f"integrity_check failed for {db}: {result}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="还原 demo 数据包到 data/")
    parser.add_argument(
        "zip_path",
        type=Path,
        nargs="?",
        default=ROOT / "dist" / "ohnews-demo-data.zip",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 data/")
    args = parser.parse_args()

    zip_path = args.zip_path.resolve()
    if not zip_path.exists():
        raise SystemExit(
            f"bundle not found: {zip_path}\n"
            "download it from https://github.com/OrangeLatte/OHnews/releases/latest/download/ohnews-demo-data.zip"
        )

    if DATA.exists() and any(DATA.iterdir()):
        if not args.force:
            raise SystemExit(
                f"{DATA} is not empty; pass --force to overwrite (or move it aside first)"
            )
        import shutil

        shutil.rmtree(DATA)

    DATA.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if not any(n == "data/silver.sqlite" for n in names):
            raise SystemExit("bundle malformed: data/silver.sqlite missing")
        zf.extractall(ROOT)
        manifest = {}
        if "data/DEMO_MANIFEST.json" in names:
            manifest = json.loads(zf.read("data/DEMO_MANIFEST.json"))

    dbs = sorted(DATA.glob("*.sqlite")) + [DATA / "events.db"]
    for db in [d for d in dbs if d.exists()]:
        _verify(db)

    print(f"demo data restored to {DATA}")
    print(f"bundle created at: {manifest.get('created_at', 'unknown')}")
    print("start the stack: bash scripts/dev/demo_up.sh --skip-download")


if __name__ == "__main__":
    main()
