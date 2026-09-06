"""monitor_executor 单元测试（零 HTTP）：fake 迭代器注入 + 真实 ResearchStore。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_agents.monitor_executor import run_monitor
from oh_contracts.monitoring import Monitor, MonitorRun
from oh_contracts.schemas import BronzeRecord
from oh_storage.research_store import ResearchStore

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _rec(
    item_key: str, *, title: str, body: str = "", published: datetime | None = NOW
) -> BronzeRecord:
    return BronzeRecord(
        source_id="rss-x",
        item_key=item_key,
        external_id=item_key,
        url_hash=f"u:{item_key}",
        content_hash=f"c:{item_key}",
        fetched_at=NOW,
        published_at=published,
        raw={},
        normalized={"title": title, "body": body},
    )


class _Env:
    """tmp sqlite store + 直接造 Monitor/Run 的小环境。"""

    def __init__(self, tmp_path: Path, *, window: str = "7d") -> None:
        self.db = tmp_path / "research.sqlite"
        store = self._store()
        store.create_monitor(
            Monitor(
                monitor_id="mon-x",
                target_type="entity",
                target_ref="fed",
                question="美联储叙事是否转向？",
                window=window,
                created_at=NOW.isoformat(),
            )
        )
        store.add_monitor_run(
            MonitorRun(run_id="mrun-x", monitor_id="mon-x", started_at=NOW.isoformat())
        )
        store.close()

    def _store(self) -> ResearchStore:
        return ResearchStore.open(self.db)

    def run(self, records: object, *, timeout_s: float = 60.0, run_id: str = "mrun-x") -> None:
        run_monitor(
            "mon-x",
            run_id,
            bronze_iter_factory=lambda: records,  # type: ignore[arg-type]
            store_factory=self._store,
            now=lambda: NOW,
            timeout_s=timeout_s,
        )


def _row(store: ResearchStore, run_id: str = "mrun-x") -> dict:
    return next(r for r in store.monitor_runs_for("mon-x") if r["run_id"] == run_id)


def test_run_monitor_succeeded_and_update(tmp_path: Path) -> None:
    env = _Env(tmp_path)
    env.run(
        [
            _rec("k1", title="Fed holds rates", published=datetime(2026, 9, 1, tzinfo=UTC)),
            _rec(
                "k2",
                title="Markets",
                body="fed officials diverge",
                published=datetime(2026, 9, 2, tzinfo=UTC),
            ),
            _rec("k3", title="ECB", body="euro area"),
        ]
    )
    store = env._store()
    row = _row(store)
    assert row["status"] == "succeeded" and row["finished_at"] == NOW.isoformat()
    assert row["output"]["hits"] == 2 and row["output"]["window_applied"] is True
    updates = store.pending_updates("mon-x")
    assert len(updates) == 1
    upd = updates[0]
    assert upd.run_id == "mrun-x"
    assert upd.summary == "首次运行：窗口 7d 内命中 2 篇相关文档"
    assert upd.delta == {"new_articles": 2, "total_hits": 2, "window": "7d", "window_applied": True}
    assert sorted(upd.evidence_refs) == ["k1", "k2"]
    assert upd.suggested_case_action == "new_candidate"
    store.close()


def test_run_monitor_increment_vs_snapshot(tmp_path: Path) -> None:
    env = _Env(tmp_path)
    store = env._store()
    store.confirm_monitor_snapshot("mon-x", datetime(2026, 9, 2, 12, 0, tzinfo=UTC).isoformat())
    env.run(
        [
            _rec("old", title="Fed day", published=datetime(2026, 9, 2, 9, 0, tzinfo=UTC)),
            _rec("new", title="Fed night", published=datetime(2026, 9, 2, 15, 0, tzinfo=UTC)),
            # published_at 缺失：已有快照时不计入增量（PIT：未知时间不声称"新"）
            _rec("unknown", title="Fed undated", published=None),
        ]
    )
    row = _row(store)
    assert row["output"]["hits"] == 2 and row["output"]["new_articles"] == 1
    upd = store.pending_updates("mon-x")[0]
    assert upd.summary == "相对上次确认快照：新增 1 篇相关文档（窗口 7d 内共命中 2 篇）"
    assert upd.evidence_refs == ["new"]
    assert upd.suggested_case_action == "new_candidate"
    store.close()


def test_run_monitor_no_new_articles(tmp_path: Path) -> None:
    env = _Env(tmp_path)
    store = env._store()
    store.confirm_monitor_snapshot("mon-x", datetime(2026, 9, 2, tzinfo=UTC).isoformat())
    env.run([_rec("stale", title="Fed old", published=datetime(2026, 9, 1, tzinfo=UTC))])
    upd = store.pending_updates("mon-x")[0]
    assert upd.delta["new_articles"] == 0 and upd.evidence_refs == []
    assert upd.suggested_case_action == "none"
    store.close()


def test_run_monitor_evidence_cap(tmp_path: Path) -> None:
    env = _Env(tmp_path)
    env.run([_rec(f"k{i:02d}", title=f"Fed memo {i}") for i in range(12)])
    store = env._store()
    upd = store.pending_updates("mon-x")[0]
    assert upd.delta == {
        "new_articles": 12,
        "total_hits": 12,
        "window": "7d",
        "window_applied": True,
    }
    assert len(upd.evidence_refs) == 10  # 上限 10
    store.close()


def test_run_monitor_exception_marks_failed(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    def _boom() -> Iterator[BronzeRecord]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    env.run(_boom())
    store = env._store()
    row = _row(store)
    assert row["status"] == "failed" and row["error"] == "boom" and row["finished_at"]
    assert row["output"] is None and store.pending_updates("mon-x") == []
    store.close()


def test_run_monitor_empty_error_uses_type_name(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    def _silent() -> Iterator[BronzeRecord]:
        raise RuntimeError()
        yield  # pragma: no cover

    env.run(_silent())
    store = env._store()
    assert _row(store)["error"] == "RuntimeError"  # str(exc) 为空 → 类型名兜底
    store.close()


def test_run_monitor_timeout_bounded(tmp_path: Path) -> None:
    env = _Env(tmp_path)

    def _slow() -> Iterator[BronzeRecord]:
        time.sleep(0.3)
        yield _rec("k1", title="Fed")

    env.run(_slow(), timeout_s=0.05)
    store = env._store()
    row = _row(store)
    assert row["status"] == "failed" and "exceeded" in row["error"]
    store.close()


def test_run_monitor_persists_output_json_raw(tmp_path: Path) -> None:
    env = _Env(tmp_path)
    env.run([])
    store = env._store()
    raw = store._conn.execute(
        "SELECT output_json FROM monitor_runs WHERE run_id = 'mrun-x'"
    ).fetchone()[0]
    assert json.loads(raw) == {
        "stage": "succeeded",
        "hits": 0,
        "new_articles": 0,
        "window": "7d",
        "window_applied": True,
        "window_start": "2026-08-27T12:00:00+00:00",
        "window_end": NOW.isoformat(),
        "duplicate_update": False,
    }
    store.close()


def test_window_filters_out_of_range(tmp_path: Path) -> None:
    """窗口语义：published_at 在窗口外（>7d 前）不计 hits（规格七：严格按窗口过滤）。"""
    env = _Env(tmp_path)
    env.run(
        [
            _rec("in-window", title="fed 最新声明", published=NOW - timedelta(days=2)),
            _rec("out-window", title="fed 旧声明", published=NOW - timedelta(days=20)),
        ]
    )
    store = env._store()
    row = _row(store)
    output = row["output"] or {}
    assert output["window_applied"] is True
    assert output["hits"] == 1
    assert output["new_articles"] == 1
    upd = store.pending_updates("mon-x")[0]
    assert upd.delta["window_applied"] is True
    assert "窗口 7d 内" in upd.summary
    store.close()


def test_window_skips_unknown_published(tmp_path: Path) -> None:
    """窗口启用时 published_at 缺失 → 诚实排除（未知时间不得声称在窗口内）。"""
    env = _Env(tmp_path)
    env.run([_rec("no-time", title="fed 无时间文", published=None)])
    store = env._store()
    output = _row(store)["output"] or {}
    assert output["window_applied"] is True
    assert output["hits"] == 0
    store.close()


def test_window_unparseable_full_scan(tmp_path: Path) -> None:
    """不可解析 window → window_applied=False 全量检索（诚实标记，不假装过滤过）。"""
    env = _Env(tmp_path, window="xyz")
    env.run([_rec("any-time", title="fed 旧文", published=NOW - timedelta(days=200))])
    store = env._store()
    output = _row(store)["output"] or {}
    assert output["window_applied"] is False
    assert output["window_start"] is None
    assert output["hits"] == 1  # 全量：窗口外仍在（诚实，不假装过滤）
    assert "全量检索" in store.pending_updates("mon-x")[0].summary
    store.close()


def test_duplicate_update_suppressed(tmp_path: Path) -> None:
    """P0-2b：同内容重复运行不生成重复 update（数值+证据集合一致即视为同一增量）。"""
    env = _Env(tmp_path)
    recs = [_rec("dup-1", title="fed 加息文", published=NOW - timedelta(days=1))]
    env.run(recs)
    env._store().add_monitor_run(
        MonitorRun(run_id="mrun-x2", monitor_id="mon-x", started_at=NOW.isoformat())
    )
    env.run(recs, run_id="mrun-x2")  # 同一窗口同一数据再跑一次（新 run）
    store = env._store()
    outs = [(r.get("output") or {}) for r in store.monitor_runs_for("mon-x")]
    assert sum(1 for o in outs if not o.get("duplicate_update")) == 1  # 仅首次产 update
    assert len(store.pending_updates("mon-x")) == 1  # 待复核队列无重复条目
    # 数据变化后不再判重
    env._store().add_monitor_run(
        MonitorRun(run_id="mrun-x3", monitor_id="mon-x", started_at=NOW.isoformat())
    )
    env.run([*recs, _rec("dup-2", title="fed 新增声明", published=NOW)], run_id="mrun-x3")
    outs = [(r.get("output") or {}) for r in store.monitor_runs_for("mon-x")]
    assert not outs[-1].get("duplicate_update")
    assert len(store.pending_updates("mon-x")) == 2
    store.close()
