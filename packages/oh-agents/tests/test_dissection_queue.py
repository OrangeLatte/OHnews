"""B0 筛选队列测试：打分排序/跳过已拆解/入队幂等/裁决流转。"""

import datetime as dt

from oh_agents.dissection_agent import build_queue_suggestions


class _R:
    def __init__(self, item_key: str, source_id: str, title: str, ts: dt.datetime) -> None:
        self.item_key = item_key
        self.source_id = source_id
        self.published_at = ts
        self.normalized = {"title": title}


class _Tier(str):
    pass


class _Reg:
    def match(self, text: str) -> list[str]:
        return ["fed"] if "美联储" in text else []


class _Store:
    def __init__(self) -> None:
        self.queue: dict[str, dict] = {}
        self.dissected: set[str] = set()

    def get_dissection(self, item_key: str) -> dict | None:
        return {"item_key": item_key} if item_key in self.dissected else None

    def queue_upsert(self, item_key: str, *, score: float, reasons: list, created_at: str) -> None:
        self.queue.setdefault(item_key, {"item_key": item_key, "score": score})


_NOW = dt.datetime(2026, 9, 2, 12, 0, tzinfo=dt.UTC)


def test_ranking_and_reasons() -> None:
    recs = [
        _R("k1", "govcn", "美联储官员暗示暂停加息", dt.datetime(2026, 9, 2, 10, 0, tzinfo=dt.UTC)),
        _R("k2", "wscn", "某公司财报点评", dt.datetime(2026, 9, 1, 0, 0, tzinfo=dt.UTC)),
        _R("k3", "gdelt", "美联储 study", dt.datetime(2026, 8, 20, 0, 0, tzinfo=dt.UTC)),
    ]
    tiers = {"govcn": "L1", "wscn": "L3", "gdelt": "L4"}
    out = build_queue_suggestions(recs, tier_map=tiers, registry=_Reg(), now=_NOW, limit=10)
    assert out[0]["item_key"] == "k1"  # L1+新鲜+实体命中
    assert "官方一手来源" in out[0]["reasons"]
    assert any("fed" in r for r in out[0]["reasons"])
    scores = [x["score"] for x in out]
    assert scores == sorted(scores, reverse=True)


def test_skip_dissected_and_store_upsert_idempotent() -> None:
    store = _Store()
    store.dissected.add("k1")
    recs = [
        _R("k1", "govcn", "美联储 A", dt.datetime(2026, 9, 2, 10, 0, tzinfo=dt.UTC)),
        _R("k2", "govcn", "美联储 B", dt.datetime(2026, 9, 2, 9, 0, tzinfo=dt.UTC)),
    ]
    out = build_queue_suggestions(
        recs, tier_map={"govcn": "L1"}, registry=_Reg(), now=_NOW, store=store
    )
    assert [x["item_key"] for x in out] == ["k2"]
    build_queue_suggestions(recs, tier_map={"govcn": "L1"}, registry=_Reg(), now=_NOW, store=store)
    assert len(store.queue) == 1  # 幂等：k2 只入队一次
