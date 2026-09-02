"""C3 跟踪预警统一契约：实体/主题/问题/元素 四类单元 × 跟踪/预警 两模式。

清零重建（裁决 4）：不迁移旧 watch.sqlite/alerts.sqlite，新库 tracking.sqlite。
"""

from typing import Literal

from pydantic import Field

from .strict import NonEmptyStr, _StrictBase

TrackingKind = Literal["entity", "topic", "question", "element"]
TrackingMode = Literal["track", "alert"]

TRACKING_KINDS: tuple[TrackingKind, ...] = ("entity", "topic", "question", "element")
TRACKING_MODES: tuple[TrackingMode, ...] = ("track", "alert")


class TrackingUnit(_StrictBase):
    """一个跟踪/预警单元。mode=track 增量比较；mode=alert 分位线触发。"""

    unit_id: str
    kind: TrackingKind
    query: NonEmptyStr
    label: str = ""
    mode: TrackingMode = "track"
    threshold: float | None = Field(default=None, ge=0, le=1)
    created_at: str
    last_checked_at: str | None = None


class TrackingHit(_StrictBase):
    """一次触发/更新记录（人话 summary）。"""

    unit_id: str
    kind: TrackingKind
    summary: NonEmptyStr
    triggered_at: str
