"""SIGNAL：统一收敛对象（REDESIGN.md §7）。

所有确定性检测产出的变化，最终收敛为用户能理解的对象——
系统负责 Detect，Agent 负责 Understand，用户负责 Decide。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from oh_contracts.schemas import _Strict


class SignalKind(StrEnum):
    """信号种类：每个回答一个用户问题（REDESIGN §6/§7）。"""

    ATTENTION_SPIKE = "attention_spike"  # 注意力以多快速度聚集？
    NARRATIVE_SHIFT = "narrative_shift"  # 叙事与过去相比变了多少？
    NDI_ALERT = "ndi_alert"  # 不同信息源的讲述分歧是否显著？
    EXPECTATION_GAP = "expectation_gap"  # 官方与市场是否出现预期错位？


class Signal(_Strict):
    """统一信号：检测层唯一对外产物，前端 Today 页的原子。"""

    signal_id: str
    kind: SignalKind
    entity_id: str
    title: str  # 用户语言（如 "FED Narrative Shift"）
    what_changed: str  # 一句话：发生了什么变化
    why_it_matters: str | None = None  # 一句话：为什么值得关注
    metrics: dict[str, float] = Field(default_factory=dict)  # kind 相关数值
    strength: float = Field(ge=0, le=100)  # 重要性排序 0-100
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)  # 证据链入口；语义由 evidence_kind 决定
    # ids 元素类型（R0 断点修复：双语义显式化）
    evidence_kind: Literal["item_key", "event_id"] = "event_id"
    detected_at: datetime
    as_of: datetime  # PIT 锚：只用 as_of 及更早信息计算
    # —— RECONSTRUCTION C：Signal 主体语义与解释层（可选字段向后兼容）——
    subject_type: Literal["entity", "event", "topic", "narrative"] = "entity"
    subject_id: str | None = None  # 缺省=entity_id
    novelty_score: float | None = Field(default=None, ge=0, le=1)
    persistence_score: float | None = Field(default=None, ge=0, le=1)
    baseline: float | None = None  # 检测基线值（解释层折叠用）
    current_value: float | None = None  # 当前值
