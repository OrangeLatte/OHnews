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
    """来源流带：宽度=覆盖量（两窗文章数），Hover 显示来源群体。

    growth 为覆盖变化率（百分点，+87.5 = +87.5%）；T2 低基数诚实弃权：
    n_baseline < 5 时样本不足以支撑比率读数，growth=None 且 low_baseline=True
    （前端已有低样本警示，但比率数字本身误导，故源头不产出）。
    """

    source_id: str
    label: str
    tier: str = ""
    cluster: StreamCluster = "market"
    n_baseline: int = 0
    n_current: int = 0
    growth: float | None = None
    low_baseline: bool = False


class NarrativeStream(_StrictBase):
    """叙事流带：颜色=框架，share_* ∈ [0,1] 为该窗内框架份额。

    T2 可比性校正（双口径）：share_* 为未校正原始份额；adjusted_* 为
    共同来源 cohort（两窗都出现的源）内计算的校正份额——剔除来源结构
    变化的干扰。cohort 源 <2 时 adjusted_* 为 None（不可算，诚实缺失，
    禁止用 raw 冒充校正值）。
    """

    frame: FrameKey
    label: str
    share_baseline: float = Field(ge=0, le=1, default=0.0)
    share_current: float = Field(ge=0, le=1, default=0.0)
    n_baseline: int = 0
    n_current: int = 0
    cluster_split_baseline: dict[str, float] = Field(default_factory=dict)
    cluster_split_current: dict[str, float] = Field(default_factory=dict)
    adjusted_share_baseline: float | None = Field(default=None, ge=0, le=1)
    adjusted_share_current: float | None = Field(default=None, ge=0, le=1)
    n_cohort_sources: int = 0
    # T2 同法标注：基线窗该框架标注行 < 5 时份额迁移读数不可信（诚实标记）。
    low_baseline: bool = False


class ChangeEvidenceArticle(_StrictBase):
    """变化 Drawer 的逐条证据文章引用（T1）。

    来源 = bronze 主题词检索（复用 /api/search 的分词 AND 基建，非 LLM 生成）；
    当前窗口内优先。诚实纪律：检索无命中时列表为空（前端空态），不编造引用。
    """

    item_key: str
    source_id: str
    title: str = ""
    published_at: str | None = None
    language: str = ""


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
    evidence_articles: list[ChangeEvidenceArticle] = Field(default_factory=list)
    # 检测器输出的数值读数（jsd/n_recent/n_base 等），供变化卡真实量化呈现
    metrics: dict[str, float] = Field(default_factory=dict)


class QualityWarning(_StrictBase):
    """质量门未过项/覆盖缺陷：显式暴露，不静默。"""

    code: Literal[
        "low_coverage",
        "single_source_dominant",
        "window_empty",
        "stale_data",
        "no_qualified_changes",
        "gate_insufficient_coverage",
        "source_composition_shift",
    ]
    message: str = Field(min_length=4)


class ChangeLandscape(_StrictBase):
    """沙漏场景聚合（/api/change_landscape 唯一出口）。"""

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


class ChangeFieldPoint(_StrictBase):
    """Narrative Change Field 单日数据点：泳道(tier 簇)×框架计数矩阵。"""

    date: str
    lanes: dict[str, dict[str, int]] = Field(default_factory=dict)


class ChangeFieldPayload(_StrictBase):
    """叙事场时序数据（T8）：前端只渲染不拼图。

    series 按日期升序；changes 为过 Hero Gate 的合格变化（右栏展开入口）；
    lane 键 = tier 簇（official/press/social/unknown），值 = 框架→文章数。
    """

    days: int
    series: list[ChangeFieldPoint] = Field(default_factory=list)
    changes: list[QualifiedChange] = Field(default_factory=list)
    freshness: DataFreshness
