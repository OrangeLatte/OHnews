"""Orange Hourglass 场景契约（阶段 1.5-c）。

沙漏可视化单一数据源：后端聚合全部窗口统计与质量门结果，
前端只做映射渲染（流带宽度=覆盖量、颜色=叙事框架、纹理=来源簇），
禁止在浏览器里拼图（指令 1.5 规格）。
"""

from __future__ import annotations

from enum import StrEnum
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


class EvidenceSourceCount(_StrictBase):
    """单个信源对某变化的实体证据命中计数（来源驱动按实体过滤的口径）。"""

    source_id: str
    n: int = Field(ge=0)


class EvidenceFlag(StrEnum):
    """实体证据覆盖等级：质量门后仍须逐变化披露，禁冒充合格候选。"""

    SUFFICIENT = "sufficient"  # ≥2 篇实体证据
    SINGLE_SOURCE = "single_source"  # 仅 1 篇（单源候选）
    NONE = "none"  # 0 篇（无实体证据）


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
    # 实体证据覆盖（P0-1）：按信源聚合的命中计数 + 覆盖等级
    evidence_source_breakdown: list[EvidenceSourceCount] = Field(default_factory=list)
    evidence_flag: EvidenceFlag = EvidenceFlag.NONE


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


class EffectiveFilters(_StrictBase):
    """本聚合实际生效的筛选（空=未筛选，作用于全部 bronze 记录）。"""

    source_ids: list[str] = Field(default_factory=list)
    language: str | None = None


class LandscapeSample(_StrictBase):
    """两窗样本量（筛选后口径，与 sample_baseline/sample_current 同源）。"""

    baseline: int = 0
    current: int = 0


class SourceDayPoint(_StrictBase):
    """信源×日计数点（timeseries.source_day，Small Multiples 单元=一信源）。

    day 为 published_at 的 UTC 日期（YYYY-MM-DD）；仅 bronze 窗口内
    published_at 非空的记录计入。序列按窗口总量降序、同量按 source_id
    升序排名，rank 内按 day 升序（未入选 top8 的信源不产出，前端聚合"其他"）。
    """

    source_id: str
    day: str
    n: int = Field(ge=0)


class FrameDayPoint(_StrictBase):
    """框架×日份额点（timeseries.frame_day，Small Multiples 单元=一框架）。

    share = 当日该框架计数 / 当日全部框架计数（分母含未入选 top6 的框架，
    单日 share 之和 ≈1）；n 为当日该框架计数。序列按窗口总量降序、同量按
    frame 升序排名，rank 内按 day 升序。
    """

    frame: FrameKey
    day: str
    share: float = Field(ge=0.0, le=1.0)
    n: int = Field(ge=0)


class NdiDayPoint(_StrictBase):
    """NDI×日读数点（timeseries.ndi_day，Small Multiples 单元=一 NDI 事件）。

    entity_id 取 NDIPoint.event_id（NDI 数据面无 entity 维度，事件即分歧
    主体）；仅窗口内 status=ok 点位产出（abstain 点 ndi=None 无读数，诚实
    缺失）。序列按各实体窗口内最新 NDI 降序（同 ts 取 ndi 大者，保证确定
    性）、同值按 entity_id 升序排名，rank 内按 day 升序。
    """

    entity_id: str
    day: str
    ndi: float = Field(ge=0.0, le=1.0)
    n_sources: int = Field(ge=0)


class TimeSeries(_StrictBase):
    """按天分桶时间序列（阶段 1.5-c T9）：前端统一 Small Multiples 数据面。

    分桶窗与 current_window 同源（days 参数 + 检测锚定后 det_now 切分，
    半开区间）；day_start = 三序列最早数据日（前端轴起点，可能晚于窗口首日）。
    三序列全空时整段 timeseries=None（诚实空态，不返回空结构假装有数据）。
    """

    days: int
    day_start: str
    source_day: list[SourceDayPoint] = Field(default_factory=list)
    frame_day: list[FrameDayPoint] = Field(default_factory=list)
    ndi_day: list[NdiDayPoint] = Field(default_factory=list)


class ChangeLandscape(_StrictBase):
    """沙漏场景聚合（/api/change_landscape 唯一出口）。

    effective_window 语义由 current_window 承担（检测锚定后的实际生效窗）；
    effective_filters/sample/computed_at 供前端展示筛选口径与数据新鲜度；
    timeseries 为按天分桶序列（Small Multiples），空窗为 None。
    """

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
    effective_filters: EffectiveFilters | None = None
    sample: LandscapeSample | None = None
    timeseries: TimeSeries | None = None
    computed_at: str = ""


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
