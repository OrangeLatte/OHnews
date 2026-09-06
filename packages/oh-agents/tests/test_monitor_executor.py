"""monitor_executor 单元测试（零 HTTP）：fake 迭代器注入 + 真实 ResearchStore。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from oh_agents.monitor_executor import run_monitor
from oh_contracts.monitoring import Monitor, MonitorRun
from oh_contracts.schemas import BronzeRecord
from oh_storage.research_store import ResearchStore

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _rec(
    item_key: str, *, title: str, body: str = "", published: datetime | None = None
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

    def __init__(self, tmp_path: Path) -> None:
        self.db = tmp_path / "research.sqlite"
        store = self._store()
        store.create_monitor(
            Monitor(
                monitor_id="mon-x",
                target_type="entity",
                target_ref="fed",
                question="美联储叙事是否转向？",
                window="7d",
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
    assert row["output"] == {"stage": "succeeded", "hits": 2, "new_articles": 2, "window": "7d"}
    updates = store.pending_updates("mon-x")
    assert len(updates) == 1
    upd = updates[0]
    assert upd.run_id == "mrun-x"
    assert upd.summary == "首次运行：命中 2 篇相关文档"
    assert upd.delta == {"new_articles": 2, "total_hits": 2, "window": "7d"}
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
    assert row["output"]["hits"] == 3 and row["output"]["new_articles"] == 1
    upd = store.pending_updates("mon-x")[0]
    assert upd.summary == "相对上次确认快照：新增 1 篇相关文档（窗口 7d，命中共 3 篇）"
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
    assert upd.delta == {"new_articles": 12, "total_hits": 12, "window": "7d"}
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
    assert json.loads(raw) == {"stage": "succeeded", "hits": 0, "new_articles": 0, "window": "7d"}
    store.close()
