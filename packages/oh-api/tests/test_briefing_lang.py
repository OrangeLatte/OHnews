"""briefing 本地化回归：bucket_evidence reason/claim 双语分支（EN 模式泄漏修复）。"""

import datetime as dt
from types import SimpleNamespace

from oh_api.briefing import bucket_evidence
from oh_contracts.enums import SourceTier, StanceLabel
from oh_contracts.schemas import BronzeRecord
from oh_contracts.signals import Signal, SignalKind

NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)


def _signal() -> Signal:
    return Signal(
        signal_id="sig-1",
        kind=SignalKind.NARRATIVE_SHIFT,
        entity_id="fed",
        title="t",
        what_changed="w",
        strength=50,
        confidence=1.0,
        evidence_ids=["k1"],
        evidence_kind="item_key",
        detected_at=NOW,
        as_of=NOW,
    )


def _bronze() -> BronzeRecord:
    return BronzeRecord(
        source_id="src_zh",
        item_key="k1",
        external_id="k1",
        url_hash="u",
        content_hash="c",
        fetched_at=NOW,
        published_at=NOW,
        raw={},
        normalized={"title": "Fed hikes", "body": "The Fed raises rates again."},
    )


class _Store:
    def stances_asof(self, _as_of: dt.datetime) -> list:
        stance = SimpleNamespace(item_key="k1", stance=StanceLabel.SUPPORTIVE, event_id=None)
        return [stance]


_TIER = {"src_zh": SourceTier.FINANCIAL_PRESS}


def test_bucket_evidence_reason_claim_zh() -> None:
    ev = bucket_evidence(
        _signal(),
        bronze_by_key={"k1": _bronze()},
        store=_Store(),
        tier_map=_TIER,
        as_of=NOW,
        claim="",
        lang="zh",
    )
    cite = ev.supporting[0]
    assert cite.reason == "立场标注为「支持」"
    assert cite.claim == "关于 fed 的narrative_shift信号"


def test_bucket_evidence_reason_claim_en() -> None:
    ev = bucket_evidence(
        _signal(),
        bronze_by_key={"k1": _bronze()},
        store=_Store(),
        tier_map=_TIER,
        as_of=NOW,
        claim="",
        lang="en",
    )
    cite = ev.supporting[0]
    assert cite.reason == 'Stance annotated as "supportive"'
    assert cite.claim == "narrative_shift signal for fed"
