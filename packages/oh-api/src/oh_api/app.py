"""FastAPI 应用：只读数据端点 + 问诊 + 决策日志 + SSE 总线 v0。

依赖注入：create_app(paths) 传数据路径；连接惰性创建。
SSE v0：进程内 asyncio 总线（裁决 D：单进程零 Redis），
其他模块经 publish_sse() 推流；Last-Event-ID 语义 Phase 5b 完善。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from oh_agents.alerts import check_alerts
from oh_agents.archive import ArchiveStore
from oh_agents.chat import ChatStore, run_chat, run_chat_command
from oh_agents.decision_log import DecisionLog
from oh_agents.dissection_agent import (
    build_dissection_graph,
    build_queue_suggestions,
    fallback_elements_from_hints,
)
from oh_agents.intel_pipeline import build_daily_intel
from oh_agents.morning_brief import build_brief
from oh_agents.orchestrator import (
    answer_question,
    build_context_packet,
    offline_artifact,
    run_intent,
)
from oh_agents.parent_planner import build_research_plan
from oh_agents.report_agent import REPORT_KIND_ZH, build_report_graph
from oh_agents.research import run_research
from oh_agents.specialists import SPECIALISTS
from oh_agents.tracking import TrackingStore
from oh_agents.translation_agent import build_translation_graph
from oh_agents.watch_update import compute_watch_update
from oh_api.agents import build_router as build_agent_sessions_router
from oh_api.briefing import _corpus_lang, build_briefing, build_briefing_with_signals, build_dossier
from oh_api.change_landscape import build_change_field, build_change_landscape
from oh_api.charts import build_emotion_density, build_flow_daily, build_ndi_rank
from oh_api.metrics import build_router as build_metrics_router
from oh_api.object_api import build_collection_router, build_object_router, build_workflow_router
from oh_api.search import build_router as build_search_router
from oh_contracts.archive import ARCHIVE_KINDS, AgentPaper, ArchiveItem
from oh_contracts.belief import BeliefCreate, BeliefSnapshot
from oh_contracts.briefing import BriefingResponse, ChangeDossier, EvidenceCitation
from oh_contracts.change_landscape import ChangeFieldPayload, ChangeLandscape
from oh_contracts.dissection import ArticleDissection
from oh_contracts.enums import SourceTier, Tier
from oh_contracts.intents import Intent
from oh_contracts.reports import AgentReport
from oh_contracts.schemas import NDIPoint
from oh_contracts.text import strip_html
from oh_contracts.tracking import TrackingUnit
from oh_contracts.translations import TRANSLATION_TARGETS, TranslationItem
from oh_contracts.watching import WatchReview, WatchUpdate
from oh_pipeline.anatomy import cluster_distributions, cluster_pairwise, entity_opposition
from oh_pipeline.detect import detect_signals
from oh_pipeline.entities import DEFAULT_ENTITIES, EntityRegistry
from oh_pipeline.event_status import assess_event
from oh_pipeline.evidence import build_evidence
from oh_pipeline.spectra import sentence_spectrum
from oh_pipeline.svo import parse_passage
from oh_storage.bronze_parquet import ParquetBronzeWriter
from oh_storage.connection import connect
from oh_storage.research_store import ResearchStore
from oh_storage.sqlite_store import SqliteStore
from pydantic import BaseModel, Field, ValidationError

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


_RE_TAG = re.compile(r"<[^>]+>")

# Monitor scheduler worker 单例（跨 create_app 调用；pytest 由 OHNEWS_SCHEDULER=0 关闭）
_SCHEDULER_WORKERS: dict[str, Any] = {}


def _strip_tags(text: str) -> str:
    """剥离 HTML 标签（收件箱预览展示用；内容本身不变）。"""
    stripped = _RE_TAG.sub(" ", text)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        stripped = stripped.replace(entity, char)
    return stripped.strip()


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


class SourceDiscoveryOutput(BaseModel):
    """Agent 对 URL 的可注册建议；注册仍必须经过用户确认。"""

    source_id: str = Field(pattern=r"^[a-z0-9_-]{2,40}$")
    adapter: Literal["rss", "json_api", "html", "browser"]
    tier: Literal["L1", "L2", "L3", "L4"]
    language: str = Field(pattern=r"^[a-z]{2,8}$")
    source_subject: str = Field(min_length=1, max_length=160)
    method: str = Field(min_length=1, max_length=240)
    expected_frequency: str = Field(min_length=1, max_length=80)
    rationale: str = Field(min_length=1, max_length=500)
    caveats: list[str] = Field(default_factory=list, max_length=5)
    confidence: float = Field(ge=0, le=1)


class MonitorAnalysisOutput(BaseModel):
    """监测增量的结构化分析；只允许基于 update 与引用文章。"""

    executive_summary: str = Field(min_length=1, max_length=700)
    what_changed: list[str] = Field(default_factory=list, max_length=5)
    evidence_assessment: list[str] = Field(default_factory=list, max_length=5)
    uncertainties: list[str] = Field(default_factory=list, max_length=5)
    recommended_review: str = Field(min_length=1, max_length=400)


def _lang_map(path: Path) -> dict[str, str]:
    """source_id → language（双语化数据层：briefing/watch 按语料 majority 语言出文案）。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    out: dict[str, str] = {}
    for item in doc.get("sources", []):
        sid = item.get("source_id")
        lang = item.get("language")
        if sid and lang:
            out[str(sid)] = str(lang)
    return out


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


class HomePayload(BaseModel):
    """首页单次聚合响应（T4）：消除前端多请求竞态与重复 briefing_viewed。"""

    briefing: BriefingResponse
    landscape: ChangeLandscape
    watches: list[dict[str, Any]]


class PlanRequestBody(BaseModel):
    """POST /api/agent/plan 请求体（question 可选覆盖 Case 研究问题）。

    必须模块级定义：app.py 启用 `from __future__ import annotations`，
    函数内局部类的字符串注解 FastAPI 解析不到会退化为 query 参数。
    """

    case_id: str
    question: str = ""


class TrackEventIn(BaseModel):
    """前端埋点事件（阶段 1-e 闭集）。"""

    event: Literal[
        "briefing_viewed",
        "change_opened",
        "change_dismissed_as_noise",
        "evidence_opened",
        "source_opened",
        "counter_evidence_requested",
        "insufficient_evidence_seen",
        "investigation_started",
        "judgment_saved",
        "judgment_change_type",
        "watch_created",
        "watch_update_reviewed",
        "case_created",
        "case_closed",
    ]
    session: str = Field(min_length=1)


class _WatchLike:
    """C3：TrackingUnit → compute_watch_update 的 watch 适配（.type/.query/.last_checked_at）。"""

    def __init__(self, unit: Any) -> None:
        self.watch_id = unit.unit_id
        self.type = unit.kind
        self.query = unit.query
        self.last_checked_at = unit.last_checked_at


def create_app(paths: AppPaths | None = None) -> FastAPI:
    paths = paths or AppPaths()
    from oh_api.ingestion import Ingestion, build_ingestion_router

    ingestion = Ingestion(paths.root, paths.sources_yaml)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if os.getenv("OHNEWS_SCHEDULER", "1") == "1":
            ingestion.start()
        try:
            yield
        finally:
            ingestion.stop.set()
            if ingestion.thread:
                await asyncio.to_thread(ingestion.thread.join, 8)

    app = FastAPI(title="OH!News API", version="0.1.0", lifespan=lifespan)
    app.include_router(build_ingestion_router(ingestion))

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

    def _lang_map_safe() -> dict[str, str]:
        return _lazy("lang_map", lambda: _lang_map(paths.sources_yaml))

    def _corpus_lang_safe() -> str:
        return _corpus_lang(list(_bronze().iter_records()), _lang_map_safe())

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

    def _product_events() -> Any:
        from oh_agents.product_events import ProductEventStore

        db = paths.root / "product_events.sqlite"
        return _lazy("product_events", lambda: ProductEventStore(db))

    def _archive() -> Any:
        """Phase D 档案库（确认式存档；agent 报纸组合）。"""
        cached = getattr(app.state, "_archive_store", None)
        if cached is None:
            cached = ArchiveStore(paths.root / "archive.sqlite")
            app.state._archive_store = cached
        return cached

    def _beliefs() -> Any:
        from oh_agents.beliefs import BeliefStore

        db = paths.root / "belief.sqlite"
        return _lazy("beliefs", lambda: BeliefStore(db))

    # Clean-slate Phase 1：research.sqlite 新对象库（零改动旧库）
    def _research() -> Any:
        from oh_storage.research_store import ResearchStore

        return _lazy(
            "research",
            lambda: ResearchStore.open(paths.root / "research.sqlite"),
        )

    # Clean-slate Phase 2：案例分析线工作流（keys 缺失时 router=None → offline 诚实降级）
    def _workflows() -> Any:
        from oh_agents.case_workflows import CaseWorkflows

        return _lazy(
            "workflows",
            lambda: CaseWorkflows(
                research=_research(),
                router=_chat_router(),
                now_fn=lambda: _now().isoformat(),
                # 必须大于 router 内部超时（models.yaml timeout_s=180），
                # 否则外层 asyncio.timeout 先触发且 str(TimeoutError) 为空，根因不可见。
                llm_timeout=320.0,
            ),
        )

    # 子路由（全局搜索 / 埋点指标）——模块化 APIRouter，主线统一挂载
    app.include_router(
        build_search_router(
            lambda: _bronze().iter_records(),
            events_fn=lambda: _store().events_asof(_now()),
            alias_fn=lambda: [a for eid in _registry().ids() for a in _registry().get(eid).aliases],
            # P1-A 五类型精确定位：案例/监测器/实体清单注入（小集合线性扫描）
            cases_fn=lambda: [
                {
                    "case_id": c.case_id,
                    "title": c.title,
                    "question": c.question,
                    "status": c.status,
                }
                for c in _research().list_cases()
            ],
            monitors_fn=lambda: [
                {
                    "monitor_id": m.monitor_id,
                    "question": m.question,
                    "target_ref": m.target_ref,
                    "status": m.status,
                }
                for m in _research().list_monitors()
            ],
            entities_fn=lambda: [
                {"entity_id": e.entity_id, "aliases": list(e.aliases)} for e in DEFAULT_ENTITIES
            ],
        )
    )
    app.include_router(build_metrics_router(lambda: _product_events()))
    app.include_router(
        build_object_router(
            lambda: _research(),
            _now,
            # P0-B Monitor 执行闭环：按线程惰性构建 bronze 迭代器（后台线程内重取）
            lambda: _bronze().iter_records(),
            # R10 判断变化线：Belief 快照存储（belief.sqlite）
            lambda: _beliefs(),
        )
    )
    app.include_router(
        build_workflow_router(lambda: _workflows(), lambda: _research(), now_fn=_now)
    )
    app.include_router(build_collection_router(lambda: _research()))

    # ---- 阶段0e：启动清理——进程重启遗留的 queued/running → failed（interrupted）----
    def _reap_on_startup() -> int:
        store = ResearchStore.open(paths.root / "research.sqlite")
        try:
            n1 = store.reap_stale_runs(finished_at=_now().isoformat())
            n2 = store.reap_stale_monitor_runs(finished_at=_now().isoformat())
            return n1 + n2
        finally:
            store.close()

    _reap_on_startup()

    # ---- 第十一轮 P0-D：真实 Monitor scheduler worker ----
    # 环境变量 gate（默认开）：pytest 场景设 OHNEWS_SCHEDULER=0 防后台线程副作用。
    # 模块级单例：uvicorn reload/多次 create_app 不重复起线程。
    if os.getenv("OHNEWS_SCHEDULER", "1") == "1" and "worker" not in _SCHEDULER_WORKERS:
        from oh_agents.scheduler_worker import SchedulerWorker

        def _sched_store() -> ResearchStore:
            return ResearchStore.open(paths.root / "research.sqlite")

        worker = SchedulerWorker(_sched_store, lambda: _bronze().iter_records())
        worker.start()
        _SCHEDULER_WORKERS["worker"] = worker

    @app.get("/api/scheduler/heartbeat", include_in_schema=True)
    def scheduler_heartbeat() -> dict[str, Any]:
        """调度 worker 心跳：alive/ticks/fired_total/last_error（进程级真值）。"""
        worker = _SCHEDULER_WORKERS.get("worker")
        if worker is None:
            return {
                "alive": False,
                "note": "scheduler worker not started (OHNEWS_SCHEDULER=0 or reload race)",
            }
        return worker.heartbeat()

    # ---- 阶段0b：真实 LLM 健康检查（轻量 ping + 60s 缓存；非 key 存在性检查）----
    _llm_health: dict[str, Any] = {
        "ts": 0.0,
        "ready": False,
        "detail": "not checked",
        "latency_ms": 0,
    }

    def _ping_llm(force: bool = False) -> dict[str, Any]:
        import time as _time

        now = _time.time()
        if not force and now - float(_llm_health["ts"]) < 60.0:
            return {k: _llm_health[k] for k in ("ready", "detail", "latency_ms", "checked_at")}
        checked_at = _now().isoformat()
        router = _chat_router()
        if router is None:
            _llm_health.update(
                ts=now,
                ready=False,
                detail="router not configured",
                latency_ms=0,
                checked_at=checked_at,
            )
        else:
            t0 = _time.perf_counter()
            try:
                asyncio.run(
                    router.raw_complete(
                        Tier.EXECUTE,
                        "You are a connectivity health check.",
                        "Reply with the single word OK.",
                    )
                )
                _llm_health.update(
                    ts=now,
                    ready=True,
                    detail="ping ok",
                    latency_ms=int((_time.perf_counter() - t0) * 1000),
                    checked_at=checked_at,
                )
            except Exception as exc:  # noqa: BLE001 - 健康检查捕获一切并如实报告
                _llm_health.update(
                    ts=now,
                    ready=False,
                    detail=str(exc) or type(exc).__name__,
                    latency_ms=int((_time.perf_counter() - t0) * 1000),
                    checked_at=checked_at,
                )
        return {
            "ready": _llm_health["ready"],
            "detail": _llm_health["detail"],
            "latency_ms": _llm_health["latency_ms"],
            "checked_at": _llm_health.get("checked_at") or checked_at,
        }

    @app.get("/api/llm/health")
    def llm_health(refresh: bool = False) -> dict[str, Any]:
        """真实连通性：轻量 ping（60s 缓存；?refresh=true 强制）。"""
        return _ping_llm(force=refresh)

    # 后台预热（不阻塞启动；失败静默——端点可再次查询）
    def _warmup() -> None:
        import time as _t

        _t.sleep(3.0)
        try:
            _ping_llm()
        except Exception:
            pass

    threading.Thread(target=_warmup, daemon=True, name="llm-health-warmup").start()

    # ---- Agent 会话（A4）：会话账本 + user_gate 随时补充输入 ----
    def _agent_sessions() -> Any:
        from oh_agents.agent_base import AgentSessions

        singleton = getattr(app.state, "_agent_sessions", None)
        if singleton is None:
            singleton = AgentSessions(paths.root / "agent_sessions.sqlite")
            app.state._agent_sessions = singleton
        return singleton

    app.include_router(build_agent_sessions_router(lambda: _agent_sessions()))

    class ParentBrief(BaseModel):
        """E2：总控台简报（确定性汇总，不跑 LLM）。"""

        sessions_by_kind: dict[str, int]
        latest_session: dict[str, Any] | None
        queue_pending: int
        queue_top: list[dict[str, Any]]
        providers: dict[str, bool]
        health: dict[str, int]
        suggestions: list[str]

    @app.get("/api/agent/parent/brief", response_model=ParentBrief)
    def parent_brief() -> ParentBrief:
        """汇总 02/03/04 会话、拆解队列、供应商与数据健康（07 需求 c/d）。"""
        sessions = _agent_sessions().list_sessions()
        by_kind: dict[str, int] = {}
        for row in sessions:
            k = str(row.get("agent_kind") or "?")
            by_kind[k] = by_kind.get(k, 0) + 1
        latest = max(
            sessions,
            key=lambda r: str(r.get("last_active_at") or ""),
            default=None,
        )
        pending = _store().queue_items(status="pending", limit=5)
        queue_count = len(_store().queue_items(status="pending", limit=200))
        providers = {
            "deepseek": bool(_get_key("deepseek")),
            "zhipu": bool(_get_key("zhipu")),
            "tavily": bool(_get_key("tavily")),
        }
        health = {
            "events": _store().count_events(),
            "stances": _store().count_stances(),
            "dissections": _store().count_dissections(),
        }
        tips: list[str] = []
        if queue_count:
            tips.append(f"拆解队列有 {queue_count} 篇待处理——到调查台接受或忽略")
        if not providers["zhipu"] and not providers["deepseek"]:
            tips.append("尚未配置模型 Key——拆解与报告将走词典降级")
        if not tips:
            tips.append("一切正常——变化、拆解、报告链路可用")
        return ParentBrief(
            sessions_by_kind=by_kind,
            latest_session=latest,
            queue_pending=queue_count,
            queue_top=pending,
            providers=providers,
            health=health,
            suggestions=tips,
        )

    @app.get("/api/agent/dissect/suggestions")
    def agent_queue_suggestions(limit: int = 5) -> list[dict[str, Any]]:
        """B0：现场打分并幂等入队，返回建议列表（用户确认后进入拆解队列）。"""
        return build_queue_suggestions(
            _bronze().iter_records(),
            tier_map=_tier_map(),
            registry=_registry(),
            now=_now(),
            store=_store(),
            limit=max(1, min(limit, 20)),
        )

    @app.post("/api/agent/dissect/queue")
    def agent_queue_decide(body: dict[str, Any]) -> dict[str, Any]:
        """B0：用户裁决（accept=进入拆解队列 / dismiss=忽略）。"""
        item_key = str(body.get("item_key") or "")
        action = str(body.get("action") or "")
        if not item_key or action not in {"accept", "dismiss"}:
            raise HTTPException(status_code=422, detail="item_key 与 action(accept|dismiss) 必填")
        status = "accepted" if action == "accept" else "dismissed"
        ok = _store().queue_decide(item_key, status=status, decided_at=_now().isoformat())
        if not ok:
            raise HTTPException(status_code=404, detail="队列中无此 item_key")
        return {"ok": True, "status": status}

    @app.post("/api/agent/dissect", response_model=ArticleDissection)
    async def agent_dissect(body: dict[str, Any]) -> ArticleDissection:
        """B1 文章拆解：item_key → 18 元素（缓存复用，force=true 重拆）。

        LLM 全候选失败 → offline 词典兜底（engine=offline，诚实降级）。
        """
        item_key = str(body.get("item_key", "")).strip()
        force = bool(body.get("force", False))
        if not item_key:
            raise HTTPException(status_code=422, detail="item_key 必填")
        store = _store()
        if not force:
            cached = store.get_dissection(item_key)
            if cached is not None:
                cached["cached"] = True  # 仅供展示；ArticleDissection 无此字段则忽略
                cached.pop("cached", None)
                return ArticleDissection.model_validate(cached)
        rec = next((r for r in _bronze().iter_records() if r.item_key == item_key), None)
        if rec is None:
            raise HTTPException(status_code=404, detail="bronze 无此 item_key")
        norm = rec.normalized or {}
        text = str(norm.get("body") or norm.get("title") or rec.raw or "")
        hint = store.get_annotation(item_key) or {}
        graph = build_dissection_graph(
            router=_chat_router(),
            store=store,
            fallback_fn=lambda _s: fallback_elements_from_hints(hint),
            now_fn=_now,
        )
        out = await graph.ainvoke(
            {
                "item_key": item_key,
                "title": str((rec.normalized or {}).get("title") or ""),
                # 全文传图（agent 内部按句界分块，spans 覆盖全文）；20000 防极端超长
                "text": text[:20000],
                "language": str((rec.normalized or {}).get("language") or ""),
                "hints": json.dumps(hint, ensure_ascii=False)[:1500],
            }
        )
        return out["dissection"]

    @app.get("/api/articles/detail")
    def article_detail(source_id: str, item_key: str) -> dict[str, Any]:
        """单文全文（搜索→研究入口）：取 bronze 原文不截断，供一键入案。"""
        rec = next(
            (
                r
                for r in _bronze().iter_records()
                if r.item_key == item_key and (not source_id or r.source_id == source_id)
            ),
            None,
        )
        if rec is None:
            raise HTTPException(status_code=404, detail="bronze 无此 item_key")
        norm = rec.normalized or {}
        return {
            "item_key": rec.item_key,
            "source_id": rec.source_id,
            "title": _strip_tags(str(norm.get("title") or "")),
            "url": str(norm.get("url") or ""),
            # 剥离 HTML 标签：入案正文必须为纯文本，拆解 span 偏移才与渲染一致
            "body": _strip_tags(str(norm.get("body") or norm.get("title") or rec.raw or "")),
            "published_at": (rec.published_at or rec.fetched_at).isoformat(),
            "language": str(norm.get("language") or ""),
        }

    @app.get("/api/inbox")
    def inbox(
        source_id: list[str] = Query(default_factory=list),  # noqa: B008
        q: str = "",
        language: str = "",
        days: int = 0,
        element: str = "",
        value: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """研究收件箱：bronze 多条件筛选 + cased/dissected 标记 + 元素级筛选。

        - source_id 多选（空=全部源，按时间倒序取 limit）
        - q 对 title+body 子串（大小写不敏感）；language 精确；days 时间窗
        - element/value 查 silver 历史拆解缓存（如 actor=美联储）
        - cased/dissected 来自 research 库 external_key 联查
        """
        research = _research()
        cased = research.cased_keys()
        dissected = research.dissected_keys()
        silver = _store()
        now = _now()

        def _search(query: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for rec in _bronze().iter_records():
                norm = rec.normalized or {}
                if source_id and rec.source_id not in source_id:
                    continue
                rec_lang = str(norm.get("language") or "")
                if language and rec_lang != language:
                    continue
                pub = rec.published_at or rec.fetched_at
                if days > 0 and pub is not None and (now - pub).days > days:
                    continue
                title = str(norm.get("title") or "")
                body = str(norm.get("body") or "")
                t_hit = True
                if query:
                    ql = query.lower()
                    if ql not in title.lower() and ql not in body.lower():
                        continue
                    t_hit = ql in title.lower()
                if element and value:
                    d = silver.get_dissection(rec.item_key)
                    els = d.get("elements") if isinstance(d, dict) else None
                    hit = any(
                        isinstance(e, dict)
                        and e.get("element") == element
                        and value.lower() in str(e.get("content") or "").lower()
                        for e in (els or [])
                    )
                    if not hit:
                        continue
                rows.append(
                    {
                        "item_key": rec.item_key,
                        "source_id": rec.source_id,
                        "title": _strip_tags(title),
                        "url": str(norm.get("url") or ""),
                        "language": rec_lang,
                        "published_at": pub.isoformat() if hasattr(pub, "isoformat") else str(pub),
                        "body_preview": _strip_tags(body)[:200],
                        "cased": rec.item_key in cased,
                        "dissected": rec.item_key in dissected,
                        "title_match": t_hit,
                    }
                )
            rows.sort(
                key=lambda r: (bool(r["title_match"]), str(r["published_at"])),
                reverse=True,
            )
            return rows[:limit]

        rows = _search(q.strip())
        q_effective = q.strip()
        # 诚实降级（P0-D 主路径保障）：实体规范化名（如"中国财政部"）常不等于
        # bronze 原文措辞（正文写"财政部"）；全名 0 命中且为 CJK 长词时，按去尾/
        # 去头双向生成子串候选，长度降序逐个重试（上限 4 次），q_effective 如实
        # 披露实际生效的检索词。
        has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in q_effective)
        if not rows and len(q_effective) >= 3 and has_cjk:
            words = q_effective.split() or [q_effective]
            candidates: list[str] = []
            for w in words:
                if len(w) < 2:
                    continue
                for i in range(1, len(w) - 1):
                    candidates.append(w[:-i])
                    candidates.append(w[i:])
                candidates.append(w[1:])
            for cand in sorted(dict.fromkeys(candidates), key=len, reverse=True)[:4]:
                trial = _search(cand)
                if trial:
                    rows = trial
                    q_effective = cand
                    break
        return {"n": len(rows), "rows": rows, "q_effective": q_effective}

    @app.post("/api/agent/translate", response_model=TranslationItem)
    async def agent_translate(body: dict[str, Any]) -> TranslationItem:
        """E1：翻译学家工作流——生成翻译副本（独立表，不改写原文）。

        LLM 失败/超时 → engine=offline 空译文诚实降级。
        """
        item_key = str(body.get("item_key") or "")
        target = str(body.get("target_language") or "en")
        if not item_key or target not in TRANSLATION_TARGETS:
            raise HTTPException(status_code=422, detail="item_key 与合法 target_language 必填")
        rec = next((r for r in _bronze().iter_records() if r.item_key == item_key), None)
        if rec is None:
            raise HTTPException(status_code=404, detail="bronze 无此 item_key")
        norm = rec.normalized or {}
        title = str(norm.get("title") or "")
        text = str(norm.get("body") or title or rec.raw or "")[:2500]
        lang = str(norm.get("language") or "")
        out = await build_translation_graph(
            router=_chat_router(), store=_store(), now_fn=_now
        ).ainvoke(
            {
                "item_key": item_key,
                "title": title,
                "text": text,
                "source_language": lang,
                "target_language": target,
            }
        )
        return TranslationItem.model_validate(out["translation"])

    @app.get(
        "/api/agent/translations/{item_key:path}",
        response_model=TranslationItem | None,
    )
    def agent_translation(item_key: str, target_language: str = "en") -> TranslationItem | None:
        """已存翻译副本（按目标语言；无则 None）。"""
        if target_language not in TRANSLATION_TARGETS:
            raise HTTPException(status_code=422, detail="非法 target_language")
        row = _store().get_translation(item_key, target_language)
        return TranslationItem.model_validate(row) if row else None

    @app.post("/api/agent/report", response_model=AgentReport)
    async def agent_report(body: dict[str, Any]) -> AgentReport:
        """B2：基于已存拆解生成六型研究报告（llm，失败降级 offline）。

        item_key 必须已拆解（409 先拆解）且 bronze 存在（404）。
        """
        item_key = str(body.get("item_key") or "")
        kind = str(body.get("kind") or "")
        if not item_key or kind not in REPORT_KIND_ZH:
            raise HTTPException(status_code=422, detail="item_key 与合法 kind 必填")
        store = _store()
        dis = store.get_dissection(item_key)
        if dis is None:
            raise HTTPException(status_code=409, detail="该文章尚未拆解，请先拆解再生成报告")
        rec = next((r for r in _bronze().iter_records() if r.item_key == item_key), None)
        if rec is None:
            raise HTTPException(status_code=404, detail="bronze 无此 item_key")
        norm = rec.normalized or {}
        text = str(norm.get("body") or norm.get("title") or rec.raw or "")[:2500]
        graph = build_report_graph(router=_chat_router(), store=store, now_fn=_now)
        out = await graph.ainvoke(
            {
                "item_key": item_key,
                "kind": kind,
                "text": text,
                "dissection_json": json.dumps(dis, ensure_ascii=False)[:6000],
            }
        )
        return out["report"]

    @app.get(
        "/api/agent/reports/{item_key:path}",
        response_model=list[AgentReport],
    )
    def agent_reports(item_key: str) -> list[AgentReport]:
        """某文章全部研究报告（按 created_at 升序）。"""
        out: list[AgentReport] = []
        for r in _store().reports_for_item(item_key):
            try:
                out.append(AgentReport.model_validate(r))
            except ValidationError:
                continue
        return out

    @app.get("/api/agent/dissections/{item_key:path}", response_model=ArticleDissection | None)
    def agent_dissection_get(item_key: str) -> ArticleDissection | None:
        d = _store().get_dissection(item_key)
        return ArticleDissection.model_validate(d) if d else None

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
        for env_name in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "TAVILY_API_KEY"):
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
            "tavily": _get_key("tavily") is not None,
            "llm_ready": _chat_router() is not None,
        }

    @app.post("/api/keys")
    def keys_save(body: dict[str, str]) -> dict[str, Any]:
        """保存运行时 keys（热生效，无需重启；持久化到 gitignored runtime_keys.json）。"""
        allowed = {"DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "TAVILY_API_KEY"}
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

    @app.get("/api/briefing", response_model=BriefingResponse)
    def briefing(
        days: int = 3, top: int = 5, lang: str = "zh", min_per_source: int = 10
    ) -> BriefingResponse:
        """产品 Briefing（阶段 1-b）：DataFreshness + ChangeBrief 队列（人话语义）。

        changes 为空 = 「今天没有值得看的变化」显式状态（硬验收 7）。
        """
        return build_briefing(
            bronze_iter=_bronze().iter_records(),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            lang=lang,
            lang_by_source=_lang_map_safe(),
            now=_now(),
            days=max(1, days),
            top=top,
            min_per_source=min_per_source,
        )

    @app.get("/api/flow/daily")
    def flow_daily(days: int = 30) -> list[dict[str, Any]]:
        """G1：每日文章量按语言分列（bronze published_at 计数，PIT ts≤now）。"""
        doc: dict[str, Any] = {}
        if paths.sources_yaml.exists():
            with paths.sources_yaml.open(encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        raw_sources = doc.get("sources") or {}
        if isinstance(raw_sources, list):
            # 真实 sources.yaml 为条目列表（每项含 source_id/language）
            lang_by_source = {
                str(item.get("source_id")): str(item.get("language") or "other")
                for item in raw_sources
                if isinstance(item, dict) and item.get("source_id")
            }
        else:
            lang_by_source = {
                sid: str((cfg or {}).get("language") or "other") for sid, cfg in raw_sources.items()
            }
        return build_flow_daily(
            list(_bronze().iter_records()),
            lang_by_source=lang_by_source,
            now=_now(),
            days=max(1, min(days, 120)),
        )

    @app.get("/api/ndi/rank")
    def ndi_rank(limit: int = 8) -> list[dict[str, Any]]:
        """G3：实体分歧榜——每实体最新可测 NDI 降序 Top-N（弃权点不计）。"""
        return build_ndi_rank(
            _store().ndi_all(), registry=_registry(), now=_now(), limit=max(1, min(limit, 20))
        )

    @app.get("/api/annotations/emotion")
    def annotations_emotion(days: int = 30) -> list[dict[str, Any]]:
        """G4：每日情绪密度均值时序（S1 annotations expressed）。"""
        return build_emotion_density(
            _store().annotations_asof(_now()), now=_now(), days=max(1, min(days, 120))
        )

    @app.get("/api/annotations/actions")
    def annotations_actions(days: int = 30) -> dict[str, Any]:
        """动作脉冲：按文章发布时间聚合词典 SRL action，绝不把它伪装成情绪。"""
        now = _now()
        since = now - timedelta(days=max(1, min(days, 120)))
        daily: Counter[str] = Counter()
        directions: Counter[str] = Counter()
        evidence: dict[str, list[dict[str, str]]] = defaultdict(list)
        registry = EntityRegistry()
        for rec in _bronze().iter_records():
            raw_ts = (rec.normalized or {}).get("published_at") or rec.published_at
            try:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if not since <= ts <= now:
                continue
            body = strip_html(str((rec.normalized or {}).get("body") or ""))[:6000]
            actions = [a for sent in parse_passage(body, registry) for a in sent.get("actions", [])]
            if not actions:
                continue
            day = ts.date().isoformat()
            daily[day] += len(actions)
            for action in actions:
                direction = str(action.get("direction") or "unknown")
                directions[direction] += 1
                if len(evidence[direction]) < 3:
                    evidence[direction].append(
                        {
                            "item_key": rec.item_key,
                            "title": str((rec.normalized or {}).get("title") or "")[:140],
                        }
                    )
        # 每日连续化（用户要求：窗口内每天都要有可视化呈现；无动作日 count=0 基线柱）
        cur = (now - timedelta(days=max(1, min(days, 120)))).date()
        end = now.date()
        filled: list[dict[str, Any]] = []
        while cur <= end:
            day = cur.isoformat()
            filled.append({"date": day, "count": daily.get(day, 0)})
            cur += timedelta(days=1)
        return {
            "daily": filled,
            "top_actions": [
                {"action": k, "count": v, "evidence": evidence[k]}
                for k, v in directions.most_common(8)
            ],
        }

    @app.get("/api/change-field", response_model=ChangeFieldPayload)
    def change_field(days: int = 30, lang: str = "zh") -> ChangeFieldPayload:
        """叙事场时序（T8）：每日×泳道×框架计数 + 合格变化点（前端只渲染）。"""
        now = _now()
        records = list(_bronze().iter_records())
        landscape = build_change_landscape(
            bronze_iter=iter(records),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            lang=lang,
            lang_by_source=_lang_map_safe(),
            now=now,
            days=7,
        )
        return build_change_field(
            records=records,
            rows=_store().stances_asof(now),
            tier_map=_tier_map(),
            now=now,
            days=max(1, days),
            changes=landscape.qualified_changes,
        )

    @app.get("/api/change-landscape", response_model=ChangeLandscape)
    def change_landscape(
        days: int = 7,
        top: int = 5,
        min_per_source: int = 10,
        source_id: list[str] = Query(default_factory=list),  # noqa: B008
        language: str | None = None,
        lang: str = "zh",
    ) -> ChangeLandscape:
        """叙事变化场聚合（阶段 1.5-c，T1 更名去沙漏）：后端拼图，前端只渲染。

        source_id 可多值；筛选作用于两窗/检测/证据全链（effective_filters 回显）。
        """
        return build_change_landscape(
            bronze_iter=_bronze().iter_records(),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            lang=lang,
            lang_by_source=_lang_map_safe(),
            now=_now(),
            days=max(1, days),
            top=top,
            min_per_source=min_per_source,
            source_ids=source_id,
            language=language or None,
        )

    @app.get("/api/home", response_model=HomePayload)
    def home(days: int = 7, lang: str = "zh", top: int = 5) -> HomePayload:
        """首页单次聚合（T4）：briefing + 变化场 + watchlist 一次返回。

        消除前端 4 并发请求竞态；briefing_viewed 去重到前端单一数据源。
        """
        now = _now()
        records = list(_bronze().iter_records())
        briefing_result = build_briefing_with_signals(
            bronze_iter=iter(records),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            lang=lang,
            lang_by_source=_lang_map_safe(),
            now=now,
            days=max(1, days),
            top=top,
        )
        return HomePayload(
            briefing=briefing_result[0],
            landscape=build_change_landscape(
                bronze_iter=iter(records),
                store=_store(),
                registry=_registry(),
                tier_map=_tier_map(),
                lang_by_source=_lang_map_safe(),
                now=now,
                days=max(1, days),
                top=top,
                briefing_result=briefing_result,
            ),
            watches=[w.__dict__ for w in _watch_store().list()],
        )

    @app.get("/api/changes/{change_id}", response_model=ChangeDossier)
    def change_dossier(change_id: str, days: int = 3) -> ChangeDossier:
        """变化详情包（阶段 1-b）：Dossier 含三桶证据 + 缺口 + 覆盖摘要。"""
        dossier = build_dossier(
            change_id,
            bronze_iter=_bronze().iter_records(),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            now=_now(),
            days=max(1, days),
        )
        if dossier is None:
            raise HTTPException(404, f"change not found: {change_id}")
        return dossier

    @app.get("/api/changes/{change_id}/evidence", response_model=list[EvidenceCitation])
    def change_evidence(
        change_id: str,
        bucket: Literal["supporting", "contradicting", "context"],
    ) -> list[EvidenceCitation]:
        """分桶证据（阶段 1-b）：Evidence Drawer 惰性加载入口。

        v1 简化：内部复用 Dossier 组装（未做信号级缓存），docstring 记录。
        """
        dossier = build_dossier(
            change_id,
            bronze_iter=_bronze().iter_records(),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            now=_now(),
        )
        if dossier is None:
            raise HTTPException(404, f"change not found: {change_id}")
        return list(getattr(dossier.evidence, bucket))

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

    def _topic_hits(query: str, now: datetime) -> int:
        """topic 订阅命中计数（7 天窗标题/正文，与 refresh 快照同语义）。"""
        terms = [t.strip().lower() for t in query.split(",") if t.strip()]
        if not terms:
            return 0
        cutoff = now - timedelta(days=7)
        n = 0
        for rec in _bronze().iter_records():
            pub = rec.published_at or rec.fetched_at
            if pub < cutoff:
                continue
            text = (
                str(rec.normalized.get("title", "")) + "\n" + str(rec.normalized.get("body", ""))
            ).lower()
            if any(t in text for t in terms):
                n += 1
        return n

    @app.get("/api/watches/{watch_id}/update", response_model=WatchUpdate)
    def watch_update(watch_id: str) -> WatchUpdate:
        """增量更新预览（阶段 3）：只读计算，查看 ≠ 复核。

        since = max(上次复核, 该主体最新判断时间)；写回仅由显式 review 触发。
        """
        w = _watch_store().get(watch_id)
        if w is None:
            raise HTTPException(404, "watch not found")
        now = _now()
        briefing = build_briefing(
            bronze_iter=_bronze().iter_records(),
            store=_store(),
            registry=_registry(),
            tier_map=_tier_map(),
            lang_by_source=_lang_map_safe(),
            now=now,
            days=3,
            top=30,
        )
        beliefs = _beliefs() if w.type == "entity" else None
        topic_hits = _topic_hits(w.query, now) if w.type == "topic" else None
        return compute_watch_update(
            w, briefing, beliefs=beliefs, now=now, topic_hits=topic_hits, lang=_corpus_lang_safe()
        )

    @app.post("/api/watches/{watch_id}/review", response_model=WatchReview)
    def watch_review(watch_id: str) -> WatchReview:
        """标记已复核（阶段 3）：仅推进 last_checked_at，不写摘要。"""
        now = _now()
        if not _watch_store().mark_reviewed(watch_id, now=now):
            raise HTTPException(404, "watch not found")
        return WatchReview(watch_id=watch_id, reviewed_at=now.isoformat())

    def _tracking() -> Any:
        """C3 跟踪预警统一库（清零重建，不迁移旧 watch/alerts 数据）。"""
        if not hasattr(app.state, "_tracking_store"):
            app.state._tracking_store = TrackingStore(paths.root / "tracking.sqlite")
        return app.state._tracking_store

    @app.post("/api/archive", response_model=ArchiveItem, status_code=201)
    def archive_save(body: dict[str, Any]) -> ArchiveItem:
        """确认式存档（用户显式动作触发）；kind 闭集三档案库。"""
        kind = str(body.get("kind") or "")
        if kind not in ARCHIVE_KINDS:
            raise HTTPException(status_code=422, detail="kind 必须为三档案库闭集")
        title = str(body.get("title") or "").strip()
        if len(title) < 8:
            raise HTTPException(status_code=422, detail="title 至少 8 字")
        aid = _archive().save_item(
            kind=kind,
            title=title,
            ref_kind=str(body.get("ref_kind") or kind),
            ref_id=str(body.get("ref_id") or ""),
            payload=dict(body.get("payload") or {}),
            note=str(body.get("note") or ""),
        )
        got = _archive().get_item(aid)
        assert got is not None
        return ArchiveItem.model_validate(got)

    @app.get("/api/archive")
    def archive_list(kind: str | None = None) -> dict[str, Any]:
        """档案列表（可选 kind 过滤）+ 分库计数。"""
        if kind is not None and kind not in ARCHIVE_KINDS:
            raise HTTPException(status_code=422, detail="未知档案库")
        return {"items": _archive().list_items(kind), "counts": _archive().counts()}

    @app.delete("/api/archive/{archive_id}", status_code=204)
    def archive_delete(archive_id: str) -> Response:
        if not _archive().remove_item(archive_id):
            raise HTTPException(status_code=404, detail="档案不存在")
        return Response(status_code=204)

    @app.post("/api/archive/paper", response_model=AgentPaper, status_code=201)
    def archive_paper(body: dict[str, Any]) -> AgentPaper:
        """D2 档案报纸：按 item_ids 或按库最新 N 条组合 + 卷首语（offline 模板）。"""
        st = _archive()
        item_ids = [str(x) for x in (body.get("item_ids") or [])]
        if not item_ids:
            kind = body.get("kind")
            items = st.list_items(kind if kind in ARCHIVE_KINDS else None, limit=12)
            item_ids = [it["archive_id"] for it in items]
        items = [st.get_item(i) for i in item_ids]
        items = [it for it in items if it is not None]
        if not items:
            raise HTTPException(status_code=409, detail="没有可选的档案条目")
        by_kind: dict[str, int] = {}
        for it in items:
            by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
        comp = "、".join(f"{k}×{n}" for k, n in sorted(by_kind.items()))
        foreword = str(
            body.get("foreword")
            or f"编者按：本期报纸由 {len(items)} 条档案组合而成（{comp}）。"
            "系统按用户筛选汇总，观点归属原档案，未自动添加新结论。"
        )
        title = str(body.get("title") or "").strip() or f"档案报纸 · {comp}"
        if len(title) < 8:
            title = title + "（自动命名）"
        pid = st.save_paper(title=title, item_ids=item_ids, foreword=foreword)
        papers = [x for x in st.list_papers() if x["paper_id"] == pid]
        return AgentPaper.model_validate(papers[0])

    @app.get("/api/archive/papers", response_model=list[AgentPaper])
    def archive_papers() -> list[AgentPaper]:
        return [AgentPaper.model_validate(x) for x in _archive().list_papers()]

    @app.post("/api/track", status_code=204, include_in_schema=False)
    async def track_sink(body: TrackEventIn) -> Response:
        """遥测接收点：闭集校验后丢弃（纲领 §11：埋点不影响主路径）。"""
        return Response(status_code=204)

    @app.get("/api/tracking")
    def tracking_list(kind: str | None = None) -> dict[str, Any]:
        """统一跟踪/预警单元清单 + 最近命中。"""
        st = _tracking()
        units = st.list(kind if kind in {"entity", "topic", "question", "element"} else None)
        return {
            "units": [u.model_dump(mode="json") for u in units],
            "hits": [h.model_dump(mode="json") for h in st.hits(limit=50)],
        }

    @app.post("/api/tracking", status_code=201, response_model=TrackingUnit)
    def tracking_add(body: dict[str, Any]) -> TrackingUnit:
        """新增跟踪/预警单元（四类 kind × track/alert 两模式）。"""
        kind = str(body.get("kind") or "")
        query = str(body.get("query") or "").strip()
        mode = str(body.get("mode") or "track")
        threshold = body.get("threshold")
        if kind not in {"entity", "topic", "question", "element"} or not query:
            raise HTTPException(422, "kind 必须为四类闭集且 query 必填")
        if mode not in {"track", "alert"}:
            raise HTTPException(422, "mode 必须为 track 或 alert")
        th = float(threshold) if threshold is not None else None
        return _tracking().add(
            kind=kind,
            query=query,
            mode=mode,
            label=str(body.get("label") or ""),
            threshold=th,
        )

    @app.delete("/api/tracking/{unit_id}", status_code=204)
    def tracking_remove(unit_id: str) -> Response:
        if not _tracking().remove(unit_id):
            raise HTTPException(404, "unit not found")
        return Response(status_code=204)

    @app.get("/api/tracking/{unit_id}/update")
    def tracking_update(unit_id: str, lang: str = "zh") -> dict[str, Any]:
        """增量视图：track=briefing 命中；alert=最近触发；element=拆解元素命中。"""
        st = _tracking()
        unit = st.get(unit_id)
        if unit is None:
            raise HTTPException(404, "unit not found")
        now = _now()
        if unit.mode == "alert":
            hits = st.hits(unit_id, limit=1)
            return {
                "summary": hits[0].summary if hits else "尚无触发记录",
                "review_hint": "",
                "new_changes": [],
                "since": unit.last_checked_at,
            }
        if unit.kind == "entity":
            briefing, _sig = build_briefing_with_signals(
                bronze_iter=_bronze().iter_records(),
                store=_store(),
                registry=_registry(),
                tier_map=_tier_map(),
            lang_by_source=_lang_map_safe(),
                now=now,
                days=7,
                top=30,
            )
            upd = compute_watch_update(
                _WatchLike(unit), briefing, beliefs=_beliefs(), now=now, lang=lang
            )
        elif unit.kind == "topic":
            briefing, _sig = build_briefing_with_signals(
                bronze_iter=_bronze().iter_records(),
                store=_store(),
                registry=_registry(),
                tier_map=_tier_map(),
                lang=lang,
                lang_by_source=_lang_map_safe(),
                now=now,
                days=7,
                top=30,
            )
            upd = compute_watch_update(
                _WatchLike(unit),
                briefing,
                beliefs=None,
                now=now,
                topic_hits=_topic_hits(unit.query, now),
                lang=lang,
            )
        elif unit.kind == "element":
            ek, _, val = unit.query.partition(":")
            n = 0
            for d in _store().dissections_asof(now):
                for e in d.get("elements") or []:
                    content = str(e.get("content", "")).lower()
                    if e.get("element") == ek and (not val or val.lower() in content):
                        n += 1
            upd = SimpleNamespace(
                summary=f"窗口内 {n} 篇拆解命中元素「{unit.query}」",
                review_hint="有新命中时建议复核你的相关判断" if n else "",
                new_changes=[],
                since=unit.last_checked_at,
            )
        else:
            upd = SimpleNamespace(
                summary="问题类暂不支持增量比较（阶段 4 接入）",
                review_hint="",
                new_changes=[],
                since=unit.last_checked_at,
            )
        return {
            "summary": upd.summary,
            "review_hint": upd.review_hint,
            "new_changes": [
                c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                for c in getattr(upd, "new_changes", []) or []
            ],
            "since": upd.since,
        }

    @app.post("/api/tracking/{unit_id}/review")
    def tracking_review(unit_id: str) -> dict[str, Any]:
        """标记已复核：仅推进 last_checked_at。"""
        if not _tracking().mark_checked(unit_id, now=_now().isoformat()):
            raise HTTPException(404, "unit not found")
        return {"ok": True}

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

    # ---- 认知快照（阶段 2 判断闭环：仅用户确认写入）----
    @app.post("/api/beliefs", response_model=BeliefSnapshot, status_code=201)
    def create_belief(body: BeliefCreate) -> BeliefSnapshot:
        """保存一次用户判断：snapshot_id/change_type/believed_at 服务端生成。

        change_type 由该 change 的既有快照自动判定（首条=new，否则=revised）。
        """
        from uuid import uuid4

        store = _beliefs()
        prev = store.latest_for_change(body.change_id)
        snap = BeliefSnapshot(
            snapshot_id=f"bs-{uuid4().hex[:8]}",
            change_id=body.change_id,
            subject_id=body.subject_id,
            subject_label=body.subject_label,
            stance=body.stance,
            confidence=body.confidence,
            rationale=body.rationale,
            change_type="revised" if prev is not None else "new",
            believed_at=_now(),
        )
        store.save(snap)
        return snap

    @app.get("/api/beliefs", response_model=list[BeliefSnapshot])
    def beliefs_for_change(change_id: str) -> list[BeliefSnapshot]:
        """某变化的全部认知快照（believed_at 升序，前端展示差异用）。"""
        return _beliefs().for_change(change_id)

    @app.get("/api/beliefs/timeline", response_model=list[BeliefSnapshot])
    def beliefs_timeline(subject_id: str) -> list[BeliefSnapshot]:
        """某实体的认知时间线（跨变化，believed_at 升序）。"""
        return _beliefs().timeline(subject_id)

    @app.post("/api/track", status_code=204)
    def track(body: dict[str, Any]) -> Response:
        """产品事件埋点（阶段 1-e）：主路径 7 事件闭集，匿名 session。

        body: {event, session, object_id?, from_page?, freshness?, meta?}。
        fire-and-forget 语义：任何失败不阻塞用户主路径（422 仅闭集违规）。
        """
        event = str(body.get("event") or "")
        session = str(body.get("session") or "")
        if not session:
            raise HTTPException(422, "session required (anonymous client uuid)")
        try:
            _product_events().append(
                event,
                session,
                object_id=str(body.get("object_id") or ""),
                from_page=str(body.get("from_page") or ""),
                freshness=str(body.get("freshness") or ""),
                meta=dict(body.get("meta") or {}),
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return Response(status_code=204)

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
    def sources_list(
        tier: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        q: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """信息源管理面（订阅中心）：全源清单 + Bronze 产出统计（C1 服务端筛选）。"""
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
                    "kind": spec.get("kind") or spec.get("adapter") or "?",
                    "tier": spec.get("tier", "?"),
                    "language": spec.get("language", "?"),
                    "enabled": bool(spec.get("enabled", True)),
                    "n_7d": c7.get(sid, 0),
                    "n_30d": c30.get(sid, 0),
                    "last_seen": last_seen.get(sid),
                }
            )
        rows.sort(key=lambda r: (-r["n_7d"], -r["n_30d"], r["source_id"]))
        if tier:
            rows = [r for r in rows if str(r["tier"]).upper() == tier.upper()]
        if kind:
            rows = [r for r in rows if r["kind"] == kind]
        if language:
            rows = [r for r in rows if r["language"] == language]
        if enabled is not None:
            rows = [r for r in rows if r["enabled"] == enabled]
        if q:
            rows = [r for r in rows if q.lower() in str(r["source_id"]).lower()]
        return {"n": len(rows), "sources": rows}

    @app.post("/api/monitors/updates/{update_id}/analysis")
    async def monitor_update_analysis(update_id: str) -> dict[str, Any]:
        """按需生成 MonitorUpdate 的 Agent 分析，严格限定于本次增量证据。

        只读产物不会替用户 accept/ignore 更新或创建 Case；模型不可用时返回同形
        规则摘要，并明确 engine=offline，保证用户仍可完成证据复核。
        """
        update = _research().get_update(update_id)
        if update is None:
            raise HTTPException(404, f"monitor update not found: {update_id}")
        monitor = _research().get_monitor(update.monitor_id)
        refs = set(update.evidence_refs)
        evidence: list[dict[str, str]] = []
        for rec in _bronze().iter_records():
            if rec.item_key not in refs:
                continue
            normalized = rec.normalized or {}
            evidence.append(
                {
                    "item_key": rec.item_key,
                    "source_id": rec.source_id,
                    "title": str(normalized.get("title") or ""),
                    "excerpt": _strip_tags(str(normalized.get("body") or ""))[:420],
                }
            )
            if len(evidence) >= 10:
                break
        delta = update.delta if isinstance(update.delta, dict) else {}
        fallback = {
            "executive_summary": update.summary,
            "what_changed": [
                f"新增相关文档：{delta.get('new_articles', '—')}",
                f"窗口内总命中：{delta.get('total_hits', '—')}",
            ],
            "evidence_assessment": [
                f"本次可复核证据：{len(evidence)} 条引用（最多展示 10 条）",
                "该摘要未比较全文立场；请在创建或加入 Case 前打开原文核对。",
            ],
            "uncertainties": [
                "监测命中是关键词相关性，不等同于事实确认或因果结论。",
                "未确认快照前，新增量不应作为已采纳判断。",
            ],
            "recommended_review": "先核对证据来源与原文，再选择新建 Case、加入已有 Case 或忽略。",
        }
        llm = _chat_router()
        if llm is None:
            return {"engine": "offline", "status": "abstained", "analysis": fallback}
        system = (
            "你是 OH!News 跟踪预警分析师。只能依据提供的 Monitor 增量与原文摘录分析，"
            "禁止编造外部事实、禁止把关键词命中写成事实确认或预测。明确证据不足、样本限制，"
            "最后仅给出人工复核建议，不得自动决定写入操作。"
        )
        user = json.dumps(
            {
                "monitor": {
                    "question": monitor.question if monitor else "",
                    "target": monitor.target_ref if monitor else "",
                    "window": monitor.window if monitor else "",
                },
                "update": {
                    "summary": update.summary,
                    "delta": delta,
                    "evidence_refs": update.evidence_refs,
                },
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
        try:
            async with asyncio.timeout(90.0):
                analysis, ref, usage = await llm.invoke(
                    Tier.EXECUTE, system, user, MonitorAnalysisOutput
                )
            return {
                "engine": "llm",
                "status": "succeeded",
                "model_hint": f"{ref.provider}/{ref.model_id}",
                # Router Usage is a frozen dataclass, not a Pydantic model.
                # Keep telemetry serialization from turning a successful model
                # response into an apparent offline fallback.
                "usage": asdict(usage) if usage else None,
                "analysis": analysis.model_dump(),
            }
        except Exception as exc:  # noqa: BLE001 - 同形离线分析，但不伪装模型成功
            return {
                "engine": "offline",
                "status": "abstained",
                "error": str(exc) or type(exc).__name__,
                "analysis": fallback,
            }

    @app.post("/api/sources/suggest")
    async def source_suggest(body: dict[str, Any]) -> dict[str, Any]:
        """URL → Agent 信源建议 → HITL 注册。

        Agent 只提出主体、语言、适配器和采集频率；不声称已访问 URL，也不静默注册。
        模型不可用/超时时保留可审计的规则建议，而非伪装为 AI 结果。
        """
        url = str(body.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "url must start with http(s)://")
        host = urlparse(url).netloc.lower().removeprefix("www.")
        core = re.sub(r"\.[a-z]{2,}(\.[a-z]{2})?$", "", host) or host
        core = re.sub(r"[^a-z0-9_-]", "_", core)
        if url.rstrip("/").lower().endswith((".xml", "/rss", "/feed")) or "rss" in url.lower():
            kind = "rss"
        elif "/api/" in url or url.lower().endswith(".json"):
            kind = "json_api"
        else:
            kind = "html"
        social = {"x.com", "twitter.com", "reddit.com", "weibo.com", "t.me"}
        gov_hits = ("gov", "centralbank", "federalreserve", "ecb", "boj", "pbc")
        tier = "L4" if host in social else ("L1" if any(g in host for g in gov_hits) else "L3")
        tld_lang = {
            "cn": "zh",
            "kr": "ko",
            "jp": "ja",
            "de": "de",
            "fr": "fr",
            "ru": "ru",
            "br": "pt",
            "in": "hi",
            "tw": "zh",
            "hk": "zh",
        }
        tld = host.rsplit(".", 1)[-1]
        language = tld_lang.get(tld, "en")
        method_map = {
            "rss": "RSS 轮询拉取（公开订阅端点）",
            "json_api": "JSON API 定期拉取",
            "html": "浏览器渲染抓取",
        }
        freq_map = {"rss": "建议 6h", "json_api": "建议 12h", "html": "建议 1d"}
        robots = (
            "RSS 公开端点；仍遵循 robots.txt 与站点条款"
            if kind == "rss"
            else "需渲染抓取；尊重 robots.txt 与访问限制，超时退避"
        )
        heuristic = {
            "source_id": core,
            "adapter": kind,
            "tier": tier,
            "language": language,
            "params": {"url": url},
        }
        preview = {
            "subject": f"识别主体：{host}（建议 id：{core}）",
            "method": f"采集方法：{method_map[kind]}",
            "expected_frequency": f"预计频率：{freq_map[kind]}（可调整）",
            "robots_policy": f"访问限制：{robots}",
            "dedupe_strategy": "去重策略：item_key = 规范化 URL + 发布方 + 发布时间",
            "ingest_plan": "落库方案：bronze parquet（raw+normalized）→ silver 标注管线异步处理",
        }
        result: dict[str, Any] = {
            "url": url,
            "suggestion": heuristic,
            "rationale": "启发式建议（主机名/路径/域名后缀推断），注册前请人工确认等级与语言",
            "preview": preview,
            "engine": "rule",
            "agent_status": "abstained",
        }
        llm = _chat_router()
        if llm is None:
            result["agent_error"] = "LLM 未配置；已返回规则建议，需人工复核。"
            return result
        system = (
            "你是新闻情报平台的信源接入分析师。仅根据 URL 与规则初判输出保守建议。"
            "不得声称已访问 URL、不得绕过 robots.txt；不确定时使用 html，并在 caveats 说明。"
            "所有注册必须由用户确认。"
        )
        user = (
            f"URL: {url}\n规则初判: {json.dumps(heuristic, ensure_ascii=False)}\n"
            "请识别信源主体、adapter、tier、语言、建议频率、理由与风险。"
        )
        try:
            async with asyncio.timeout(45.0):
                discovered, ref, usage = await llm.invoke(
                    Tier.EXECUTE, system, user, SourceDiscoveryOutput
                )
            data = discovered.model_dump()
            result.update(
                {
                    "suggestion": {
                        "source_id": data["source_id"],
                        "adapter": data["adapter"],
                        "tier": data["tier"],
                        "language": data["language"],
                        "params": {"url": url},
                    },
                    "rationale": data["rationale"],
                    "preview": {
                        **preview,
                        "subject": f"识别主体：{data['source_subject']}",
                        "method": f"采集方法：{data['method']}",
                        "expected_frequency": f"预计频率：{data['expected_frequency']}",
                        "agent_caveats": "风险提示："
                        + ("；".join(data["caveats"]) or "需人工复核"),
                    },
                    "engine": "llm",
                    "agent_status": "succeeded",
                    "model_hint": f"{ref.provider}/{ref.model_id}",
                    "confidence": data["confidence"],
                    "usage": asdict(usage) if usage else None,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 降级必须显式
            result["agent_error"] = str(exc) or type(exc).__name__
        return result

    @app.post("/api/sources")
    def source_register(body: dict[str, Any]) -> dict[str, Any]:
        """C2：确认建议后注册信源（文本追加写 config/sources.yaml，保留既有注释）。

        source_id 冲突 409；adapter 闭集校验 422。
        """
        sid = str(body.get("source_id") or "").strip()
        adapter = str(body.get("adapter") or "").strip()
        if not sid or not re.fullmatch(r"[a-z0-9_-]{2,40}", sid):
            raise HTTPException(422, "source_id 需 2-40 位小写字母/数字/下划线/连字符")
        if adapter not in {"rss", "gdelt", "fred", "json_api", "html", "browser", "reddit_cdp"}:
            raise HTTPException(422, f"unknown adapter: {adapter}")
        tier = str(body.get("tier") or "L3")
        if tier not in {"L1", "L2", "L3", "L4"}:
            raise HTTPException(422, "tier must be L1-L4")
        language = str(body.get("language") or "en")
        params_url = str(body.get("url") or "")
        if paths.sources_yaml.exists():
            existing = paths.sources_yaml.read_text(encoding="utf-8")
        else:
            existing = "version: 2\n\nsources:\n"
        if re.search(rf"^\s*- source_id:\s*{re.escape(sid)}\s*$", existing, re.M):
            raise HTTPException(409, f"source_id 已存在: {sid}")
        block = (
            f"\n  - source_id: {sid}\n"
            f"    adapter: {adapter}\n"
            f"    tier: {tier}\n"
            f"    language: {language}\n"
            f"    credibility_prior: 0.5\n"
            f"    enabled: true\n"
            f"    params:\n"
            f'      url: "{params_url}"\n'
        )
        with paths.sources_yaml.open("a", encoding="utf-8") as f:
            f.write(block)
        return {
            "ok": True,
            "source_id": sid,
            "adapter": adapter,
            "tier": tier,
            "language": language,
        }

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

        with open(paths.sources_yaml, encoding="utf-8") as f:
            registry = build_registry(yaml.safe_load(f) or {})
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

    @app.get("/api/events/{event_id}")
    def event_detail(event_id: str) -> dict[str, Any]:
        """单事件详情（R0 断点修复：详情页不再拉全量列表 .find）。

        R1：内联该事件的 EventAssessment（M2 评估层——状态/置信/证据强度/观察）。
        """
        now = _now()
        store = _store()
        for e in store.events_asof(now):
            if e.event_id == event_id:
                series = store.ndi_series(event_id)
                latest = series[-1] if series else None
                rows = [r for r in store.stances_asof(now) if r.event_id == event_id]
                assessment = None
                if rows:
                    keys = {r.item_key for r in rows}
                    recs = [rec for rec in _bronze().iter_records() if rec.item_key in keys]
                    a = assess_event(event_id, build_evidence(recs, _tier_map()), rows)
                    assessment = a.model_dump(mode="json")
                return {
                    "event_id": e.event_id,
                    "title": e.title,
                    "summary": e.summary,
                    "entities": e.entities,
                    "as_of": e.as_of.isoformat(),
                    "first_seen": e.first_seen.isoformat() if e.first_seen else None,
                    "ndi": latest.ndi if latest else None,
                    "ndi_status": latest.status if latest else "none",
                    "n_sources": latest.n_sources if latest else 0,
                    "assessment": assessment,
                }
        raise HTTPException(404, f"event not found: {event_id}")

    @app.post("/api/evidence/by_keys")
    def evidence_by_keys(body: dict[str, Any]) -> list[dict[str, Any]]:
        """item_key 反查原始文章摘录（R0 断点修复：narrative_shift 证据链入口）。

        body: {"item_keys": [...]}；按入参顺序返回，未命中跳过；上限 200。
        """
        keys = body.get("item_keys") or []
        if not isinstance(keys, list) or not keys or len(keys) > 200:
            raise HTTPException(422, "item_keys must be a non-empty list of <=200 ids")
        ordered: list[str] = []
        seen: set[str] = set()
        for k in keys:
            ks = str(k)
            if ks not in seen:
                seen.add(ks)
                ordered.append(ks)
        out: dict[str, dict[str, Any]] = {}
        for rec in _bronze().iter_records():
            if rec.item_key not in seen:
                continue
            n = rec.normalized
            out[rec.item_key] = {
                "item_key": rec.item_key,
                "source_id": rec.source_id,
                "title": str(n.get("title") or ""),
                "url": str(n.get("url") or ""),
                "published_at": str(n.get("published_at") or ""),
                "quote": strip_html(str(n.get("body") or n.get("title") or ""))[:400],
            }
            if len(out) == len(seen):
                break
        return [out[k] for k in ordered if k in out]

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

    # chat 指挥模式可选参数（document/claim/report 定位；透传给工作流）
    _CHAT_PARAM_KEYS = (
        "document_revision_id",
        "document_revision_ids",
        "claim_id",
        "report_type",
        "title",
        "item_key",
        "target_language",
        "question",
    )

    @app.post("/api/chat")
    async def chat(body: dict[str, Any]) -> dict[str, Any]:
        """对话指挥 Agent（chat_graph + command mode）：意图路由 → 工作流触发 → 卡片。

        指挥意图（plan/dissect/compare/report/challenge）触发 CaseWorkflows
        （异步 202 协议：chat 只回 run_id 不等待）；status/observe/hitl 只读
        汇总；question 走 LLM⇄tools 循环。响应新增 intent/message_type/cards
        字段（不破坏既有 reply/citations/tools_used/rounds/offline）。
        无 keys/config 降级离线聚合；工作流触发不依赖 chat LLM。
        """
        message = str(body.get("message", "")).strip()
        if not message and not body.get("confirmed_action"):
            raise HTTPException(422, "message required")
        thread_id = str(body.get("thread_id") or uuid4().hex[:12])
        case_id = str(body.get("case_id") or "")
        params = {k: body[k] for k in _CHAT_PARAM_KEYS if body.get(k) is not None}
        # P0-1 确认通道：前端 confirm_action 卡「确认执行」后重发原始消息+
        # confirmed_action（服务端凭 confirmed=True 放行写操作门）。
        confirmed_action = body.get("confirmed_action") or None
        if confirmed_action:
            message = str(confirmed_action.get("message") or message or "").strip()
            params.update(
                {k: v for k, v in (confirmed_action.get("params") or {}).items() if v is not None}
            )
        cs = _chat_store()
        now = _now()
        ts = now.isoformat()
        history = [{"role": m["role"], "content": m["content"]} for m in cs.messages(thread_id)]
        cs.append(thread_id, "user", message, ts)
        try:
            result = await run_chat_command(
                message,
                history,
                bronze=_bronze(),
                store=_store(),
                gold=_store(),
                registry=_registry(),
                research=_research(),
                workflows=_workflows(),
                research_factory=_research,
                workflows_factory=_workflows,
                router=_chat_router(),
                gdelt_proxy=os.getenv("OHNEWS_GDELT_PROXY"),
                now=now,
                case_id=case_id,
                params=params,
                confirmed=bool(confirmed_action),
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
                    f"（模型调用未成功，以下为确定性数据摘要。\n"
                    f"失败原因节选：{str(exc)[:160]}）\n\n"
                )
                result = {
                    **fallback,
                    "reply": degraded + fallback["reply"],
                    "llm_error": str(exc)[:300],
                    "intent": "question",
                    "intent_by": "fallback",
                    "cards": [],
                }
            except Exception as exc2:  # 连离线聚合都失败→最小回复
                result = {
                    "reply": f"服务暂时不可用：{str(exc2)[:200]}",
                    "citations": [],
                    "tools_used": [],
                    "rounds": 0,
                    "llm_error": str(exc2)[:300],
                    "intent": "question",
                    "intent_by": "fallback",
                    "cards": [],
                }
        # 消息九类型（阶段 2 对话约束）：指挥结果自带类型；错误标 error
        if result.get("llm_error"):
            message_type: str = "error"
        else:
            message_type = str(result.get("message_type") or "answer")
        cards = list(result.get("cards") or [])
        cs.append(
            thread_id, "assistant", result["reply"], now.isoformat(), message_type, cards=cards
        )
        await publish_sse(
            "chat_done",
            {
                "thread_id": thread_id,
                "rounds": result.get("rounds", 0),
                "tools": list(result.get("tools_used") or []),
                "intent": result.get("intent", "question"),
                "n_cards": len(cards),
            },
        )
        return {
            "thread_id": thread_id,
            "reply": result["reply"],
            "citations": list(result.get("citations") or []),
            "tools_used": list(result.get("tools_used") or []),
            "rounds": result.get("rounds", 0),
            "offline": _chat_router() is None,
            "intent": result.get("intent", "question"),
            "intent_by": result.get("intent_by", "fallback"),
            "message_type": message_type,
            "cards": cards,
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

    # ---- 阶段 2 Agent OS：专项注册表 + Parent 规划 ----

    @app.get("/api/agent/specialists")
    def agent_specialists() -> dict[str, Any]:
        """9 专项 Agent 注册表（Parent + 专项 架构的数据真源）。"""
        return {"n": len(SPECIALISTS), "specialists": [dict(s) for s in SPECIALISTS]}

    @app.post("/api/agent/plan")
    async def agent_plan(body: PlanRequestBody) -> JSONResponse:
        """Parent 规划（阶段 2）：同步快操作，202 + run_id 供追踪。

        读 Case 上下文（文档/claims/已跑工作流）→ ModelRouter 结构化输出
        PlanOut → 落 agent_runs（kind=plan）。模型未配置/失败 → status=failed
        + 根因（诚实降级，与 case_workflows 语义一致）；空 steps = 弃权。
        """
        research = _research()
        if not research.get_case(body.case_id):
            raise HTTPException(404, f"case not found: {body.case_id}")
        result = await build_research_plan(
            body.case_id,
            question=body.question,
            research=research,
            router=_chat_router(),
            now_fn=lambda: _now().isoformat(),
        )
        return JSONResponse(status_code=202, content=result)

    @app.get("/api/agent/plans")
    def agent_plans(case_id: str, limit: int = 5) -> dict[str, Any]:
        """某 Case 最近的研究计划（kind=plan 的 agent_runs，新→旧）。"""
        plans = _research().plan_runs(case_id=case_id, limit=max(1, min(limit, 50)))
        return {"n": len(plans), "plans": plans}

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

    @app.get("/api/intel/daily")
    def intel_daily(
        days: int = 7,
        min_per_source: int = 2,
        top_n: int = 10,
    ) -> dict[str, Any]:
        """M2 四层情报快照（R1：评估/信号/叙事/洞察 → JSON，engine=offline）。

        PIT：build_daily_intel 内部只用 as_of 及更早数据；无 side effect（只读）。
        """
        d = build_daily_intel(
            _bronze().iter_records(),
            _store(),
            EntityRegistry(DEFAULT_ENTITIES),
            _tier_map(),
            as_of=_now(),
            lookback_days=days,
            min_per_source=min_per_source,
            top_n=top_n,
        )
        return {
            "as_of": d.as_of.isoformat(),
            "assessments": [a.model_dump(mode="json") for a in d.assessments],
            "signals": [s.model_dump(mode="json") for s in d.signals],
            "narratives": [n.model_dump(mode="json") for n in d.narratives],
            "insights": [i.model_dump(mode="json") for i in d.insights],
        }

    @app.get("/api/intel/latest")
    def intel_latest() -> dict[str, Any]:
        reps = _intel_ledger().latest(1)
        if not reps:
            raise HTTPException(404, "no intel reports")
        return reps[0].model_dump(mode="json")

    @app.get("/api/graph")
    def knowledge_graph(
        min_weight: float = 1.0,
        max_nodes: int = 30,
    ) -> dict[str, Any]:
        """KG v2 类型化实体边（M3-S3：entity_edges 表只读投影）。"""
        now = _now()
        registry = EntityRegistry(DEFAULT_ENTITIES)
        raw = [e for e in _store().edges_asof(now) if float(e["weight"]) >= min_weight]
        strength: dict[str, float] = defaultdict(float)
        neighbors: dict[str, dict[str, float]] = defaultdict(dict)
        for e in raw:
            s, d, w = str(e["src"]), str(e["dst"]), float(e["weight"])
            strength[s] += w
            strength[d] += w
            neighbors[s][d] = neighbors[s].get(d, 0.0) + w
            neighbors[d][s] = neighbors[d].get(s, 0.0) + w
        nodes = sorted(strength, key=lambda n: (-strength[n], n))[:max_nodes]
        keep = set(nodes)
        return {
            "generated_at": now.isoformat(),
            "nodes": [
                {
                    "id": n,
                    "entity_type": registry.entity_type(n),
                    "strength": round(strength[n], 1),
                    "degree": len(neighbors[n]),
                    "top_neighbors": sorted(neighbors[n], key=lambda x: (-neighbors[n][x], x))[:5],
                }
                for n in nodes
            ],
            "edges": [
                {
                    "src": e["src"],
                    "dst": e["dst"],
                    "kind": e["kind"],
                    "weight": e["weight"],
                    "first_seen": e["first_seen"],
                    "last_seen": e["last_seen"],
                    "n_evidence": len(e["evidence"]),
                    "evidence": e["evidence"],
                }
                for e in raw
                if str(e["src"]) in keep and str(e["dst"]) in keep
            ],
        }

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
