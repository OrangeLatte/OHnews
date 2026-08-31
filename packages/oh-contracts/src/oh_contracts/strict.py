"""产品层严格模型基础件（阶段 2 从 briefing.py 提取，供全部契约模块共用）。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
HeadlineStr = Annotated[str, StringConstraints(min_length=8, strip_whitespace=True)]


class _StrictBase(BaseModel):
    """产品层统一严格模型：多余字段拒绝。"""

    model_config = {"extra": "forbid"}


__all__ = ["HeadlineStr", "NonEmptyStr", "_StrictBase"]
