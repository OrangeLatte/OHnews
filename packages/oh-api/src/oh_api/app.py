"""FastAPI 应用：只读数据端点 + 问诊 + 决策日志 + SSE 总线 v0。

依赖注入：create_app(paths) 传数据路径；连接惰性创建。
SSE v0：进程内 asyncio 总线（裁决 D：单进程零 Redis），
其他模块经 publish_sse() 推流；Last-Event-ID 语义 Phase 5b 完善。
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from oh_agents.alerts import check_alerts
from oh_agents.decision_log import DecisionLog
from oh_agents.morning_brief import build_brief
from oh_agents.research import run_research
from oh_contracts.enums import SourceTier
from oh_contracts.text import strip_html
from oh_pipeline.entities import EntityRegistry
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.sqlite_store import SqliteStore

# --- SSE 总线 v0 ------------------------------------------------------------

_SUBSCRIBERS: set[asyncio.Queue[str]] = set()
_SSE_SEQ = 0


async def publish_sse(event: str, payload: dict[str, Any]) -> None:
    """向所有订阅者推送 SSE 消息（无人订阅时零开销）。"""
    global _SSE_SEQ
    if not _SUBSCRIBERS:
        return
    _SSE_SEQ += 1
    msg = f"id: {_SSE_SEQ}\nevent: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    for q in list(_SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            _SUBSCRIBERS.discard(q)


@dataclass
class AppPaths:
    """运行时数据路径（默认 data/ 布局）+ 可注入时钟（测试 PIT 控制）。"""

    root: Path = Path("data")
    sources_yaml: Path = Path("config/sources.yaml")
    logs_dir: Path = Path(".opencode/logs/opencode")
    alerts_db: Path | None = None  # None → root/alerts.sqlite（跟随测试 tmp_path 隔离）
    now_fn: Any = None  # () -> datetime；None = datetime.now(UTC)


def _load_tier_map(path: Path) -> dict[str, SourceTier]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return {
        s["source_id"]: SourceTier(s["tier"])
        for s in doc.get("sources", [])
        if s.get("source_id") and s.get("tier")
    }


def create_app(paths: AppPaths | None = None) -> FastAPI:
    paths = paths or AppPaths()
    app = FastAPI(title="OH!News API", version="0.1.0")

    # 惰性单例（lifespan 不持有 IO）。
    # thread-local：FastAPI sync 端点在线程池执行，sqlite 连接禁止跨线程复用
    # （ProgrammingError）；每线程各建一套实例（DDL 幂等，WAL 多连接并发读安全）。
    state: dict[tuple[int, str], Any] = {}

    def _lazy(name: str, factory: Callable[[], Any]) -> Any:
        key = (threading.get_ident(), name)
        if key not in state:
            state[key] = factory()
        return state[key]

    def _now() -> datetime:
        return paths.now_fn() if paths.now_fn else datetime.now(UTC)

    def _store() -> SqliteStore:
        return _lazy("store", lambda: SqliteStore(connect(paths.root / "silver.sqlite")))

    def _bronze() -> ParquetBronzeWriter:
        return _lazy("bronze", lambda: ParquetBronzeWriter(paths.root / "bronze"))

    def _decisions() -> DecisionLog:
        return _lazy("decisions", lambda: DecisionLog(paths.root / "decisions.sqlite"))

    def _tier_map() -> dict[str, SourceTier]:
        return _lazy("tier_map", lambda: _load_tier_map(paths.sources_yaml))

    def _alerts() -> Any:
        from oh_agents.alerts import AlertStore

        db = paths.alerts_db or (paths.root / "alerts.sqlite")
        return _lazy("alerts", lambda: AlertStore(db))

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "time": datetime.now(UTC).isoformat()}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        store = _store()
        now = _now()
        events = store.events_asof(now)
        stances = store.stances_asof(now)
        points = [p for e in events for p in store.ndi_series(e.event_id)]
        ok = sum(1 for p in points if p.status == "ok")
        return {
            "events": len(events),
            "stances": len(stances),
            "ndi_points": len(points),
            "ndi_ok": ok,
            "ndi_abstain": len(points) - ok,
            "bronze_records": sum(1 for _ in _bronze().iter_records()),
        }

    @app.get("/api/flow/summary")
    def flow_summary(days: int = 30) -> dict[str, Any]:
        """信息流总览（情报大屏数据面）：Bronze 量级 × 框架流 × NDI 总览 × 事件链路。

        daily：published_at（PIT 视角，缺失回落 fetched_at）按 日期×层级×语言 聚合；
        sources：近窗口每源产出量（星系图节点大小）；frames/ndi 来自 Silver/Gold。
        """
        from collections import Counter

        now = _now()
        cutoff = now - timedelta(days=days)
        tier_map = _tier_map()

        daily: Counter[tuple[str, str, str]] = Counter()
        src_n: Counter[str] = Counter()
        src_lang: dict[str, str] = {}
        src_last: dict[str, str] = {}
        for rec in _bronze().iter_records():
            ts = rec.published_at or rec.fetched_at
            if ts < cutoff:
                continue
            day = ts.date().isoformat()
            tier = tier_map.get(rec.source_id)
            tier_v = tier.value if tier is not None else "?"
            lang = str(rec.normalized.get("lang", "?"))
            daily[(day, tier_v, lang)] += 1
            src_n[rec.source_id] += 1
            src_lang.setdefault(rec.source_id, lang)
            src_last[rec.source_id] = ts.isoformat()

        store = _store()
        frames = [f for f in store.flow_frames() if f["date"] >= cutoff.date().isoformat()]
        ndi = [
            {
                "event_id": p.event_id,
                "ts": p.ts.isoformat(),
                "ndi": p.ndi,
                "ci_low": p.ci_low,
                "ci_high": p.ci_high,
                "n_sources": p.n_sources,
                "status": p.status,
                "language": p.language,
                "low_confidence": p.low_confidence,
            }
            for p in store.ndi_all()
            if p.ts >= cutoff
        ]
        links = []
        for e in store.events_asof(now):
            if e.as_of < cutoff:
                continue
            for ent in e.entities:
                links.append(
                    {
                        "event_id": e.event_id,
                        "entity": ent,
                        "title": e.title,
                        "as_of": e.as_of.isoformat(),
                    }
                )
        return {
            "generated_at": now.isoformat(),
            "days": days,
            "daily": [
                {"date": d, "tier": t, "language": lg, "n": n}
                for (d, t, lg), n in sorted(daily.items())
            ],
            "frames": frames,
            "sources": [
                {
                    "source_id": s,
                    "n": n,
                    "language": src_lang.get(s, "?"),
                    "tier": (tier_map[s].value if s in tier_map else "?"),
                    "last_seen": src_last.get(s),
                }
                for s, n in sorted(src_n.items(), key=lambda kv: -kv[1])
            ],
            "ndi": ndi,
            "event_links": links,
        }

    @app.get("/api/events")
    def events(days: int = 7) -> list[dict[str, Any]]:
        store = _store()
        now = _now()
        cutoff = now - timedelta(days=days)
        out = []
        for e in store.events_asof(now):
            if e.as_of < cutoff:
                continue
            series = store.ndi_series(e.event_id)
            latest = series[-1] if series else None
            out.append(
                {
                    "event_id": e.event_id,
                    "title": e.title,
                    "entities": e.entities,
                    "as_of": e.as_of.isoformat(),
                    "ndi": latest.ndi if latest else None,
                    "ndi_status": latest.status if latest else "none",
                    "n_sources": latest.n_sources if latest else 0,
                }
            )
        return out

    @app.get("/api/events/{event_id}/ndi")
    def event_ndi(event_id: str, language: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "ts": p.ts.isoformat(),
                "language": p.language,
                "ndi": p.ndi,
                "ci_low": p.ci_low,
                "ci_high": p.ci_high,
                "n_sources": p.n_sources,
                "status": p.status,
            }
            for p in _store().ndi_series(event_id, language=language)
        ]

    @app.get("/api/events/{event_id}/evidence")
    def event_evidence(event_id: str) -> list[dict[str, Any]]:
        """证据链：claim → 原文摘录（一键引用格式，裁决/研究员提案）。"""
        store = _store()
        now = _now()
        rows = [r for r in store.stances_asof(now) if r.event_id == event_id]
        if not rows:
            raise HTTPException(404, "no stances for event")
        quotes: dict[str, str] = {}
        for rec in _bronze().iter_records():
            quotes[rec.item_key] = strip_html(
                str(rec.normalized.get("body") or rec.normalized.get("title") or "")
            )
        return [
            {
                "source_id": r.source_id,
                "entity_id": r.entity_id,
                "frame": str(r.frame),
                "stance": str(r.stance),
                "confidence": r.confidence,
                "engine": str(r.engine),
                "ts": r.ts.isoformat(),
                "item_key": r.item_key,
                "quote": quotes.get(r.item_key, "")[:160],
            }
            for r in sorted(rows, key=lambda x: -x.confidence)
        ]

    @app.get("/api/brief")
    def brief(watchlist: str = "fed,trump,ecb", top: int = 5) -> dict[str, Any]:
        b = build_brief(
            _bronze(),
            _store(),
            _store(),
            [w.strip() for w in watchlist.split(",") if w.strip()],
            now=_now(),
            top_n=top,
        )
        return {"text": b.render_text(), "items": len(b.items)}

    @app.post("/api/research")
    async def research(body: dict[str, str]) -> dict[str, Any]:
        question = body.get("question", "").strip()
        if not question:
            raise HTTPException(422, "question required")
        result = await run_research(
            question,
            bronze=_bronze(),
            store=_store(),
            gold=_store(),
            registry=EntityRegistry(),
            now=_now(),
        )
        await publish_sse("research_done", {"question": question, "confidence": result.confidence})
        return {
            "answer": result.answer,
            "confidence": result.confidence,
            "citations": list(result.citations),
            "tool_calls": list(result.tool_calls),
        }

    @app.get("/api/decisions")
    def list_decisions(entity_id: str) -> list[dict[str, Any]]:
        return [
            {
                "decision_id": d.decision_id,
                "event_id": d.event_id,
                "ndi_at_decision": d.ndi_at_decision,
                "decision": d.decision,
                "created_at": d.created_at.isoformat(),
                "outcome": d.outcome,
            }
            for d in _decisions().list_for(entity_id)
        ]

    @app.post("/api/decisions")
    def add_decision(body: dict[str, Any]) -> dict[str, Any]:
        entity_id = str(body.get("entity_id", "")).strip()
        decision = str(body.get("decision", "")).strip()
        if not entity_id or not decision:
            raise HTTPException(422, "entity_id and decision required")
        import uuid

        d = _decisions().log(
            decision_id=uuid.uuid4().hex[:12],
            entity_id=entity_id,
            decision=decision,
            event_id=body.get("event_id"),
            ndi_at_decision=body.get("ndi_at_decision"),
        )
        return {"decision_id": d.decision_id}

    @app.post("/api/decisions/{decision_id}/resolve")
    def resolve_decision(decision_id: str, body: dict[str, str]) -> dict[str, str]:
        outcome = body.get("outcome", "").strip()
        if not outcome:
            raise HTTPException(422, "outcome required")
        _decisions().resolve(decision_id, outcome)
        return {"decision_id": decision_id, "resolved": "true"}

    # --- dev 日志监控（opencode 会话镜像，只读） -----------------------------

    @app.get("/api/dev/logs")
    def dev_logs() -> dict[str, Any]:
        d = paths.logs_dir
        files: list[dict[str, Any]] = []
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file() and p.suffix in {".json", ".jsonl", ".txt", ".log"}:
                    st = p.stat()
                    files.append(
                        {
                            "file": p.name,
                            "mtime": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                            "size": st.st_size,
                        }
                    )
        files.sort(key=lambda x: x["mtime"], reverse=True)
        return {"logs_dir": str(d), "files": files[:50]}

    @app.get("/api/dev/logs/{name}")
    def dev_log_preview(name: str) -> dict[str, Any]:
        if "/" in name or ".." in name:
            raise HTTPException(400, "invalid name")
        p = paths.logs_dir / name
        if p.suffix not in {".json", ".jsonl", ".txt", ".log"}:
            raise HTTPException(404, "log not found")
        if not p.is_file():
            raise HTTPException(404, "log not found")
        with p.open(encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = [ln.rstrip("\n") for ln in lines[-200:]]
        return {"file": name, "lines": tail}

    # --- 预警订阅（Phase 6：规则阈值触发，NDI 历史分位数，同实体每日 1 次） ---

    @app.get("/api/alerts/rules")
    def alert_rules() -> list[dict[str, Any]]:
        return [
            {
                "rule_id": r.rule_id,
                "entity_id": r.entity_id,
                "percentile": r.percentile,
                "window_days": r.window_days,
                "created_at": r.created_at.isoformat(),
            }
            for r in _alerts().list_rules()
        ]

    @app.post("/api/alerts/rules")
    def add_alert_rule(body: dict[str, Any]) -> dict[str, Any]:
        entity_id = str(body.get("entity_id", "")).strip()
        percentile = float(body.get("percentile", 0.9))
        window_days = int(body.get("window_days", 90))
        if not entity_id:
            raise HTTPException(422, "entity_id required")
        import uuid

        try:
            r = _alerts().add_rule(
                uuid.uuid4().hex[:8], entity_id, percentile, window_days=window_days
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"rule_id": r.rule_id}

    @app.delete("/api/alerts/rules/{rule_id}")
    def delete_alert_rule(rule_id: str) -> dict[str, str]:
        if not _alerts().remove_rule(rule_id):
            raise HTTPException(404, "rule not found")
        return {"rule_id": rule_id, "deleted": "true"}

    @app.get("/api/alerts/hits")
    def alert_hits(limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "rule_id": h.rule_id,
                "entity_id": h.entity_id,
                "event_id": h.event_id,
                "event_title": h.event_title,
                "ndi": h.ndi,
                "baseline": h.baseline,
                "triggered_at": h.triggered_at.isoformat(),
            }
            for h in _alerts().list_hits(limit)
        ]

    @app.post("/api/alerts/check")
    def run_alert_check() -> dict[str, Any]:
        hits = check_alerts(_store(), _store(), _alerts(), now=_now())
        return {
            "triggered": len(hits),
            "hits": [
                {
                    "rule_id": h.rule_id,
                    "entity_id": h.entity_id,
                    "event_id": h.event_id,
                    "event_title": h.event_title,
                    "ndi": h.ndi,
                    "baseline": h.baseline,
                }
                for h in hits
            ],
        }

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        """SSE 订阅（agent 运行事件/NDI 更新/研究完成推送）。"""
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        _SUBSCRIBERS.add(q)

        async def gen():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15)
                        yield msg
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                _SUBSCRIBERS.discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # --- dashboard 路由（懒导入避免循环） ---
    from oh_api.dashboard import register_dashboard

    register_dashboard(app, _store, _bronze, _decisions, _tier_map)
    return app


__all__ = ["AppPaths", "create_app", "publish_sse"]
