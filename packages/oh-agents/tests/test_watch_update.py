"""WatchUpdate 计算器测试（阶段 3）。"""

from __future__ import annotations

from datetime import UTC, datetime

from oh_agents.beliefs import BeliefStore
from oh_agents.watch import Watch
from oh_agents.watch_update import compute_watch_update
from oh_contracts.briefing import ChangeBrief, DataFreshness
from oh_contracts.watching import WatchKind

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _fresh() -> DataFreshness:
    return DataFreshness(
        as_of="2026-08-30T08:15:00+00:00",
        coverage_start="2026-08-27T00:00:00+00:00",
        staleness="aging",
        note="数据覆盖 8 月 27 日至 30 日",
    )


def _brief(subject_id: str = "fed") -> ChangeBrief:
    return ChangeBrief(
        change_id="sig-shift-fed-20260831",
        kind="narrative_shift",
        headline="美联储叙事出现转变",
        what="市场报道框架从损失转向收益",
        why_now="近三日报道框架占比发生明显迁移",
        strength_word="notable",
        urgency="medium",
        subjects=[{"kind": "entity", "id": subject_id, "label": "美联储"}],
    )


def _briefing(*changes: ChangeBrief) -> object:
    from oh_contracts.briefing import BriefingResponse

    return BriefingResponse(freshness=_fresh(), changes=list(changes))


def test_entity_watch_picks_subject_changes() -> None:
    w = Watch("watch-1", "entity", "fed", NOW.isoformat(), None, None)
    u = compute_watch_update(w, _briefing(_brief("fed"), _brief("pboc")), now=NOW)  # type: ignore[arg-type]
    assert u.kind == "entity"
    assert u.has_changes
    assert len(u.new_changes) == 1
    assert u.new_changes[0].subjects[0].id == "fed"
    assert "1 件新变化" in u.summary


def test_entity_watch_no_changes_summary() -> None:
    w = Watch("watch-1", "entity", "boj", NOW.isoformat(), None, None)
    u = compute_watch_update(w, _briefing(_brief("fed")), now=NOW)  # type: ignore[arg-type]
    assert not u.has_changes
    assert u.new_changes == []
    assert "没有新变化" in u.summary
    assert u.review_hint == ""


def test_belief_baseline_drives_review_hint() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        beliefs = BeliefStore(Path(d) / "b.sqlite")
        from oh_contracts.belief import BeliefSnapshot

        beliefs.save(
            BeliefSnapshot(
                snapshot_id="bs-test0001",
                change_id="sig-shift-fed-20260831",
                subject_id="fed",
                subject_label="美联储",
                stance="maintain",
                confidence=0.6,
                rationale="先维持观察",
                change_type="new",
                believed_at="2026-08-31T09:00:00+00:00",
            )
        )
        w = Watch("watch-1", "entity", "fed", NOW.isoformat(), None, None)
        u = compute_watch_update(w, _briefing(_brief("fed")), beliefs=beliefs, now=NOW)  # type: ignore[arg-type]
        assert u.since == "2026-08-31T09:00:00+00:00"
        assert "建议复核" in u.review_hint


def test_topic_watch_counts() -> None:
    w = Watch("watch-2", "topic", "关税", NOW.isoformat(), None, None)
    u = compute_watch_update(w, _briefing(), now=NOW, topic_hits=3)  # type: ignore[arg-type]
    assert u.kind == "topic"
    assert u.has_changes
    assert u.new_articles == 3
    assert "3 篇相关报道" in u.summary


def test_question_watch_honest_boundary() -> None:
    w = Watch("watch-3", "question", "美联储是否会转向", NOW.isoformat(), None, None)
    u = compute_watch_update(w, _briefing(), now=NOW)  # type: ignore[arg-type]
    assert u.kind == "question"
    assert not u.has_changes
    assert u.note != ""
    assert "暂不支持" in u.summary


def test_kinds_covered() -> None:
    assert set(WatchKind.__args__) == {"entity", "topic", "question"}
