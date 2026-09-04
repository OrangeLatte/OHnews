"""Object API（Clean-slate Phase 1）：围绕对象的命令式端点，非页面大包。

范围：Case / DocumentRevision / AnalysisRun / Artifact+Commit / Monitor / HITL。
AgentRun 记录先行（Phase 2 接入 Orchestrator 执行）；/api/observations 归 Phase 3。
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from oh_contracts.agent_runtime import (
    AgentRun,
    AgentThread,
    HITLRequest,
    WorkspaceContext,
)
from oh_contracts.artifacts import Artifact, ArtifactRevision, UserCommit
from oh_contracts.case import AnalysisRun, Claim, ResearchCase
from oh_contracts.monitoring import (
    CollectionPlan,
    CollectionRun,
    Monitor,
    MonitorRun,
    MonitorUpdate,
)
from oh_storage.research_store import ResearchStore
from pydantic import BaseModel, Field


class DocumentIn(BaseModel):
    """挂载文档：逻辑 article + 本次抓取的不可变正文。"""

    document_id: str
    document_revision_id: str
    source_id: str
    body: str
    canonical_url: str = ""
    content_hash: str = ""
    language: str = ""
    published_at: str = ""
    external_key: str = ""  # bronze item_key（收件箱 cased/dissected 标记）


class RunIn(BaseModel):
    kind: str
    case_id: str
    input_refs: list[str] = []
    model: str = ""
    prompt_version: str = ""


class RunFinishIn(BaseModel):
    status: str
    token_in: int = 0
    token_out: int = 0
    error: str = ""
    output_artifact_id: str | None = None


class ArtifactIn(BaseModel):
    artifact_id: str
    case_id: str
    klass: str
    title: str
    report_type: str | None = None


class RevisionIn(BaseModel):
    revision_id: str
    run_id: str = ""
    content: dict = {}


class ClaimIn(BaseModel):
    """建 Claim（用户/Agent 通用）；span_ids 引用已有 EvidenceSpan。"""

    statement: str = Field(min_length=1)
    kind: Literal["factual", "opinion"] = "factual"
    span_ids: list[str] = []
    created_by: Literal["user", "agent"] = "user"


class ExtractionReviewIn(BaseModel):
    """元素复核 HITL：confirmed 认可 / rejected 否决。"""

    human_status: Literal["confirmed", "rejected"]


class CommitIn(BaseModel):
    commit_id: str
    revision_id: str
    user_note: str = ""


class MonitorIn(BaseModel):
    monitor_id: str
    target_type: str
    target_ref: str
    question: str
    trigger_conditions: list[str] = []
    window: str = "7d"
    schedule: str = "6h"
    case_id: str | None = None


class MonitorPatchIn(BaseModel):
    """PATCH /monitors/{id}：全部可选，None 不改动。"""

    question: str | None = None
    trigger_conditions: list[str] | None = None
    window: str | None = None
    schedule: str | None = None
    status: str | None = None


class ReviewIn(BaseModel):
    """MonitorUpdate 的 HITL 决策；body 可省略（等价 ignore，兼容旧客户端）。"""

    decision: Literal["ignore", "new_case", "join_case"] = "ignore"
    case_id: str = ""


class AgentRunIn(BaseModel):
    run_id: str
    thread_id: str
    workflow: str
    context: dict | None = None
    model: str = ""
    prompt_version: str = ""


class HITLDecideIn(BaseModel):
    status: str
    note: str = ""


def build_object_router(
    research_fn: Callable[[], ResearchStore], now_fn: Callable[[], datetime]
) -> APIRouter:
    router = APIRouter()

    def _now() -> str:
        return now_fn().isoformat()

    def _store() -> ResearchStore:
        return research_fn()

    # ---------- cases ----------

    @router.post("/api/cases")
    def create_case(case: ResearchCase) -> dict:
        store = _store()
        if store.get_case(case.case_id):
            raise HTTPException(409, f"case exists: {case.case_id}")
        store.create_case(case)
        return {"case_id": case.case_id, "status": case.status}

    @router.get("/api/cases")
    def list_cases(status: str | None = None, include_closed: bool = False) -> list[dict]:
        """默认排除 closed（关闭即从工作列表移除）；include_closed=1 全量可见。

        行内合并 n_documents/n_runs 聚合（列表卡片计数）。
        """
        store = _store()
        cases = store.list_cases(status)
        if not include_closed and status is None:
            cases = [c for c in cases if c.status != "closed"]
        counts = store.case_counts()
        out = []
        for c in cases:
            row = c.model_dump()
            row.update(counts.get(c.case_id, {"n_documents": 0, "n_runs": 0}))
            out.append(row)
        return out

    @router.post("/api/cases/{case_id}/close")
    def close_case(case_id: str) -> dict:
        """关闭案例（软删）：状态机终态之一，保留全部审计链（claims/runs/
        monitor 决策引用不可物理删除），工作列表默认不再显示。"""
        store = _store()
        case = store.get_case(case_id)
        if not case:
            raise HTTPException(404, case_id)
        store.update_case_status(case_id, "closed", updated_at=_now(), closed_at=_now())
        return {"case_id": case_id, "status": "closed"}

    @router.get("/api/cases/{case_id}")
    def get_case(case_id: str) -> dict:
        store = _store()
        case = store.get_case(case_id)
        if not case:
            raise HTTPException(404, case_id)
        claims = []
        for c in store.claims_for_case(case_id):
            item = c.model_dump()
            # A3：Claim→原文一步可达（span quote 直接内联）。
            item["spans"] = [
                {
                    "span_id": sp.span_id,
                    "quote": sp.quote,
                    "char_start": sp.char_start,
                    "char_end": sp.char_end,
                    "polarity": sp.polarity,
                    "document_revision_id": sp.document_revision_id,
                }
                for sp in store.spans_by_ids(c.span_ids)
            ]
            claims.append(item)
        return {
            "case": case.model_dump(),
            "claims": claims,
            "analysis_runs": [r for r in _runs_index(store) if r["case_id"] == case_id],
            # A4：Monitor 决策进入同一时间线。
            "monitor_decisions": store.decisions_for_case(case_id),
        }

    @router.post("/api/cases/{case_id}/claims")
    def create_claim(case_id: str, body: ClaimIn) -> dict:
        """建 Claim：B6 门（research_report 提交前 Challenge 必经）的前提路径。"""
        store = _store()
        if not store.get_case(case_id):
            raise HTTPException(404, f"case not found: {case_id}")
        known = {s.span_id for s in store.spans_by_ids(body.span_ids)}
        unknown = [s for s in body.span_ids if s not in known]
        if unknown:
            raise HTTPException(422, f"unknown span_ids: {unknown}")
        claim = Claim(
            claim_id=f"claim-{uuid4().hex[:12]}",
            case_id=case_id,
            statement=body.statement,
            kind=body.kind,
            span_ids=body.span_ids,
            created_by=body.created_by,
            created_at=_now(),
        )
        store.add_claim(claim)
        return claim.model_dump()

    @router.post("/api/cases/{case_id}/documents")
    def attach_document(case_id: str, doc: DocumentIn) -> dict:
        store = _store()
        if not store.get_case(case_id):
            raise HTTPException(404, f"case not found: {case_id}")
        try:
            store.add_document_revision(
                doc.document_revision_id,
                doc.document_id,
                source_id=doc.source_id,
                body=doc.body,
                fetched_at=_now(),
                canonical_url=doc.canonical_url,
                content_hash=doc.content_hash,
                language=doc.language,
                published_at=doc.published_at,
                external_key=doc.external_key,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        store.link_case_document(case_id, doc.document_revision_id, _now())
        return {"document_revision_id": doc.document_revision_id, "case_id": case_id}

    @router.get("/api/cases/{case_id}/documents")
    def list_case_documents(case_id: str) -> list[dict]:
        if not _store().get_case(case_id):
            raise HTTPException(404, f"case not found: {case_id}")
        return _store().case_documents(case_id)

    # ---------- analysis runs ----------

    @router.post("/api/analysis-runs")
    def create_run(run_in: RunIn) -> dict:
        store = _store()
        if not store.get_case(run_in.case_id):
            raise HTTPException(404, f"case not found: {run_in.case_id}")
        run = AnalysisRun(
            run_id=run_in.kind.replace("_", "-") + "-" + now_fn().strftime("%Y%m%d%H%M%S%f"),
            case_id=run_in.case_id,
            kind=run_in.kind,  # type: ignore[arg-type]
            model=run_in.model,
            prompt_version=run_in.prompt_version,
            input_refs=run_in.input_refs,
            status="queued",
        )
        store.add_analysis_run(run)
        return {"run_id": run.run_id, "status": "queued"}

    @router.get("/api/analysis-runs")
    def list_analysis_runs(limit: int = 50) -> list[dict]:
        """最近分析运行（Agent 面板 Recent runs 数据源）。"""
        return [r.model_dump() for r in _store().analysis_runs(limit)]

    @router.post("/api/analysis-runs/{run_id}/finish")
    def finish_run(run_id: str, finish: RunFinishIn) -> dict:
        _store().finish_analysis_run(
            run_id,
            status=finish.status,
            token_in=finish.token_in,
            token_out=finish.token_out,
            error=finish.error,
            output_artifact_id=finish.output_artifact_id,
            finished_at=_now(),
        )
        return {"run_id": run_id, "status": finish.status}

    # ---------- artifacts & commit ----------

    @router.post("/api/artifacts")
    def create_artifact(artifact: ArtifactIn) -> dict:
        _store().create_artifact(
            Artifact(
                artifact_id=artifact.artifact_id,
                case_id=artifact.case_id,
                klass=artifact.klass,  # type: ignore[arg-type]
                title=artifact.title,
                report_type=artifact.report_type,  # type: ignore[arg-type]
                created_at=_now(),
            )
        )
        return {"artifact_id": artifact.artifact_id}

    @router.post("/api/artifacts/{artifact_id}/revisions")
    def add_revision(artifact_id: str, revision: RevisionIn) -> dict:
        _store().add_artifact_revision(
            ArtifactRevision(
                revision_id=revision.revision_id,
                artifact_id=artifact_id,
                run_id=revision.run_id,
                content=revision.content,
                created_at=_now(),
            )
        )
        return {"revision_id": revision.revision_id, "status": "draft"}

    @router.get("/api/artifacts/{artifact_id}/revisions")
    def list_revisions(artifact_id: str) -> list[dict]:
        return _store().artifact_revisions(artifact_id)

    @router.post("/api/artifacts/{artifact_id}/commit")
    def commit_artifact(artifact_id: str, commit_in: CommitIn) -> dict:
        """归档唯一入口（HITL 终点）：UserCommit + current 指针事务置换。"""
        store = _store()
        # B6 Challenge 必经门：研究报告提交前，若案内存在 Claim 则必须至少
        # 跑过一次 ChallengeClaim（无 Claim 的案不设此门，避免死锁）。
        art = store.get_artifact_by_revision(commit_in.revision_id)
        if (
            art is not None
            and art.klass == "research_report"
            and art.case_id
            and store.claims_for_case(art.case_id)
            and not store.has_case_run(art.case_id, "challenge", status="succeeded")
        ):
            raise HTTPException(
                422,
                "challenge required: case has claims but no ChallengeClaim run;"
                " run /api/cases/{id}/challenge before committing research_report",
            )
        try:
            result = store.commit_revision(
                commit_in.revision_id,
                UserCommit(
                    commit_id=commit_in.commit_id,
                    revision_id=commit_in.revision_id,
                    user_note=commit_in.user_note,
                    committed_at=_now(),
                ),
            )
        except KeyError as exc:
            raise HTTPException(404, f"revision not found: {commit_in.revision_id}") from exc
        if result["artifact_id"] != artifact_id:
            raise HTTPException(409, "revision does not belong to artifact")
        return result

    @router.get("/api/artifacts")
    def artifacts_list(klass: str | None = None) -> list[dict]:
        """正式档案列表：只返回有 UserCommit 的版本（draft 永不可见）。"""
        return _store().archive_list(klass)

    # ---------- monitors ----------

    @router.post("/api/monitors")
    def create_monitor(monitor: MonitorIn) -> dict:
        _store().create_monitor(
            Monitor(
                monitor_id=monitor.monitor_id,
                target_type=monitor.target_type,  # type: ignore[arg-type]
                target_ref=monitor.target_ref,
                question=monitor.question,
                trigger_conditions=monitor.trigger_conditions,
                window=monitor.window,
                schedule=monitor.schedule,
                case_id=monitor.case_id,
                created_at=_now(),
            )
        )
        return {"monitor_id": monitor.monitor_id, "status": "active"}

    @router.patch("/api/monitors/{monitor_id}")
    def patch_monitor(monitor_id: str, body: MonitorPatchIn) -> dict:
        """修改监测器（HITL 写操作；None 字段不改动）。"""
        if not _store().get_monitor(monitor_id):
            raise HTTPException(404, monitor_id)
        patch = body.model_dump(exclude_none=True)
        if not patch:
            raise HTTPException(422, "empty patch")
        ok = _store().update_monitor(monitor_id, **patch)
        if not ok:
            raise HTTPException(404, monitor_id)
        return {"monitor_id": monitor_id, "updated": sorted(patch)}

    @router.delete("/api/monitors/{monitor_id}")
    def delete_monitor(monitor_id: str) -> dict:
        """删除监测器及其 runs/updates（HITL 删除，连带三表）。"""
        if not _store().get_monitor(monitor_id):
            raise HTTPException(404, monitor_id)
        _store().delete_monitor(monitor_id)
        return {"monitor_id": monitor_id, "deleted": True}

    @router.get("/api/monitors")
    def list_monitors(status: str | None = None) -> list[dict]:
        return [m.model_dump() for m in _store().list_monitors(status)]

    @router.get("/api/monitors/{monitor_id}/runs")
    def monitor_runs(monitor_id: str) -> list[dict]:
        """监测器运行时间线（新→旧，最多 50 条）。"""
        if not _store().get_monitor(monitor_id):
            raise HTTPException(404, monitor_id)
        return _store().monitor_runs_for(monitor_id)

    @router.post("/api/monitors/{monitor_id}/runs")
    def add_monitor_run(monitor_id: str) -> dict:
        run_id = f"mrun-{now_fn().strftime('%Y%m%d%H%M%S%f')}"
        _store().add_monitor_run(
            MonitorRun(run_id=run_id, monitor_id=monitor_id, status="queued", started_at=_now())
        )
        return {"run_id": run_id}

    @router.post("/api/monitors/{monitor_id}/updates")
    def add_monitor_update(monitor_id: str, update: MonitorUpdate) -> dict:
        if update.monitor_id != monitor_id:
            raise HTTPException(409, "monitor_id mismatch")
        _store().add_monitor_update(update)
        return {"update_id": update.update_id, "reviewed": False}

    @router.get("/api/monitors/{monitor_id}/updates")
    def pending_updates(monitor_id: str) -> list[dict]:
        return [u.model_dump() for u in _store().pending_updates(monitor_id)]

    @router.post("/api/monitors/updates/{update_id}/review")
    def review_update(update_id: str, body: ReviewIn | None = None) -> dict:
        """MonitorUpdate HITL 决策：忽略 / 接受为新候选 Case / 加入已有 Case。

        决策与关联 Case 落审计列（迁移 v3），永不静默丢弃；决策动作本身即留痕。
        """
        store = _store()
        update = store.get_update(update_id)
        if update is None:
            raise HTTPException(404, update_id)
        decision = body.decision if body else "ignore"
        case_id = ""
        if decision == "new_case":
            monitor = store.get_monitor(update.monitor_id)
            if monitor is None:
                raise HTTPException(404, f"monitor not found: {update.monitor_id}")
            case_id = f"case-{uuid4().hex[:8]}"
            now = _now()
            store.create_case(
                ResearchCase(
                    case_id=case_id,
                    question=monitor.question,
                    origin="watch_candidate",
                    created_by="watch",
                    created_at=now,
                    updated_at=now,
                )
            )
        elif decision == "join_case":
            if not body or not body.case_id:
                raise HTTPException(422, "join_case requires case_id")
            if not store.get_case(body.case_id):
                raise HTTPException(404, f"case not found: {body.case_id}")
            case_id = body.case_id
        if not store.mark_update_reviewed(update_id, decision=decision, decision_case_id=case_id):
            raise HTTPException(404, update_id)
        return {
            "update_id": update_id,
            "reviewed": True,
            "decision": decision,
            "case_id": case_id,
        }

    @router.post("/api/monitors/{monitor_id}/confirm-snapshot")
    def confirm_snapshot(monitor_id: str) -> dict:
        ok = _store().confirm_monitor_snapshot(monitor_id, _now())
        if not ok:
            raise HTTPException(404, monitor_id)
        return {"monitor_id": monitor_id, "confirmed_at": _now()}

    # ---------- agent runtime (Phase 1 记录层；执行接入在 Phase 2) ----------

    @router.post("/api/agent/threads")
    def create_thread(thread: AgentThread) -> dict:
        _store().create_thread(thread)
        return {"thread_id": thread.thread_id}

    @router.post("/api/agent/runs")
    def create_agent_run(run_in: AgentRunIn) -> dict:
        try:
            context = WorkspaceContext(**run_in.context) if run_in.context else None
        except Exception as exc:
            raise HTTPException(422, f"invalid context: {exc}") from exc
        _store().add_agent_run(
            AgentRun(
                run_id=run_in.run_id,
                thread_id=run_in.thread_id,
                workflow=run_in.workflow,  # type: ignore[arg-type]
                context=context,
                model=run_in.model,
                prompt_version=run_in.prompt_version,
                started_at=_now(),
            )
        )
        return {"run_id": run_in.run_id, "status": "queued"}

    @router.post("/api/agent/runs/{run_id}/finish")
    def finish_agent_run(run_id: str, body: dict) -> dict:
        _store().finish_agent_run(
            run_id,
            status=body.get("status", "succeeded"),
            error=body.get("error", ""),
            checkpoint_ref=body.get("checkpoint_ref", ""),
            finished_at=_now(),
        )
        return {"run_id": run_id}

    # ---------- Agent 面板（只读视图） ----------

    @router.get("/api/agent/threads")
    def list_threads(limit: int = 20) -> list[dict]:
        return [t.model_dump() for t in _store().list_threads(limit)]

    @router.get("/api/agent/runs")
    def list_agent_runs(thread_id: str | None = None, limit: int = 20) -> list[dict]:
        return [r.model_dump() for r in _store().list_agent_runs(thread_id, limit)]

    @router.get("/api/agent/runs/{run_id}/tool-calls")
    def list_tool_calls(run_id: str) -> list[dict]:
        return [c.model_dump() for c in _store().tool_calls_for_run(run_id)]

    @router.get("/api/usage")
    def usage() -> dict:
        store = _store()
        return {"summary": store.usage_summary(), "counts": store.counts()}

    # ---------- HITL ----------

    @router.post("/api/hitl")
    def create_hitl(req: HITLRequest) -> dict:
        _store().create_hitl(req)
        return {"hitl_id": req.hitl_id, "status": "awaiting_user"}

    @router.get("/api/hitl/pending")
    def pending_hitl() -> list[dict]:
        return [h.model_dump() for h in _store().pending_hitl()]

    @router.post("/api/hitl/{hitl_id}/decide")
    def decide_hitl(hitl_id: str, body: HITLDecideIn) -> dict:
        if body.status not in ("approved", "rejected"):
            raise HTTPException(422, "status must be approved/rejected")
        ok = _store().decide_hitl(
            hitl_id,
            status=body.status,
            decided_by="user",
            decided_at=_now(),
            note=body.note,
        )
        if not ok:
            raise HTTPException(404, f"no awaiting hitl: {hitl_id}")
        return {"hitl_id": hitl_id, "status": body.status}

    # ---------- 内部 ----------

    def _runs_index(store: ResearchStore) -> list[dict[str, Any]]:
        rows = store._conn.execute(
            "SELECT run_id, case_id, kind, status, model, prompt_version,"
            " token_in, token_out, error, started_at, finished_at,"
            " output_artifact_id, output_json"
            " FROM analysis_runs ORDER BY started_at DESC LIMIT 200"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # output_json → output（REPORT 模式草稿预览依赖 artifact_id/revision_id）
            raw = d.pop("output_json", None)
            d["output"] = json.loads(raw) if raw else None
            out.append(d)
        return out

    return router


class DissectIn(BaseModel):
    document_revision_id: str


class TranslateIn(BaseModel):
    document_revision_id: str
    target_language: str = "en"


class CompareIn(BaseModel):
    document_revision_ids: list[str]


class ReportIn(BaseModel):
    report_type: str
    title: str
    text: str = ""
    item_key: str = ""


class ChallengeIn(BaseModel):
    claim_id: str


class PressEditionIn(BaseModel):
    """编排报纸：入编对象只认 current committed 版本；发布走 commit 端点（HITL）。"""

    artifact_ids: list[str] = Field(min_length=1)
    title: str = Field(min_length=1)
    note: str = ""


def build_workflow_router(
    workflows_fn: Callable[[], Any],
    research_fn: Callable[[], ResearchStore],
    now_fn: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Phase 2 工作流端点：web → CaseWorkflows（offline 时诚实 abstained）。

    异步协议：POST → 202 {run_id, status=queued} → 后台线程执行 →
    GET /api/analysis-runs/{run_id} 轮询；同 kind+case+input_refs 的活跃运行
    幂等复用；POST /api/analysis-runs/{run_id}/cancel 取消（仅 queued/running）。
    workflows_fn 必须与 research_fn 一样按线程注入（sqlite 连接禁止跨线程）。
    """
    _now = now_fn or (lambda: datetime.now(UTC))
    router = APIRouter()

    def _wf() -> Any:
        return workflows_fn()

    def _store() -> ResearchStore:
        return research_fn()

    def _launch(
        op: str,
        *,
        kind: str,
        case_id: str,
        refs: list[str],
        call,
    ) -> JSONResponse:
        """统一异步启动：幂等复用活跃 run → queued 落库 → 后台线程执行 → 202。"""
        store = _store()
        refs_json = json.dumps(list(refs), ensure_ascii=False, separators=(",", ":"))
        existing = store.active_run(kind, case_id, refs_json)
        if existing is not None:
            return JSONResponse(
                status_code=202,
                content={
                    "run_id": existing["run_id"],
                    "status": existing["status"],
                    "reused": True,
                    "poll": f"/api/analysis-runs/{existing['run_id']}",
                },
            )
        run = AnalysisRun(
            run_id="run-" + _now().strftime("%Y%m%d%H%M%S%f") + "-" + uuid4().hex[:6],
            case_id=case_id,
            kind=kind,  # type: ignore[arg-type]
            status="queued",
            input_refs=list(refs),
            started_at=_now().isoformat(),
        )
        store.add_analysis_run(run)

        def _exec() -> None:
            try:
                call(run.run_id)
            except Exception as exc:  # 兜底：任何未捕获异常落 failed（诚实根因）
                # 线程内重取连接（sqlite 连接禁止跨线程；research_fn 按线程注入）
                try:
                    research_fn().finish_analysis_run(
                        run.run_id,
                        status="failed",
                        error=str(exc) or type(exc).__name__,
                        finished_at=_now().isoformat(),
                    )
                except Exception:  # noqa: BLE001 - 连接级失败不反噬线程
                    pass

        threading.Thread(target=_exec, daemon=True, name=f"wf-{op}-{run.run_id}").start()
        return JSONResponse(
            status_code=202,
            content={
                "run_id": run.run_id,
                "status": "queued",
                "reused": False,
                "poll": f"/api/analysis-runs/{run.run_id}",
            },
        )

    @router.post("/api/cases/{case_id}/dissect")
    def dissect(case_id: str, body: DissectIn) -> JSONResponse:
        return _launch(
            "dissect",
            kind="dissect",
            case_id=case_id,
            refs=[body.document_revision_id],
            call=lambda run_id: asyncio.run(
                _wf().dissect_document(case_id, body.document_revision_id, run_id=run_id)
            ),
        )

    @router.post("/api/cases/{case_id}/translate")
    def translate(case_id: str, body: TranslateIn) -> JSONResponse:
        return _launch(
            "translate",
            kind="translate",
            case_id=case_id,
            refs=[body.document_revision_id],
            call=lambda run_id: asyncio.run(
                _wf().translate_document(
                    body.document_revision_id,
                    case_id=case_id,
                    target_language=body.target_language,
                    run_id=run_id,
                )
            ),
        )

    @router.post("/api/cases/{case_id}/compare")
    def compare(case_id: str, body: CompareIn) -> JSONResponse:
        return _launch(
            "compare",
            kind="compare",
            case_id=case_id,
            refs=list(body.document_revision_ids),
            call=lambda run_id: asyncio.run(
                _wf().compare_sources(case_id, body.document_revision_ids, run_id=run_id)
            ),
        )

    @router.post("/api/cases/{case_id}/report")
    def report(case_id: str, body: ReportIn) -> JSONResponse:
        return _launch(
            "report",
            kind="report",
            case_id=case_id,
            refs=[body.item_key or body.title],
            call=lambda run_id: asyncio.run(
                _wf().build_report(case_id, **body.model_dump(), run_id=run_id)
            ),
        )

    @router.post("/api/cases/{case_id}/challenge")
    def challenge(case_id: str, body: ChallengeIn) -> JSONResponse:
        return _launch(
            "challenge",
            kind="challenge",
            case_id=case_id,
            refs=[body.claim_id],
            call=lambda run_id: asyncio.run(
                _wf().challenge_claim(case_id, body.claim_id, run_id=run_id)
            ),
        )

    @router.get("/api/analysis-runs/{run_id}")
    def get_run(run_id: str) -> dict:
        run = _store().get_analysis_run(run_id)
        if run is None:
            raise HTTPException(404, f"analysis run not found: {run_id}")
        return run

    @router.post("/api/analysis-runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict:
        ok = _store().cancel_analysis_run(run_id, finished_at=_now().isoformat())
        if not ok:
            raise HTTPException(409, f"run not cancellable (finished or absent): {run_id}")
        return {"run_id": run_id, "status": "cancelled"}

    @router.post("/api/press-editions")
    def press_edition(body: PressEditionIn) -> dict:
        """ComposePressEdition：已确认 Artifact → press_edition 草稿（不可直接发布）。"""
        try:
            return _wf().compose_press_edition(body.artifact_ids, title=body.title, note=body.note)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/api/documents/{revision_id:path}/extractions")
    def extractions(revision_id: str) -> list[dict]:
        """逐元素提取（内联 span 偏移，供原文多色标注渲染）。"""
        store = _store()
        rid = unquote(revision_id)
        out = []
        for row in store.extractions_for_revision(rid):
            row["spans"] = [
                {
                    "span_id": s.span_id,
                    "char_start": s.char_start,
                    "char_end": s.char_end,
                    "quote": s.quote,
                }
                for s in store.spans_by_ids(row["span_ids"])
            ]
            out.append(row)
        return out

    @router.post("/api/extractions/{extraction_id}/review")
    def review_extraction(extraction_id: str, body: ExtractionReviewIn) -> dict:
        """元素 HITL 复核：confirmed（认可拆解）/ rejected（人工否决）。"""
        if body.human_status not in ("confirmed", "rejected"):
            raise HTTPException(422, "human_status must be confirmed|rejected")
        if not _store().set_extraction_human_status(extraction_id, body.human_status):
            raise HTTPException(404, extraction_id)
        return {"extraction_id": extraction_id, "human_status": body.human_status}

    @router.get("/api/documents/{revision_id:path}/body")
    def document_body(revision_id: str) -> dict:
        """不可变正文（READ 模式原文色块标注渲染源）。"""
        rid = unquote(revision_id)
        row = _store().get_document_revision(rid)
        if not row:
            raise HTTPException(404, rid)
        return {
            "document_revision_id": rid,
            "source_id": row["source_id"],
            "language": row["language"],
            "canonical_url": row["canonical_url"],
            "body": row["body"],
        }

    return router


# ---------- 运行中心（Collection Plan/Run）----------


class PlanIn(BaseModel):
    """新建采集计划；enabled 恒为 False，启用必须走 enable 端点（HITL 语义）。"""

    source_ids: list[str] = Field(min_length=1)
    mode: Literal["realtime", "scheduled", "backfill"] = "scheduled"
    schedule: str = ""
    time_range: str = ""


class PlanEnableIn(BaseModel):
    """启用/停用计划（蓝图：启用计划属于写操作，需显式确认）。"""

    enabled: bool


class CollectionRunStartIn(BaseModel):
    """登记一次采集执行；真实进度/产出由确定性采集 runner 回写 finish。"""

    run_id: str = ""


class CollectionRunFinishIn(BaseModel):
    """采集运行收尾（status: queued/running/succeeded/failed）。"""

    status: Literal["running", "succeeded", "failed"] = "succeeded"
    progress: float = 1.0
    items_collected: int = 0
    error: str = ""


def build_collection_router(research_fn: Callable[[], ResearchStore]) -> APIRouter:
    """Sources 运行中心端点：采集计划 CRUD（启用 HITL 语义）+ 运行列表/登记/收尾。"""

    router = APIRouter()

    def _store() -> ResearchStore:
        return research_fn()

    @router.get("/api/collection/plans")
    def list_plans() -> list[dict]:
        return [p.model_dump() for p in _store().list_plans()]

    @router.post("/api/collection/plans")
    def create_plan(body: PlanIn) -> dict:
        now = datetime.now().astimezone().isoformat()
        plan = CollectionPlan(
            plan_id=f"plan-{uuid4().hex[:8]}",
            source_ids=body.source_ids,
            mode=body.mode,
            schedule=body.schedule,
            time_range=body.time_range,
            enabled=False,
            created_by="user",
            created_at=now,
        )
        _store().create_collection_plan(plan)
        return plan.model_dump()

    @router.post("/api/collection/plans/{plan_id}/enable")
    def enable_plan(plan_id: str, body: PlanEnableIn) -> dict:
        if not _store().set_plan_enabled(plan_id, body.enabled):
            raise HTTPException(404, f"plan not found: {plan_id}")
        return {"plan_id": plan_id, "enabled": body.enabled}

    @router.get("/api/collection/runs")
    def list_runs(plan_id: str | None = None, limit: int = 50) -> list[dict]:
        return [r.model_dump() for r in _store().list_runs(plan_id=plan_id, limit=limit)]

    @router.post("/api/collection/plans/{plan_id}/runs")
    def start_run(plan_id: str, body: CollectionRunStartIn) -> dict:
        if not any(p.plan_id == plan_id for p in _store().list_plans()):
            raise HTTPException(404, f"plan not found: {plan_id}")
        now = datetime.now().astimezone().isoformat()
        run = CollectionRun(
            run_id=body.run_id or f"crun-{uuid4().hex[:8]}",
            plan_id=plan_id,
            status="running",
            started_at=now,
        )
        _store().add_collection_run(run)
        return run.model_dump()

    @router.post("/api/collection/runs/{run_id}/finish")
    def finish_run(run_id: str, body: CollectionRunFinishIn) -> dict:
        now = datetime.now().astimezone().isoformat()
        _store().finish_collection_run(
            run_id,
            status=body.status,
            progress=body.progress,
            items_collected=body.items_collected,
            error=body.error,
            finished_at=now,
        )
        return {"run_id": run_id, "status": body.status}

    return router
