"""P0-B Monitor 真实执行闭环：202 → 后台执行 → 明确终态 → MonitorUpdate 增量
→ confirm 门 → 幂等复用。bronze 通过 ParquetBronzeWriter 写入真实分区（tmp 隔离），
执行器经 app 注入的 bronze_iter_factory 读到（测试侧即真实数据链路）。"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from oh_api.app import AppPaths, create_app
from oh_contracts.schemas import BronzeRecord
from oh_storage.bronze_parquet import ParquetBronzeWriter


def make_now() -> datetime:
    return datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


@pytest.fixture()
def env(tmp_path: Path) -> tuple[TestClient, Path]:
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("version: 2\nsources: []\n", encoding="utf-8")
    app = create_app(AppPaths(root=tmp_path, sources_yaml=sources_yaml, now_fn=make_now))
    return TestClient(app), tmp_path


def _bronze_rec(
    item_key: str,
    *,
    title: str = "",
    body: str = "",
    published: datetime | None = None,
    fetched: datetime | None = None,
) -> BronzeRecord:
    return BronzeRecord(
        source_id="rss-x",
        item_key=item_key,
        external_id=item_key,
        url_hash=f"u:{item_key}",
        content_hash=f"c:{item_key}",
        fetched_at=fetched or datetime(2026, 9, 3, 10, 0, tzinfo=UTC),
        published_at=published,
        raw={"k": item_key},
        normalized={"title": title, "body": body},
    )


def _write_bronze(tmp: Path, records: list[BronzeRecord]) -> None:
    ParquetBronzeWriter(tmp / "bronze").write(records)


def _create_monitor(client: TestClient, monitor_id: str, target_ref: str = "fed") -> None:
    assert (
        client.post(
            "/api/monitors",
            json={
                "monitor_id": monitor_id,
                "target_type": "entity",
                "target_ref": target_ref,
                "question": "美联储叙事是否转向？",
                "window": "7d",
            },
        ).status_code
        == 200
    )


def _await_monitor_run(
    client: TestClient, monitor_id: str, run_id: str, timeout: float = 10.0
) -> dict:
    """轮询至终态（硬验收：限定时间内明确终态；超时断言失败而非无限等待）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = client.get(f"/api/monitors/{monitor_id}/runs").json()
        row = next((r for r in rows if r["run_id"] == run_id), None)
        if row is not None and row["status"] in ("succeeded", "failed", "cancelled"):
            return row
        time.sleep(0.05)
    raise AssertionError(f"monitor run {run_id} did not reach terminal state in {timeout}s")


def test_monitor_run_closed_loop(env: tuple[TestClient, Path]) -> None:
    """执行闭环：POST /runs 202 → 终态 succeeded + output 计数 → 1 条 MonitorUpdate
    （summary/delta/evidence_refs/suggested_case_action）→ 刷新后记录仍在。"""
    client, tmp = env
    _create_monitor(client, "mon-loop")
    k_title, k_body, k_miss = "bk-1", "bk-2", "bk-3"
    _write_bronze(
        tmp,
        [
            _bronze_rec(
                k_title,
                title="Fed signals rate path shift",
                published=datetime(2026, 9, 1, tzinfo=UTC),
            ),
            _bronze_rec(
                k_body,
                title="Markets",
                body="the fed hinted at a pause",
                published=datetime(2026, 9, 2, tzinfo=UTC),
            ),
            _bronze_rec(
                k_miss,
                title="ECB outlook",
                body="euro area inflation",
                published=datetime(2026, 9, 2, tzinfo=UTC),
            ),
        ],
    )

    r = client.post("/api/monitors/mon-loop/runs")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["reused"] is False and body["poll"]
    run_id = body["run_id"]

    run = _await_monitor_run(client, "mon-loop", run_id)
    assert run["status"] == "succeeded" and run["error"] == ""
    assert run["output"]["hits"] == 2 and run["output"]["window_applied"] is True
    assert run["output"]["window_start"] is not None

    # 无快照 → 首次运行语义：全部命中计为增量
    pending = client.get("/api/monitors/mon-loop/updates").json()
    assert len(pending) == 1
    upd = pending[0]
    assert upd["run_id"] == run_id
    assert upd["summary"] == "首次运行：窗口 7d 内命中 2 篇相关文档"
    assert upd["delta"] == {
        "new_articles": 2,
        "total_hits": 2,
        "window": "7d",
        "window_applied": True,
    }
    assert sorted(upd["evidence_refs"]) == sorted([k_title, k_body])  # 增量文档 item_key
    assert upd["suggested_case_action"] == "new_candidate"
    assert upd["reviewed"] is False

    # 刷新语义：重新 GET，运行记录与更新仍在（真实持久化，非内存态）
    again = client.get("/api/monitors/mon-loop/runs").json()
    assert [r["run_id"] for r in again] == [run_id]
    assert again[0]["output"]["hits"] == 2
    assert len(client.get("/api/monitors/mon-loop/updates").json()) == 1


def test_monitor_run_increment_after_snapshot(env: tuple[TestClient, Path]) -> None:
    """增量语义：确认快照后再运行，new_articles 只算快照后发布的文档。"""
    client, tmp = env
    _create_monitor(client, "mon-inc")
    old1, old2, fresh = "bi-1", "bi-2", "bi-3"
    _write_bronze(
        tmp,
        [
            _bronze_rec(old1, title="Fed minutes out", published=datetime(2026, 9, 1, tzinfo=UTC)),
            _bronze_rec(
                old2, title="Fed and the dollar", published=datetime(2026, 9, 2, tzinfo=UTC)
            ),
        ],
    )
    run1 = client.post("/api/monitors/mon-inc/runs").json()["run_id"]
    assert _await_monitor_run(client, "mon-inc", run1)["status"] == "succeeded"

    # HITL 基线推进（门：有 succeeded run → 200）
    assert client.post("/api/monitors/mon-inc/confirm-snapshot").status_code == 200

    # 快照后新增一篇（published 9/5 > 快照 9/3T12:00）
    _write_bronze(
        tmp,
        [_bronze_rec(fresh, title="Fed cuts rates", published=datetime(2026, 9, 5, tzinfo=UTC))],
    )
    run2 = client.post("/api/monitors/mon-inc/runs").json()["run_id"]
    run = _await_monitor_run(client, "mon-inc", run2)
    assert run["output"]["hits"] == 3 and run["output"]["window_applied"] is True

    updates = {u["run_id"]: u for u in client.get("/api/monitors/mon-inc/updates").json()}
    assert set(updates) == {run1, run2}
    u2 = updates[run2]
    assert u2["summary"] == "相对上次确认快照：新增 1 篇相关文档（窗口 7d 内共命中 3 篇）"
    assert u2["delta"] == {
        "new_articles": 1,
        "total_hits": 3,
        "window": "7d",
        "window_applied": True,
    }
    assert u2["evidence_refs"] == [fresh]
    assert u2["suggested_case_action"] == "new_candidate"
    # 快照前的 run1 update 不被改写（审计只追加）
    assert updates[run1]["delta"] == {
        "new_articles": 2,
        "total_hits": 2,
        "window": "7d",
        "window_applied": True,
    }


def test_confirm_snapshot_gate(env: tuple[TestClient, Path]) -> None:
    """confirm 门：无 run / 最近 run failed → 422；succeeded 后 → 200。"""
    client, tmp = env
    _create_monitor(client, "mon-gate")

    # 无任何 run → 422
    r = client.post("/api/monitors/mon-gate/confirm-snapshot")
    assert r.status_code == 422 and "no successful run result" in r.json()["detail"]

    # 直接造一条 failed run（started_at 早于冻结 now，确保后续真实 run 排序在前）
    from oh_contracts.monitoring import MonitorRun
    from oh_storage.research_store import ResearchStore

    store = ResearchStore.open(tmp / "research.sqlite")
    store.add_monitor_run(
        MonitorRun(
            run_id="mrun-fail",
            monitor_id="mon-gate",
            status="failed",
            started_at="2026-09-03T11:00:00+00:00",
            error="injected",
        )
    )
    store.close()
    r = client.post("/api/monitors/mon-gate/confirm-snapshot")
    assert r.status_code == 422 and "failed" in r.json()["detail"]

    # 真实执行 succeeded → 门放行
    run_id = client.post("/api/monitors/mon-gate/runs").json()["run_id"]
    assert _await_monitor_run(client, "mon-gate", run_id)["status"] == "succeeded"
    r = client.post("/api/monitors/mon-gate/confirm-snapshot")
    assert r.status_code == 200 and r.json()["confirmed_at"]


def test_run_idempotent_reuse(
    env: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """幂等：活跃 run（queued/running）期间连发 POST /runs → reused=True 同 run_id。

    用慢速假执行器占住活跃状态，保证两次 POST 的时序确定性。
    """
    client, _tmp = env
    _create_monitor(client, "mon-idem")

    import oh_agents.monitor_executor as me

    def _slow(*args: object, **kwargs: object) -> None:
        time.sleep(0.4)

    monkeypatch.setattr(me, "run_monitor", _slow)
    b1 = client.post("/api/monitors/mon-idem/runs").json()
    b2 = client.post("/api/monitors/mon-idem/runs").json()
    assert b1["reused"] is False and b1["status"] == "queued"
    assert b2["reused"] is True and b2["run_id"] == b1["run_id"]
