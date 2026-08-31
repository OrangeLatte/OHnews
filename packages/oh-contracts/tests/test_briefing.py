"""briefing.py 产品语义契约测试（阶段 1-a）。"""

from datetime import UTC, datetime

import pytest
from oh_contracts.briefing import (
    ChangeBrief,
    ChangeDossier,
    CoverageSummary,
    DataFreshness,
    EvidenceCitation,
    EvidenceGap,
    EvidenceSet,
    SubjectRef,
    TechnicalAnnex,
)
from oh_contracts.enums import SourceTier
from pydantic import ValidationError

NOW = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


def _citation(**overrides: object) -> EvidenceCitation:
    base: dict[str, object] = {
        "item_key": "wscn:https://x/1:2026-08-30T01:00:00+00:00",
        "source_id": "wscn",
        "source_tier": SourceTier.FINANCIAL_PRESS,
        "title": "市场报道标题",
        "quote": "官方表示将调整政策。",
        "url": "https://wallstreetcn.com/articles/1",
        "published_at": NOW,
    }
    base.update(overrides)
    return EvidenceCitation(**base)  # type: ignore[arg-type]


def test_change_brief_rejects_short_user_language_fields() -> None:
    """what/why_now/headline 是用户语言主字段：≥8 字门禁。"""
    with pytest.raises(ValidationError):
        ChangeBrief(
            change_id="chg-1",
            kind="narrative_shift",
            headline="短的",
            what="有效观察句七个字以上",
            why_now="有效原因说明七个字以上",
            strength_word="notable",
        )
    brief = ChangeBrief(
        change_id="chg-1",
        kind="narrative_shift",
        headline="美联储叙事从损失转向收益",
        what="近窗报道主导框架由损失迁移至收益",
        why_now="官方与市场语料的框架占比出现明显反转",
        strength_word="notable",
        subjects=[SubjectRef(kind="entity", id="fed", label="美联储")],
    )
    assert brief.urgency == "medium"
    assert brief.subjects[0].label == "美联储"


def test_evidence_citation_quote_bounds_and_optional_url() -> None:
    with pytest.raises(ValidationError):
        _citation(quote="")
    with pytest.raises(ValidationError):
        _citation(quote="x" * 401)
    bare = _citation(url=None, published_at=None)
    assert bare.url is None and bare.published_at is None


def test_evidence_gap_is_first_class_and_never_an_evidence_item() -> None:
    """缺失证据独立建模：不在三桶内，字段语义为「期望但未观测」。"""
    gap = EvidenceGap(
        gap_id="gap-fed-1",
        expectation="缺少官方一手来源对利率路径的直接表态",
        reason="no_primary_source",
        subject=SubjectRef(kind="entity", id="fed", label="美联储"),
        suggestion="等待 FOMC 会议纪要或官员讲话",
    )
    evidence = EvidenceSet(gaps=[gap])
    assert evidence.n_items == 0
    assert evidence.gaps[0].reason == "no_primary_source"
    with pytest.raises(ValidationError):
        EvidenceGap(gap_id="g", expectation="短的", reason="nonsense")


def test_evidence_set_buckets_and_n_items() -> None:
    a = _citation()
    b = _citation(item_key="gdelt:2:2026-08-30T02:00:00+00:00")
    evidence = EvidenceSet(supporting=[a], contradicting=[b])
    assert evidence.n_items == 2
    assert EvidenceSet().n_items == 0


def test_data_freshness_defaults_stale_and_carries_coverage() -> None:
    fresh = DataFreshness(
        as_of=NOW,
        coverage_start=datetime(2026, 8, 24, tzinfo=UTC),
        coverage_end=NOW,
        staleness="fresh",
        note="数据截至 9 月 1 日 06:00 UTC",
    )
    assert fresh.coverage_end == NOW
    assert DataFreshness(as_of=NOW).staleness == "stale"


def test_technical_annex_none_means_unmeasured_not_zero() -> None:
    """诚实边界：不可测指标必须留 None，禁止 0 冒充。"""
    annex = TechnicalAnnex(signal_id="sig-1", engine="offline")
    assert annex.ndi is None and annex.jsd is None
    with pytest.raises(ValidationError):
        TechnicalAnnex(ndi=1.5)
    with pytest.raises(ValidationError):
        TechnicalAnnex(intelligence_score=100.5)


def test_subject_ref_kind_is_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        SubjectRef(kind="company", id="fed", label="美联储")


def test_change_dossier_roundtrip_with_nested_set() -> None:
    dossier = ChangeDossier(
        change_id="chg-fed-1",
        kind="divergence_rise",
        headline="官方与市场对同一事件的解释出现明显分歧",
        what="官方语料强调政策稳健，市场语料聚焦资产价格风险",
        why_now="近窗叙事分歧指数升至近 60 日高位",
        status="contested",
        subjects=[SubjectRef(kind="event", id="ev-fed-20260829", label="Fed 事件")],
        evidence=EvidenceSet(
            supporting=[_citation()],
            gaps=[
                EvidenceGap(
                    gap_id="gap-1",
                    expectation="缺少第二家官方一手来源佐证",
                    reason="single_cluster",
                )
            ],
        ),
        coverage=CoverageSummary(
            n_independent_sources=14,
            n_primary_sources=2,
            time_span_days=1.0,
            languages=["zh", "en"],
            note="14 个独立信源，其中 2 个官方一手",
        ),
        freshness=DataFreshness(as_of=NOW, staleness="aging", note="数据截至 8 月 30 日"),
        technical=TechnicalAnnex(signal_id="sig-1", ndi=0.7, jsd=0.43),
    )
    payload = dossier.model_dump(mode="json")
    assert payload["evidence"]["supporting"][0]["url"].startswith("https://")
    assert payload["coverage"]["n_primary_sources"] == 2
    assert ChangeDossier.model_validate(payload) == dossier


def test_dossier_rejects_unknown_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ChangeDossier(
            change_id="c",
            kind="attention_spike",
            headline="注意力异常聚集的报道潮",
            what="报道量相对基线出现三倍以上跃升",
            why_now="多个此前沉默的信源在同一窗口密集发文",
            status="developing",
            evidence=EvidenceSet(),
            coverage=CoverageSummary(
                n_independent_sources=0,
                n_primary_sources=0,
                time_span_days=0,
                note="暂无可用覆盖统计",
            ),
            freshness=DataFreshness(as_of=NOW),
            rogue_field="must fail",
        )
