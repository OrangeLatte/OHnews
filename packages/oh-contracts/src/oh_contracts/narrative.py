"""情报本体重构层（RECONSTRUCTION §C）。

四层本体：Event(status) → Signal(subject/novelty/persistence) → Narrative → Insight。
本模块只放契约，不放逻辑；purity 测试强制零 IO。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from .schemas import _Strict
from .signals import Signal, SignalKind

__all__ = [
    "EventStatus",
    "EvidenceRole",
    "EvidenceStrength",
    "EvidenceItem",
    "EventAssessment",
    "NarrativeMomentum",
    "NarrativeStatement",
    "Insight",
    "SignalKind",
    "Signal",
]


class EventStatus(StrEnum):
    """事件验证状态（RECONSTRUCTION P6）：保守默认 unverified。"""

    CONFIRMED = "confirmed"  # ≥1 primary 佐证 + ≥3 独立源
    CONTESTED = "contested"  # primary 源之间立场冲突
    DEVELOPING = "developing"  # 多源报道但无 primary 佐证
    UNVERIFIED = "unverified"  # 样本不足（默认）


class EvidenceRole(StrEnum):
    """证据在情报层级中的角色（RECONSTRUCTION F-05）。"""

    PRIMARY = "primary"  # 官方一手（L1）
    SECONDARY = "secondary"  # 通讯社/权威二手（L2）
    COMMENTARY = "commentary"  # 市场评论与分析（L3）
    SOCIAL = "social"  # 社媒信号（L4）


class EvidenceStrength(StrEnum):
    """证据强度四档（RECONSTRUCTION P7/P8）：替代裸 confidence 直出。"""

    STRONG = "strong"
    MODERATE = "moderate"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"

    @property
    def score(self) -> float:
        """排名因子用数值（RECONSTRUCTION §H：Insufficient=0 → 门禁封顶）。"""
        return {"strong": 1.0, "moderate": 0.7, "limited": 0.4, "insufficient": 0.0}[self.value]


class EvidenceItem(_Strict):
    """单条证据：provenance 锚定 Bronze item_key，可回溯原文。"""

    item_key: str
    source_id: str
    role: EvidenceRole
    quote: str = Field(min_length=1, max_length=400)
    published_at: datetime


class EventAssessment(_Strict):
    """事件级情报评估（Event 页 07 段 + 首页卡同源）。"""

    event_id: str
    status: EventStatus
    confidence: float = Field(ge=0, le=1)
    evidence_strength: EvidenceStrength
    n_independent_sources: int = Field(ge=0)
    n_primary_sources: int = Field(ge=0)
    observation: str
    interpretation: str | None = None
    alternative_explanation: str | None = None
    what_to_watch_next: str | None = None
    engine: Literal["llm", "offline"] = "offline"


class NarrativeMomentum(StrEnum):
    """叙事动量。"""

    RISING = "rising"
    STEADY = "steady"
    FADING = "fading"


class NarrativeStatement(_Strict):
    """语义叙事对象（RECONSTRUCTION P4）：框架计数之上的人们在相信什么。"""

    narrative_id: str  # nar-{entity}-{window}，幂等
    statement: str = Field(min_length=8)
    entity_id: str
    event_ids: list[str] = Field(default_factory=list)
    supporting_item_keys: list[str] = Field(default_factory=list)  # provenance
    opposing_item_keys: list[str] = Field(default_factory=list)
    source_cluster: str  # "official" | "financial_press" | "social" | "mixed"
    momentum: NarrativeMomentum = NarrativeMomentum.STEADY
    confidence: float = Field(ge=0, le=1)
    divergence: float = Field(ge=0, le=1)  # 该叙事跨簇分歧
    first_seen: datetime
    window: str  # 如 "2026-W35" 或 "2026-08-24/30"
    engine: Literal["llm", "offline"] = "offline"


class Insight(_Strict):
    """最高层输出（RECONSTRUCTION P5）：五段强制，永不把指标当结论。"""

    insight_id: str
    headline: str = Field(min_length=8)
    observation: str = Field(min_length=8)
    interpretation: str
    evidence_strength: EvidenceStrength
    alternative_explanations: list[str] = Field(min_length=1)  # 强制 ≥1 条备择
    what_changed: str
    why_it_matters: str | None = None
    what_to_watch_next: str | None = None
    related_signal_ids: list[str] = Field(default_factory=list)
    related_event_ids: list[str] = Field(default_factory=list)
    related_narrative_ids: list[str] = Field(default_factory=list)
    intelligence_score: float = Field(ge=0, le=100)
    engine: Literal["llm", "offline"] = "offline"
    generated_at: datetime
    as_of: datetime  # PIT 锚
