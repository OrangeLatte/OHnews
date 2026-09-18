"""导出开箱即用的 demo 数据包（GitHub Release asset）。

对核心 SQLite 逐库 VACUUM INTO：绕过 wal/shm，产出自包含的一致性快照
（wal 中未 checkpoint 的已提交数据同样会被读出）。bronze parquet 层
整体复制。敏感与临时文件（runtime_keys.json、*.bak、*.log、wal/shm）
一律不入包。打包前后对每个库执行 integrity_check。

用法：uv run python scripts/dev/demo_snapshot.py [--out dist/ohnews-demo-data.zip]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

CORE_DBS = [
    "silver.sqlite",
    "research.sqlite",
    "archive.sqlite",
    "tracking.sqlite",
    "watch.sqlite",
    "belief.sqlite",
    "decisions.sqlite",
    "intel.sqlite",
    "library.sqlite",
    "product_events.sqlite",
    "ingestion.sqlite",
    "chat.sqlite",
    "events.db",
]

EXCLUDE_SUFFIXES = (".log", ".lock")


def _integrity_check(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise SystemExit(f"integrity_check failed for {db}: {result}")
    finally:
        conn.close()


def _vacuum_into(src: Path, dst: Path) -> int:
    """VACUUM INTO 生成干净快照（无 wal/shm），返回快照字节数。"""
    conn = sqlite3.connect(src)
    try:
        conn.execute("VACUUM INTO ?", (str(dst),))
    finally:
        conn.close()
    return dst.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description="导出 demo 数据包")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "dist" / "ohnews-demo-data.zip",
        help="输出 zip 路径",
    )
    args = parser.parse_args()

    if not DATA.exists():
        raise SystemExit(f"data/ not found at {DATA}")
    if not (DATA / "silver.sqlite").exists():
        raise SystemExit("silver.sqlite missing — nothing to snapshot")

    out_zip: Path = args.out.resolve()
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    staging = out_zip.parent / f".{out_zip.stem}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    snap_data = staging / "data"
    snap_data.mkdir(parents=True)

    manifest: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(),
        "databases": {},
        "bronze_files": 0,
    }

    for name in CORE_DBS:
        src = DATA / name
        if not src.exists():
            continue
        _integrity_check(src)
        size = _vacuum_into(src, snap_data / name)
        manifest["databases"][name] = size  # type: ignore[index]

    bronze_src = DATA / "bronze"
    if bronze_src.exists():
        shutil.copytree(bronze_src, snap_data / "bronze")
        manifest["bronze_files"] = sum(  # type: ignore[assignment]
            1 for p in (snap_data / "bronze").rglob("*") if p.is_file()
        )

    # manifest 放 data/ 内：restore 后随 data/ 落位（data/ 已 gitignore），不散落仓库根
    (snap_data / "DEMO_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file() and not path.name.endswith(EXCLUDE_SUFFIXES):
                zf.write(path, path.relative_to(staging))

    shutil.rmtree(staging)
    total_mb = out_zip.stat().st_size / 1_048_576
    print(f"demo bundle: {out_zip} ({total_mb:.1f} MB)")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
