"""Watch 追踪闭环契约（阶段 3）：WatchUpdate = 自上次认知以来的增量。

核心语义（纲领阶段 3）：
- 「让用户有明确返回理由」：WatchUpdate 必须回答「自上次查看/判断以来发生了什么」，
  而不是罗列最新内容。
- 「查看 ≠ 复核」：计算 WatchUpdate 不产生任何写回；用户显式确认「已复核」
  才推进 last_checked_at（Review Judgment 语义）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from oh_contracts.briefing import ChangeBrief, DataFreshness
from oh_contracts.strict import HeadlineStr, NonEmptyStr, _StrictBase

WatchKind = Literal["entity", "topic", "question"]


class WatchUpdate(_StrictBase):
    """单条 watch 的增量视图（阶段 3：自上次认知快照以来的变化）。

    - entity 类型：new_changes 携带新 ChangeBrief 队列（可下钻 /changes/{id}）；
    - topic 类型：new_articles 给出窗口内命中计数；
    - question 类型：v1 不做增量计算，note 说明（诚实边界）。
    """

    watch_id: NonEmptyStr
    kind: WatchKind
    query: NonEmptyStr
    since: str | None = None
    """增量起点（max(上次复核, 最新判断时间)；None = 从未有基线，全量为新）。"""
    has_changes: bool
    summary: HeadlineStr
    """人话总结：「自 X 以来有 N 件新变化」/「自上次查看以来没有新变化」。"""
    review_hint: str = ""
    """复核提示：有新变化且存在历史判断时提示建议复核判断。"""
    freshness: DataFreshness | None = None
    new_changes: list[ChangeBrief] = Field(default_factory=list)
    new_articles: int | None = None
    note: str = ""
    """类型边界说明（如 question 类型 v1 不支持增量）。"""


class WatchReview(_StrictBase):
    """复核确认回执：仅用户显式动作写入（Review Judgment）。"""

    watch_id: NonEmptyStr
    reviewed_at: str
    note: str = ""
