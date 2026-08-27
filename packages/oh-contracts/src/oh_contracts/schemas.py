"""全局 Pydantic v2 契约（extra='forbid' 严格 schema，ai-hedge-fund 契约模式）。

时间字段一律 tz-aware datetime（UTC）；序列化到 SQLite/Parquet 时统一 isoformat。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from oh_contracts.enums import (
    ClaimKind,
    EpistemicStatus,
    ExtractionEngine,
    FrameLabel,
    SourceTier,
    SSEEvent,
    StanceLabel,
)


class _Strict(BaseModel):
    """公共基类：禁止未知字段、实例不可变（契约即契约）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceMeta(_Strict):
    """信源元数据（裁决 C SourceAdapter.describe 的契约面；蓝图 §6 图3）。"""

    source_id: str
    language: Literal["zh", "en", "de", "fr", "it"]
    tier: SourceTier
    credibility_prior: float = Field(ge=0.0, le=1.0)
    bias: str | None = None
    rate_limit_rpm: int = Field(default=30, ge=1)
    needs_browser: bool = False
    paywall: bool = False


class BronzeRecord(_Strict):
    """Bronze 层原始记录（裁决 C：item_key=(source, external_id, ts) 幂等主键）。"""

    source_id: str
    item_key: str
    external_id: str
    url_hash: str
    content_hash: str
    fetched_at: datetime
    published_at: datetime | None = None
    raw: dict[str, Any]
    normalized: dict[str, Any] = Field(default_factory=dict)


class EventRecord(_Strict):
    """Silver 层事件（as_of 为 PIT 锚点：一切下游指标只用 as_of 之前信息）。"""

    event_id: str
    title: str
    summary: str = ""
    entities: list[str] = Field(default_factory=list)
    as_of: datetime
    first_seen: datetime | None = None


class StanceRow(_Strict):
    """Silver 层立场行（裁决 A 不变量：NDI 唯一数据来源）。

    由 Tagger 分层路由产出：规则 85% / 小模型 10% / LLM 5%，
    携带 calibrated confidence 与 engine 标注；ABSTAIN 行不进分布计算。
    """

    event_id: str
    source_id: str
    entity_id: str
    frame: FrameLabel
    stance: StanceLabel
    confidence: float = Field(ge=0.0, le=1.0)
    engine: ExtractionEngine
    item_key: str
    ts: datetime


class Evidence(_Strict):
    """证据链叶子：claim → 原文（quote + 偏移 + 发布时间 + 信源）。"""

    source_id: str
    url: str
    published_at: datetime
    quote: str
    offset: int | None = None


class Claim(_Strict):
    """声明（裁决 H：仅事实性 claim 计算真实性 T；观点性 claim 产 FramingScore）。"""

    claim_id: str
    text: str
    kind: ClaimKind
    evidence: list[Evidence] = Field(default_factory=list)
    t_score: float | None = None


class Hypothesis(_Strict):
    """LLM 假设（裁决 A：hypothesis_gen 只读输出，永不写回 NDI）。"""

    event_id: str
    text: str
    drivers: list[str] = Field(default_factory=list)
    cite: list[str] = Field(default_factory=list)


class NarrativeCard(_Strict):
    """证据解释卡（evidence_interpreter 输出；认知状态强制标注）。"""

    event_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    epistemic_status: EpistemicStatus
    narrative: str


class NDIPoint(_Strict):
    """Gold 层叙事分歧指数点位（status=abstain 时 ndi/ci 必为 None）。

    language：within-language 管线标识（裁决 F：Phase 1 zh / Phase 2 en，
    跨语言二级叠加属 Phase 7 门禁；"all" = 未分语言的历史混算，向后兼容）。
    """

    event_id: str
    ts: datetime
    ndi: float | None = Field(default=None, ge=0.0, le=1.0)
    ci_low: float | None = None
    ci_high: float | None = None
    n_sources: int = Field(ge=0)
    status: Literal["ok", "abstain"]
    language: str = "all"

    def model_post_init(self, __context: Any) -> None:
        if self.status == "abstain" and self.ndi is not None:
            raise ValueError("abstain 点位不得携带 ndi 数值")


class SSEMessage(_Strict):
    """SSE 事件信封（进程内 asyncio 总线 → Web；Last-Event-ID 按 seq 重放）。"""

    run_id: str
    seq: int = Field(ge=0)
    event: SSEEvent
    node: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
