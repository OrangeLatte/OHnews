"""CaseWorkflows 测试：offline 诚实降级 / LLM 主路径 / 确定性比较与提交。"""

import asyncio
import hashlib
from typing import Any

import pytest
from oh_agents.case_workflows import CaseWorkflows
from oh_agents.dissection_agent import DissectionOutputP
from oh_agents.report_agent import ReportOutputP
from oh_agents.translation_agent import TranslationOutputP
from oh_contracts.case import ElementExtraction, ResearchCase
from oh_contracts.dissection import DissectionElement, DissectionSpan
from oh_contracts.reports import ReportSection
from oh_llm.config import ModelRef
from oh_storage.research_store import ResearchStore

_TEXT = "美联储官员周三表示，通胀放缓令九月的利率决定保有空间。"


class MultiRouter:
    """按 schema 类型分派的结构化输出桩。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[type] = []

    async def invoke(self, tier: Any, system: str, user: str, schema: type) -> tuple:
        self.calls.append(schema)
        if self.fail:
            raise RuntimeError("all candidates failed")
        if schema is DissectionOutputP:
            out = DissectionOutputP(
                elements=[
                    DissectionElement(
                        element="actor",
                        content="美联储",
                        spans=[DissectionSpan(start=0, end=3)],
                    ),
                    DissectionElement(element="tone", content="谨慎"),
                ]
            )
            return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None
        if schema is TranslationOutputP:
            out = TranslationOutputP(title="Fed hints pause", body="Fed officials said ...")
            return out, ModelRef(provider="zhipu", model_id="glm-5.3-flash"), None
        if schema is ReportOutputP:
            out = ReportOutputP(
                sections=[ReportSection(title="核实结论与证据链", body="叙事分歧上升。")]
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
    with_span = [r for r in rows if r["span_ids"]]
    assert len(with_span) == 1
    spans = store.spans_by_ids(with_span[0]["span_ids"])
    assert spans[0].quote == "美联储"


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
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    out = wf.compare_sources(case_id, [r1, r2])
    assert out["agreement"] == []
    assert "actor" in out["conflicts"]
    assert out["comparison_id"]
    with pytest.raises(ValueError):
        wf.compare_sources(case_id, [r1])


def test_report_then_commit_via_archive(store, case_id) -> None:
    wf = CaseWorkflows(research=store, router=MultiRouter(), now_fn=_NOW)
    out = asyncio.run(wf.build_report(case_id, report_type="veracity", title="核实报告"))
    assert out["status"] == "succeeded"
    assert store.archive_list() == []
    committed = wf.commit_artifact(out["revision_id"], commit_note="人工确认")
    assert committed["artifact_id"] == out["artifact_id"]
    assert committed["superseded_revision_id"] == ""
    archive = store.archive_list()
    assert len(archive) == 1 and archive[0]["current_revision_id"] == out["revision_id"]


def test_challenge_claim_requires_existing_claim(store, case_id) -> None:
    wf = CaseWorkflows(research=store, now_fn=_NOW)
    with pytest.raises(KeyError):
        wf.challenge_claim(case_id, "claim-missing")


def test_compose_press_edition_committed_only(store, case_id) -> None:
    """入编只认 current committed 版本；draft/缺失 artifact 诚实 skipped；发布走 HITL。"""
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
