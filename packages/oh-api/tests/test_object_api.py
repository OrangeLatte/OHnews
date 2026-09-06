"""Object API 冒烟：Case → Document → Run → Artifact → Commit → HITL 全链。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from oh_api.app import AppPaths, create_app


def make_now() -> datetime:
    return datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("version: 2\nsources: []\n", encoding="utf-8")
    app = create_app(AppPaths(root=tmp_path, sources_yaml=sources_yaml, now_fn=make_now))
    return TestClient(app)


@pytest.fixture()
def app_env(tmp_path: Path) -> tuple[TestClient, Path]:
    """client + 数据目录（异步协议测试需要直接打开 research.sqlite 造数）。"""
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("version: 2\nsources: []\n", encoding="utf-8")
    app = create_app(AppPaths(root=tmp_path, sources_yaml=sources_yaml, now_fn=make_now))
    return TestClient(app), tmp_path


CASE = {
    "case_id": "case-t1",
    "question": "美联储叙事是否转向？",
    "origin": "observe",
    "created_at": "2026-09-03T12:00:00+00:00",
    "updated_at": "2026-09-03T12:00:00+00:00",
}


def test_case_document_run_commit_chain(client: TestClient) -> None:
    # 创建 Case
    r = client.post("/api/cases", json=CASE)
    assert r.status_code == 200 and r.json()["case_id"] == "case-t1"
    # 重复创建 → 409
    assert client.post("/api/cases", json=CASE).status_code == 409

    # 挂载不可变文档版本
    r = client.post(
        "/api/cases/case-t1/documents",
        json={
            "document_id": "doc-1",
            "document_revision_id": "rev-1",
            "source_id": "wscn",
            "body": "央行暗示可能调整利率路径。",
            "content_hash": "c:abc",
            "language": "zh",
        },
    )
    assert r.status_code == 200
    assert (
        client.post(
            "/api/cases/case-t1/documents",
            json={
                "document_id": "doc-1",
                "document_revision_id": "rev-1",
                "source_id": "wscn",
                "body": "重复版本冲突",
            },
        ).status_code
        == 409
    )

    # 详情
    detail = client.get("/api/cases/case-t1").json()
    assert detail["case"]["question"].startswith("美联储")

    # 分析运行 queued → finish
    r = client.post(
        "/api/analysis-runs",
        json={"kind": "dissect", "case_id": "case-t1", "input_refs": ["rev-1"]},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    r = client.post(
        f"/api/analysis-runs/{run_id}/finish",
        json={"status": "succeeded", "token_in": 100, "token_out": 50},
    )
    assert r.json()["status"] == "succeeded"

    # Artifact 草稿 → 提交归档（HITL 终点语义）
    assert (
        client.post(
            "/api/artifacts",
            json={
                "artifact_id": "art-1",
                "case_id": "case-t1",
                "klass": "research_report",
                "title": "美联储叙事研判",
                "report_type": "econ_financial",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/artifacts/art-1/revisions",
            json={"revision_id": "r1", "content": {"claims": []}},
        ).status_code
        == 200
    )
    # Archive 在 Commit 前为空（draft 不可见）
    assert client.get("/api/artifacts").json() == []
    r = client.post(
        "/api/artifacts/art-1/commit",
        json={"commit_id": "c1", "revision_id": "r1", "user_note": "确认归档"},
    )
    assert r.status_code == 200
    archive = client.get("/api/artifacts").json()
    assert len(archive) == 1 and archive[0]["artifact_id"] == "art-1"


def test_monitor_flow(client: TestClient) -> None:
    r = client.post(
        "/api/monitors",
        json={
            "monitor_id": "mon-t1",
            "target_type": "case",
            "target_ref": "case-t1",
            "question": "分歧是否扩大",
            "trigger_conditions": ["ndi_slope>0.5"],
        },
    )
    assert r.status_code == 200
    assert client.get("/api/monitors").json()[0]["monitor_id"] == "mon-t1"

    # 更新（增量）→ 待复核 → 复核 → 确认快照
    # 先建 run（FK 约束），用返回的真实 run_id 提交 update；
    # P0-B：POST /runs 真实执行（bronze 空 → 0 命中）→ 终态后确认快照门放行
    r = client.post("/api/monitors/mon-t1/runs")
    assert r.status_code == 202 and r.json()["reused"] is False
    run_id = r.json()["run_id"]
    run = _await_monitor_run(client, "mon-t1", run_id)
    assert run["status"] == "succeeded" and run["output"]["stage"] == "succeeded"
    update = {
        "update_id": "u1",
        "run_id": run_id,
        "monitor_id": "mon-t1",
        "summary": "自快照以来新增 5 篇",
        "delta": {"new_articles": 5},
        "created_at": "2026-09-03T12:30:00+00:00",
    }
    assert client.post("/api/monitors/mon-t1/updates", json=update).status_code == 200
    pending = client.get("/api/monitors/mon-t1/updates").json()
    # 2 条：用户提交 u1 + 执行器自动产出（bronze 空 → 首次运行 0 命中）
    assert len(pending) == 2
    assert pending[0]["summary"].startswith("自快照以来")  # created_at 12:30 > 自动 12:00
    assert pending[1]["update_id"].startswith("mupd-")
    assert client.post("/api/monitors/updates/u1/review").json()["reviewed"] is True
    r = client.post("/api/monitors/mon-t1/confirm-snapshot")
    assert r.status_code == 200 and r.json()["confirmed_at"]


def test_update_review_status_derived(client: TestClient) -> None:
    """review_status 派生键：unreviewed / ignored / accepted（API 层 dict，契约模型不变）。"""
    assert (
        client.post(
            "/api/monitors",
            json={
                "monitor_id": "mon-rs",
                "target_type": "topic",
                "target_ref": "tariff",
                "question": "关税叙事是否升级",
                "trigger_conditions": [],
                "notification": "email",
            },
        ).status_code
        == 200
    )
    r = client.post("/api/monitors/mon-rs/runs")
    run_id = r.json()["run_id"]
    _await_monitor_run(client, "mon-rs", run_id)  # 执行器自动产出一条 0 命中 update
    created = client.post(
        "/api/monitors/mon-rs/updates",
        json={
            "update_id": "u-rs-1",
            "run_id": run_id,
            "monitor_id": "mon-rs",
            "summary": "增量 A",
            "created_at": "2026-09-03T12:30:00+00:00",
        },
    ).json()
    assert created["review_status"] == "unreviewed"

    pending = client.get("/api/monitors/mon-rs/updates").json()
    # 2 条（u-rs-1 + 执行器自动 update），只断言目标 update 的派生状态
    assert [u["review_status"] for u in pending if u["update_id"] == "u-rs-1"] == ["unreviewed"]

    # ignore → ignored
    r = client.post("/api/monitors/updates/u-rs-1/review", json={"decision": "ignore"})
    assert r.json()["review_status"] == "ignored"

    # 第二条：new_case → accepted（并建候选 Case）
    update2 = {
        "update_id": "u-rs-2",
        "run_id": run_id,
        "monitor_id": "mon-rs",
        "summary": "增量 B",
        "created_at": "2026-09-03T12:40:00+00:00",
    }
    client.post("/api/monitors/mon-rs/updates", json=update2)
    r = client.post("/api/monitors/updates/u-rs-2/review", json={"decision": "new_case"})
    body = r.json()
    assert body["review_status"] == "accepted" and body["case_id"].startswith("case-")


def test_hitl_flow(client: TestClient) -> None:
    client.post(
        "/api/agent/threads",
        json={"thread_id": "th-1", "created_at": "2026-09-03T12:00:00+00:00"},
    )
    r = client.post(
        "/api/agent/runs",
        json={"run_id": "ar-1", "thread_id": "th-1", "workflow": "CreateCase"},
    )
    assert r.status_code == 200 and r.json()["status"] == "queued"

    r = client.post(
        "/api/hitl",
        json={
            "hitl_id": "h-1",
            "run_id": "ar-1",
            "action": "commit_artifact",
            "payload": {"revision_id": "r1"},
        },
    )
    assert r.json()["status"] == "awaiting_user"
    assert len(client.get("/api/hitl/pending").json()) == 1
    r = client.post("/api/hitl/h-1/decide", json={"status": "approved", "note": "ok"})
    assert r.json()["status"] == "approved"
    assert client.get("/api/hitl/pending").json() == []


def _await_run(client: TestClient, run_id: str, timeout: float = 10.0) -> dict:
    """轮询至终态（异步协议：202 → 后台执行 → GET run）。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/analysis-runs/{run_id}").json()
        if body["status"] in ("succeeded", "abstained", "failed", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach terminal state")


def _await_monitor_run(
    client: TestClient, monitor_id: str, run_id: str, timeout: float = 10.0
) -> dict:
    """轮询 MonitorRun 至终态（P0-B 异步协议：202 → 后台执行 → GET runs 时间线）。"""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = client.get(f"/api/monitors/{monitor_id}/runs").json()
        row = next((r for r in rows if r["run_id"] == run_id), None)
        if row is not None and row["status"] in ("succeeded", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    raise AssertionError(f"monitor run {run_id} did not reach terminal state")


def test_workflow_endpoints_offline_honest(client: TestClient) -> None:
    """异步协议：POST → 202 queued → 后台执行 → offline 诚实 abstained。"""
    client.post("/api/cases", json=CASE)
    client.post(
        "/api/cases/case-t1/documents",
        json={
            "document_id": "doc-2",
            "document_revision_id": "rev-w1",
            "source_id": "wscn",
            "body": "美联储官员表示通胀正在放缓。",
            "content_hash": "c:w1",
            "language": "zh",
        },
    )
    r = client.post("/api/cases/case-t1/dissect", json={"document_revision_id": "rev-w1"})
    assert r.status_code == 202
    data = r.json()
    assert data["status"] == "queued" and data["reused"] is False and data["poll"]

    run = _await_run(client, data["run_id"])
    assert run["status"] == "abstained" and run["error"]  # 诚实根因非空

    # 提取列表（READ 模式数据源，offline 无元素）
    r = client.get("/api/documents/rev-w1/extractions")
    assert r.status_code == 200 and r.json() == []

    # 比较需要 >= 2 版本 → 异步失败（run failed + 根因）
    r = client.post("/api/cases/case-t1/compare", json={"document_revision_ids": ["rev-w1"]})
    assert r.status_code == 202
    failed = _await_run(client, r.json()["run_id"])
    assert failed["status"] == "failed" and "2 个" in failed["error"]

    # 报告空证据包（有文档但无拆解元素）→ 诚实 failed，不产 draft（不假 succeeded）
    r = client.post(
        "/api/cases/case-t1/report",
        json={"report_type": "veracity", "title": "核实报告"},
    )
    assert r.status_code == 202
    body = _await_run(client, r.json()["run_id"])
    assert body["status"] == "failed" and "报告证据包为空" in body["error"]
    assert not body["output_artifact_id"]

    # challenge 不存在的 claim → 异步 failed（KeyError 根因）
    r = client.post("/api/cases/case-t1/challenge", json={"claim_id": "claim-x"})
    assert r.status_code == 202
    ch = _await_run(client, r.json()["run_id"])
    assert ch["status"] == "failed" and "claim-x" in ch["error"]


def test_report_feedback_passthrough_pins_version_chain(app_env: tuple[TestClient, Path]) -> None:
    """ReportIn.feedback 必须透传 build_report（P0-C T3；防 pydantic 静默丢字段）。

    同 (case, report_type) 连续报告 → 同 artifact 追加版本：output 留
    revised_from（上一 revision_id）+ feedback 原文（offline 路径诚实 abstained）。
    """
    from oh_contracts.case import ElementExtraction
    from oh_storage.research_store import ResearchStore

    client, root = app_env
    client.post("/api/cases", json=CASE)
    store = ResearchStore.open(root / "research.sqlite")
    store.add_document_revision(
        "rev-fb",
        "doc-fb",
        source_id="wscn",
        body="美联储官员表示通胀正在放缓。",
        fetched_at="2026-09-03T12:00:00+00:00",
        content_hash="c:fb",
        language="zh",
    )
    store.link_case_document("case-t1", "rev-fb", "2026-09-03T12:00:00+00:00")
    store.add_extraction(
        ElementExtraction(
            extraction_id="ext-fb",
            case_id="case-t1",
            document_revision_id="rev-fb",
            element_key="actor",
            normalized_value="美联储",
        )
    )
    store.close()

    r1 = client.post(
        "/api/cases/case-t1/report", json={"report_type": "veracity", "title": "核实报告"}
    )
    out1 = _await_run(client, r1.json()["run_id"])
    assert out1["output"]["artifact_id"] and out1["output"]["revision_id"]

    r2 = client.post(
        "/api/cases/case-t1/report",
        json={
            "report_type": "veracity",
            "title": "核实报告",
            "feedback": "请补充九月决议的概率区间并引用挑战问题",
        },
    )
    out2 = _await_run(client, r2.json()["run_id"])
    assert out2["output"]["feedback"] == "请补充九月决议的概率区间并引用挑战问题"
    assert out2["output"]["artifact_id"] == out1["output"]["artifact_id"]
    assert out2["output"]["revised_from"] == out1["output"]["revision_id"]
    assert out2["output"]["prompt_version"] == "report-v2"


def test_async_protocol_idempotent_cancel(app_env: tuple[TestClient, Path]) -> None:
    """幂等复用活跃 run + cancel 状态机 + 启动清理（reap）。"""
    from oh_storage.research_store import ResearchStore

    client, root = app_env
    client.post("/api/cases", json=CASE)

    # 幂等：直接种一个 running run（同 kind/case/refs），POST 应复用而非新建
    store = ResearchStore.open(root / "research.sqlite")
    from oh_contracts.case import AnalysisRun

    run = AnalysisRun(
        run_id="run-seeded",
        case_id="case-t1",
        kind="dissect",
        status="running",
        input_refs=["rev-x"],
        started_at="2026-01-01T00:00:00",
    )
    store.add_analysis_run(run)
    store.close()

    r = client.post("/api/cases/case-t1/dissect", json={"document_revision_id": "rev-x"})
    assert r.status_code == 202
    body = r.json()
    assert body["reused"] is True and body["run_id"] == "run-seeded"

    # cancel：running → cancelled；终态再 cancel → 409
    assert client.post("/api/analysis-runs/run-seeded/cancel").json()["status"] == "cancelled"
    assert client.post("/api/analysis-runs/run-seeded/cancel").status_code == 409
    assert client.get("/api/analysis-runs/run-seeded").json()["status"] == "cancelled"

    # reap：重启清理遗留 queued/running
    store = ResearchStore.open(root / "research.sqlite")
    store.add_analysis_run(
        AnalysisRun(
            run_id="run-stale",
            case_id="case-t1",
            kind="report",
            status="queued",
            input_refs=["t"],
            started_at="2026-01-01T00:00:00",
        )
    )
    assert store.reap_stale_runs(finished_at="2026-01-02T00:00:00") >= 1
    assert store.get_analysis_run("run-stale")["status"] == "failed"  # type: ignore[index]
    store.close()


def test_collection_center_flow(client: TestClient) -> None:
    """运行中心闭环：建计划（enabled 恒 False）→ enable → 登记 run → 收尾 → 列表。"""
    created = client.post(
        "/api/collection/plans",
        json={"source_ids": ["reuters", "ft_com"], "mode": "scheduled", "schedule": "6h"},
    )
    assert created.status_code == 200
    plan = created.json()
    assert plan["enabled"] is False and plan["created_by"] == "user"

    assert client.post(
        f"/api/collection/plans/{plan['plan_id']}/enable", json={"enabled": True}
    ).json()
    assert {"plan_id": plan["plan_id"], "enabled": True}

    run = client.post(f"/api/collection/plans/{plan['plan_id']}/runs", json={})
    assert run.status_code == 200
    run_id = run.json()["run_id"]
    assert run.json()["status"] == "running"

    fin = client.post(
        f"/api/collection/runs/{run_id}/finish",
        json={"status": "succeeded", "progress": 1.0, "items_collected": 7},
    )
    assert fin.json()["status"] == "succeeded"

    runs = client.get(f"/api/collection/runs?plan_id={plan['plan_id']}").json()
    assert len(runs) == 1 and runs[0]["items_collected"] == 7
    assert client.get("/api/collection/plans").json()[0]["enabled"] is True

    assert (
        client.post("/api/collection/plans/plan-nope/enable", json={"enabled": True}).status_code
        == 404
    )
    assert client.post("/api/collection/plans/plan-nope/runs", json={}).status_code == 404
    empty = client.post("/api/collection/plans", json={"source_ids": [], "mode": "scheduled"})
    assert empty.status_code == 422


def test_review_decision_paths(client: TestClient) -> None:
    """HITL 三按钮：接受为新候选 Case / 加入已有 Case / 忽略，全部留痕。"""
    client.post(
        "/api/monitors",
        json={
            "monitor_id": "mon-d1",
            "target_type": "entity",
            "target_ref": "fed",
            "question": "美联储叙事是否转向？",
        },
    )
    r = client.post("/api/monitors/mon-d1/runs")
    run_id = r.json()["run_id"]
    _await_monitor_run(client, "mon-d1", run_id)
    # 执行器自动 update（bronze 空 → 0 命中）先行 ignore，避免污染尾部 pending 断言
    auto = [
        u["update_id"]
        for u in client.get("/api/monitors/mon-d1/updates").json()
        if u["update_id"].startswith("mupd-")
    ]
    for uid in auto:
        client.post(f"/api/monitors/updates/{uid}/review", json={"decision": "ignore"})

    def _update(uid: str) -> dict:
        return {
            "update_id": uid,
            "run_id": run_id,
            "monitor_id": "mon-d1",
            "summary": "新增鹰派表态 3 例",
            "delta": {"hawkish": 3},
            "created_at": "2026-09-03T12:30:00+00:00",
        }

    for uid in ("u-new", "u-join", "u-join2", "u-ign"):
        assert client.post("/api/monitors/mon-d1/updates", json=_update(uid)).status_code == 200

    # 接受为新候选 Case（origin=watch_candidate, created_by=watch）
    r = client.post("/api/monitors/updates/u-new/review", json={"decision": "new_case"})
    assert r.status_code == 200
    case_id = r.json()["case_id"]
    assert case_id.startswith("case-")
    case = client.get(f"/api/cases/{case_id}").json()["case"]
    assert case["origin"] == "watch_candidate" and case["created_by"] == "watch"

    # 加入已有 Case：case 必须存在；缺 case_id → 422
    assert (
        client.post(
            "/api/monitors/updates/u-join/review",
            json={"decision": "join_case", "case_id": case_id},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/monitors/updates/u-join2/review",
            json={"decision": "join_case", "case_id": "case-missing"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/monitors/updates/u-join2/review", json={"decision": "join_case"}
        ).status_code
        == 422
    )

    # u-join2 负例后补有效决策
    assert (
        client.post("/api/monitors/updates/u-join2/review", json={"decision": "ignore"}).status_code
        == 200
    )

    # 忽略：不建 Case，仅决策留痕；全部复核后 pending 清空
    r = client.post("/api/monitors/updates/u-ign/review", json={"decision": "ignore"})
    assert r.json()["decision"] == "ignore" and r.json()["case_id"] == ""
    assert client.get("/api/monitors/mon-d1/updates").json() == []
    assert client.post("/api/monitors/updates/u-none/review").status_code == 404


def test_challenge_gate_and_history_enrichment(client: TestClient) -> None:
    """B6 Challenge 必经门 + A3 span 内联 + A4 决策入 Case 时间线。"""
    case = {**CASE, "case_id": "case-g1"}
    assert client.post("/api/cases", json=case).status_code == 200

    # Claim 创建路径（B6 门的前提）；未知 span → 422
    r = client.post(
        "/api/cases/case-g1/claims",
        json={"statement": "美联储内部对利率路径存在分歧", "kind": "factual"},
    )
    assert r.status_code == 200
    claim_id = r.json()["claim_id"]
    assert (
        client.post(
            "/api/cases/case-g1/claims",
            json={"statement": "x", "span_ids": ["span-none"]},
        ).status_code
        == 422
    )

    # research_report 草稿
    assert (
        client.post(
            "/api/artifacts",
            json={
                "artifact_id": "art-g1",
                "case_id": "case-g1",
                "klass": "research_report",
                "title": "分歧研判",
                "report_type": "narrative",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/artifacts/art-g1/revisions",
            json={"revision_id": "r-g1", "content": {"text": "v1"}},
        ).status_code
        == 200
    )

    # B6：案内有 Claim 但无 Challenge run → 422
    blocked = client.post(
        "/api/artifacts/art-g1/commit",
        json={"commit_id": "cg1", "revision_id": "r-g1"},
    )
    assert blocked.status_code == 422 and "challenge" in blocked.json()["detail"]

    # ChallengeClaim（异步协议）→ succeeded 后 commit 放行
    r = client.post("/api/cases/case-g1/challenge", json={"claim_id": claim_id})
    assert r.status_code == 202
    ch = _await_run(client, r.json()["run_id"])
    assert ch["status"] == "succeeded"
    assert (
        client.post(
            "/api/artifacts/art-g1/commit",
            json={"commit_id": "cg1", "revision_id": "r-g1", "user_note": "过挑战门"},
        ).status_code
        == 200
    )

    # A4：Monitor 决策（join_case → case-g1）进入 Case 详情
    assert (
        client.post(
            "/api/monitors",
            json={
                "monitor_id": "mon-g1",
                "target_type": "case",
                "target_ref": "case-g1",
                "question": "分歧是否扩大",
            },
        ).status_code
        == 200
    )
    run_id = client.post("/api/monitors/mon-g1/runs").json()["run_id"]
    assert (
        client.post(
            "/api/monitors/mon-g1/updates",
            json={
                "update_id": "u-g1",
                "run_id": run_id,
                "monitor_id": "mon-g1",
                "summary": "自快照以来新增 3 篇",
                "delta": {"new_articles": 3},
                "created_at": "2026-09-03T13:00:00+00:00",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/monitors/updates/u-g1/review",
            json={"decision": "join_case", "case_id": "case-g1"},
        ).status_code
        == 200
    )

    detail = client.get("/api/cases/case-g1").json()
    assert detail["monitor_decisions"] == [
        {
            "update_id": "u-g1",
            "monitor_id": "mon-g1",
            "summary": "自快照以来新增 3 篇",
            "decision": "join_case",
            "decision_case_id": "case-g1",
            "created_at": "2026-09-03T13:00:00+00:00",
        }
    ]
    # A3：claims 内联 spans（本测试无 span → 空列表字段存在）
    assert detail["claims"][0]["spans"] == []
    assert any(
        r["kind"] == "challenge" and r["status"] == "succeeded" for r in detail["analysis_runs"]
    )


def test_confirm_claim_user_gate(client: TestClient) -> None:
    """R4：user_confirmed 只能由用户显式 confirm 给出；重复幂等；未知 404。"""
    case = {**CASE, "case_id": "case-cg1"}
    assert client.post("/api/cases", json=case).status_code == 200
    r = client.post(
        "/api/cases/case-cg1/claims",
        json={"statement": "测试主张", "kind": "factual"},
    )
    assert r.status_code == 200
    cid = r.json()["claim_id"]
    assert r.json()["status"] == "unverified"

    ok = client.post(f"/api/claims/{cid}/confirm")
    assert ok.status_code == 200 and ok.json()["status"] == "user_confirmed"
    # 幂等重复确认
    again = client.post(f"/api/claims/{cid}/confirm")
    assert again.status_code == 200 and again.json()["confirmed"] is True
    # detail 中状态可读回
    detail = client.get("/api/cases/case-cg1").json()
    assert detail["claims"][0]["status"] == "user_confirmed"
    # 未知 claim → 404
    assert client.post("/api/claims/claim-none/confirm").status_code == 404


def test_commit_blocks_non_succeeded_report_run(app_env: tuple[TestClient, Path]) -> None:
    """T1 归档门：报告源 run 弃权/失败/运行中 → 422 不可归档；legacy 无 run_id 放行。"""
    from oh_contracts.case import AnalysisRun
    from oh_storage.research_store import ResearchStore

    client, tmp = app_env
    assert client.post("/api/cases", json={**CASE, "case_id": "case-ab"}).status_code == 200
    store = ResearchStore.open(tmp / "research.sqlite")
    store.add_analysis_run(
        AnalysisRun(
            run_id="run-ab",
            case_id="case-ab",
            kind="report",
            engine="llm",
            status="abstained",
            input_refs=["t"],
            started_at="2026-09-03T12:00:00+00:00",
        )
    )
    store.close()
    assert (
        client.post(
            "/api/artifacts",
            json={
                "artifact_id": "art-ab",
                "case_id": "case-ab",
                "klass": "research_report",
                "title": "离线降级稿",
                "report_type": "veracity",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/artifacts/art-ab/revisions",
            json={"revision_id": "r-ab", "run_id": "run-ab", "content": {"engine": "offline"}},
        ).status_code
        == 200
    )
    blocked = client.post(
        "/api/artifacts/art-ab/commit", json={"commit_id": "c-ab", "revision_id": "r-ab"}
    )
    assert blocked.status_code == 422
    detail = blocked.json()["detail"]
    assert "弃权" in detail or "abstained" in detail
    # artifact 保留为草稿（门只拦归档，不删数据）
    assert client.get("/api/artifacts").json() == []

    # legacy：revision 无 run_id → 不拦（历史数据兼容）
    assert (
        client.post(
            "/api/artifacts/art-ab/revisions",
            json={"revision_id": "r-legacy", "content": {"text": "legacy"}},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/artifacts/art-ab/commit",
            json={"commit_id": "c-legacy", "revision_id": "r-legacy"},
        ).status_code
        == 200
    )


def test_monitor_scheduler_health(client: TestClient) -> None:
    """T3：有 run 历史 → scheduled 且 next_run_estimate=last+schedule；cron 诚实 unscheduled。"""
    for mid, schedule in (("mon-sch", "6h"), ("mon-cron", "0 */6 * * *")):
        assert (
            client.post(
                "/api/monitors",
                json={
                    "monitor_id": mid,
                    "target_type": "case",
                    "target_ref": "case-t1",
                    "question": "分歧是否扩大",
                    "schedule": schedule,
                },
            ).status_code
            == 200
        )
    r = client.post("/api/monitors/mon-sch/runs")
    run_id = r.json()["run_id"]
    run = _await_monitor_run(client, "mon-sch", run_id)  # 真实执行闭环（bronze 空 → succeeded）
    assert run["output"]["hits"] == 0
    r = client.get("/api/monitors/mon-sch/scheduler").json()
    assert r["monitor_id"] == "mon-sch" and r["schedule"] == "6h"
    assert r["scheduler_health"] == "scheduled"
    assert r["last_run"] == {
        "run_id": run_id,
        "status": "succeeded",
        "started_at": "2026-09-03T12:00:00+00:00",
    }
    assert r["next_run_estimate"] == "2026-09-03T18:00:00+00:00"
    assert r["note"] == "estimate from last run + schedule; no live scheduler process"

    # cron 文本解析不了 → 诚实 unscheduled + estimate=None（不猜 cron 语义；
    # 配置问题优先于历史状态暴露）
    cron = client.get("/api/monitors/mon-cron/scheduler").json()
    assert cron["scheduler_health"] == "unscheduled" and cron["next_run_estimate"] is None
    assert cron["last_run"] is None
    assert client.get("/api/monitors/mon-none/scheduler").status_code == 404


def test_monitor_scheduler_no_history(client: TestClient) -> None:
    """T3：无 run 历史 → no_history，last_run/estimate 均为 None（诚实缺失）。"""
    assert (
        client.post(
            "/api/monitors",
            json={
                "monitor_id": "mon-fresh",
                "target_type": "topic",
                "target_ref": "tariff",
                "question": "关税叙事是否升级",
                "schedule": "1d",
            },
        ).status_code
        == 200
    )
    r = client.get("/api/monitors/mon-fresh/scheduler").json()
    assert r["scheduler_health"] == "no_history"
    assert r["last_run"] is None and r["next_run_estimate"] is None
    assert r["schedule"] == "1d" and r["note"]


def test_artifact_diff_identical_content(client: TestClient) -> None:
    """T4：同 content 两版本 → changes 全 False；evidence_refs 集合差为空。"""
    client.post("/api/cases", json=CASE)
    assert (
        client.post(
            "/api/artifacts",
            json={
                "artifact_id": "art-d0",
                "case_id": "case-t1",
                "klass": "press_edition",
                "title": "晨报",
            },
        ).status_code
        == 200
    )
    content = {
        "title": "头版",
        "sections": [
            {"title": "宏观", "body": "正文一"},
            {"title": "市场", "body": "正文二"},
        ],
        "evidence_refs": ["a", "b"],
    }
    for rid in ("d0-r1", "d0-r2"):
        assert (
            client.post(
                "/api/artifacts/art-d0/revisions", json={"revision_id": rid, "content": content}
            ).status_code
            == 200
        )
    r = client.get("/api/artifacts/art-d0/diff", params={"from": "d0-r1", "to": "d0-r2"})
    assert r.status_code == 200
    body = r.json()
    assert body["artifact_id"] == "art-d0"
    assert body["from"]["revision_id"] == "d0-r1" and body["from"]["status"] == "draft"
    assert body["to"]["revision_id"] == "d0-r2" and body["to"]["created_at"]
    assert {c["field"] for c in body["changes"]} == {
        "title",
        "sections[0]",
        "sections[1]",
        "evidence_refs",
    }
    assert all(c["changed"] is False for c in body["changes"])
    ev = next(c for c in body["changes"] if c["field"] == "evidence_refs")
    assert ev["from_value"] == [] and ev["to_value"] == []


def test_artifact_diff_field_changes_and_ownership(client: TestClient) -> None:
    """T4：字段级差异（sections 只含 title 不输出正文全文；evidence_refs 集合差）+ 归属 404。"""
    client.post("/api/cases", json=CASE)
    for aid in ("art-d1", "art-d2"):
        assert (
            client.post(
                "/api/artifacts",
                json={
                    "artifact_id": aid,
                    "case_id": "case-t1",
                    "klass": "research_report",
                    "title": aid,
                },
            ).status_code
            == 200
        )
    c1 = {
        "title": "v1",
        "sections": [{"title": "同题", "body": "旧正文"}],
        "evidence_refs": ["a", "b"],
        "note": None,
    }
    c2 = {
        "title": "v2",
        "sections": [{"title": "同题", "body": "新正文"}],
        "evidence_refs": ["b", "c"],
    }
    assert (
        client.post(
            "/api/artifacts/art-d1/revisions", json={"revision_id": "d1-r1", "content": c1}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/artifacts/art-d1/revisions", json={"revision_id": "d1-r2", "content": c2}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/artifacts/art-d2/revisions", json={"revision_id": "d2-r1", "content": {}}
        ).status_code
        == 200
    )

    body = client.get("/api/artifacts/art-d1/diff", params={"from": "d1-r1", "to": "d1-r2"}).json()
    changes = {c["field"]: c for c in body["changes"]}
    assert changes["title"]["changed"] is True and changes["title"]["to_value"] == "v2"
    sec = changes["sections[0]"]
    assert sec["changed"] is True  # body 变化 → changed，但正文不出现在载荷
    assert sec["from_value"] == {"title": "同题"} and sec["to_value"] == {"title": "同题"}
    assert "body" not in (sec["from_value"] or {}) and "body" not in (sec["to_value"] or {})
    ev = changes["evidence_refs"]
    assert ev["changed"] is True and ev["from_value"] == ["a"] and ev["to_value"] == ["c"]
    # 键并集：c1 独有键缺失侧诚实以 None 对比
    assert changes["note"]["from_value"] is None and changes["note"]["changed"] is False

    # 归属校验：revision 属于其他 artifact / 不存在 → 404
    cross = client.get("/api/artifacts/art-d1/diff", params={"from": "d1-r1", "to": "d2-r1"})
    assert cross.status_code == 404
    missing = client.get("/api/artifacts/art-d1/diff", params={"from": "d1-r1", "to": "nope"})
    assert missing.status_code == 404


def test_close_case_and_list_filter(app_env: tuple[TestClient, Path]) -> None:
    """关闭案例：默认列表排除 closed；include_closed=1 可见；404 负例。"""
    client, _ = app_env
    case = dict(CASE, case_id="case-x", question="对某叙事的拆解与比较")
    r = client.post("/api/cases", json=case)
    assert r.status_code == 200
    assert any(c["case_id"] == "case-x" for c in client.get("/api/cases").json())
    assert client.post("/api/cases/case-x/close").json() == {
        "case_id": "case-x",
        "status": "closed",
    }
    assert all(c["case_id"] != "case-x" for c in client.get("/api/cases").json())
    assert any(c["case_id"] == "case-x" for c in client.get("/api/cases?include_closed=1").json())
    assert client.post("/api/cases/case-none/close").status_code == 404
    # 显式 status 查询不受默认过滤影响
    assert any(c["case_id"] == "case-x" for c in client.get("/api/cases?status=closed").json())


def test_review_extraction_hitl(app_env: tuple[TestClient, Path]) -> None:
    """元素复核 HITL：confirmed/rejected 落库；422 非法值；404 未知 id。"""
    from oh_contracts.case import ElementExtraction, EvidenceSpan
    from oh_storage.research_store import ResearchStore

    client, tmp = app_env
    store = ResearchStore.open(tmp / "research.sqlite")
    store.add_document_revision(
        "rev-h",
        "doc-h",
        source_id="wscn",
        body="美联储表示通胀正在放缓。",
        fetched_at="2026-09-03T12:00:00+00:00",
    )
    store.add_span(
        EvidenceSpan(
            span_id="sp-1", document_revision_id="rev-h", char_start=0, char_end=4, quote="美联储"
        )
    )
    store.add_extraction(
        ElementExtraction(
            extraction_id="ex-h",
            case_id="case-t1",
            document_revision_id="rev-h",
            element_key="hard_fact",
            normalized_value="通胀放缓",
            span_ids=["sp-1"],
            confidence=0.9,
        )
    )
    store.close()

    r = client.post("/api/extractions/ex-h/review", json={"human_status": "confirmed"})
    assert r.status_code == 200 and r.json()["human_status"] == "confirmed"
    assert client.get("/api/documents/rev-h/extractions").json()[0]["human_status"] == "confirmed"
    assert (
        client.post("/api/extractions/ex-h/review", json={"human_status": "pending"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/extractions/ex-none/review", json={"human_status": "rejected"}
        ).status_code
        == 404
    )


def test_closed_case_lifecycle_gate(app_env: tuple[TestClient, Path]) -> None:
    """统一状态机纪律：closed Case 禁止 attach/claim/workflow/commit（409）。"""
    client, _ = app_env
    case = dict(CASE, case_id="case-cg")
    assert client.post("/api/cases", json=case).status_code == 200
    r = client.post(
        "/api/cases/case-cg/documents",
        json={
            "document_id": "doc-cg",
            "document_revision_id": "rev-cg",
            "source_id": "wscn",
            "body": "央行暗示可能调整利率路径。",
            "content_hash": "c:cg",
            "language": "zh",
        },
    )
    assert r.status_code == 200
    assert client.post("/api/cases/case-cg/close").status_code == 200

    # attach / claim / dissect / compare / report / challenge 全部 409
    assert (
        client.post(
            "/api/cases/case-cg/documents",
            json={
                "document_id": "doc-cg2",
                "document_revision_id": "rev-cg2",
                "source_id": "wscn",
                "body": "补充材料。",
                "content_hash": "c:cg2",
                "language": "zh",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/cases/case-cg/claims",
            json={"statement": "某主张", "kind": "factual", "created_by": "user"},
        ).status_code
        == 409
    )
    for kind, body in (
        ("dissect", {"document_revision_id": "rev-cg"}),
        ("translate", {"document_revision_id": "rev-cg"}),
        ("compare", {"document_revision_ids": ["rev-cg", "rev-cg2"]}),
        ("report", {"report_type": "structured_summary", "title": "报告"}),
        ("challenge", {"claim_id": "claim-x"}),
    ):
        resp = client.post(f"/api/cases/case-cg/{kind}", json=body)
        assert resp.status_code == 409, f"{kind} should be 409, got {resp.status_code}"

    # commit 关联 closed case 的 artifact → 409
    r = client.post(
        "/api/artifacts",
        json={
            "artifact_id": "art-cg",
            "case_id": "case-cg",
            "klass": "research_report",
            "title": "报告",
        },
    )
    assert r.status_code == 200
    client.post(
        "/api/artifacts/art-cg/revisions",
        json={"revision_id": "rev-art-cg", "content": {"s": 1}, "status": "draft"},
    )
    r = client.post(
        "/api/artifacts/art-cg/commit",
        json={"commit_id": "cmt-cg", "revision_id": "rev-art-cg", "commit_note": "x"},
    )
    assert r.status_code == 409
    # 未知 case → 404（gate 先于写）
    assert (
        client.post("/api/cases/case-none/dissect", json={"document_revision_id": "r"}).status_code
        == 404
    )


def test_failed_run_retry_allowed(app_env: tuple[TestClient, Path]) -> None:
    """失败任务可重试：active_run 只认 queued/running，failed 不阻塞重新 POST。"""
    client, root = app_env
    case = dict(CASE, case_id="case-rt")
    assert client.post("/api/cases", json=case).status_code == 200
    client.post(
        "/api/cases/case-rt/documents",
        json={
            "document_id": "doc-rt",
            "document_revision_id": "rev-rt",
            "source_id": "wscn",
            "body": "正文。",
            "content_hash": "c:rt",
            "language": "zh",
        },
    )
    r1 = client.post("/api/cases/case-rt/dissect", json={"document_revision_id": "rev-rt"}).json()
    # 直接把 run 置为 failed（模拟终态失败）
    import sqlite3

    conn = sqlite3.connect(root / "research.sqlite")
    conn.execute(
        "UPDATE analysis_runs SET status='failed', error='simulated' WHERE run_id=?",
        (r1["run_id"],),
    )
    conn.commit()
    conn.close()
    # 同参数重试 → 新 run（不因 failed 复用）
    r2 = client.post("/api/cases/case-rt/dissect", json={"document_revision_id": "rev-rt"}).json()
    assert r2["run_id"] != r1["run_id"]
    assert r2["reused"] is False


def test_case_belief_snapshot_lineage(client: TestClient) -> None:
    """R10 判断变化线：快照创建 + change_type 派生（首条 new，其后 revised）。"""
    r = client.post(
        "/api/cases",
        json={
            "case_id": "case-belief-1",
            "question": "判断变化线验证",
            "origin": "question",
            "created_by": "user",
            "created_at": "2026-09-03T12:00:00+00:00",
            "updated_at": "2026-09-03T12:00:00+00:00",
        },
    )
    assert r.status_code == 200
    body = {
        "change_id": "claim-b1",
        "subject_id": "case-belief-1",
        "subject_label": "日元干预叙事",
        "stance": "adjust",
        "confidence": 0.7,
        "rationale": "新增反证后调整看法",
    }
    r1 = client.post("/api/cases/case-belief-1/beliefs", json=body)
    assert r1.status_code == 201, r1.text
    snap1 = r1.json()
    assert snap1["change_type"] == "new"
    assert snap1["stance"] == "adjust"
    r2 = client.post("/api/cases/case-belief-1/beliefs", json={**body, "stance": "reverse"})
    assert r2.status_code == 201
    assert r2.json()["change_type"] == "revised"
    lst = client.get("/api/cases/case-belief-1/beliefs")
    assert lst.status_code == 200
    data = lst.json()
    assert data["n"] == 2
    assert [b["stance"] for b in data["beliefs"]] == ["adjust", "reverse"]
    assert client.get("/api/cases/case-none/beliefs").status_code == 404


def test_extraction_deep_link_detail(app_env: tuple[TestClient, Path]) -> None:
    """P1-9 证据深链：单条提取端点返回文档版本+首个有效 span；404 未知 id。"""
    from oh_contracts.case import ElementExtraction, EvidenceSpan
    from oh_storage.research_store import ResearchStore

    client, tmp = app_env
    store = ResearchStore.open(tmp / "research.sqlite")
    store.add_document_revision(
        "rev-dl",
        "doc-dl",
        source_id="wscn",
        body="美联储表示通胀正在放缓。",
        fetched_at="2026-09-03T12:00:00+00:00",
    )
    store.add_span(
        EvidenceSpan(
            span_id="sp-dl", document_revision_id="rev-dl", char_start=0, char_end=4, quote="美联储"
        )
    )
    store.add_extraction(
        ElementExtraction(
            extraction_id="ex-dl",
            case_id="case-t1",
            document_revision_id="rev-dl",
            element_key="actor",
            normalized_value="美联储",
            span_ids=["sp-dl"],
            confidence=0.9,
        )
    )
    store.close()

    d = client.get("/api/extractions/ex-dl").json()
    assert d["document_revision_id"] == "rev-dl"
    assert d["span"]["span_id"] == "sp-dl" and d["span"]["char_end"] == 4
    assert client.get("/api/extractions/ex-none").status_code == 404
