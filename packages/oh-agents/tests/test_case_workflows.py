"""CaseWorkflows 测试：offline 诚实降级 / LLM 主路径 / 确定性比较与提交。"""

import asyncio
import hashlib
from typing import Any

import pytest
from oh_agents.case_workflows import CaseWorkflows
from oh_agents.dissection_agent import DissectionOutputP
from oh_agents.report_agent import ReportOutputP
from oh_agents.translation_agent import TranslationOutputP
from oh_contracts.case import Claim, ElementExtraction, ResearchCase
from oh_contracts.dissection import DissectionElement, DissectionSpan
from oh_contracts.reports import ReportSection
from oh_llm.config import ModelRef
from oh_storage.research_store import ResearchStore

_TEXT = "美联储官员周三表示，通胀放缓令九月的利率决定保有空间。"


class MultiRouter:
    """按 schema 类型分派的结构化输出桩（记录 prompt 供注入断言）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[type] = []
        self.prompts: list[str] = []

    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        self.calls.append(schema)
        self.prompts.append(user)
        if self.fail:
            raise RuntimeError("all candidates failed")
        if schema is DissectionOutputP:
            out = DissectionOutputP(
                elements=[
                    DissectionElement(
                        element="actor",
                        content="美联储",
                        spans=[DissectionSpan(start=0, end=3)],
                        confidence=1.0,
                    ),
                    DissectionElement(element="tone", content="谨慎", confidence=0.7),
                ]
            )
            return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None
        if schema is TranslationOutputP:
            out = TranslationOutputP(title="Fed hints pause", body="Fed officials said ...")
            return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None
        if schema is ReportOutputP:
            out = ReportOutputP(
                sections=[
                    ReportSection(
                        title="核实结论与证据链",
                        body="叙事分歧上升。",
                        evidence_refs=["ext-r1"],
                    )
                ]
            )
            return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None
        raise AssertionError(f"unexpected schema: {schema}")


@pytest.fixture()
def store(tmp_path):
    return ResearchStore.open(tmp_path / "research.sqlite")


@pytest.fixture()
def case_id(store):
    cid = "case-t1"
    ts = "2026-09-02T00:00:00+00:00"
    store.create_case(
        ResearchCase(case_id=cid, question="美联储九月会暂停加息吗？", created_at=ts, updated_at=ts)
    )
    return cid


def _NOW():
    return "2026-09-02T12:00:00+00:00"


def _add_revision(store, *, rev_id: str, body: str = _TEXT, language: str = "zh") -> str:
    store.add_document_revision(
        rev_id,
        "doc-1",
        source_id="reuters",
        body=body,
        fetched_at="2026-09-02T00:00:00+00:00",
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        language=language,
    )
    return rev_id


def _seed_report_evidence(store, case_id: str) -> None:
    """报告最小证据包：1 篇挂载文档 + 1 条拆解提取（报告 failed 门槛之上）。"""
    rev = _add_revision(store, rev_id="drev-r1")
    store.link_case_document(case_id, rev, _NOW())
    store.add_extraction(
        ElementExtraction(
            extraction_id="ext-r1",
            case_id=case_id,
            document_revision_id=rev,
            element_key="actor",
            normalized_value="美联储",
        )
    )


def test_dissect_offline_abstains_honestly(store, case_id) -> None:
    rev = _add_revision(store, rev_id="drev-1")
    wf = CaseWorkflows(research=store, router=None, now_fn=_NOW)
    out = asyncio.run(wf.dissect_document(case_id, rev))
    assert out["status"] == "abstained"
    assert out["engine"] == "offline"
    assert out["extraction_ids"] == []
    run = store.get_analysis_run(out["run_id"])
    assert run is not None and run["status"] == "abstained"


def test_dissect_llm_persists_extractions_and_spans(store, case_id) -> None:
    rev = _add_revision(store, rev_id="drev-2")
    wf = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    out = asyncio.run(wf.dissect_document(case_id, rev))
    assert out["status"] == "succeeded"
    assert len(out["extraction_ids"]) == 2
    rows = store.extractions_for_revision(rev)
    assert len(rows) == 2
    # confidence 采用模型自报校准值：显式事实 1.0 / 推断类 0.7（不再一律 1.0）
    by_key = {r["element_key"]: r for r in rows}
    assert by_key["actor"]["confidence"] == 1.0
    assert by_key["tone"]["confidence"] == 0.7
    with_span = [r for r in rows if r["span_ids"]]
    assert len(with_span) == 1
    spans = store.spans_by_ids(with_span[0]["span_ids"])
    assert spans[0].quote == "美联储"


def test_dissect_and_report_pass_analysis_locale_to_prompt(store, case_id) -> None:
    """P1-8 analysis_locale：workflow 层透传 → user prompt 含输出语言约束行。"""
    rev = _add_revision(store, rev_id="drev-9")
    store.link_case_document(case_id, rev, _NOW())
    router = MultiRouter()
    wf = CaseWorkflows(research=store, router=router, now_fn=_NOW)
    asyncio.run(wf.dissect_document(case_id, rev, analysis_locale="zh"))
    assert any("分析输出语言" in p and "使用 中文 书写" in p for p in router.prompts)
    # 报告路径：最小证据包之上，analysis_locale="en" → English 约束行
    store.add_extraction(
        ElementExtraction(
            extraction_id="ext-al",
            case_id=case_id,
            document_revision_id=rev,
            element_key="actor",
            normalized_value="美联储",
        )
    )
    n_prompts = len(router.prompts)
    asyncio.run(
        wf.build_report(case_id, report_type="veracity", title="AL 报告", analysis_locale="en")
    )
    report_prompts = router.prompts[n_prompts:]
    assert any("分析输出语言" in p and "使用 English 书写" in p for p in report_prompts)


def test_translate_creates_new_revision_and_is_idempotent(store) -> None:
    rev = _add_revision(store, rev_id="drev-3")
    wf = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    out1 = asyncio.run(wf.translate_document(rev, target_language="en"))
    assert out1["duplicate"] is False
    tr = store.get_document_revision(out1["translation_revision_id"])
    assert tr is not None and tr["language"] == "en"
    out2 = asyncio.run(wf.translate_document(rev, target_language="en"))
    assert out2["duplicate"] is True


def test_compare_sources_matrix(store, case_id) -> None:
    r1 = _add_revision(store, rev_id="drev-4")
    r2 = _add_revision(store, rev_id="drev-5", body="其他正文", language="zh")
    shared = "利率决议维持不变"
    for rev_id, actor in (("drev-4", "美联储"), ("drev-5", "欧洲央行")):
        store.add_extraction(
            ElementExtraction(
                extraction_id=f"ext-{rev_id}",
                case_id=case_id,
                document_revision_id=rev_id,
                element_key="actor",
                normalized_value=actor,
            )
        )
        store.add_extraction(
            ElementExtraction(
                extraction_id=f"ext-topic-{rev_id}",
                case_id=case_id,
                document_revision_id=rev_id,
                element_key="hard_fact",
                normalized_value=shared,
            )
        )
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    out = wf.compare_sources(case_id, [r1, r2])
    # hard_fact 相同 → agreement；actor 不同 → 事实冲突；单侧缺失绝不进两者
    assert "hard_fact" in out["agreement"]
    assert out["conflicts"]["actor"]["classification"] == "fact_conflict"
    assert out["comparison_id"]
    with pytest.raises(ValueError):
        wf.compare_sources(case_id, [r1])


def test_compare_blocks_unrelated_events(store, case_id) -> None:
    r1 = _add_revision(store, rev_id="drev-6")
    r2 = _add_revision(store, rev_id="drev-7", body="完全另一条线", language="en")
    for rev_id, actor, fact in (
        ("drev-6", "美联储", "通胀数据走高"),
        ("drev-7", "加沙卫生部门", "人道主义走廊谈判"),
    ):
        for key, val in (("actor", actor), ("hard_fact", fact)):
            store.add_extraction(
                ElementExtraction(
                    extraction_id=f"ext-{key}-{rev_id}",
                    case_id=case_id,
                    document_revision_id=rev_id,
                    element_key=key,
                    normalized_value=val,
                )
            )
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    out = wf.compare_sources(case_id, [r1, r2])
    assert out["blocked"] is True
    assert out["eligibility"]["same_event_probability"] == "low"
    assert out["comparison_id"] is None
    # 诚实语义：被门槛拦截 = 弃权不执行（abstained，非 succeeded）
    run = store.get_analysis_run(out["run_id"])
    assert run is not None and run["status"] == "abstained"
    # 不落 ComparisonSet：不编造跨事件比较
    row = store._conn.execute(
        "SELECT COUNT(*) FROM comparison_sets WHERE case_id = ?", (case_id,)
    ).fetchone()
    assert row[0] == 0


def test_compare_missing_never_agree(store, case_id) -> None:
    """T5：单侧缺失元素绝不进 agreement/conflicts（missing ≠ agree）。

    种数模式与 test_compare_sources_matrix 一致：actor（相异）+ hard_fact（共享）
    保证通过 eligibility 门槛，implicit_bias 仅文档 A 有 → 必须落在 missing。
    """
    r1 = _add_revision(store, rev_id="drev-m1")
    r2 = _add_revision(store, rev_id="drev-m2", body="另一版本正文", language="zh")
    shared = "利率决议维持不变"
    for rev_id, actor in (("drev-m1", "美联储"), ("drev-m2", "欧洲央行")):
        store.add_extraction(
            ElementExtraction(
                extraction_id=f"ext-actor-{rev_id}",
                case_id=case_id,
                document_revision_id=rev_id,
                element_key="actor",
                normalized_value=actor,
            )
        )
        store.add_extraction(
            ElementExtraction(
                extraction_id=f"ext-fact-{rev_id}",
                case_id=case_id,
                document_revision_id=rev_id,
                element_key="hard_fact",
                normalized_value=shared,
            )
        )
    store.add_extraction(
        ElementExtraction(
            extraction_id="ext-bias-m1",
            case_id=case_id,
            document_revision_id=r1,
            element_key="implicit_bias",
            normalized_value="暗示市场恐慌",
        )
    )
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    out = wf.compare_sources(case_id, [r1, r2])
    assert "implicit_bias" in out["missing"]
    assert "implicit_bias" not in out["agreement"]
    assert "implicit_bias" not in out["conflicts"]


def test_report_then_commit_via_archive(store, case_id) -> None:
    """报告证据包注入真实材料；inputs 可核对；evidence_refs 原样落 content。"""
    _seed_report_evidence(store, case_id)
    store.add_claim(
        Claim(
            claim_id="claim-r1",
            case_id=case_id,
            statement="美联储暗示九月暂停加息",
            kind="factual",
            created_by="user",
            created_at=_NOW(),
        )
    )
    router = MultiRouter()
    wf = CaseWorkflows(research=store, router=router, now_fn=_NOW)
    out = asyncio.run(wf.build_report(case_id, report_type="veracity", title="核实报告"))
    assert out["status"] == "succeeded"
    # prompt 注入真实 Case 材料：source_id / 正文片段 / 主张陈述
    prompt = router.prompts[-1]
    assert "reuters" in prompt
    assert "美联储官员周三" in prompt
    assert "美联储暗示九月暂停加息" in prompt
    # inputs 清单：报告输入与页面 ResearchState 一致
    run = store.get_analysis_run(out["run_id"])
    assert run is not None
    assert run["output"]["inputs"] == {
        "n_documents": 1,
        "n_extractions": 1,
        "n_claims": 1,
        "n_challenge_runs": 0,
        "n_compare_runs": 0,
        "truncated": False,
    }
    assert store.archive_list() == []
    committed = wf.commit_artifact(out["revision_id"], commit_note="人工确认")
    assert committed["artifact_id"] == out["artifact_id"]
    assert committed["superseded_revision_id"] == ""
    archive = store.archive_list()
    assert len(archive) == 1 and archive[0]["current_revision_id"] == out["revision_id"]
    # sections 原样保存（含 evidence_refs）+ content 携带 inputs
    revs = store.artifact_revisions(out["artifact_id"])
    assert revs[0]["content"]["sections"][0]["evidence_refs"] == ["ext-r1"]
    assert revs[0]["content"]["inputs"]["n_documents"] == 1


def test_report_empty_evidence_fails_honestly(store, case_id) -> None:
    """无拆解材料 → run failed 不产 draft（诚实失败，不假 succeeded）。"""
    wf = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    with pytest.raises(RuntimeError, match="报告证据包为空"):
        asyncio.run(wf.build_report(case_id, report_type="veracity", title="核实报告"))
    # 有文档但无拆解元素同样失败
    rev = _add_revision(store, rev_id="drev-r0")
    store.link_case_document(case_id, rev, _NOW())
    with pytest.raises(RuntimeError, match="报告证据包为空"):
        asyncio.run(wf.build_report(case_id, report_type="veracity", title="核实报告"))
    failed = [r for r in store.analysis_runs() if r.kind == "report"]
    assert len(failed) == 2 and all(r.status == "failed" for r in failed)
    row = store._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()
    assert row[0] == 0


def test_report_evidence_pack_covers_runs_and_truncation(store, case_id) -> None:
    """证据包含挑战/比较 run 产物；超长正文截断并标注（truncated=True）。"""
    r1 = _add_revision(store, rev_id="drev-c1")
    r2 = _add_revision(store, rev_id="drev-c2", body="美联储官员暗示九月暂停加息。")
    store.link_case_document(case_id, r1, _NOW())
    store.link_case_document(case_id, r2, _NOW())
    for rev in (r1, r2):
        store.add_extraction(
            ElementExtraction(
                extraction_id=f"ext-{rev}",
                case_id=case_id,
                document_revision_id=rev,
                element_key="hard_fact",
                normalized_value="通胀放缓",
            )
        )
    store.add_claim(
        Claim(
            claim_id="claim-c1",
            case_id=case_id,
            statement="通胀放缓",
            kind="factual",
            created_at=_NOW(),
        )
    )
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    wf.compare_sources(case_id, [r1, r2])
    wf.challenge_claim(case_id, "claim-c1")
    pack, inputs = wf._collect_report_evidence(case_id)
    assert inputs["n_documents"] == 2
    assert inputs["n_extractions"] == 2
    assert inputs["n_claims"] == 1
    assert inputs["n_challenge_runs"] == 1
    assert inputs["n_compare_runs"] == 1
    assert inputs["truncated"] is False
    assert pack["compare_runs"][0]["agreement"] == ["hard_fact"]
    assert pack["challenge_runs"][0]["questions"]
    # 超长正文：截断到 6000 字符并注明
    r3 = _add_revision(store, rev_id="drev-big", body="长" * 7000)
    store.link_case_document(case_id, r3, _NOW())
    store.add_extraction(
        ElementExtraction(
            extraction_id="ext-big",
            case_id=case_id,
            document_revision_id=r3,
            element_key="actor",
            normalized_value="美联储",
        )
    )
    pack, inputs = wf._collect_report_evidence(case_id)
    assert inputs["truncated"] is True
    big = next(d for d in pack["documents"] if d["document_revision_id"] == r3)
    assert len(big["body"]) == 6000
    assert "截断" in big["body_note"]


def test_report_context_integrity_triple_check(store, case_id) -> None:
    """T2 三重校验：declared/serialized/loaded 一致时 succeeded；篡改 declared → failed。"""
    _seed_report_evidence(store, case_id)
    wf = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    out = asyncio.run(wf.build_report(case_id, report_type="veracity", title="一致报告"))
    assert out["status"] == "succeeded"
    run = store.get_analysis_run(out["run_id"])
    assert run is not None
    assert run["output"]["inputs"]["n_documents"] == 1
    assert run["output"]["inputs"]["n_extractions"] == 1

    # 人为篡改 declared（模拟计数漂移）→ context_integrity_failed，run failed 不产 draft
    wf_tampered = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    orig = wf_tampered._collect_report_evidence

    def _tamper(cid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        pack, inputs = orig(cid)
        return pack, {**inputs, "n_extractions": int(inputs["n_extractions"]) + 3}

    wf_tampered._collect_report_evidence = _tamper  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="context_integrity_failed"):
        asyncio.run(wf_tampered.build_report(case_id, report_type="veracity", title="篡改报告"))
    failed = [
        r
        for r in store.analysis_runs()
        if r.status == "failed" and "context_integrity_failed" in r.error
    ]
    assert len(failed) == 1
    assert "declared=" in failed[0].error and "serialized=" in failed[0].error
    # 篡改路径不产新 artifact（不冒充成功）
    row = store._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()
    assert row[0] == 1


def test_challenge_claim_requires_existing_claim(store, case_id) -> None:
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    with pytest.raises(KeyError):
        wf.challenge_claim(case_id, "claim-missing")


def test_compose_press_edition_committed_only(store, case_id) -> None:
    """入编只认 current committed 版本；draft/缺失 artifact 诚实 skipped；发布走 HITL。"""
    _seed_report_evidence(store, case_id)
    wf = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    a = asyncio.run(wf.build_report(case_id, report_type="veracity", title="核实报告"))
    b = asyncio.run(wf.build_report(case_id, report_type="intent", title="意图分析报告"))
    wf.commit_artifact(a["revision_id"])
    # b 保持 draft：不入编
    out = wf.compose_press_edition(
        [a["artifact_id"], b["artifact_id"], "art-missing"], title="本周叙事审查报纸"
    )
    assert out["status"] == "draft" and out["n_sections"] == 1
    assert out["skipped"] == [
        {"artifact_id": b["artifact_id"], "reason": "no_committed_revision"},
        {"artifact_id": "art-missing", "reason": "artifact_not_found"},
    ]
    with pytest.raises(ValueError):
        wf.compose_press_edition(["art-missing"], title="空编排应拒绝")
    # commit → 进入 Archive，klass=press_edition
    wf.commit_artifact(out["revision_id"])
    rows = store.archive_list("press_edition")
    assert len(rows) == 1 and rows[0]["case_id"] == case_id
