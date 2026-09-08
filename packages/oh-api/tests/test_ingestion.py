"""Durable Inbox API/runner regression tests; no external requests or paid models."""

import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from oh_api.ingestion import (
    Ingestion,
    JobRequest,
    ScheduleRequest,
    build_ingestion_router,
    safe_error,
)
from oh_contracts.schemas import BronzeRecord
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore


@pytest.fixture
def service(tmp_path, monkeypatch):
    sources = tmp_path / "sources.yaml"
    sources.write_text("sources: []\n")
    result = Ingestion(tmp_path / "data", sources)
    adapters = {key: SimpleNamespace(source_id=key) for key in ("a", "b")}
    monkeypatch.setattr(
        result,
        "registry",
        lambda: SimpleNamespace(all=lambda: list(adapters.values()), get=lambda sid: adapters[sid]),
    )
    return result


def online(service):
    with closing(connect(service.db)) as db, db:
        db.execute("INSERT OR REPLACE INTO heartbeat VALUES(1,?)", (time.time(),))


def test_api_validates_and_conflicts(service):
    app = FastAPI()
    app.include_router(build_ingestion_router(service))
    client = TestClient(app)
    assert client.post("/api/ingestion/jobs", json={"kind": "analyze"}).status_code == 503
    online(service)
    for payload in (
        {"kind": "collect"},
        {"kind": "collect", "source_ids": ["unknown"]},
        {"kind": "analyze", "days": 0},
        {"kind": "analyze", "days": 31},
    ):
        assert client.post("/api/ingestion/jobs", json=payload).status_code == 422
    response = client.post("/api/ingestion/jobs", json={"kind": "analyze"})
    assert response.status_code == 202
    assert client.post("/api/ingestion/jobs", json={"kind": "analyze"}).status_code == 409
    job_id = response.json()["id"]
    assert client.get(f"/api/ingestion/jobs/{job_id}").json()["status"] == "queued"
    assert client.get("/api/ingestion/jobs/absent").status_code == 404
    assert (
        client.put(
            "/api/ingestion/schedule", json={"kind": "analyze", "interval_hours": 0}
        ).status_code
        == 422
    )


def test_queue_and_progress_survive_reopen(service):
    job = service.enqueue(JobRequest(kind="analyze"))
    service.update(
        job["id"],
        stage="annotations",
        done=3,
        total=8,
        details=[{"ok": False, "source_id": "a", "error": "TimeoutError"}],
    )
    reopened = Ingestion(service.root, service.sources)
    saved = reopened.job(job["id"])
    assert (saved["done"], saved["total"]) == (3, 8)
    assert saved["details"][0]["error"] == "TimeoutError"


def test_atomic_single_active_job(service):
    from concurrent.futures import ThreadPoolExecutor

    def submit(_):
        try:
            return service.enqueue(JobRequest(kind="analyze"))["status"]
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(submit, range(6)))
    assert results.count("queued") == 1
    assert results.count(409) == 5


def test_schedule_coalesces_busy_and_pause(service):
    service.set_schedule(ScheduleRequest(kind="analyze", enabled=True, interval_hours=1))
    due = service.snapshot()["schedule"]["next_run"]
    service.tick_schedule(due - 1)
    assert not service.snapshot()["jobs"]
    service.tick_schedule(due + 3600 * 5 + 5)
    snapshot = service.snapshot()
    assert len(snapshot["jobs"]) == 1
    assert snapshot["jobs"][0]["origin"] == "scheduled"
    next_due = snapshot["schedule"]["next_run"]
    assert next_due == due + 3600 * 6
    service.tick_schedule(next_due + 1)
    assert service.snapshot()["schedule"]["next_run"] == next_due
    service.set_schedule(ScheduleRequest(kind="analyze", enabled=False))
    assert service.snapshot()["schedule"]["next_run"] is None


@pytest.mark.parametrize("both_failed, expected", [(False, "partial"), (True, "failed")])
def test_collection_records_individual_failures(service, monkeypatch, both_failed, expected):
    from oh_sources.runner import FetchResult

    async def collect(adapter, **kwargs):
        ok = adapter.source_id == "a" and not both_failed
        return FetchResult(
            adapter.source_id,
            ok,
            n_items=3 if ok else 0,
            n_written=2 if ok else 0,
            error=None if ok else "HTTP 403 https://host/?key=private",
        )

    monkeypatch.setattr("oh_sources.runner.run_collector", collect)
    job = service.enqueue(JobRequest(kind="collect", source_ids=["a", "b"]))
    service.execute(job["id"])
    saved = service.job(job["id"])
    assert saved["status"] == expected
    assert saved["done"] == saved["total"] == 2
    assert "403" in saved["details"][1]["error"]
    assert "private" not in str(saved)


def test_analysis_writes_annotations_with_empty_event_result(service):
    now = datetime.now(UTC)
    record = BronzeRecord(
        source_id="a",
        item_key="test-a",
        external_id="a",
        url_hash="u",
        content_hash="c",
        fetched_at=now,
        published_at=now - timedelta(hours=1),
        raw={},
        normalized={
            "title": "Concern rises",
            "body": "Companies announce job cuts and express fear.",
        },
    )
    ParquetBronzeWriter(service.root / "bronze").write([record])
    job = service.enqueue(JobRequest(kind="analyze"))
    service.execute(job["id"])
    saved = service.job(job["id"])
    assert saved["status"] == "succeeded", saved
    assert saved["details"][0]["annotated"] == 1
    assert saved["details"][1]["note"] == "no_qualifying_events"
    with closing(connect(service.root / "silver.sqlite")) as db:
        assert SqliteStore(db).get_annotation("test-a") is not None


def test_analysis_exception_not_success(service, monkeypatch):
    def broken(*args):
        raise TimeoutError("secret text")

    monkeypatch.setattr(service, "analyze", broken)
    job = service.enqueue(JobRequest(kind="analyze"))
    service.execute(job["id"])
    assert service.job(job["id"])["status"] == "failed"
    assert service.job(job["id"])["error"] == "TimeoutError"


def test_worker_recovers_interrupted_but_preserves_queue(service):
    job = service.enqueue(JobRequest(kind="analyze"))
    service.update(job["id"], status="running")
    service.start()
    try:
        for _ in range(40):
            if service.job(job["id"])["status"] == "failed":
                break
            time.sleep(0.05)
        assert service.job(job["id"])["error"] == "interrupted_by_restart"
    finally:
        service.stop.set()
        service.thread.join(3)


def test_error_redaction():
    assert "sk-abcdef" not in safe_error("Unauthorized Bearer sk-abcdef token=private")
    assert "private" not in safe_error("Unauthorized Bearer sk-abcdef token=private")


def test_queued_job_executes_in_subprocess(service):
    job = service.enqueue(JobRequest(kind="analyze"))
    service.start()
    try:
        for _ in range(100):
            saved = service.job(job["id"])
            if saved["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        assert saved["status"] == "succeeded", saved
        assert saved["started_at"] is not None
    finally:
        service.stop.set()
        service.thread.join(8)


def test_analysis_nonempty_graph(service):
    from conftest import seed_event

    service.sources.write_text(
        "sources:\n  - source_id: gov\n    tier: L1\n    language: zh\n"
        "  - source_id: wscn\n    tier: L3\n    language: zh\n"
    )
    with closing(connect(service.root / "silver.sqlite")) as db:
        seed_event(
            ParquetBronzeWriter(service.root / "bronze"),
            SqliteStore(db),
            "test-ingestion",
            datetime.now(UTC),
        )
    job = service.enqueue(JobRequest(kind="analyze"))
    service.execute(job["id"])
    saved = service.job(job["id"])
    assert saved["status"] == "succeeded", saved
    assert saved["details"][0]["annotated"] == 24
    assert saved["details"][1]["events"] > 0
    assert saved["details"][1]["ndi_points"] > 0
