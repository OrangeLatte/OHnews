"""runner 测试：退避重试 / 幂等去重 / 失败报告 / 健康度自动降级（全离线）。"""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from oh_contracts.enums import SourceTier
from oh_contracts.schemas import SourceMeta
from oh_sources import runner as runner_mod
from oh_sources.base import Draft, SourceAdapter
from oh_sources.runner import FetchResult, collect_all, run_collector

SINCE = datetime(2026, 8, 26, tzinfo=UTC)
UNTIL = datetime(2026, 8, 27, tzinfo=UTC)


class FakeAdapter(SourceAdapter):
    """可控失败次数的假适配器。"""

    def __init__(self, source_id: str = "fake", failures: int = 0) -> None:
        super().__init__(
            SourceMeta(
                source_id=source_id,
                language="zh",
                tier=SourceTier.WIRE,
                credibility_prior=0.5,
                rate_limit_rpm=6000,
            )
        )
        self._failures = failures
        self.calls = 0

    async def fetch(self, since: datetime, until: datetime) -> list[Draft]:
        self.calls += 1
        if self.calls <= self._failures:
            raise RuntimeError("boom")
        return [
            Draft(
                external_id="x1",
                title="标题",
                url="http://e/x1",
                published_at=SINCE,
                body="正文",
            )
        ]


class SpyTracker:
    """FetchLogSink 假实现：可固定 health_score。"""

    def __init__(self, score: float | None = None) -> None:
        self.records: list[dict] = []
        self._score = score

    def record(self, **kw) -> None:
        self.records.append(kw)

    def health_score(self, source_id: str) -> float | None:
        return self._score


class MemWriter:
    """BronzeSink 假实现（内存去重语义与 ParquetBronzeWriter.iter_records 一致）。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def write(self, records) -> int:
        n = 0
        for r in records:
            if r.item_key in self.rows:
                continue
            self.rows[r.item_key] = {"source_id": r.source_id}
            n += 1
        return n

    def iter_records(self, source_id=None):
        for k, v in self.rows.items():
            if source_id is None or v["source_id"] == source_id:
                yield type("R", (), {"item_key": k, "source_id": v["source_id"]})()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_delay: float) -> None:
        return None

    monkeypatch.setattr(runner_mod.asyncio, "sleep", _instant)


def test_retry_then_success_and_dedup():
    """失败 2 次第 3 次成功 → ok；重复采集写 0 行（item_key 幂等）。"""
    adapter = FakeAdapter(failures=2)
    writer = MemWriter()
    result = asyncio.run(run_collector(adapter, writer, since=SINCE, until=UNTIL))
    assert adapter.calls == 3
    assert result.ok and result.n_items == 1 and result.n_written == 1

    result2 = asyncio.run(run_collector(adapter, writer, since=SINCE, until=UNTIL))
    assert result2.ok and result2.n_written == 0


def test_retries_exhausted_reports_root_cause():
    adapter = FakeAdapter(failures=5)
    tracker = SpyTracker()
    result = asyncio.run(
        run_collector(adapter, MemWriter(), since=SINCE, until=UNTIL, tracker=tracker)
    )
    assert not result.ok
    assert "RuntimeError: boom" in (result.error or "")
    assert tracker.records and tracker.records[-1]["ok"] is False


def test_collect_all_degrades_low_health():
    registry = type("R", (), {"all": staticmethod(lambda: [FakeAdapter("bad", failures=0)])})()
    tracker = SpyTracker(score=0.1)
    results = asyncio.run(
        collect_all(registry, MemWriter(), since=SINCE, until=UNTIL, tracker=tracker)
    )
    assert len(results) == 1
    assert not results[0].ok
    assert results[0].error.startswith("degraded")


def test_collect_all_only_whitelist():
    adapter_a, adapter_b = FakeAdapter("a"), FakeAdapter("b")
    registry = type("R", (), {"all": staticmethod(lambda: [adapter_a, adapter_b])})()
    results = asyncio.run(collect_all(registry, MemWriter(), since=SINCE, until=UNTIL, only={"b"}))
    assert [r.source_id for r in results] == ["b"]
    assert adapter_a.calls == 0 and adapter_b.calls == 1


def test_collect_all_fallback_chain_recovers():
    """主源硬失败 → 备用链逐个尝试 → 备用成功：attempts 留痕 + 备用结果入列。"""
    bad = FakeAdapter("primary", failures=99)
    good = FakeAdapter("fb1")
    registry = type(
        "R",
        (),
        {
            "all": staticmethod(lambda: [bad]),
            "fallbacks": lambda self, sid: [good],
        },
    )()
    results = asyncio.run(collect_all(registry, MemWriter(), since=SINCE, until=UNTIL))
    primary = [r for r in results if r.source_id == "primary"][0]
    assert primary.ok and primary.attempts == ("fb1",)
    fb_res = [r for r in results if r.source_id == "fb1"][0]
    assert fb_res.ok and fb_res.n_written == 1


def test_collect_all_fallback_chain_all_fail():
    """主源与备用源皆败：主源 ok=False + attempts 留痕 + 报备用链失败。"""
    bad = FakeAdapter("primary", failures=99)
    fb = FakeAdapter("fb_dead", failures=99)
    registry = type(
        "R",
        (),
        {
            "all": staticmethod(lambda: [bad]),
            "fallbacks": lambda self, sid: [fb],
        },
    )()
    results = asyncio.run(collect_all(registry, MemWriter(), since=SINCE, until=UNTIL))
    primary = [r for r in results if r.source_id == "primary"][0]
    assert not primary.ok
    assert primary.attempts == ("fb_dead",)
    assert "RuntimeError: boom" in (primary.error or "")


def test_collect_all_no_fallbacks_attribute_still_works():
    """registry 无 fallbacks()（鸭子类型兼容旧用法）→ 正常采集。"""
    registry = type("R", (), {"all": staticmethod(lambda: [FakeAdapter("solo")])})()
    results = asyncio.run(collect_all(registry, MemWriter(), since=SINCE, until=UNTIL))
    assert results[0].ok and results[0].attempts == ()


def test_fetch_result_is_json_serializable():
    payload = json.dumps(FetchResult("s", ok=True, n_items=1, n_written=1).__dict__)
    assert '"ok": true' in payload
