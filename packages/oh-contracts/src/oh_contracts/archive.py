"""Phase D 档案契约：三档案库（元素/研究/交叉分析）+ 档案报纸。

纪律：**存档必须用户显式确认**（前端确认动作触发 POST），系统不自动存档；
报纸为用户筛选后 agent 组合的产物，同样确认式保存。
"""

from typing import Literal

from pydantic import Field

from .strict import HeadlineStr, NonEmptyStr, _StrictBase

ArchiveKind = Literal["dissection", "report", "cross_analysis"]
ARCHIVE_KINDS: tuple[ArchiveKind, ...] = ("dissection", "report", "cross_analysis")
ARCHIVE_KIND_ZH = {
    "dissection": "元素档案",
    "report": "研究档案",
    "cross_analysis": "交叉分析档案",
}


class ArchiveItem(_StrictBase):
    """单条档案（payload 为来源对象完整 JSON，回读即用）。"""

    archive_id: str
    kind: ArchiveKind
    title: HeadlineStr
    ref_kind: NonEmptyStr
    ref_id: NonEmptyStr
    payload: dict[str, object] = Field(default_factory=dict)
    note: str = ""
    created_at: str


class AgentPaper(_StrictBase):
    """档案报纸：用户筛选组合 + 卷首语（agent 生成，确认式保存）。"""

    paper_id: str
    title: HeadlineStr
    item_ids: list[str] = Field(default_factory=list)
    foreword: str = ""
    created_at: str


__all__ = ["ARCHIVE_KINDS", "ARCHIVE_KIND_ZH", "AgentPaper", "ArchiveItem", "ArchiveKind"]
