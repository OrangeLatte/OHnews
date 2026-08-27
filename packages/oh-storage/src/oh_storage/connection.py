"""统一 SQLite 连接工厂（裁决 D：WAL + busy_timeout=5000 + synchronous=NORMAL，单写者）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path | str) -> sqlite3.Connection:
    """创建统一 PRAGMA 配置的 SQLite 连接。

    - journal_mode=WAL：读写不互阻塞
    - busy_timeout=5000：写冲突等待而非立即报错
    - synchronous=NORMAL：WAL 下安全的持久性/性能折中
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
