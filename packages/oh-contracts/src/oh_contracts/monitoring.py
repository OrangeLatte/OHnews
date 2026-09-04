"""持续监测层契约（Clean-slate Phase 1）：Monitor 与 Collection。

- Monitor 统一取代 watches/tracking/alerts 三套旧模型。
- MonitorUpdate 只回答"自上次用户确认快照以来发生了什么"。
- CollectionPlan/CollectionRun 是确定性 ETL 的调度对象；LLM 不得进入执行链。
"""

from typing import Literal

from pydantic import Field

from .strict import NonEmptyStr, _StrictBase

MonitorTarget = Literal[
    "case",
    "entity",
    "topic",
    "question",
    "article",
    "claim",
    "stance",
    "sentiment",
    "action",
    "element",
]
MonitorStatus = Literal["active", "paused", "closed", "needs_review"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
CollectionMode = Literal["realtime", "scheduled", "backfill"]

MONITOR_TARGETS: tuple[MonitorTarget, ...] = (
    "case",
    "entity",
    "topic",
    "question",
    "article",
    "claim",
    "stance",
    "sentiment",
    "action",
    "element",
)


class Monitor(_StrictBase):
    """持续追踪任务：对象 + 问题 + 触发 + 频率 + 通知 + 上次确认快照。"""

    monitor_id: str
    target_type: MonitorTarget
    target_ref: str
    question: NonEmptyStr
    trigger_conditions: list[str] = []
    window: str = "7d"
    schedule: str = "6h"
    status: MonitorStatus = "active"
    notification: str = "in_app"
    last_confirmed_snapshot_at: str | None = None
    case_id: str | None = None
    created_by: Literal["user", "agent"] = "user"
    created_at: str


class MonitorRun(_StrictBase):
    """一次监测执行（确定性检查 + 可选模型摘要）。"""

    run_id: str
    monitor_id: str
    status: RunStatus = "queued"
    started_at: str = ""
    finished_at: str = ""
    error: str = ""


class MonitorUpdate(_StrictBase):
    """自上次用户确认快照以来的增量；reviewed=False 时仅出现在待复核队列。"""

    update_id: str
    run_id: str
    monitor_id: str
    summary: NonEmptyStr
    delta: dict = Field(default_factory=dict)
    evidence_refs: list[str] = []
    suggested_case_action: Literal["none", "new_candidate", "join_existing"] = "none"
    reviewed: bool = False
    created_at: str


class CollectionPlan(_StrictBase):
    """信源采集计划（realtime/scheduled/backfill）；启用需 HITL。"""

    plan_id: str
    source_ids: list[str] = Field(min_length=1)
    mode: CollectionMode = "scheduled"
    schedule: str = ""
    time_range: str = ""
    enabled: bool = False
    created_by: Literal["user", "agent"] = "user"
    created_at: str


class CollectionRun(_StrictBase):
    """一次采集执行及结果（进度/产出/失败/重试由 runner 写入）。"""

    run_id: str
    plan_id: str
    status: RunStatus = "queued"
    progress: float = Field(default=0.0, ge=0, le=1)
    items_collected: int = 0
    last_error: str = ""
    started_at: str = ""
    finished_at: str = ""
