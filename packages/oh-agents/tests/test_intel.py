"""intel_graph 六角色情报循环测试（离线降级路径）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from oh_agents.intel.ach import EvidenceBundle, RedTeamAgent
from oh_agents.intel.cartographer import co_occurrence_network, top_hubs
from oh_agents.intel.chief import ChiefAnalystAgent
from oh_agents.intel.intel_graph import IntelLedger, daily_volume_series, run_intel_cycle
from oh_contracts.intel import IntelReport
from oh_contracts.schemas import EventRecord, NDIPoint

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def _events() -> list[EventRecord]:
    out = []
    for d in range(10, 28):
        day = datetime(2026, 8, d, 23, 0, tzinfo=UTC)
        ents = ["fed", "boe"] if d % 2 else ["fed", "ecb", "boj"]
        out.append(
            EventRecord(
                event_id=f"ev-fed-202608{d:02d}",
                title="t",
                entities=ents,
                as_of=day,
            )
        )
    return out


def _ndi() -> list[NDIPoint]:
    pts = []
    for i, ev in enumerate(_events()):
        pts.append(
            NDIPoint(
                event_id=ev.event_id,
                ts=ev.as_of.isoformat(),
                ndi=0.2 + 0.02 * i,
                ci_low=0.1,
                ci_high=0.4,
                n_sources=3,
                status="ok",
                language="all",
            )
        )
    pts.append(
        NDIPoint(
            event_id="ev-x",
            ts=NOW.isoformat(),
            ndi=None,
            ci_low=None,
            ci_high=None,
            n_sources=1,
            status="abstain",
            language="all",
        )
    )
    return pts


def test_daily_volume_series() -> None:
    dates, series = daily_volume_series(_events(), now=NOW)
    assert len(dates) == 21
    assert sum(series["fed"]) == 18
    assert dates[-1] == "2026-08-28"


def test_cartographer_network() -> None:
    net = co_occurrence_network(_events(), min_weight=2)
    ids = {n["id"] for n in net["nodes"]}
    assert {"fed", "boe", "ecb"} <= ids
    e = next(x for x in net["edges"] if {x["source"], x["target"]} == {"fed", "boe"})
    assert e["weight"] >= 2
    assert top_hubs(net, k=1)[0]["id"] == "fed"


def test_redteam_offline_matrix() -> None:
    bundle = EvidenceBundle(
        scope="t",
        ndi_latest=0.55,
        ndi_absent_ratio=0.6,
        official_share=0.1,
        scout_anomalies=["volume_spike:fed(z=3.2)"],
    )
    m = asyncio.run(RedTeamAgent(None).run(bundle))
    assert len(m.hypotheses) == 3
    # ACH 纪律：至少一个矛盾
    assert any(c.score == -1 for h in m.hypotheses for c in h.cells)
    ranked = m.ranked()
    assert m.conclusion_index == ranked[0][0]


def test_chief_offline_terms() -> None:
    bundle = EvidenceBundle(scope="t", ndi_latest=0.6)
    m = asyncio.run(RedTeamAgent(None).run(bundle))
    kjs, summary = asyncio.run(ChiefAnalystAgent(None).run(bundle, m, 0.85))
    assert 2 <= len(kjs) <= 4
    assert all(k.term in {"likely", "highly_likely", "almost_certain"} for k in kjs)
    assert "非投资建议" in summary


def test_intel_cycle_offline_e2e(tmp_path) -> None:
    rep = asyncio.run(
        run_intel_cycle(
            events=_events(),
            stances_by_event={},
            official_rows=4,
            total_rows=20,
            ndi_points=_ndi(),
            ndi_percentile=0.9,
            now=NOW,
            router=None,
        )
    )
    assert rep.engine == "offline"
    assert rep.ach is not None and len(rep.key_judgments) >= 2
    assert rep.network["nodes"]
    # 往返持久化
    led = IntelLedger(tmp_path / "intel.sqlite")
    led.save(rep)
    back = led.latest()
    assert back[0].report_id == rep.report_id
    assert isinstance(back[0], IntelReport)


def test_intel_ledger_empty(tmp_path) -> None:
    led = IntelLedger(tmp_path / "i.sqlite")
    assert led.latest() == []
