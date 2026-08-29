"""Intent 与 Artifact 契约（REDESIGN_AGENT v3：Action-driven 非 Prompt-driven）。

Intent = GUI 动作的唯一入口（按钮 → Intent → Orchestrator）；
Artifact = Agent 结构化产物的唯一契约（Analyst 五层强制）；
ContextPacket = 结构化上下文（取代消息堆历史）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from oh_contracts.enums import SourceTier
from oh_contracts.schemas import _Strict


class IntentKind(StrEnum):
    """GUI 动作意图（REDESIGN_AGENT §Action-driven；CHALLENGE=触发式红队）。"""

    EXPLAIN_SIGNAL = "explain_signal"
    EXPLAIN_CAUSE = "explain_cause"
    COMPARE_NARRATIVES = "compare_narratives"
    SHOW_EVIDENCE = "show_evidence"
    START_INVESTIGATION = "start_investigation"
    CHALLENGE = "challenge"


class TargetKind(StrEnum):
    """Intent 作用对象的类型。"""

    SIGNAL = "signal"
    EVENT = "event"
    ENTITY = "entity"
    TOPIC = "topic"


class Intent(_Strict):
    """一次可执行的 Agent 调用请求（按钮 → Intent → Orchestrator）。"""

    intent: IntentKind
    target_kind: TargetKind
    target_id: str
    message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArtifactKind(StrEnum):
    """五类 Artifact（REDESIGN_AGENT §Artifact 契约）。"""

    ANALYSIS = "analysis"
    EVIDENCE = "evidence"
    COMPARISON = "comparison"
    HYPOTHESIS = "hypothesis"
    CHALLENGE = "challenge"


class AnalysisArtifact(_Strict):
    """Analyst 五层强制输出（Observation→Interpretation→Evidence→Alternative→Uncertainty）。

    观察层必须有内容；其余四层允许占位说明（离线降级时如实标注），
    但禁止整份为空——那是"看起来在分析"的幻觉输出。
    """

    kind: ArtifactKind = ArtifactKind.ANALYSIS
    target_id: str
    intent: IntentKind
    observation: str
    interpretation: str
    evidence: list[str] = Field(default_factory=list)
    alternative: str | None = None
    uncertainty: str | None = None
    engine: str = "offline"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _check_observation(self) -> AnalysisArtifact:
        if not self.observation.strip():
            raise ValueError("observation layer must not be empty")
        return self


class ContextPacket(_Strict):
    """结构化上下文包（取代消息堆历史；Orchestrator 组装，Agent 只读）。

    全部字段是确定性快照（Signal/事件/NDI/stance/证据引用），
    Agent 不自行拼历史——跨轮记忆仍由 ChatStore 承担。
    """

    intent: IntentKind
    target_kind: TargetKind
    target_id: str
    entity_id: str | None = None
    signal: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    ndi_points: list[dict[str, Any]] = Field(default_factory=list)
    stances: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def summary_text(self) -> str:
        """渲染为注入 prompt 的结构化文本（What changed / Why / 数据线）。"""
        lines: list[str] = [
            f"Intent: {self.intent.value}",
            f"Target: {self.target_kind.value}:{self.target_id}",
        ]
        if self.signal:
            lines.append(
                f"Signal: {self.signal.get('title', '')} (strength={self.signal.get('strength')})"
            )
            wc = self.signal.get("what_changed")
            wm = self.signal.get("why_it_matters")
            if wc:
                lines.append(f"What changed: {wc}")
            if wm:
                lines.append(f"Why it matters: {wm}")
        if self.event:
            lines.append(
                f"Event: {self.event.get('title', '')} as_of={self.event.get('as_of', '')}"
            )
        if self.ndi_points:
            latest = self.ndi_points[-1]
            lines.append(
                f"NDI latest: {latest.get('ndi')} "
                f"(status={latest.get('status')}, n_sources={latest.get('n_sources')})"
            )
        if self.stances:
            official = [s for s in self.stances if s.get("tier") == SourceTier.OFFICIAL.value]
            lines.append(f"Stance rows: {len(self.stances)} (official={len(official)})")
        for n in self.notes:
            lines.append(f"Note: {n}")
        return "\n".join(lines)
