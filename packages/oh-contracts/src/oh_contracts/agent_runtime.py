"""交互层契约（Clean-slate Phase 1）：全局 Agent Runtime。

- 一个 Runtime（Research Orchestrator）+ 可组合 Workflow；四页各一套 Agent 的结构废弃。
- AgentRun 记录 model/prompt_version/token/工具/错误，可审计。
- 所有写操作经 HITLRequest 结构化确认。
"""

from typing import Literal

from pydantic import Field, field_validator

from .strict import NonEmptyStr, _StrictBase

Workspace = Literal["observe", "cases", "sources", "monitors", "archive", "settings"]
WorkflowName = Literal[
    "CreateCase",
    "DissectDocument",
    "NormalizeLanguage",
    "CompareSources",
    "BuildReport",
    "ChallengeClaim",
    "DraftSourceSpec",
    "CreateMonitor",
    "ReviewMonitorUpdate",
    "CommitArtifact",
    "ComposePressEdition",
]
AgentRunStatus = Literal["queued", "running", "awaiting_hitl", "succeeded", "failed", "cancelled"]
HITLAction = Literal[
    "commit_artifact",
    "draft_source_spec",
    "enable_collection_plan",
    "start_backfill",
    "delete_object",
    "create_case",
    "update_monitor",
]
HITLStatus = Literal["proposed", "awaiting_user", "approved", "rejected", "expired"]

WORKFLOWS: tuple[WorkflowName, ...] = (
    "CreateCase",
    "DissectDocument",
    "NormalizeLanguage",
    "CompareSources",
    "BuildReport",
    "ChallengeClaim",
    "DraftSourceSpec",
    "CreateMonitor",
    "ReviewMonitorUpdate",
    "CommitArtifact",
    "ComposePressEdition",
)


class PlanStep(_StrictBase):
    """研究计划单步（Parent 规划输出）；kind 属 WorkflowName 闭集。"""

    step_id: NonEmptyStr
    kind: WorkflowName
    title: NonEmptyStr
    rationale: str = ""

    @field_validator("kind")
    @classmethod
    def _kind_in_closed_set(cls, value: WorkflowName) -> WorkflowName:
        """显式闭集校验（Literal 之外的运行时兜底，报错信息可读）。"""
        if value not in WORKFLOWS:
            raise ValueError(f"kind 必须属于 WORKFLOWS 闭集，收到: {value!r}")
        return value


class PlanOut(_StrictBase):
    """Parent 研究计划（LLM 结构化输出契约；空 steps = 诚实弃权）。"""

    steps: list[PlanStep] = []


class WorkspaceContext(_StrictBase):
    """发送给模型的上下文包；用户可见、可裁剪（Dock 内展示）。"""

    workspace: Workspace
    case_id: str | None = None
    monitor_id: str | None = None
    artifact_id: str | None = None
    selection: str = ""
    lens: str = ""
    window: str = ""
    extra_refs: list[str] = []


class AgentThread(_StrictBase):
    """对话线程（按 case/workspace 归档；同一会话系统贯穿全部工作空间）。"""

    thread_id: str
    case_id: str | None = None
    title: str = ""
    created_at: str


class ToolCall(_StrictBase):
    """一次工具调用（经 Tool Gateway，禁止裸表读取）。"""

    call_id: str
    run_id: str
    tool: NonEmptyStr
    ok: bool = True
    latency_ms: int = 0
    error: str = ""


class HITLRequest(_StrictBase):
    """结构化人工确认卡：对象、版本、来源、影响范围。"""

    hitl_id: str
    run_id: str
    action: HITLAction
    payload: dict = Field(default_factory=dict)
    status: HITLStatus = "awaiting_user"
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""


class PromptVersion(_StrictBase):
    """Prompt 版本登记（system prompt hash 溯源）。"""

    prompt_id: str
    version: str
    system_prompt_hash: str = ""
    created_at: str


class ModelUsage(_StrictBase):
    """一次模型调用用量（供应商/模型/token/成本/时间）。"""

    usage_id: str
    run_id: str
    provider: str = ""
    model: str
    token_in: int = 0
    token_out: int = 0
    cost_usd: float = 0.0
    error: str = ""
    ts: str = ""


class AgentRun(_StrictBase):
    """一次有边界的执行；checkpoint 支持中断/恢复/fork。"""

    run_id: str
    thread_id: str
    workflow: WorkflowName
    status: AgentRunStatus = "queued"
    context: WorkspaceContext | None = None
    model: str = ""
    prompt_version: str = ""
    tool_call_ids: list[str] = []
    hitl_ids: list[str] = []
    checkpoint_ref: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
