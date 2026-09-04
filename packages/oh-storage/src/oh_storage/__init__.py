"""OH!News 存储层。

裁决 D：单进程默认（单写者），Repository 协议化——切换 PG/部署态 profile 零改码。
分层：Bronze（parquet 分区 append-only）→ Silver（sqlite events/stances）
    → Gold（sqlite ndi_series）。
"""

from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.protocols import BronzeWriter, GoldReader, SilverStore
from oh_storage.research_store import ResearchStore
from oh_storage.sqlite_store import SqliteStore

__all__ = [
    "BronzeWriter",
    "GoldReader",
    "ParquetBronzeWriter",
    "ResearchStore",
    "SilverStore",
    "SqliteStore",
    "connect",
]
