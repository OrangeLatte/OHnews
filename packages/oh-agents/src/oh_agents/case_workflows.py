"""Research Case 工作流编排（Phase 2）：案例分析线 6 个 Workflow 的落地实现。

写路径全部进入 research.sqlite（ResearchStore）；可选 silver store 双写
（upsert_dissection / upsert_report / upsert_translation，复用既有行为）。
LLM 经 router 注入（oh-llm Tier 路由，结构化输出）；router=None 时诚实降级：
graph 产出 engine=offline → AnalysisRun.status=abstained，永不冒充 LLM 产物。
HITL 语义：commit_artifact 只接受已被用户批准后的提交（UserCommit 即留痕），
批准动作由 API 层 /api/hitl/{id}/decide 完成，本层不做静默写。
"""

import datetime as _dt
import hashlib
import json
import uuid
from typing import Any
from uuid import uuid4

from oh_contracts.agent_runtime import ModelUsage
from oh_contracts.artifacts import Artifact, ArtifactRevision, UserCommit
from oh_contracts.case import AnalysisRun, ComparisonSet, ElementExtraction, EvidenceSpan

from .dissection_agent import build_dissection_graph
from .report_agent import build_report_graph
from .translation_agent import build_translation_graph


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


# ArtifactReportType（contracts/artifacts）→ AgentReport.ReportKind（reports）
_REPORT_TYPE_TO_KIND: dict[str, str] = {
    "veracity": "truth",
    "intent": "intent",
    "attribution": "causal",
    "narrative": "narrative",
    "trend": "trend",
    "structured_summary": "summary",
    "econ_financial": "summary",
}


def _default_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_MAX_REPORT_BODY_CHARS = 6000


class CaseWorkflows:
    """案例分析线工作流编排：拆解 → 副本 → 比较 → 报告 → 挑战 → 提交。"""

    def __init__(
        self,
        *,
        research: Any,
        router: Any = None,
        silver: Any = None,
        now_fn: Any = None,
        llm_timeout: float = 90.0,
    ) -> None:
        self._research = research
        self._router = router
        self._silver = silver
        self._now_fn = now_fn or _default_now
        self._llm_timeout = llm_timeout
        self._dissect_graph: Any = None
        self._report_graph: Any = None
        self._translation_graph: Any = None

    # ---------- 基础设施 ----------

    def _now(self) -> str:
        return str(self._now_fn())

    def _graph_now(self) -> _dt.datetime:
        """子图时钟：graph 侧要求 datetime 对象（dissected_at 等字段）。"""
        value = self._now_fn()
        if isinstance(value, str):
            return _dt.datetime.fromisoformat(value)
        return value

    def _rid(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def _begin_run(
        self,
        case_id: str,
        kind: str,
        *,
        engine: str,
        input_refs: list[str] | None = None,
        run_id: str | None = None,
    ) -> AnalysisRun:
        """开始运行；异步协议下 API 层先建 queued run，此处领任务（queued→running）复用。"""
        if run_id:
            existing = self._research.get_analysis_run(run_id)
            if existing is None:
                raise KeyError(f"analysis run not found: {run_id}")
            self._research.start_analysis_run(run_id)
            # output 是 v4 轮询专用富结果列，不属于 AnalysisRun 契约模型
            data = {k: v for k, v in existing.items() if k != "output"}
            return AnalysisRun(**{**data, "status": "running"})
        run = AnalysisRun(
            run_id=self._rid("run"),
            case_id=case_id,
            kind=kind,  # type: ignore[arg-type]
            engine=engine,  # type: ignore[arg-type]
            status="running",
            input_refs=list(input_refs or []),
            started_at=self._now(),
        )
        self._research.add_analysis_run(run)
        return run

    def _finish_run(
        self,
        run: AnalysisRun,
        status: str,
        *,
        error: str = "",
        output_artifact_id: str | None = None,
        usage: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        self._research.finish_analysis_run(
            run.run_id,
            status=status,  # type: ignore[arg-type]
            token_in=int((usage or {}).get("prompt_tokens") or 0),
            token_out=int((usage or {}).get("completion_tokens") or 0),
            error=error,
            output_artifact_id=output_artifact_id,
            output_json=_dumps(output) if output else "",
            finished_at=self._now(),
        )
        if usage:
            self._research.add_model_usage(
                ModelUsage(
                    usage_id=f"usg-{uuid4().hex[:12]}",
                    run_id=run.run_id,
                    provider=str(usage.get("provider") or ""),
                    model=str(usage.get("model") or ""),
                    token_in=int(usage.get("prompt_tokens") or 0),
                    token_out=int(usage.get("completion_tokens") or 0),
                    cost_usd=0.0,
                    ts=self._now(),
                )
            )
        run.status = status  # type: ignore[assignment]

    def _require_revision(self, document_revision_id: str) -> dict:
        rev = self._research.get_document_revision(document_revision_id)
        if rev is None:
            raise KeyError(f"document_revision not found: {document_revision_id}")
        return rev

    # ---------- W1 拆解 DissectDocument ----------

    async def dissect_document(
        self,
        case_id: str,
        document_revision_id: str,
        *,
        analysis_locale: str = "",
        run_id: str | None = None,
    ) -> dict:
        """单篇文档 → 十八元素拆解；元素与 span 落库（human_status=unreviewed）。

        analysis_locale 非空时注入 user prompt 约束分析输出语言（P1-8）。
        """
        rev = self._require_revision(document_revision_id)
        run = self._begin_run(
            case_id,
            "dissect",
            engine="llm",
            input_refs=[document_revision_id],
            run_id=run_id,
        )
        if self._dissect_graph is None:
            self._dissect_graph = build_dissection_graph(
                router=self._router,
                store=self._silver,
                now_fn=self._graph_now,
                llm_timeout=self._llm_timeout,
            )
        state_in: dict[str, Any] = {
            "item_key": document_revision_id,
            "title": str(rev.get("canonical_url") or rev.get("document_id") or ""),
            "text": str(rev.get("body") or ""),
            "language": str(rev.get("language") or ""),
            "publisher": str(rev.get("source_id") or ""),
        }
        if analysis_locale:
            state_in["analysis_locale"] = analysis_locale
        state = await self._dissect_graph.ainvoke(state_in)
        d = state.get("dissection")
        _usage = state.get("usage")
        if d is None:
            error = "; ".join(state.get("errors", [])) or "dissection graph 未产出结果"
            self._finish_run(run, "failed", error=error, usage=_usage)
            raise RuntimeError(error)
        if state.get("llm_failed"):
            final_status, final_error = "abstained", f"llm_failed: {state['llm_failed']}"
        elif d.engine == "offline":
            # persist 层的权威判定（含 llm_empty_output 降级）——run 状态必须与之一致
            final_status = "abstained"
            final_error = "; ".join(state.get("errors", [])) or "llm_empty_output"
        else:
            final_status, final_error = "succeeded", ""
        extraction_ids = self._persist_elements(
            case_id=case_id,
            document_revision_id=document_revision_id,
            text=str(rev.get("body") or ""),
            dissection=d,
            analysis_run_id=run.run_id,
        )
        self._finish_run(
            run,
            final_status,
            error=final_error,
            usage=_usage,
            output={
                "engine": d.engine,
                "extraction_ids": extraction_ids,
                "n_elements": len(d.elements),
            },
        )
        return {
            "run_id": run.run_id,
            "status": final_status,
            "engine": d.engine,
            "extraction_ids": extraction_ids,
            "dissection": d.model_dump(mode="json"),
        }

    def _persist_elements(
        self,
        *,
        case_id: str,
        document_revision_id: str,
        text: str,
        dissection: Any,
        analysis_run_id: str,
    ) -> list[str]:
        """拆解元素 → EvidenceSpan + ElementExtraction（引用具体版本与 run）。

        confidence 优先取模型自报校准值（prompt 约束推断类不得 1.0）；
        模型未自报时维持旧语义：llm=1.0 / offline=0.0。
        """
        ids: list[str] = []
        for el in dissection.elements:
            span_ids: list[str] = []
            for sp in el.spans:
                start, end = int(sp.start), int(sp.end)
                if start >= len(text) or end > len(text) or start >= end:
                    continue
                span = EvidenceSpan(
                    span_id=self._rid("span"),
                    document_revision_id=document_revision_id,
                    char_start=start,
                    char_end=end,
                    quote=text[start:end],
                )
                self._research.add_span(span)
                span_ids.append(span.span_id)
            if el.confidence is not None:
                confidence, uncertainty = float(el.confidence), ""
            else:
                confidence = 1.0 if dissection.engine == "llm" else 0.0
                uncertainty = "" if dissection.engine == "llm" else "offline 兜底拆解"
            extraction = ElementExtraction(
                extraction_id=self._rid("ext"),
                case_id=case_id,
                document_revision_id=document_revision_id,
                element_key=el.element,
                normalized_value=el.content,
                span_ids=span_ids,
                confidence=confidence,
                uncertainty_reason=uncertainty,
                analysis_run_id=analysis_run_id,
            )
            self._research.add_extraction(extraction)
            ids.append(extraction.extraction_id)
        return ids

    # ---------- W2 语言副本 NormalizeLanguage ----------

    async def translate_document(
        self,
        document_revision_id: str,
        *,
        case_id: str = "",
        target_language: str = "en",
        run_id: str | None = None,
    ) -> dict:
        """译文落为新 document_revision（UNIQUE(document_id, content_hash) 幂等）。"""
        rev = self._require_revision(document_revision_id)
        run = self._begin_run(
            case_id,
            "translate",
            engine="llm",
            input_refs=[document_revision_id],
            run_id=run_id,
        )
        if self._translation_graph is None:
            self._translation_graph = build_translation_graph(
                router=self._router, store=self._silver, now_fn=self._graph_now
            )
        state = await self._translation_graph.ainvoke(
            {
                "item_key": document_revision_id,
                "title": str(rev.get("canonical_url") or ""),
                "text": str(rev.get("body") or ""),
                "source_language": str(rev.get("language") or ""),
                "target_language": target_language,
            }
        )
        body_out = str(state.get("body_out") or "")
        _usage = state.get("usage")
        if not body_out:
            error = "; ".join(state.get("errors", [])) or "translation graph 未产出译文"
            self._finish_run(run, "failed", error=error, usage=_usage)
            raise RuntimeError(error)
        new_rev_id = self._rid("drev")
        try:
            self._research.add_document_revision(
                new_rev_id,
                str(rev["document_id"]),
                source_id=str(rev["source_id"]),
                body=body_out,
                fetched_at=self._now(),
                canonical_url=str(rev.get("canonical_url") or ""),
                content_hash=_content_hash(body_out),
                language=target_language,
                published_at=str(rev.get("published_at") or ""),
            )
        except ValueError:
            self._finish_run(
                run,
                "succeeded",
                usage=_usage,
                output={"duplicate": True, "translation_revision_id": ""},
            )
            return {
                "run_id": run.run_id,
                "status": run.status,
                "translation_revision_id": "",
                "duplicate": True,
            }
        self._finish_run(
            run,
            "succeeded",
            usage=_usage,
            output={
                "duplicate": False,
                "translation_revision_id": new_rev_id,
                "target_language": target_language,
            },
        )
        return {
            "run_id": run.run_id,
            "status": run.status,
            "translation_revision_id": new_rev_id,
            "duplicate": False,
            "term_notes": list(state.get("notes") or []),
        }

    # ---------- W3 跨源比较 CompareSources ----------

    def compare_sources(
        self,
        case_id: str,
        document_revision_ids: list[str],
        *,
        note: str = "",
        run_id: str | None = None,
    ) -> dict:
        """确定性比较（rule 引擎，无 LLM）。

        先做事件相关性门槛（eligibility）：实体/主题重叠率过低时拒绝默认
        同事件交叉验证（blocked=True，不落 ComparisonSet——不编造跨事件
        比较），建议用户明确要求跨事件类比后再执行。通过后逐元素四分：
        agreement（全部有值且一致）/ conflicts（事实冲突 vs 叙事差异）/
        missing（任一版本缺值——绝不计入一致或冲突）；summary 由同一份
        分类结果计算，保证与前端统计同源。
        """
        if len(document_revision_ids) < 2:
            raise ValueError("compare_sources 需要至少 2 个 document_revision")
        run = self._begin_run(
            case_id,
            "compare",
            engine="rule",
            input_refs=document_revision_ids,
            run_id=run_id,
        )
        matrix: dict[str, dict[str, str]] = {}
        entity_tokens: list[set[str]] = []
        topic_tokens: list[set[str]] = []
        for rev_id in document_revision_ids:
            for row in self._research.extractions_for_revision(rev_id):
                key = str(row["element_key"])
                matrix.setdefault(key, {})[rev_id] = str(row.get("normalized_value") or "")
                val = str(row.get("normalized_value") or "")
                if key in ("actor", "target") and val:
                    entity_tokens.append({t for t in val.casefold().split() if len(t) > 1})
                if key in ("hard_fact", "topic", "summary") and val:
                    topic_tokens.append({t for t in val.casefold().split() if len(t) > 1})
        n = len(document_revision_ids)

        def _mean_jaccard(sets: list[set[str]]) -> float | None:
            if len(sets) < n:
                return None
            pairs = [
                len(a & b) / max(1, len(a | b)) for i, a in enumerate(sets) for b in sets[i + 1 :]
            ]
            return sum(pairs) / len(pairs) if pairs else None

        ent_score = _mean_jaccard(entity_tokens)
        top_score = _mean_jaccard(topic_tokens)
        scores = [s for s in (ent_score, top_score) if s is not None]
        avg = sum(scores) / len(scores) if scores else 0.0
        if avg >= 0.45:
            probability = "high"
        elif avg < 0.25:
            probability = "low"
        else:
            probability = "medium"
        eligibility = {
            "entity_overlap": ent_score,
            "topic_similarity": top_score,
            "same_event_probability": probability,
            "comparison_mode": (
                "same_event_cross_validation"
                if probability in ("high", "medium")
                else "cross_event_analogy"
            ),
        }
        if probability == "low":
            summary = (
                f"同事件概率低（实体/主题重叠 {avg:.2f}），已跳过默认交叉验证；"
                "如需跨事件类比分析请明确要求。"
            )
            # 诚实语义：被相关性门槛拦截 = 弃权不执行（abstained），不冒充成功
            self._finish_run(
                run,
                "abstained",
                error=summary,
                output={
                    "eligibility": eligibility,
                    "blocked": True,
                    "summary": summary,
                },
            )
            return {
                "run_id": run.run_id,
                "comparison_id": None,
                "summary": summary,
                "blocked": True,
                "eligibility": eligibility,
            }
        agreement: list[str] = []
        conflicts: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        for key, by_rev in matrix.items():
            if len(by_rev) < n:
                # 单侧/多侧缺失：独立类别，绝不计入一致或冲突
                missing.append(key)
                continue
            values = {v.strip().casefold() for v in by_rev.values() if v.strip()}
            if len(values) <= 1:
                agreement.append(key)
            else:
                cls = (
                    "fact_conflict"
                    if key
                    in (
                        "hard_fact",
                        "data_scope",
                        "quant_data",
                        "actor",
                        "target",
                        "action",
                        "timeline",
                    )
                    else "narrative_difference"
                )
                conflicts[key] = {**by_rev, "classification": cls}
        n_fact = sum(1 for c in conflicts.values() if c["classification"] == "fact_conflict")
        n_narr = len(conflicts) - n_fact
        summary = (
            f"{len(agreement)} 一致 / {len(conflicts)} 分歧（事实 {n_fact}·叙事 {n_narr}）/ "
            f"{len(missing)} 缺失，共 {n} 个版本"
        )
        comparison = ComparisonSet(
            comparison_id=self._rid("cmp"),
            case_id=case_id,
            document_revision_ids=list(document_revision_ids),
            created_at=self._now(),
            note=note or summary,
        )
        self._research.add_comparison(comparison)
        self._finish_run(
            run,
            "succeeded",
            output={
                "comparison_id": comparison.comparison_id,
                "summary": summary,
                "agreement": agreement,
                "conflicts": conflicts,
                "missing": missing,
                "eligibility": eligibility,
                "blocked": False,
            },
        )
        return {
            "run_id": run.run_id,
            "comparison_id": comparison.comparison_id,
            "summary": summary,
            "agreement": agreement,
            "conflicts": conflicts,
            "missing": missing,
        }

    # ---------- W4 报告 BuildReport ----------

    def _collect_report_evidence(self, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """收集 Case 全部真实材料作为报告证据包（只含库内可核对的 id 与原文）。

        返回 (evidence_pack, inputs 清单)；inputs 供验收方核对
        「报告输入与页面 ResearchState 一致」，truncated 标记正文截断。
        """
        truncated = False
        documents: list[dict[str, Any]] = []
        n_extractions = 0
        for doc in self._research.case_documents(case_id):
            rev_id = str(doc["document_revision_id"])
            rev = self._research.get_document_revision(rev_id) or {}
            body = str(rev.get("body") or "")
            entry: dict[str, Any] = {
                "document_revision_id": rev_id,
                "source_id": str(doc.get("source_id") or ""),
                "language": str(doc.get("language") or ""),
            }
            if len(body) > _MAX_REPORT_BODY_CHARS:
                truncated = True
                entry["body"] = body[:_MAX_REPORT_BODY_CHARS]
                entry["body_note"] = (
                    f"正文超长已截断：仅前 {_MAX_REPORT_BODY_CHARS} 字符（原文 {len(body)} 字符）"
                )
            else:
                entry["body"] = body
            elements: list[dict[str, Any]] = []
            for row in self._research.extractions_for_revision(rev_id):
                spans = self._research.spans_by_ids(list(row.get("span_ids") or []))
                elements.append(
                    {
                        "extraction_id": str(row["extraction_id"]),
                        "element_key": str(row["element_key"]),
                        "normalized_value": str(row.get("normalized_value") or ""),
                        "confidence": row.get("confidence"),
                        "human_status": str(row.get("human_status") or ""),
                        "span_quotes": [sp.quote for sp in spans],
                    }
                )
            n_extractions += len(elements)
            entry["extraction_elements"] = elements
            documents.append(entry)
        claims = [
            {"claim_id": c.claim_id, "kind": c.kind, "statement": c.statement}
            for c in self._research.claims_for_case(case_id)
        ]
        challenge_runs = [
            {
                "questions": list(out.get("questions") or []),
                "counter_evidence": list(out.get("counter_evidence") or []),
            }
            for out in self._research.run_outputs_for_case(case_id, "challenge")
        ]
        compare_runs = [
            {
                "summary": str(out.get("summary") or ""),
                "agreement": list(out.get("agreement") or []),
                "conflicts": dict(out.get("conflicts") or {}),
                "missing": list(out.get("missing") or []),
                "eligibility": dict(out.get("eligibility") or {}),
                "blocked": bool(out.get("blocked")),
            }
            for out in self._research.run_outputs_for_case(case_id, "compare")
        ]
        pack = {
            "documents": documents,
            "claims": claims,
            "challenge_runs": challenge_runs,
            "compare_runs": compare_runs,
            # 内部一致性锚点：随 evidence_json 序列化，供 build_report 三重校验
            "_counts": {"n_documents": len(documents), "n_extractions": n_extractions},
        }
        inputs = {
            "n_documents": len(documents),
            "n_extractions": n_extractions,
            "n_claims": len(claims),
            "n_challenge_runs": len(challenge_runs),
            "n_compare_runs": len(compare_runs),
            "truncated": truncated,
        }
        return pack, inputs

    async def build_report(
        self,
        case_id: str,
        *,
        report_type: str,
        title: str,
        text: str = "",
        item_key: str = "",
        analysis_locale: str = "",
        run_id: str | None = None,
    ) -> dict:
        """报告 → Artifact(draft revision)；入库需经 commit_artifact（HITL 后）。

        prompt 只注入 Case 库内真实材料（原文/拆解元素/主张/挑战/比较），
        杜绝「报告只看到字段名」的空转；材料为空（无文档或无拆解）→
        run failed 不产 draft（诚实失败，不假 succeeded）。
        analysis_locale 非空时注入 user prompt 约束分析输出语言（P1-8）。
        """
        if report_type not in _REPORT_TYPE_TO_KIND:
            raise ValueError(f"未知 report_type: {report_type}")
        run = self._begin_run(
            case_id,
            "report",
            engine="llm",
            input_refs=[item_key or title],
            run_id=run_id,
        )
        pack, inputs = self._collect_report_evidence(case_id)
        if inputs["n_documents"] == 0 or inputs["n_extractions"] == 0:
            error = "报告证据包为空：无已拆解文档"
            self._finish_run(run, "failed", error=error)
            raise RuntimeError(error)
        # 三重校验（declared / serialized / loaded 同一对象三处来源必须相等）：
        # declared = inputs 清单计数；serialized = 实际放入 evidence_json 的条目数；
        # loaded = json.loads(evidence_json) 后 len 计数。不一致即上下文完整性破坏，
        # run failed 不产 draft（绝不把缺料报告冒充成功）。
        evidence_json = _dumps(pack)
        declared = (int(inputs["n_documents"]), int(inputs["n_extractions"]))
        serialized = (
            len(pack["documents"]),
            sum(len(d["extraction_elements"]) for d in pack["documents"]),
        )
        loaded_pack = json.loads(evidence_json)
        loaded = (
            len(loaded_pack["documents"]),
            sum(len(d["extraction_elements"]) for d in loaded_pack["documents"]),
        )
        if declared != serialized or declared != loaded:
            error = (
                "context_integrity_failed: "
                f"declared={declared}, serialized={serialized}, loaded={loaded}"
            )
            self._finish_run(run, "failed", error=error)
            raise RuntimeError(error)
        if self._report_graph is None:
            self._report_graph = build_report_graph(
                router=self._router, store=self._silver, now_fn=self._graph_now
            )
        state_in: dict[str, Any] = {
            "item_key": item_key or title,
            "kind": _REPORT_TYPE_TO_KIND[report_type],
            "title": title,
            "text": text,
            "dissection_json": "",
            "evidence_json": evidence_json,
        }
        if analysis_locale:
            state_in["analysis_locale"] = analysis_locale
        state = await self._report_graph.ainvoke(state_in)
        report = state.get("report")
        _usage = state.get("usage")
        if report is None:
            error = "; ".join(state.get("errors", [])) or "report graph 未产出结果"
            self._finish_run(run, "failed", error=error, usage=_usage)
            raise RuntimeError(error)
        if state.get("llm_failed"):
            final_status, final_error = "abstained", f"llm_failed: {state['llm_failed']}"
        elif report.engine == "offline":
            final_status = "abstained"
            final_error = "; ".join(state.get("errors", [])) or "llm_empty_output"
        else:
            final_status, final_error = "succeeded", ""
        artifact = Artifact(
            artifact_id=self._rid("art"),
            case_id=case_id,
            klass="research_report",
            title=title,
            report_type=report_type,  # type: ignore[arg-type]
            created_at=self._now(),
        )
        self._research.create_artifact(artifact)
        revision = ArtifactRevision(
            revision_id=self._rid("rev"),
            artifact_id=artifact.artifact_id,
            run_id=run.run_id,
            content={
                "report_id": report.report_id,
                "kind": report.kind,
                "sections": [s.model_dump(mode="json") for s in report.sections],
                "engine": report.engine,
                "model_hint": report.model_hint,
                "inputs": inputs,
            },
            status="draft",
            created_at=self._now(),
        )
        self._research.add_artifact_revision(revision)
        self._finish_run(
            run,
            final_status,
            error=final_error,
            usage=_usage,
            output_artifact_id=artifact.artifact_id,
            output={
                "status": final_status,
                "artifact_id": artifact.artifact_id,
                "revision_id": revision.revision_id,
                "engine": report.engine,
                "inputs": inputs,
            },
        )
        return {
            "run_id": run.run_id,
            "status": final_status,
            "artifact_id": artifact.artifact_id,
            "revision_id": revision.revision_id,
        }

    # ---------- W5 挑战 ChallengeClaim ----------

    def challenge_claim(self, case_id: str, claim_id: str, *, run_id: str | None = None) -> dict:
        """确定性交叉核对（rule 引擎）：同案其他主张 + 提取分歧 → 质询清单。"""
        run = self._begin_run(
            case_id,
            "challenge",
            engine="rule",
            input_refs=[claim_id],
            run_id=run_id,
        )
        claims = self._research.claims_for_case(case_id)
        target = next((c for c in claims if c.claim_id == claim_id), None)
        if target is None:
            self._finish_run(run, "failed", error=f"claim not found: {claim_id}")
            raise KeyError(f"claim not found: {claim_id}")
        others = [c for c in claims if c.claim_id != claim_id]
        span_by_id: dict[str, Any] = {}
        for c in others:
            for sp in self._research.spans_by_ids(c.span_ids):
                span_by_id[sp.span_id] = sp
        counter_evidence = [
            {"span_id": sp.span_id, "quote": sp.quote}
            for sp in span_by_id.values()
            if sp.polarity == "refutes"
        ]
        questions = [
            f"主张「{target.statement[:40]}…」是否有独立第二信源？"
            if len(target.span_ids) < 2
            else "该主张已有多个证据锚，核对引用是否准确。",
        ]
        if counter_evidence:
            questions.append(f"案内存在 {len(counter_evidence)} 条反驳向证据，须逐条核对。")
        self._finish_run(
            run,
            "succeeded",
            output={
                "claim_id": claim_id,
                "questions": questions,
                "counter_evidence": counter_evidence,
                "related_claims": [c.claim_id for c in others],
            },
        )
        return {
            "run_id": run.run_id,
            "claim_id": claim_id,
            "questions": questions,
            "counter_evidence": counter_evidence,
            "related_claims": [c.claim_id for c in others],
        }

    # ---------- W6 提交 CommitArtifact ----------

    def commit_artifact(self, revision_id: str, commit_note: str = "") -> dict:
        """提交 draft → committed（Archive 唯一入口）；HITL 批准在 API 层先行。"""
        run = self._begin_run("", "commit_check", engine="rule", input_refs=[revision_id])
        commit = UserCommit(
            commit_id=self._rid("cmt"),
            revision_id=revision_id,
            user_note=commit_note,
            committed_at=self._now(),
        )
        try:
            result = self._research.commit_revision(revision_id, commit)
        except Exception as exc:  # noqa: BLE001
            self._finish_run(run, "failed", error=str(exc))
            raise
        self._finish_run(run, "succeeded")
        return {"run_id": run.run_id, **result}

    # ---------- W7 编排 ComposePressEdition ----------

    def compose_press_edition(
        self,
        artifact_ids: list[str],
        *,
        title: str,
        note: str = "",
    ) -> dict:
        """筛选已确认 Artifact → 结构化编排 press_edition 草稿（rule 引擎）。

        只取各 Artifact 的 current committed 版本（未 commit 的草稿不入编，
        Archive 语义一致）；无 committed 版本的 artifact 记入 skipped 诚实披露，
        全部不可用则 ValueError。发布仍需走 commit_artifact（HITL 终点）。
        """
        if not title.strip():
            raise ValueError("title 不能为空")
        ordered_ids = list(dict.fromkeys(artifact_ids))
        if not ordered_ids:
            raise ValueError("artifact_ids 不能为空")
        run = self._begin_run("", "report", engine="rule", input_refs=ordered_ids)
        sections: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        case_id = ""
        for aid in ordered_ids:
            artifact = self._research.get_artifact(aid)
            if artifact is None:
                skipped.append({"artifact_id": aid, "reason": "artifact_not_found"})
                continue
            case_id = case_id or artifact.case_id
            rev = next(
                (
                    r
                    for r in self._research.artifact_revisions(aid)
                    if r["revision_id"] == artifact.current_revision_id
                    and r["status"] == "committed"
                ),
                None,
            )
            if rev is None:
                skipped.append({"artifact_id": aid, "reason": "no_committed_revision"})
                continue
            sections.append(
                {
                    "artifact_id": aid,
                    "revision_id": rev["revision_id"],
                    "title": artifact.title,
                    "klass": artifact.klass,
                    "content": rev["content"],
                }
            )
        if not sections:
            error = f"无可入编的已确认版本: skipped={skipped}"
            self._finish_run(run, "failed", error=error)
            raise ValueError(error)
        artifact = Artifact(
            artifact_id=self._rid("art"),
            case_id=case_id,
            klass="press_edition",
            title=title,
            created_at=self._now(),
        )
        self._research.create_artifact(artifact)
        revision = ArtifactRevision(
            revision_id=self._rid("rev"),
            artifact_id=artifact.artifact_id,
            run_id=run.run_id,
            content={"note": note, "sections": sections, "skipped": skipped},
            status="draft",
            created_at=self._now(),
        )
        self._research.add_artifact_revision(revision)
        self._finish_run(run, "succeeded", output_artifact_id=artifact.artifact_id)
        return {
            "run_id": run.run_id,
            "artifact_id": artifact.artifact_id,
            "revision_id": revision.revision_id,
            "status": "draft",
            "n_sections": len(sections),
            "skipped": skipped,
        }
