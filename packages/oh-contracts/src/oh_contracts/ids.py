"""幂等主键与内容指纹（双 hash 纪律：url_hash + content_hash）。"""

from __future__ import annotations

import hashlib


def url_hash(url: str) -> str:
    """URL 指纹（SHA-256 前 16 位，域前缀 "u:"）：同一 URL 重发/改版可识别。"""
    return hashlib.sha256(f"u:{url}".encode()).hexdigest()[:16]


def content_hash(text: str) -> str:
    """内容指纹（SHA-256 前 16 位，域前缀 "c:"）：不同 URL 同内容去重。"""
    return hashlib.sha256(f"c:{text}".encode()).hexdigest()[:16]


def make_item_key(source_id: str, external_id: str, ts: str) -> str:
    """采集幂等主键（裁决 C）：item_key = (source, external_id, ts)。

    同源同外部 ID 同时间戳 → 同一 item；重复采集天然幂等。
    """
    return f"{source_id}:{external_id}:{ts}"
