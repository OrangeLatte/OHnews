"""Durable Inbox operations. One OS-locked executor per data directory.

The queue survives restarts; interrupted work is reported, never called successful.
Schedules coalesce missed intervals into one run, and do not replay an outage backlog.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import re
import threading
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import yaml
from fastapi import APIRouter, HTTPException
from oh_storage.connection import connect
from pydantic import BaseModel, Field


def safe_error(error: str | None) -> str:
    """Retain diagnostic reason, but strip addresses and common credential formats."""
    message = re.sub(r"https?://\S+", "[source URL]", error or "collector_failed")
    message = re.sub(
        r"(?i)(bearer\s+\S+|sk-[\w-]+|(?:key|token|password|secret)\s*[=:]\s*\S+)",
        "[redacted]",
        message,
    )
    return message[:400]


class JobRequest(BaseModel):
    kind: Literal["collect", "analyze", "collect_analyze"]
    source_ids: list[str] = Field(default_factory=list, max_length=300)
    days: int = Field(default=1, ge=1, le=30)


class ScheduleRequest(JobRequest):
    enabled: bool = False
    interval_hours: Literal[1, 6, 12, 24] = 24


class Ingestion:
    def __init__(self, root: Path, sources: Path):
        self.root, self.sources = root.resolve(), sources.resolve()
        self.db = self.root / "ingestion.sqlite"
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        with closing(connect(self.db)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at REAL NOT NULL, started_at REAL, finished_at REAL,
                    stage TEXT NOT NULL DEFAULT 'queued', done INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL DEFAULT 0, details TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT 'manual'
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_pending_job ON jobs((1))
                    WHERE status IN ('queued', 'running');
                CREATE TABLE IF NOT EXISTS schedule (
                    id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL,
                    next_run REAL, last_job_id TEXT
                );
                CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY, ts REAL);
            """)

    def registry(self):
        from oh_sources.registry import build_registry

        return build_registry(yaml.safe_load(self.sources.read_text()) or {})

    def validate(self, body: JobRequest) -> JobRequest:
        if body.kind != "analyze":
            available = {a.source_id for a in self.registry().all()}
            ids = sorted(set(body.source_ids))
            if not ids or not set(ids) <= available:
                raise HTTPException(422, "Select at least one enabled, registered source")
            return body.model_copy(update={"source_ids": ids})
        # Analysis uses the complete window, not a source-biased subset.
        return body.model_copy(update={"source_ids": []})

    def enqueue(self, body: JobRequest, origin: str = "manual") -> dict:
        import sqlite3

        body = self.validate(body)
        job_id = f"ing-{uuid4().hex}"
        try:
            with closing(connect(self.db)) as db, db:
                db.execute(
                    "INSERT INTO jobs(id,status,payload,created_at,origin) VALUES(?,?,?,?,?)",
                    (job_id, "queued", body.model_dump_json(), time.time(), origin),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "A collection/analysis job is already active") from exc
        return self.job(job_id)

    def job(self, job_id: str) -> dict:
        with closing(connect(self.db)) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["details"] = json.loads(result["details"])
        return result

    def update(self, job_id: str, **fields):
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "stage",
            "done",
            "total",
            "details",
            "error",
        }
        if not fields.keys() <= allowed:
            raise ValueError("Unknown job field")
        if "details" in fields:
            fields["details"] = json.dumps(fields["details"], ensure_ascii=False)
        with closing(connect(self.db)) as db, db:
            db.execute(
                "UPDATE jobs SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                (*fields.values(), job_id),
            )

    def set_schedule(self, body: ScheduleRequest):
        # Disabling remains possible even after a source has been removed.
        if body.enabled:
            body = self.validate(body)
        next_run = time.time() + body.interval_hours * 3600 if body.enabled else None
        with closing(connect(self.db)) as db, db:
            db.execute(
                "INSERT INTO schedule(id,payload,next_run) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,next_run=excluded.next_run",
                (body.model_dump_json(), next_run),
            )
        return self.snapshot()["schedule"]

    def snapshot(self):
        with closing(connect(self.db)) as db:
            ids = [
                r[0] for r in db.execute("SELECT id FROM jobs ORDER BY created_at DESC LIMIT 20")
            ]
            schedule = db.execute("SELECT * FROM schedule WHERE id=1").fetchone()
            heartbeat = db.execute("SELECT ts FROM heartbeat WHERE id=1").fetchone()
            successes = dict(
                db.execute(
                    "SELECT json_extract(payload,'$.kind'), max(finished_at) FROM jobs "
                    "WHERE status='succeeded' GROUP BY json_extract(payload,'$.kind')"
                ).fetchall()
            )
        return {
            "jobs": [self.job(i) for i in ids],
            "schedule": {**dict(schedule), "payload": json.loads(schedule["payload"])}
            if schedule
            else None,
            "worker_online": bool(heartbeat and time.time() - heartbeat[0] < 10),
            "last_success": successes,
        }

    def tick_schedule(self, now: float):
        # Called only by the lock owner; insertion and advancing next_run are atomic.
        with closing(connect(self.db)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM schedule WHERE id=1 AND next_run<=?", (now,)).fetchone()
            if (
                not row
                or db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running')").fetchone()
            ):
                return
            body = ScheduleRequest.model_validate_json(row["payload"])
            if not body.enabled:
                return
            job_id = f"ing-{uuid4().hex}"
            db.execute(
                "INSERT INTO jobs(id,status,payload,created_at,origin) VALUES(?,?,?,?,?)",
                (job_id, "queued", body.model_dump_json(), now, "scheduled"),
            )
            interval = body.interval_hours * 3600
            next_run = row["next_run"] + (int((now - row["next_run"]) / interval) + 1) * interval
            db.execute(
                "UPDATE schedule SET next_run=?,last_job_id=? WHERE id=1", (next_run, job_id)
            )

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(target=self.loop, name="inbox-ingestion", daemon=True)
        self.thread.start()

    def loop(self):
        import subprocess
        import sys

        # OS releases the lock on crash. Other API processes can take over safely.
        with (self.root / "ingestion.lock").open("a") as lock:
            while not self.stop.is_set():
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self.stop.wait(1)
            else:
                return
            with closing(connect(self.db)) as db, db:
                db.execute(
                    "UPDATE jobs SET status='failed',error='interrupted_by_restart',"
                    "finished_at=? WHERE status='running'",
                    (time.time(),),
                )
            process = None
            try:
                while not self.stop.is_set():
                    with closing(connect(self.db)) as db, db:
                        db.execute("INSERT OR REPLACE INTO heartbeat VALUES(1,?)", (time.time(),))
                    self.tick_schedule(time.time())
                    if process is None:
                        with closing(connect(self.db)) as db:
                            row = db.execute(
                                "SELECT id FROM jobs WHERE status='queued' LIMIT 1"
                            ).fetchone()
                        if row:
                            job_id = row[0]
                            self.update(job_id, status="running", started_at=time.time())
                            # Fixed module/arguments; no shell or user-provided executable.
                            process = subprocess.Popen(
                                [
                                    sys.executable,
                                    "-m",
                                    "oh_api.ingestion",
                                    str(self.root),
                                    str(self.sources),
                                    job_id,
                                ],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                pass_fds=(lock.fileno(),),
                            )
                            deadline = time.monotonic() + 3600
                    elif process.poll() is not None or time.monotonic() > deadline:
                        if process.poll() is None:
                            process.kill()
                            process.wait()
                        if self.job(job_id)["status"] == "running":
                            self.update(
                                job_id,
                                status="failed",
                                error="worker_exit_or_timeout",
                                finished_at=time.time(),
                            )
                        process = None
                    self.stop.wait(1)
            finally:
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    self.update(
                        job_id,
                        status="failed",
                        error="interrupted_by_shutdown",
                        finished_at=time.time(),
                    )
                with closing(connect(self.db)) as db, db:
                    db.execute("DELETE FROM heartbeat")

    def execute(self, job_id: str):
        from oh_sources.runner import run_collector
        from oh_storage.bronze_parquet import ParquetBronzeWriter

        details = []
        try:
            body = self.validate(JobRequest.model_validate(self.job(job_id)["payload"]))
            now = datetime.now(UTC)
            bronze = ParquetBronzeWriter(self.root / "bronze")
            if body.kind != "analyze":
                registry = self.registry()
                for index, sid in enumerate(body.source_ids):
                    self.update(
                        job_id, stage=f"collect:{sid}", done=index, total=len(body.source_ids)
                    )
                    try:
                        result = asyncio.run(
                            asyncio.wait_for(
                                run_collector(
                                    registry.get(sid),
                                    writer=bronze,
                                    since=now - timedelta(days=body.days),
                                    until=now,
                                ),
                                timeout=180,
                            )
                        )
                        details.append(
                            {
                                "source_id": sid,
                                "ok": result.ok,
                                "written": result.n_written,
                                "fetched": result.n_items,
                                "error": safe_error(result.error) if not result.ok else "",
                                "duration_ms": result.duration_ms,
                            }
                        )
                    except Exception as exc:
                        details.append(
                            {
                                "source_id": sid,
                                "ok": False,
                                "written": 0,
                                "error": type(exc).__name__,
                            }
                        )
                    self.update(job_id, done=index + 1, details=details)
            if body.kind != "collect":
                self.analyze(job_id, body.days, now, bronze, details)
            failures = sum(not d.get("ok", True) for d in details)
            status = (
                "failed"
                if failures and failures == len(details)
                else "partial"
                if failures
                else "succeeded"
            )
            self.update(
                job_id, status=status, stage="finished", finished_at=time.time(), details=details
            )
        except Exception as exc:
            # Never put provider keys, raw URLs or complete tracebacks in public job responses.
            self.update(job_id, status="failed", error=type(exc).__name__, finished_at=time.time())

    def analyze(self, job_id, days, now, bronze, details):
        from oh_agents.graph import GraphDeps, build_analysis_graph
        from oh_contracts.enums import SourceTier
        from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
        from oh_pipeline.events import EventBuilder
        from oh_pipeline.semantics import annotate_document
        from oh_storage.sqlite_store import SqliteStore

        self.update(job_id, stage="scan", done=0, total=0)
        records = [
            r
            for r in bronze.iter_records()
            if r.published_at and now - timedelta(days=days) <= r.published_at <= now
        ]
        registry = EntityRegistry(DEFAULT_ENTITIES)
        with closing(connect(self.root / "silver.sqlite")) as conn:
            store = SqliteStore(conn)
            self.update(job_id, stage="annotations", done=0, total=len(records))
            annotated = 0
            for i, rec in enumerate(records):
                text = (
                    f"{rec.normalized.get('title', '')}\n{rec.normalized.get('body', '')}".strip()
                )
                if text:
                    ann = annotate_document(
                        rec.item_key, text, registry, annotated_at=rec.published_at
                    )
                    store.upsert_annotation(
                        ann.item_key,
                        ann.model_dump(mode="json"),
                        engine="lexicon",
                        annotated_at=rec.published_at,
                    )
                    annotated += 1
                if (i + 1) % 25 == 0 or i + 1 == len(records):
                    self.update(job_id, done=i + 1)
            details.append(
                {
                    "stage": "annotations",
                    "ok": True,
                    "documents": len(records),
                    "annotated": annotated,
                }
            )
            self.update(job_id, stage="events_ndi", done=0, total=0, details=details)
            built = EventBuilder(registry).build(records, min_articles=3, min_sources=2)
            for item in built:
                store.upsert_event(item.event)
            specs = (yaml.safe_load(self.sources.read_text()) or {}).get("sources", [])
            points = []
            if built:
                deps = GraphDeps(
                    bronze=bronze,
                    store=store,
                    gold=store,
                    tier_map={s["source_id"]: SourceTier(s["tier"]) for s in specs},
                    lang_map={s["source_id"]: s.get("language", "zh") for s in specs},
                    languages=tuple(sorted({s.get("language", "zh") for s in specs})),
                    lookback_days=days,
                    min_per_source=10,
                )
                result = asyncio.run(
                    asyncio.wait_for(
                        build_analysis_graph(deps).ainvoke(
                            {
                                "events_input": [b.event.model_dump() for b in built],
                                "now": now.isoformat(),
                            }
                        ),
                        timeout=1800,
                    )
                )
                points = result.get("ndi_points", [])
            details.append(
                {
                    "stage": "events_ndi",
                    "ok": True,
                    "events": len(built),
                    "ndi_points": len(points),
                    "note": "no_qualifying_events" if not built else "descriptive_only",
                }
            )


def build_ingestion_router(service: Ingestion) -> APIRouter:
    router = APIRouter(prefix="/api/ingestion", tags=["Inbox operations"])

    @router.get("/status")
    def status():
        return service.snapshot()

    @router.get("/jobs/{job_id}")
    def detail(job_id: str):
        return service.job(job_id)

    @router.post("/jobs", status_code=202)
    def start(body: JobRequest):
        if not service.snapshot()["worker_online"]:
            raise HTTPException(503, "Ingestion worker is offline")
        return service.enqueue(body)

    @router.put("/schedule")
    def schedule(body: ScheduleRequest):
        return service.set_schedule(body)

    return router


if __name__ == "__main__":
    import sys

    Ingestion(Path(sys.argv[1]), Path(sys.argv[2])).execute(sys.argv[3])
