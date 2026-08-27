"""Bronze 层：分区 parquet 写入/读取（append-only，按天重写合并）。

分区布局：{root}/source={source_id}/{YYYY}/{MM}/{DD}.parquet（zstd 压缩，
row group 由 pyarrow 默认控制）。同日重复写入 → 读旧表拼接后整日重写
（架构专家 P2-2：避免小文件碎片化）。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from oh_contracts.schemas import BronzeRecord

_SCHEMA = pa.schema(
    [
        ("item_key", pa.string()),
        ("source_id", pa.string()),
        ("external_id", pa.string()),
        ("url_hash", pa.string()),
        ("content_hash", pa.string()),
        ("fetched_at", pa.timestamp("us", tz="UTC")),
        ("published_at", pa.timestamp("us", tz="UTC")),
        ("raw_json", pa.string()),
        ("normalized_json", pa.string()),
    ]
)


def _record_to_row(r: BronzeRecord) -> dict[str, object]:
    return {
        "item_key": r.item_key,
        "source_id": r.source_id,
        "external_id": r.external_id,
        "url_hash": r.url_hash,
        "content_hash": r.content_hash,
        "fetched_at": r.fetched_at,
        "published_at": r.published_at,
        "raw_json": json.dumps(r.raw, ensure_ascii=False),
        "normalized_json": json.dumps(r.normalized, ensure_ascii=False),
    }


def _row_to_record(row: dict[str, object]) -> BronzeRecord:
    return BronzeRecord(
        source_id=str(row["source_id"]),
        item_key=str(row["item_key"]),
        external_id=str(row["external_id"]),
        url_hash=str(row["url_hash"]),
        content_hash=str(row["content_hash"]),
        fetched_at=row["fetched_at"],  # type: ignore[arg-type]
        published_at=row["published_at"],  # type: ignore[arg-type]
        raw=json.loads(str(row["raw_json"])),
        normalized=json.loads(str(row["normalized_json"])),
    )


class ParquetBronzeWriter:
    """BronzeWriter 的 parquet 实现（Phase 0 默认；冷归档对象存储留 adapter TODO）。"""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _day_path(self, source_id: str, day: date) -> Path:
        return self._root / f"source={source_id}" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}.parquet"

    def write(self, records: Iterable[BronzeRecord]) -> int:
        grouped: dict[Path, list[BronzeRecord]] = defaultdict(list)
        for rec in records:
            grouped[self._day_path(rec.source_id, rec.fetched_at.date())].append(rec)
        for path, recs in grouped.items():
            tables: list[pa.Table] = []
            if path.exists():
                tables.append(pq.read_table(path))
            tables.append(pa.Table.from_pylist([_record_to_row(r) for r in recs], schema=_SCHEMA))
            merged = pa.concat_tables(tables)
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(merged, path, compression="zstd")
        return sum(len(v) for v in grouped.values())

    def iter_records(self, source_id: str | None = None) -> Iterator[BronzeRecord]:
        pattern = "source=*" if source_id is None else f"source={source_id}"
        seen: set[str] = set()
        for path in sorted(self._root.glob(f"{pattern}/*/*/*.parquet")):
            for row in pq.read_table(path).to_pylist():
                item_key = str(row["item_key"])
                if item_key in seen:
                    continue
                seen.add(item_key)
                yield _row_to_record(row)
