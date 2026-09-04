"""研究层契约（Clean-slate Phase 1）：ResearchCase 中心对象。

不变量（OHNEWS_PHASE0_CLEANROOM_DESIGN.md 交付物 2）：
- document_revision_id 是分析引用的最小锚（防证据漂移）。
- Claim 必须能 ≤2 操作回跳 EvidenceSpan。
- 时间戳由调用方传入（零 IO 纪律）。
"""

from typing import Literal

from pydantic import Field, model_validator

from .dissection import ElementKey
from .enums import ClaimKind
from .strict import NonEmptyStr, _StrictBase

CaseStatus = Literal["candidate", "active", "needs_attention", "suspended", "closed", "rejected"]
CaseOrigin = Literal["observe", "article", "question", "watch_candidate", "agent_suggested"]
ClaimReview = Literal["unverified", "supported", "refuted", "uncertain"]
SpanPolarity = Literal["supports", "refutes", "context"]
HumanStatus = Literal["unreviewed", "accepted", "revised", "rejected"]
RunKind = Literal["dissect", "translate", "compare", "report", "challenge", "commit_check"]
RunStatus = Literal[
    "queued",
    "planning",
    "running",
    "awaiting_hitl",
    "succeeded",
    "abstained",
    "failed",
    "cancelled",
]

CASE_STATUSES: tuple[CaseStatus, ...] = (
    "candidate",
    "active",
    "needs_attention",
    "suspended",
    "closed",
    "rejected",
)
RUN_KINDS: tuple[RunKind, ...] = (
    "dissect",
    "translate",
    "compare",
    "report",
    "challenge",
    "commit_check",
)


class ResearchCase(_StrictBase):
    """一个正在被理解的现实变化/研究问题；产品中心对象。"""

    case_id: str
    title: str = ""
    question: NonEmptyStr
    status: CaseStatus = "candidate"
    origin: CaseOrigin = "question"
    context_note: str = ""
    created_by: Literal["user", "agent", "watch"] = "user"
    created_at: str
    updated_at: str
    closed_at: str | None = None


class EvidenceSpan(_StrictBase):
    """原文中的精确证据片段（字符偏移锚定，永不覆盖原文）。"""

    span_id: str
    document_revision_id: str
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    quote: str
    polarity: SpanPolarity = "supports"

    @model_validator(mode="after")
    def _end_after_start(self) -> "EvidenceSpan":
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        return self


class Claim(_StrictBase):
    """可被支持或反驳的陈述；绑定证据片段。"""

    claim_id: str
    case_id: str
    statement: NonEmptyStr
    kind: ClaimKind
    status: ClaimReview = "unverified"
    span_ids: list[str] = []
    created_by: Literal["user", "agent"] = "agent"
    created_at: str


class ElementExtraction(_StrictBase):
    """十八项拆解之一（引用具体 document_revision + analysis_run，可版本化）。"""

    extraction_id: str
    case_id: str = ""
    document_revision_id: str
    element_key: ElementKey
    normalized_value: str = ""
    span_ids: list[str] = []
    confidence: float = Field(default=0.0, ge=0, le=1)
    uncertainty_reason: str = ""
    analysis_run_id: str = ""
    human_status: HumanStatus = "unreviewed"


class ComparisonSet(_StrictBase):
    """一组可比较的跨源/跨语言文档（比较中间层为 comparison_en 副本）。"""

    comparison_id: str
    case_id: str
    document_revision_ids: list[str] = Field(min_length=2)
    created_at: str
    note: str = ""


class AnalysisRun(_StrictBase):
    """一次模型或规则分析运行（不可变；重跑产生新 run_id）。"""

    run_id: str
    case_id: str
    kind: RunKind
    engine: Literal["llm", "rule", "stats"] = "llm"
    model: str = ""
    prompt_version: str = ""
    status: RunStatus = "queued"
    input_refs: list[str] = []
    output_artifact_id: str | None = None
    token_in: int = 0
    token_out: int = 0
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
