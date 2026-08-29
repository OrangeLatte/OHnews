"""FastAPI 应用：只读数据端点 + 问诊 + 决策日志 + SSE 总线 v0。

依赖注入：create_app(paths) 传数据路径；连接惰性创建。
SSE v0：进程内 asyncio 总线（裁决 D：单进程零 Redis），
其他模块经 publish_sse() 推流；Last-Event-ID 语义 Phase 5b 完善。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from oh_agents.alerts import check_alerts
from oh_agents.chat import ChatStore, run_chat
from oh_agents.decision_log import DecisionLog
from oh_agents.morning_brief import build_brief
from oh_agents.orchestrator import (
    answer_question,
    build_context_packet,
    offline_artifact,
    run_intent,
)
from oh_agents.research import run_research
from oh_contracts.enums import SourceTier
from oh_contracts.intents import Intent
from oh_contracts.schemas import NDIPoint
from oh_contracts.text import strip_html
from oh_pipeline.anatomy import cluster_distributions, cluster_pairwise, entity_opposition
from oh_pipeline.detect import detect_signals
from oh_pipeline.entities import EntityRegistry
from oh_pipeline.spectra import sentence_spectrum
from oh_pipeline.svo import parse_passage
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
    chat_db: Path | None = None  # None → root/chat.sqlite
    intel_db: Path | None = None  # None → root/intel.sqlite
    watch_db: Path | None = None  # None → root/watch.sqlite
    library_db: Path | None = None  # None → root/library.sqlite
    models_yaml: Path | None = None  # None → config/models.yaml（不存在则 chat 降级离线）
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

    def _chat_store() -> ChatStore:
        db = paths.chat_db or (paths.root / "chat.sqlite")
        return _lazy("chat_store", lambda: ChatStore(db))

    def _intel_ledger() -> Any:
        from oh_agents.intel.intel_graph import IntelLedger

        db = paths.intel_db or (paths.root / "intel.sqlite")
        return _lazy("intel_ledger", lambda: IntelLedger(db))

    def _watch_store() -> Any:
        from oh_agents.watch import WatchStore

        db = paths.watch_db or (paths.root / "watch.sqlite")
        return _lazy("watch_store", lambda: WatchStore(db))

    def _library_store() -> Any:
        from oh_agents.library import LibraryStore

        db = paths.library_db or (paths.root / "library.sqlite")
        return _lazy("library_store", lambda: LibraryStore(db))

    # ---- 运行时 API keys（UI 配置 → data/runtime_keys.json，gitignored；env 优先）----
    def _runtime_keys_path() -> Path:
        return paths.root / "runtime_keys.json"

    def _runtime_keys() -> dict[str, str]:
        p = _runtime_keys_path()
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text())
            return {k: str(v) for k, v in data.items() if isinstance(v, str)}
        except Exception:
            return {}

    def _get_key(provider: str) -> str | None:
        env_name = f"{provider.upper()}_API_KEY"
        v = os.getenv(env_name)
        if v:
            return v
        return _runtime_keys().get(env_name)

    def _sync_env() -> None:
        """runtime keys 注入 os.environ——oh-llm 的 _ensure/ChatOpenAI 只读进程环境。"""
        for env_name in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY"):
            k = _runtime_keys().get(env_name)
            if k:
                os.environ[env_name] = k

    _router_gen = [0]  # keys 更新时 +1，使所有线程的 chat_router 缓存失效

    def _chat_router() -> Any:
        """chat_graph 的 ModelRouter（keys 缺失/配置不存在 → None 降级离线）。"""
        my = paths.models_yaml or Path("config/models.yaml")
        if not my.exists():
            return None

        if not (_get_key("deepseek") or _get_key("zhipu")):
            return None

        _sync_env()

        def _build() -> Any:
            from oh_llm.config import load_llm_config
            from oh_llm.router import ModelRouter

            return ModelRouter(load_llm_config(my))

        return _lazy(f"chat_router:{_router_gen[0]}", _build)

    @app.get("/api/keys")
    def keys_status() -> dict[str, Any]:
        """LLM keys 配置状态（只回布尔，永不回显 key 本身）。"""
        return {
            "deepseek": _get_key("deepseek") is not None,
            "zhipu": _get_key("zhipu") is not None,
            "llm_ready": _chat_router() is not None,
        }

    @app.post("/api/keys")
    def keys_save(body: dict[str, str]) -> dict[str, Any]:
        """保存运行时 keys（热生效，无需重启；持久化到 gitignored runtime_keys.json）。"""
        allowed = {"DEEPSEEK_API_KEY", "ZHIPU_API_KEY"}
        current = _runtime_keys()
        changed = False
        for k, v in (body or {}).items():
            if k not in allowed:
                raise HTTPException(422, f"unknown key field: {k}")
            if not isinstance(v, str) or not v.strip():
                continue
            current[k] = v.strip()
            changed = True
        if changed:
            p = _runtime_keys_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(current))
            p.chmod(0o600)
            _sync_env()
            _router_gen[0] += 1  # 重建所有线程的 ModelRouter
        return keys_status()

    def _registry() -> EntityRegistry:
        return _lazy("registry", lambda: EntityRegistry())

    @app.get("/api/today")
    def today(top: int = 10, min_per_source: int = 10) -> dict[str, Any]:
        """Daily Intelligence Briefing（REDESIGN §3/§7）：确定性变化检测 → Top-N Signal。"""
        now = _now()
        sigs = detect_signals(
            _bronze().iter_records(),
            _store(),
            _registry(),
            _tier_map(),
            now,
            min_per_source=min_per_source,
            top_n=max(1, min(top, 30)),
        )
        return {
            "date": now.date().isoformat(),
            "total": len(sigs),
            "signals": [s.model_dump(mode="json") for s in sigs],
        }

    @app.get("/api/entities")
    def entities_list() -> dict[str, Any]:
        """实体清单（Timeline/Watch 实体选择器数据源）。"""
        from oh_pipeline.entities import DEFAULT_ENTITIES

        return {
            "entities": [
                {
                    "entity_id": e.entity_id,
                    "aliases": list(e.aliases),
                    "parent_id": e.parent_id,
                }
                for e in DEFAULT_ENTITIES
            ]
        }

    @app.get("/api/timeline/{entity_id}")
    def entity_timeline(entity_id: str, days: int = 30, language: str = "any") -> dict[str, Any]:
        """实体级叙事时间轴（R3）：日粒度文章量/事件/NDI/官方-市场行数。

        language="any"（默认）不过滤——同一事件多语言点位时优先混算（all）。
        """
        registry = _registry()
        try:
            registry.get(entity_id)
        except KeyError as e:
            raise HTTPException(404, f"unknown entity: {entity_id}") from e
        now = _now()
        window = max(1, min(days, 365))
        start = (now - timedelta(days=window - 1)).date()
        store = _store()
        tier_map = _tier_map()

        articles: dict[date, int] = {}
        for rec in _bronze().iter_records():
            pub = rec.published_at or rec.fetched_at
            d = pub.date()
            if d < start or d > now.date():
                continue
            text = (
                str(rec.normalized.get("title") or "") + str(rec.normalized.get("body") or "")[:600]
            )
            if not text.strip():
                continue
            if entity_id in registry.match(text):
                articles[d] = articles.get(d, 0) + 1

        events = [ev for ev in store.events_asof(now) if entity_id in (ev.entities or [])]
        events_by_day: dict[date, list[str]] = {}
        for ev in events:
            events_by_day.setdefault(ev.as_of.date(), []).append(ev.event_id)

        ndi_by_event: dict[str, NDIPoint] = {}
        entity_event_ids = {ev.event_id for ev in events}
        for p in store.ndi_all():
            if p.event_id not in entity_event_ids:
                continue
            if language != "any" and p.language != language:
                continue
            prev = ndi_by_event.get(p.event_id)
            rank = {"all": 0, "zh": 1, "en": 2, "cross": 3}
            if prev is None or rank.get(p.language, 9) < rank.get(prev.language, 9):
                ndi_by_event[p.event_id] = p

        official: dict[date, int] = {}
        market: dict[date, int] = {}
        for row in store.stances_asof(now):
            if row.entity_id != entity_id or row.ts.date() < start:
                continue
            is_official = tier_map.get(row.source_id) == SourceTier.OFFICIAL
            bucket = official if is_official else market
            bucket[row.ts.date()] = bucket.get(row.ts.date(), 0) + 1

        points: list[dict[str, Any]] = []
        for i in range(window):
            d = start + timedelta(days=i)
            ev_ids = events_by_day.get(d, [])
            ndi_val = next(
                (ndi_by_event[eid].ndi for eid in ev_ids if eid in ndi_by_event),
                None,
            )
            points.append(
                {
                    "date": d.isoformat(),
                    "articles": articles.get(d, 0),
                    "n_events": len(ev_ids),
                    "event_ids": ev_ids,
                    "ndi": ndi_val,
                    "official_rows": official.get(d, 0),
                    "market_rows": market.get(d, 0),
                }
            )
        # R3：事件主导框架（全量 stance 行 argmax；v0 简化，不按簇分开计数）
        frame_counts: dict[str, dict[str, int]] = {}
        for row in store.stances_asof(now):
            if row.event_id not in entity_event_ids:
                continue
            counts = frame_counts.setdefault(row.event_id, {})
            counts[row.frame] = counts.get(row.frame, 0) + 1

        def dominant_frame(eid: str) -> str | None:
            c = frame_counts.get(eid)
            if not c:
                return None
            return max(c.items(), key=lambda kv: (kv[1], kv[0]))[0]

        event_cards = [
            {
                "event_id": ev.event_id,
                "title": ev.title,
                "as_of": ev.as_of.isoformat(),
                "ndi": ndi_by_event.get(ev.event_id, None) and ndi_by_event[ev.event_id].ndi,
                "dominant_frame": dominant_frame(ev.event_id),
            }
            for ev in events
            if ev.as_of.date() >= start
        ]
        event_cards.sort(key=lambda c: c["as_of"], reverse=True)
        return {
            "entity_id": entity_id,
            "days": window,
            "language": language,
            "points": points,
            "events": event_cards,
        }

    @app.get("/api/watches")
    def watches_list() -> dict[str, Any]:
        return {"watches": [w.__dict__ for w in _watch_store().list()]}

    @app.post("/api/watches", status_code=201)
    def watches_add(body: dict[str, str]) -> dict[str, Any]:
        try:
            w = _watch_store().add(
                type=str(body.get("type", "")), query=str(body.get("query", "")), now=_now()
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return w.__dict__

    @app.delete("/api/watches/{watch_id}")
    def watches_remove(watch_id: str) -> dict[str, Any]:
        if not _watch_store().remove(watch_id):
            raise HTTPException(404, "watch not found")
        return {"removed": watch_id}

    async def _refresh_one(w: Any, min_per_source: int, now: datetime) -> dict[str, Any]:
        """按类型重算单个订阅快照（entity/topic 确定性；question 接 Investigator）。"""
        query = w.query
        if w.type == "entity":
            sigs = detect_signals(
                _bronze().iter_records(),
                _store(),
                _registry(),
                _tier_map(),
                now,
                min_per_source=min_per_source,
                top_n=30,
            )
            mine = [s for s in sigs if s.entity_id == query]
            events = [
                {"event_id": e.event_id, "title": e.title, "as_of": e.as_of.isoformat()}
                for e in _store().events_asof(now)
                if query in (e.entities or [])
            ]
            # alerts 打通：该实体的既有规则触发（供订阅快照直接可见）
            rules = [r for r in _alerts().list_rules() if r.entity_id == query]
            hits = [h for h in _alerts().list_hits(limit=100) if h.entity_id == query][:3]
            summary: dict[str, Any] = {
                "kind": "entity",
                "n_signals": len(mine),
                "signals": [s.model_dump(mode="json") for s in mine[:5]],
                "n_events": len(events),
                "events": events[:10],
                "n_alert_rules": len(rules),
                "alerts": [
                    {
                        "event_title": h.event_title,
                        "ndi": h.ndi,
                        "baseline": h.baseline,
                        "triggered_at": h.triggered_at.isoformat(),
                    }
                    for h in hits
                ],
            }
        elif w.type == "topic":
            terms = [t.strip().lower() for t in query.split(",") if t.strip()]
            cutoff = now - timedelta(days=7)
            n_hits = 0
            by_source: dict[str, int] = {}
            for rec in _bronze().iter_records():
                pub = rec.published_at or rec.fetched_at
                if pub < cutoff:
                    continue
                text = (
                    str(rec.normalized.get("title", ""))
                    + "\n"
                    + str(rec.normalized.get("body", ""))
                ).lower()
                if any(t in text for t in terms):
                    n_hits += 1
                    by_source[rec.source_id] = by_source.get(rec.source_id, 0) + 1
            top_sources = sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            events = [
                {"event_id": e.event_id, "title": e.title, "as_of": e.as_of.isoformat()}
                for e in _store().events_asof(now)
                if any(t in (e.title + " " + e.summary).lower() for t in terms)
            ]
            summary = {
                "kind": "topic",
                "terms": terms,
                "days": 7,
                "n_articles": n_hits,
                "top_sources": [{"source_id": s, "n": n} for s, n in top_sources],
                "n_events": len(events),
                "events": events[:10],
            }
        else:  # question
            inv = await answer_question(
                query,
                bronze=_bronze(),
                store=_store(),
                gold=_store(),
                registry=_registry(),
                tier_map=_tier_map(),
                router=_chat_router(),
                now=now,
            )
            summary = {
                "kind": "question",
                "status": inv["status"],
                "engine": inv["engine"],
                "answer": inv["answer"],
                "n_matched_events": len(inv["events"]),
                "events": inv["events"][:10],
            }
        _watch_store().save_summary(w.watch_id, now=now, summary=summary)
        refreshed = _watch_store().get(w.watch_id)
        assert refreshed is not None
        return refreshed.__dict__

    @app.post("/api/watches/refresh_all")
    async def watches_refresh_all(min_per_source: int = 10) -> dict[str, Any]:
        """一键刷新全部订阅（供 cron / scripts/dev/refresh_watches.py 调用）。"""
        now = _now()
        results = []
        for w in _watch_store().list():
            try:
                refreshed = await _refresh_one(w, min_per_source, now)
                results.append(
                    {"watch_id": w.watch_id, "ok": True, "summary": refreshed.get("last_summary")}
                )
            except Exception as exc:  # BLE001：单条失败不阻断整体刷新
                results.append({"watch_id": w.watch_id, "ok": False, "error": str(exc)})
        return {"refreshed_at": now.isoformat(), "n": len(results), "results": results}

    @app.post("/api/watches/{watch_id}/refresh")
    async def watches_refresh(watch_id: str, min_per_source: int = 10) -> dict[str, Any]:
        store = _watch_store()
        w = store.get(watch_id)
        if w is None:
            raise HTTPException(404, "watch not found")
        return await _refresh_one(w, min_per_source, _now())

    @app.get("/api/library")
    def library_list(item_type: str | None = None) -> dict[str, Any]:
        try:
            items = _library_store().list(item_type)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"items": [i.__dict__ for i in items]}

    @app.post("/api/library", status_code=201)
    def library_add(body: dict[str, Any]) -> dict[str, Any]:
        try:
            item = _library_store().add(
                item_type=str(body.get("item_type", "")),
                title=str(body.get("title", "")),
                payload=dict(body.get("payload") or {}),
                ref_kind=body.get("ref_kind"),
                ref_id=body.get("ref_id"),
                now=_now(),
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return item.__dict__

    @app.delete("/api/library/{item_id}")
    def library_remove(item_id: str) -> dict[str, Any]:
        if not _library_store().remove(item_id):
            raise HTTPException(404, "library item not found")
        return {"removed": item_id}

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

    @app.get("/api/sources")
    def sources_list() -> dict[str, Any]:
        """信息源管理面（订阅中心）：全源清单 + Bronze 产出统计（订阅中心主表数据）。"""
        doc: dict[str, Any] = {}
        if paths.sources_yaml.exists():
            with paths.sources_yaml.open(encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        now = _now()
        c7: Counter[str] = Counter()
        c30: Counter[str] = Counter()
        last_seen: dict[str, str] = {}
        for rec in _bronze().iter_records():
            ts = rec.published_at or rec.fetched_at
            sid = rec.source_id
            if ts >= now - timedelta(days=7):
                c7[sid] += 1
            if ts >= now - timedelta(days=30):
                c30[sid] += 1
            prev = last_seen.get(sid)
            if prev is None or ts.isoformat() > prev:
                last_seen[sid] = ts.isoformat()
        rows = []
        for spec in doc.get("sources", []):
            sid = spec.get("source_id")
            if not sid:
                continue
            rows.append(
                {
                    "source_id": sid,
                    "kind": spec.get("kind", "?"),
                    "tier": spec.get("tier", "?"),
                    "language": spec.get("language", "?"),
                    "enabled": bool(spec.get("enabled", True)),
                    "n_7d": c7.get(sid, 0),
                    "n_30d": c30.get(sid, 0),
                    "last_seen": last_seen.get(sid),
                }
            )
        rows.sort(key=lambda r: (-r["n_7d"], -r["n_30d"], r["source_id"]))
        return {"n": len(rows), "sources": rows}

    @app.get("/api/sources/{source_id}/articles")
    def source_articles(source_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """单源最近文章（源详情 + 句级多色标注的数据面）。"""
        rows = []
        for rec in _bronze().iter_records():
            if rec.source_id != source_id:
                continue
            ts = rec.published_at or rec.fetched_at
            rows.append(
                {
                    "item_key": rec.item_key,
                    "title": str(rec.normalized.get("title") or ""),
                    "url": str(rec.normalized.get("url") or ""),
                    "published_at": ts.isoformat(),
                    "body": str(rec.normalized.get("body") or "")[:600],
                }
            )
        rows.sort(key=lambda r: r["published_at"], reverse=True)
        return rows[: max(1, min(limit, 100))]

    @app.post("/api/sources/{source_id}/refresh")
    def source_refresh(source_id: str, days: int = 1) -> dict[str, Any]:
        """单源采集操作（订阅中心「操作」列；同步执行，返回本窗口写入量）。"""
        from oh_sources.registry import build_registry
        from oh_sources.runner import run_collector

        registry = build_registry(paths.sources_yaml)
        try:
            adapter = registry.get(source_id)
        except KeyError as e:
            raise HTTPException(404, f"unknown source: {source_id}") from e
        now = _now()
        result = asyncio.run(
            run_collector(
                adapter,
                writer=_bronze(),
                since=now - timedelta(days=max(1, min(days, 90))),
                until=now,
            )
        )
        return {
            "source_id": result.source_id,
            "ok": result.ok,
            "n_items": result.n_items,
            "n_written": result.n_written,
            "error": result.error,
            "duration_ms": result.duration_ms,
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

    @app.get("/api/events/{event_id}/spectrum")
    def event_spectrum(event_id: str) -> list[dict[str, Any]]:
        """句级叙事光谱 v2：词级主体/动作/立场 spans + 框架兜底（只读派生）。"""
        store = _store()
        now = _now()
        rows = [r for r in store.stances_asof(now) if r.event_id == event_id]
        if not rows:
            raise HTTPException(404, "no stances for event")
        wanted = {r.item_key for r in rows}
        src_by_key: dict[str, str] = {r.item_key: r.source_id for r in rows}
        registry = EntityRegistry()
        docs: list[dict[str, Any]] = []
        for rec in _bronze().iter_records():
            if rec.item_key not in wanted:
                continue
            body = strip_html(str(rec.normalized.get("body") or rec.normalized.get("title") or ""))
            sents: list[dict[str, Any]] = []
            for base, parsed in zip(
                sentence_spectrum(body), parse_passage(body, registry), strict=False
            ):
                sents.append({**base, "spans": parsed["entities"] + parsed["actions"]})
            docs.append(
                {
                    "item_key": rec.item_key,
                    "source_id": src_by_key.get(rec.item_key, ""),
                    "title": str(rec.normalized.get("title") or ""),
                    "published_at": str(rec.normalized.get("published_at") or ""),
                    "sentences": sents,
                }
            )
        docs.sort(key=lambda d: (d["published_at"], d["item_key"]))
        return docs

    @app.get("/api/events/{event_id}/anatomy")
    def event_anatomy(event_id: str) -> dict[str, Any]:
        """分歧构成：NDI 拆解为簇对 JSD × 主体对立表（交互下钻的数据层）。"""
        store = _store()
        now = _now()
        rows = [r for r in store.stances_asof(now) if r.event_id == event_id]
        if not rows:
            raise HTTPException(404, "no stances for event")
        tier_map = _tier_map()
        series = store.ndi_series(event_id, language="all")
        latest = next((p for p in reversed(series) if p.status == "ok"), None)
        return {
            "event_id": event_id,
            "ndi": (
                {"ndi": latest.ndi, "ts": latest.ts, "n_sources": latest.n_sources}
                if latest is not None
                else None
            ),
            "clusters": cluster_distributions(rows, tier_map),
            "cluster_pairs": cluster_pairwise(rows, tier_map),
            "entity_opposition": entity_opposition(rows, tier_map),
        }

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

    @app.post("/api/chat")
    async def chat(body: dict[str, str]) -> dict[str, Any]:
        """多轮会话情报 Agent（chat_graph；无 keys/config 降级离线聚合）。"""
        message = body.get("message", "").strip()
        if not message:
            raise HTTPException(422, "message required")
        thread_id = body.get("thread_id") or uuid4().hex[:12]
        cs = _chat_store()
        now = _now()
        ts = now.isoformat()
        history = [{"role": m["role"], "content": m["content"]} for m in cs.messages(thread_id)]
        cs.append(thread_id, "user", message, ts)
        try:
            result = await run_chat(
                message,
                history,
                bronze=_bronze(),
                store=_store(),
                gold=_store(),
                registry=_registry(),
                router=_chat_router(),
                gdelt_proxy=os.getenv("OHNEWS_GDELT_PROXY"),
                now=now,
            )
        except Exception as exc:  # LLM 全候选失败→离线聚合降级回复，绝不裸 500
            try:
                fallback = await run_chat(
                    message,
                    history,
                    bronze=_bronze(),
                    store=_store(),
                    gold=_store(),
                    registry=_registry(),
                    router=None,
                    gdelt_proxy=os.getenv("OHNEWS_GDELT_PROXY"),
                    now=now,
                )
                degraded = (
                    f"（模型调用未成功，以下为确定性数据摘要。\n失败原因节选：{str(exc)[:160]}）\n\n"
                )
                result = {
                    **fallback,
                    "reply": degraded + fallback["reply"],
                    "llm_error": str(exc)[:300],
                }
            except Exception as exc2:  # 连离线聚合都失败→最小回复
                result = {
                    "reply": f"服务暂时不可用：{str(exc2)[:200]}",
                    "citations": [],
                    "tools_used": [],
                    "rounds": 0,
                }
        cs.append(thread_id, "assistant", result["reply"], now.isoformat())
        await publish_sse(
            "chat_done",
            {
                "thread_id": thread_id,
                "rounds": result["rounds"],
                "tools": list(result["tools_used"]),
            },
        )
        return {
            "thread_id": thread_id,
            "reply": result["reply"],
            "citations": list(result["citations"]),
            "tools_used": list(result["tools_used"]),
            "rounds": result["rounds"],
            "offline": _chat_router() is None,
        }

    @app.post("/api/agent/invoke")
    async def agent_invoke(body: dict[str, Any]) -> dict[str, Any]:
        """Intent 驱动入口（REDESIGN_AGENT：按钮 → Intent → Orchestrator → Agent）。

        router 缺失 → 离线五层 Artifact（确定性模板）；router 在 → chat 图
        注入 ContextPacket。tier_map/type 校验失败 → 422。
        """
        intent_raw = str(body.get("intent", "")).strip()
        target_kind_raw = str(body.get("target_kind", "")).strip()
        target_id = str(body.get("target_id", "")).strip()
        if not intent_raw or not target_kind_raw or not target_id:
            raise HTTPException(422, "intent/target_kind/target_id required")
        if target_kind_raw not in ("signal", "event", "entity", "topic"):
            raise HTTPException(422, f"unknown target_kind: {target_kind_raw}")
        try:
            intent = Intent(
                intent=intent_raw,  # type: ignore[arg-type]
                target_kind=target_kind_raw,  # type: ignore[arg-type]
                target_id=target_id,
                message=body.get("message") or None,
            )
        except Exception as exc:
            raise HTTPException(422, f"invalid intent: {exc}") from exc

        now = _now()
        packet = build_context_packet(
            intent,
            bronze=_bronze(),
            store=_store(),
            gold=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            now=now,
            min_per_source=int(body.get("min_per_source", 10)),
        )
        router = _chat_router()
        if router is None:
            art = offline_artifact(packet)
            return {
                "offline": True,
                "packet": packet.model_dump(mode="json"),
                "artifact": art.model_dump(mode="json"),
            }
        result = await run_intent(
            packet,
            bronze=_bronze(),
            store=_store(),
            gold=_store(),
            registry=_registry(),
            router=router,
            gdelt_proxy=os.getenv("OHNEWS_GDELT_PROXY"),
            now=now,
        )
        await publish_sse("agent_done", {"intent": intent.intent.value, "target": target_id})
        return {"offline": False, "packet": packet.model_dump(mode="json"), **result}

    @app.get("/api/chat/threads")
    def chat_threads() -> list[dict[str, Any]]:
        return _chat_store().threads()

    @app.get("/api/chat/{thread_id}/messages")
    def chat_messages(thread_id: str) -> list[dict[str, Any]]:
        return _chat_store().messages(thread_id)

    def _ndi_percentile(latest: float) -> float | None:
        pts = [p.ndi for p in _store().ndi_all() if p.ndi is not None]
        if len(pts) < 5:
            return None
        below = sum(1 for v in pts if v <= latest)
        return below / len(pts)

    @app.post("/api/intel/run")
    async def intel_run(body: dict[str, str] | None = None) -> dict[str, Any]:
        """一轮六角色情报循环（Scout→Cartographer→ACH→Chief；无 keys 离线降级）。"""
        from oh_agents.intel.intel_graph import run_intel_cycle

        now = _now()
        events = _store().events_asof(now)
        if not events:
            raise HTTPException(404, "no events in scope")
        stances = _store().stances_asof(now)
        by_event: dict[str, int] = {}
        for s in stances:
            by_event[s.event_id] = by_event.get(s.event_id, 0) + 1
        tier_map = _tier_map()
        official = sum(1 for s in stances if tier_map.get(s.source_id) is SourceTier.OFFICIAL)
        pts = _store().ndi_all()
        ok = [p.ndi for p in pts if p.ndi is not None]
        rep = await run_intel_cycle(
            events=events,
            stances_by_event=by_event,
            official_rows=official,
            total_rows=len(stances),
            ndi_points=pts,
            ndi_percentile=_ndi_percentile(ok[-1]) if ok else None,
            now=now,
            router=_chat_router(),
            scope=(body or {}).get("scope") or "全库巡逻",
        )
        _intel_ledger().save(rep)
        await publish_sse("intel_done", {"report_id": rep.report_id, "engine": rep.engine})
        return rep.model_dump(mode="json")

    @app.get("/api/intel/latest")
    def intel_latest() -> dict[str, Any]:
        reps = _intel_ledger().latest(1)
        if not reps:
            raise HTTPException(404, "no intel reports")
        return reps[0].model_dump(mode="json")

    @app.get("/api/intel/reports")
    def intel_reports(n: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "report_id": r.report_id,
                "created_at": r.created_at,
                "scope": r.scope,
                "engine": r.engine,
                "summary": r.summary,
            }
            for r in _intel_ledger().latest(n)
        ]

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
