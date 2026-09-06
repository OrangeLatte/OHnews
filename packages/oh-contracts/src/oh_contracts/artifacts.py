"""档案层契约（Clean-slate Phase 1）：Artifact + ArtifactRevision + UserCommit。

原则：Archive 只保存用户明确 Commit 的版本；模型草稿永远不是正式档案。
旧 archive.AgentPaper（自动保存）不迁入本模型。
"""

from typing import Literal

from pydantic import Field

from .strict import NonEmptyStr, _StrictBase

ArtifactClass = Literal[
    "element_map",
    "research_report",
    "cross_source_analysis",
    "monitor_review",
    "press_edition",
]
ReportType = Literal[
    "veracity",
    "intent",
    "attribution",
    "narrative",
    "trend",
    "structured_summary",
    "econ_financial",
]

ARTIFACT_CLASSES: tuple[ArtifactClass, ...] = (
    "element_map",
    "research_report",
    "cross_source_analysis",
    "monitor_review",
    "press_edition",
)
REPORT_TYPES: tuple[ReportType, ...] = (
    "veracity",
    "intent",
    "attribution",
    "narrative",
    "trend",
    "structured_summary",
    "econ_financial",
)


class Artifact(_StrictBase):
    """档案对象（五种正式类型）；current 指向最近一次被 Commit 的版本。"""

    artifact_id: str
    case_id: str
    klass: ArtifactClass
    title: NonEmptyStr
    report_type: ReportType | None = None
    created_at: str
    current_revision_id: str | None = None


class ArtifactRevision(_StrictBase):
    """不可变版本。legacy=True 表示迁移自旧系统的只读结果（不可再追加）。"""

    revision_id: str
    artifact_id: str
    run_id: str = ""
    content: dict = Field(default_factory=dict)
    status: Literal["draft", "committed", "superseded"] = "draft"
    legacy: bool = False
    created_at: str


class UserCommit(_StrictBase):
    """用户明确接受并保存某版本的事件（HITL 产物；归档的唯一入口）。"""

    commit_id: str
    revision_id: str
    user_note: str = ""
    committed_at: str
    created_by: str = ""  # 确认者（v10 起；旧库迁移默认空串诚实降级）
