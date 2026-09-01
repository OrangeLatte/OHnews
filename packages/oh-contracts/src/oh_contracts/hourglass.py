"""Orange Hourglass 场景契约（阶段 1.5-c）。

沙漏可视化单一数据源：后端聚合全部窗口统计与质量门结果，
前端只做映射渲染（流带宽度=覆盖量、颜色=叙事框架、纹理=来源簇），
禁止在浏览器里拼图（指令 1.5 规格）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from oh_contracts.briefing import (
    DataFreshness,
    EvidenceCitation,
)
from oh_contracts.strict import HeadlineStr, _StrictBase

StreamCluster = Literal["official", "market"]
FrameKey = Literal["loss", "gain", "responsibility", "conflict", "human_interest", "other"]


class TimeWindow(_StrictBase):
    """等长时间窗：baseline=过去窗、current=当前窗（翻转沙漏即交换两者）。"""

    start: str
    end: str
    n_articles: int = 0
    n_sources: int = 0


class SourceStream(_StrictBase):
    """来源流带：宽度=覆盖量（两窗文章数），Hover 显示来源群体。"""

    source_id: str
    label: str
    tier: str = ""
    cluster: StreamCluster = "market"
    n_baseline: int = 0
    n_current: int = 0


class NarrativeStream(_StrictBase):
    """叙事流带：颜色=框架，share_* ∈ [0,1] 为该窗内框架份额。"""

    frame: FrameKey
    label: str
    share_baseline: float = Field(ge=0, le=1, default=0.0)
    share_current: float = Field(ge=0, le=1, default=0.0)
    n_baseline: int = 0
    n_current: int = 0
    cluster_split_baseline: dict[str, float] = Field(default_factory=dict)
    cluster_split_current: dict[str, float] = Field(default_factory=dict)


class QualifiedChange(_StrictBase):
    """腰部 Change Point：已过质量门的变化（复用 Briefing 人话语义）。"""

    change_id: str
    kind: str
    headline: HeadlineStr
    what: str
    why_now: str = ""
    strength_word: str = ""
    urgency: str = ""
    subjects: list[str] = Field(default_factory=list)
    at: str | None = None


class QualityWarning(_StrictBase):
    """质量门未过项/覆盖缺陷：显式暴露，不静默。"""

    code: Literal[
        "low_coverage",
        "single_source_dominant",
        "window_empty",
        "stale_data",
        "no_qualified_changes",
    ]
    message: str = Field(min_length=4)


class HourglassScene(_StrictBase):
    """沙漏场景聚合（/api/hourglass 唯一出口）。"""

    scene_id: str
    generated_at: str
    baseline_window: TimeWindow
    current_window: TimeWindow
    source_streams: list[SourceStream] = Field(default_factory=list)
    narrative_streams: list[NarrativeStream] = Field(default_factory=list)
    qualified_changes: list[QualifiedChange] = Field(default_factory=list)
    evidence_refs: list[EvidenceCitation] = Field(default_factory=list)
    freshness: DataFreshness
    quality_warnings: list[QualityWarning] = Field(default_factory=list)
