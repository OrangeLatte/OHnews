"""镜像 opencode 会话日志到项目内 .opencode/logs/opencode/（Phase 0 日志隔离）。

蓝图 §15：opencode 全程持久化日志需在项目文件夹隔离储存；/dev/monitor（Phase 5）
消费本目录。扫描 ~/.local/share/opencode 下近 N 天修改的 .json/.jsonl 会话文件，
内容引用本项目路径（"OHnews"）则复制镜像。只读远端，不删不改。

用法：uv run python scripts/dev/collect_logs.py [--days 7]
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

#: 命中任一路径片段即视为本项目的会话
PROJECT_MARKERS = ("OHnews",)
#: 跳过的目录名（远端扫描降噪）
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", "logs"}
#: 单文件体积上限（防误读大文件）
MAX_FILE_BYTES = 20_000_000
SCAN_SUFFIXES = {".json", ".jsonl"}


def opencode_roots() -> list[Path]:
    """opencode 数据根（跨平台：XDG 展开至 ~/.local/share/opencode）。"""
    home = Path.home() / ".local" / "share" / "opencode"
    return [home] if home.exists() else []


def find_session_files(days: int) -> list[tuple[Path, Path]]:
    """返回 (root, file) 列表：root 下近 N 天修改的 json/jsonl 文件。"""
    cutoff = time.time() - days * 86400
    found: list[tuple[Path, Path]] = []
    for root in opencode_roots():
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                if path.stat().st_mtime < cutoff or path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append((root, path))
    return found


def references_project(text: str) -> bool:
    return any(marker in text for marker in PROJECT_MARKERS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="回看天数（默认 7）")
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path(".opencode/logs/opencode"),
        help="镜像目标目录（相对项目根）",
    )
    args = parser.parse_args()

    dest_root = args.dest
    copied = 0
    for root, path in find_session_files(args.days):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not references_project(text):
            continue
        rel = path.relative_to(root)
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1

    print(f"镜像完成：{copied} 个会话文件 → {dest_root}")


if __name__ == "__main__":
    main()
