"""ResearchStore 测试：schema 幂等、Case 生命周期、Commit 事务、Monitor 增量、HITL。"""

from __future__ import annotations

from pathlib import Path

import pytest
from oh_contracts.agent_runtime import AgentRun, AgentThread, HITLRequest, ToolCall
from oh_contracts.artifacts import Artifact, ArtifactRevision, UserCommit
from oh_contracts.case import (
    AnalysisRun,
    Claim,
    ComparisonSet,
    ElementExtraction,
    EvidenceSpan,
    ResearchCase,
)
from oh_contracts.monitoring import (
    CollectionPlan,
    CollectionRun,
    Monitor,
    MonitorRun,
    MonitorUpdate,
)
from oh_storage.research_store import ResearchStore


@pytest.fixture()
def store(tmp_path: Path) -> ResearchStore:
    return ResearchStore.open(tmp_path / "research.sqlite")


T0 = "2026-09-03T00:00:00+00:00"
T1 = "2026-09-03T01:00:00+00:00"
T2 = "2026-09-03T02:00:00+00:00"


def _case(case_id: str = "case-1") -> ResearchCase:
    return ResearchCase(
        case_id=case_id,
        question="美联储叙事是否转向？",
        origin="observe",
        created_at=T0,
        updated_at=T0,
    )


def _revision(store: ResearchStore, revision_id: str = "rev-1") -> None:
    store.add_document_revision(
        revision_id,
        "doc-1",
        source_id="wallstreetcn",
        body="央行暗示可能在明年调整利率路径。",
        fetched_at=T0,
        content_hash="c:abc",
        language="zh",
    )


def test_schema_ensure_idempotent(store: ResearchStore) -> None:
    assert store.ensure_schema() == 6
    assert store.ensure_schema() == 6


def test_case_lifecycle(store: ResearchStore) -> None:
    store.create_case(_case())
    got = store.get_case("case-1")
    assert got is not None and got.status == "candidate"

    assert store.update_case_status("case-1", "active", updated_at=T1)
    assert store.get_case("case-1").status == "active"  # type: ignore[union-attr]

    assert store.update_case_status("case-1", "closed", updated_at=T2, closed_at=T2)
    closed = store.get_case("case-1")
    assert closed is not None and closed.closed_at == T2

    assert not store.update_case_status("nope", "active", updated_at=T1)


def test_document_revision_immutable(store: ResearchStore) -> None:
    _revision(store, "rev-1")
    with pytest.raises(ValueError, match="conflict"):
        _revision(store, "rev-1")
    body = store.get_document_revision("rev-1")
    assert body is not None and "利率路径" in body["body"]


def test_claim_with_spans(store: ResearchStore) -> None:
    store.create_case(_case())
    _revision(store)
    store.add_span(
        EvidenceSpan(
            span_id="span-1",
            document_revision_id="rev-1",
            char_start=0,
            char_end=5,
            quote="央行暗示",
            polarity="supports",
        )
    )
    store.add_claim(
        Claim(
            claim_id="claim-1",
            case_id="case-1",
            statement="央行释放宽松信号",
            kind="factual",
            span_ids=["span-1"],
            created_at=T1,
        )
    )
    claims = store.claims_for_case("case-1")
    assert len(claims) == 1
    spans = store.spans_by_ids(claims[0].span_ids)
    assert len(spans) == 1 and spans[0].quote == "央行暗示"


def test_extraction_review(store: ResearchStore) -> None:
    _revision(store)
    store.add_extraction(
        ElementExtraction(
            extraction_id="ext-1",
            document_revision_id="rev-1",
            element_key="explicit_stance",
            normalized_value="中性偏宽松",
            confidence=0.82,
            analysis_run_id="run-1",
        )
    )
    rows = store.extractions_for_revision("rev-1")
    assert rows[0]["human_status"] == "unreviewed"
    assert store.set_extraction_human_status("ext-1", "accepted")
    assert store.extractions_for_revision("rev-1")[0]["human_status"] == "accepted"


def test_comparison_set(store: ResearchStore) -> None:
    store.create_case(_case())
    store.add_comparison(
        ComparisonSet(
            comparison_id="cmp-1",
            case_id="case-1",
            document_revision_ids=["rev-1", "rev-2"],
            created_at=T0,
        )
    )
    with pytest.raises(ValueError, match="at least 2 items"):
        ComparisonSet(
            comparison_id="cmp-2",
            case_id="case-1",
            document_revision_ids=["rev-1"],
            created_at=T0,
        )


def test_analysis_run_flow(store: ResearchStore) -> None:
    store.create_case(_case())
    store.add_analysis_run(
        AnalysisRun(
            run_id="run-1",
            case_id="case-1",
            kind="dissect",
            model="zhipu/glm-5.3",
            prompt_version="dissect@1",
            input_refs=["rev-1"],
            started_at=T0,
        )
    )
    store.finish_analysis_run(
        "run-1", status="succeeded", token_in=1200, token_out=800, finished_at=T1
    )
    run = store.get_analysis_run("run-1")
    assert run is not None
    assert run["status"] == "succeeded" and run["token_out"] == 800


def test_artifact_commit_transaction(store: ResearchStore) -> None:
    """draft → commit v1 → commit v2：指针置换 + 旧版 superseded + UserCommit 记录。"""
    store.create_case(_case())
    store.create_artifact(
        Artifact(
            artifact_id="art-1",
            case_id="case-1",
            klass="research_report",
            title="美联储叙事研判",
            report_type="econ_financial",
            created_at=T0,
        )
    )
    store.add_artifact_revision(
        ArtifactRevision(revision_id="r1", artifact_id="art-1", content={"v": 1}, created_at=T0)
    )
    store.add_artifact_revision(
        ArtifactRevision(revision_id="r2", artifact_id="art-1", content={"v": 2}, created_at=T1)
    )
    result = store.commit_revision(
        "r1", UserCommit(commit_id="c1", revision_id="r1", committed_at=T1, user_note="初版")
    )
    assert result["artifact_id"] == "art-1"
    assert store.archive_list()[0]["title"] == "美联储叙事研判"

    result2 = store.commit_revision(
        "r2", UserCommit(commit_id="c2", revision_id="r2", committed_at=T2)
    )
    assert result2["superseded_revision_id"] == "r1"
    revs = {r["revision_id"]: r for r in store.artifact_revisions("art-1")}
    assert revs["r1"]["status"] == "superseded"
    assert revs["r2"]["status"] == "committed"
    assert len(store.archive_list()) == 1
    with pytest.raises(KeyError):
        store.commit_revision(
            "ghost", UserCommit(commit_id="x", revision_id="ghost", committed_at=T2)
        )


def test_archive_excludes_draft(store: ResearchStore) -> None:
    store.create_case(_case())
    store.create_artifact(
        Artifact(
            artifact_id="art-2",
            case_id="case-1",
            klass="element_map",
            title="仅有草稿",
            created_at=T0,
        )
    )
    store.add_artifact_revision(
        ArtifactRevision(revision_id="d1", artifact_id="art-2", content={}, created_at=T0)
    )
    assert store.archive_list() == []


def test_monitor_update_increment(store: ResearchStore) -> None:
    store.create_monitor(
        Monitor(
            monitor_id="mon-1",
            target_type="case",
            target_ref="case-1",
            question="分歧是否扩大",
            trigger_conditions=["ndi_slope>0.5"],
            created_at=T0,
        )
    )
    store.add_monitor_run(
        MonitorRun(run_id="mrun-1", monitor_id="mon-1", status="succeeded", started_at=T1)
    )
    store.add_monitor_update(
        MonitorUpdate(
            update_id="upd-1",
            run_id="mrun-1",
            monitor_id="mon-1",
            summary="自快照以来新增 12 篇、NDI +0.4σ",
            delta={"new_articles": 12},
            suggested_case_action="join_existing",
            created_at=T1,
        )
    )
    assert len(store.pending_updates("mon-1")) == 1
    store.mark_update_reviewed("upd-1")
    assert store.pending_updates("mon-1") == []
    assert store.confirm_monitor_snapshot("mon-1", T2)
    assert store.list_monitors()[0].last_confirmed_snapshot_at == T2


def test_hitl_flow(store: ResearchStore) -> None:
    store.create_thread(AgentThread(thread_id="th-1", created_at=T0))
    store.add_agent_run(
        AgentRun(run_id="arun-1", thread_id="th-1", workflow="CommitArtifact", started_at=T0)
    )
    store.add_tool_call(
        ToolCall(call_id="tc-1", run_id="arun-1", tool="artifacts.commit", latency_ms=12)
    )
    store.create_hitl(
        HITLRequest(
            hitl_id="h-1",
            run_id="arun-1",
            action="commit_artifact",
            payload={"revision_id": "r2"},
        )
    )
    assert len(store.pending_hitl()) == 1
    assert store.decide_hitl("h-1", status="approved", decided_by="user", decided_at=T1)
    assert store.pending_hitl() == []
    store.finish_agent_run("arun-1", status="succeeded", finished_at=T1)


def test_counts(store: ResearchStore) -> None:
    store.create_case(_case())
    counts = store.counts()
    assert counts["cases"] == 1 and counts["claims"] == 0


def test_case_documents_link_and_list(tmp_path):
    store = ResearchStore.open(tmp_path / "r2.sqlite")
    store.create_case(_case("case-doc"))
    store.add_document_revision("drv-1", "doc-9", source_id="s", body="b", fetched_at="t")
    store.link_case_document("case-doc", "drv-1", "2026-09-03T00:00:00+00:00")
    store.link_case_document("case-doc", "drv-1", "2026-09-03T00:00:00+00:00")  # 幂等
    rows = store.case_documents("case-doc")
    assert len(rows) == 1 and rows[0]["document_revision_id"] == "drv-1"
    assert store.case_documents("case-x") == []


def test_collection_plans_and_runs(tmp_path) -> None:
    store = ResearchStore.open(tmp_path / "r3.sqlite")
    now = "2026-09-03T00:00:00+00:00"
    plan = CollectionPlan(
        plan_id="plan-1",
        source_ids=["reuters", "ft_com"],
        mode="scheduled",
        schedule="6h",
        enabled=False,
        created_at=now,
    )
    store.create_collection_plan(plan)
    assert [p.plan_id for p in store.list_plans()] == ["plan-1"]
    assert store.set_plan_enabled("plan-1", True)
    assert not store.set_plan_enabled("plan-nope", True)
    run = CollectionRun(run_id="crun-1", plan_id="plan-1", status="running", started_at=now)
    store.add_collection_run(run)
    store.finish_collection_run(
        "crun-1", status="succeeded", progress=1.0, items_collected=42, finished_at=now
    )
    assert [r.run_id for r in store.list_runs(plan_id="plan-1")] == ["crun-1"]
    assert store.list_runs()[0].items_collected == 42
    assert store.list_runs(plan_id="plan-x") == []


def test_schema_v3_and_decision_audit(tmp_path: Path) -> None:
    """v3 迁移：MonitorUpdate 审计列存在；复核决策与关联 Case 留痕。"""
    store = ResearchStore.open(tmp_path / "research.sqlite")
    assert store.ensure_schema() == 6
    cols = {r["name"] for r in store._conn.execute("PRAGMA table_info(monitor_updates)")}
    assert {"decision", "decision_case_id"} <= cols
    store.create_monitor(
        Monitor(
            monitor_id="mon-a",
            target_type="entity",
            target_ref="fed",
            question="美联储叙事",
            created_at=T0,
        )
    )
    store.add_monitor_run(
        MonitorRun(run_id="mrun-a", monitor_id="mon-a", status="succeeded", started_at=T1)
    )
    store.add_monitor_update(
        MonitorUpdate(
            update_id="mupd-a",
            run_id="mrun-a",
            monitor_id="mon-a",
            summary="NDI 上升",
            created_at=T1,
        )
    )
    assert len(store.pending_updates()) == 1
    assert store.mark_update_reviewed("mupd-a", decision="new_case", decision_case_id="case-9")
    assert store.pending_updates() == []
    row = store._conn.execute(
        "SELECT decision, decision_case_id FROM monitor_updates WHERE update_id = 'mupd-a'"
    ).fetchone()
    assert row["decision"] == "new_case" and row["decision_case_id"] == "case-9"
