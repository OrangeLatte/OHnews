"""仓储协议（裁决 D：实现可替换，切换零改码）。

Phase 0 实现：ParquetBronzeWriter + SqliteStore。
部署态 profile（worker+Redis+PG）未来提供 PostgresStore 实现，接口不变。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from oh_contracts.schemas import BronzeRecord, EventRecord, NDIPoint, StanceRow


@runtime_checkable
class BronzeWriter(Protocol):
    """Bronze 层：append-only 原始快照，item_key 去重读取。"""

    def write(self, records: Iterable[BronzeRecord]) -> int:
        """写入一批记录（按 source/年/月/日 分区），返回写入条数。"""
        ...

    def iter_records(self, source_id: str | None = None) -> Iterator[BronzeRecord]:
        """按 item_key 去重遍历（同 key 保留首见），可选按源过滤。"""
        ...


@runtime_checkable
class SilverStore(Protocol):
    """Silver 层：结构化事件与立场行（PIT 查询以 as_of/ts 为锚）。"""

    def upsert_event(self, event: EventRecord) -> None: ...
    def append_stances(self, rows: Sequence[StanceRow]) -> int:
        """幂等追加（UNIQUE 约束），返回实际新增条数。"""
        ...

    def events_asof(self, as_of: datetime) -> list[EventRecord]: ...
    def stances_asof(self, as_of: datetime) -> list[StanceRow]: ...


@runtime_checkable
class GoldReader(Protocol):
    """Gold 层：NDI 点位（含弃权语义）读写。"""

    def append_ndi(self, point: NDIPoint) -> None: ...
    def ndi_series(self, event_id: str) -> list[NDIPoint]: ...
