"""产品语义层契约（阶段 1：认知闭环黄金路径）。

设计纪律（PRODUCT_AUDIT.md §3.4 / §6）：
- 用户语言优先：内部指标（NDI/JSD/confidence/engine）不出现在主路径字段，
  仅 TechnicalAnnex 可选承载（前端折叠「技术指标」按需展开）。
- missing evidence 是一等公民：EvidenceGap 独立建模，禁止伪装为证据条目。
- 新鲜度语义：data_as_of = 数据实际覆盖（非请求时刻 now），
  staleness 由数据覆盖末端与 now 的差距分级。
- 内部 ID 封装：面向用户的引用一律 SubjectRef（kind+id+人话 label）。
- 本文件与 narrative.py 的内部 EvidenceItem 解耦：产品层证据为 EvidenceCitation
  （含 url/title/source_tier，支撑「≤3 次操作到原文」硬验收）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from oh_contracts.enums import SourceTier

EvidenceBucket = Literal["supporting", "contradicting", "context"]

StalenessLevel = Literal["fresh", "aging", "stale"]

ChangeKind = Literal[
    "attention_spike",
    "narrative_shift",
    "divergence_rise",
    "expectation_gap",
]

StrengthWord = Literal["strong", "notable", "minor", "insufficient"]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
HeadlineStr = Annotated[str, StringConstraints(min_length=8, strip_whitespace=True)]


class _StrictBase(BaseModel):
    """产品层统一严格模型：多余字段拒绝。"""

    model_config = {"extra": "forbid"}


class DataFreshness(_StrictBase):
    """覆盖窗 + staleness 分级。

    as_of 语义：数据实际覆盖末端（如 bronze 最新 published_at），
    不是 API 请求时刻；前端展示「数据截至 {as_of}」。
    """

    as_of: datetime
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    staleness: StalenessLevel = "stale"
    note: NonEmptyStr = "数据覆盖情况未知"


class SubjectRef(_StrictBase):
    """面向用户的稳定引用：内部 id 被人话 label 包裹。"""

    kind: Literal["entity", "event", "cluster"]
    id: NonEmptyStr
    label: NonEmptyStr


class EvidenceCitation(_StrictBase):
    """产品层证据条目：引用原文的最后一公里（url 即外链）。"""

    item_key: NonEmptyStr
    source_id: NonEmptyStr
    source_tier: SourceTier
    title: NonEmptyStr
    quote: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    url: str | None = None
    published_at: datetime | None = None


class EvidenceGap(_StrictBase):
    """缺失证据（期望但未观测）：独立建模，绝不冒充证据条目。"""

    gap_id: NonEmptyStr
    expectation: HeadlineStr
    reason: Literal["no_primary_source", "single_cluster", "time_gap", "source_silent"]
    subject: SubjectRef | None = None
    suggestion: str = ""


class CoverageSummary(_StrictBase):
    """样本覆盖的人话摘要 + 原始计数（按需展开）。"""

    n_independent_sources: int = Field(ge=0)
    n_primary_sources: int = Field(ge=0)
    time_span_days: float = Field(ge=0)
    languages: list[NonEmptyStr] = Field(default_factory=list)
    note: HeadlineStr


class EvidenceSet(_StrictBase):
    """三桶证据 + 缺口：支持/反对/上下文分离呈现。"""

    supporting: list[EvidenceCitation] = Field(default_factory=list)
    contradicting: list[EvidenceCitation] = Field(default_factory=list)
    context: list[EvidenceCitation] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list)

    @property
    def n_items(self) -> int:
        """三桶条目总数（不含缺口）。"""
        return len(self.supporting) + len(self.contradicting) + len(self.context)


class TechnicalAnnex(_StrictBase):
    """内部指标附页（可选暴露，主路径禁用；前端折叠呈现）。

    诚实边界：字段缺失（None）表示该指标本次不可测（如 NDI 弃权），
    不允许用 0 或「看起来像 0 的值」冒充。
    """

    signal_id: NonEmptyStr | None = None
    engine: Literal["offline", "lexicon", "llm"] | None = None
    ndi: float | None = Field(default=None, ge=0.0, le=1.0)
    jsd: float | None = Field(default=None, ge=0.0, le=1.0)
    temperature_gap: float | None = None
    intelligence_score: float | None = Field(default=None, ge=0.0, le=100.0)
    extra: dict[str, Any] = Field(default_factory=dict)


class ChangeBrief(_StrictBase):
    """变化卡（Briefing 页 3-5 张的主语）：what / why_now / 强度人话。"""

    change_id: NonEmptyStr
    kind: ChangeKind
    headline: HeadlineStr
    what: HeadlineStr
    why_now: HeadlineStr
    strength_word: StrengthWord
    urgency: Literal["high", "medium", "low"] = "medium"
    subjects: list[SubjectRef] = Field(default_factory=list)
    published_window: tuple[datetime, datetime] | None = None


class ChangeDossier(_StrictBase):
    """变化详情包：黄金路径第二跳（Evidence Drawer 的宿主）。"""

    change_id: NonEmptyStr
    kind: ChangeKind
    headline: HeadlineStr
    what: HeadlineStr
    why_now: HeadlineStr
    status: Literal["confirmed", "contested", "developing", "unverified"]
    subjects: list[SubjectRef] = Field(default_factory=list)
    evidence: EvidenceSet
    coverage: CoverageSummary
    freshness: DataFreshness
    technical: TechnicalAnnex | None = None


class BriefingResponse(_StrictBase):
    """Briefing 页整体响应：新鲜度语义 + 有限变化队列（阶段 1 类型真源）。"""

    freshness: DataFreshness
    changes: list[ChangeBrief] = Field(default_factory=list)
