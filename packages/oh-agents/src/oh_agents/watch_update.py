"""WatchUpdate 计算器（阶段 3）：自上次认知以来的增量，查看不写回。

语义（纲领阶段 3）：
- since = max(上次复核时间, 该主体最新判断 believed_at)——判断刷新认知基线；
- entity：重跑 detect_signals 过滤该实体 → 新 ChangeBrief 队列（可下钻）；
- topic：bronze 标题/正文命中计数（窗口内、since 之后）；
- question：v1 不做增量（诚实 note），不伪装成空结果。
- 本模块只读：任何写回（last_checked_at）仅由显式 review 动作触发。
"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_contracts.briefing import BriefingResponse, ChangeBrief
from oh_contracts.watching import WatchUpdate

from oh_agents.beliefs import BeliefStore
from oh_agents.watch import Watch


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(ts: str | datetime | None) -> datetime | None:
    if ts is None or isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _latest_belief_at(beliefs: BeliefStore | None, subject_id: str) -> datetime | None:
    if beliefs is None:
        return None
    snaps = beliefs.timeline(subject_id)
    if not snaps:
        return None
    return _parse(snaps[-1].believed_at)


def _summary_for(new_changes: list[ChangeBrief], since_label: str) -> str:
    n = len(new_changes)
    if n == 0:
        return f"自{since_label}以来没有新变化"
    first = new_changes[0].headline
    return f"自{since_label}以来有 {n} 件新变化，最新：「{first}」"


def _since_label(since: datetime | None, now: datetime) -> str:
    if since is None:
        return "上次查看"
    days = (now - since).days
    if days <= 0:
        return "上次查看"
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def compute_watch_update(
    watch: Watch,
    briefing: BriefingResponse,
    *,
    beliefs: BeliefStore | None = None,
    now: datetime,
    topic_hits: int | None = None,
) -> WatchUpdate:
    """从 BriefingResponse 派生单条 watch 的增量视图（只读，不写回）。

    - entity：briefing.changes 里 subjects 命中 query（entity_id）的新变化；
    - topic：topic_hits（调用方计数，窗口语义由调用方保证）；
    - question：v1 边界 note。
    since 语义：max(上次复核, 该主体最新判断时间)——判断刷新认知基线。
    """
    checked_at = _parse(watch.last_checked_at)
    believed_at = _latest_belief_at(beliefs, watch.query) if watch.type == "entity" else None
    candidates = [t for t in (checked_at, believed_at) if t is not None]
    since = max(candidates) if candidates else None
    label = _since_label(since, now)

    if watch.type == "entity":
        # v1 局限（诚实标注）：ChangeBrief 无独立时间字段，无法逐条判「已见」；
        # detect_signals 本身 PIT 只看 now 窗口，故 briefing.changes 即当前窗口变化。
        # since 用于措辞与复核提示；逐条 seen 去重将随契约加 as_of 字段后收紧。
        new = [c for c in briefing.changes if any(s.id == watch.query for s in c.subjects)]
        has = len(new) > 0
        hint = ""
        if has and believed_at is not None:
            hint = "上次判断之后出现了新变化，建议复核你的判断。"
        return WatchUpdate(
            watch_id=watch.watch_id,
            kind="entity",
            query=watch.query,
            since=_iso(since) if since else None,
            has_changes=has,
            summary=_summary_for(new, label),
            review_hint=hint,
            freshness=briefing.freshness,
            new_changes=new,
        )

    if watch.type == "topic":
        n = topic_hits or 0
        return WatchUpdate(
            watch_id=watch.watch_id,
            kind="topic",
            query=watch.query,
            since=_iso(since) if since else None,
            has_changes=n > 0,
            summary=f"自{label}以来有 {n} 篇相关报道" if n else f"自{label}以来没有新报道",
            freshness=briefing.freshness,
            new_articles=n,
        )

    return WatchUpdate(
        watch_id=watch.watch_id,
        kind="question",
        query=watch.query,
        since=_iso(since) if since else None,
        has_changes=False,
        summary="问题型订阅暂不支持增量比较",
        note="v1 边界：question 订阅的增量比较将在 Agent 嵌入阶段（阶段 4）接入。",
        freshness=briefing.freshness,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
