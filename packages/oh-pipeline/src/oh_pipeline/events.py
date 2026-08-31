"""事件生成器 v2（M3-S2）：Bronze 文章流 → 实体×日桶 → 同日跨实体语义聚类。

v2 规则（REFACTOR_V2 §3.2）：
- 桶 = 实体 × UTC 日窗（保留 v0 语义），行级 event_id = "ev-{entity}-{YYYYMMDD}"
- 同日跨桶合并：桶文本（title+body 前 500 字符拼接）的词级 5-shingle
  Jaccard ≥ τ（默认 0.30）→ union-find 归簇
- 刻意不做 item_key 交集合并：一篇广覆盖文章会同时命中十余实体，
  桶级交集会让 union-find 雪崩成跨主题巨簇（实测 19 实体塌缩，故弃用）
- cluster_key = "evt-{hash8(日 + 簇内 item_key 排序集)}"：内容寻址，重跑幂等；
  同簇多行共享（KG 共现/簇级视图按 cluster_key 聚合，stances/ndi 外键不变）
- 合格门在簇级：簇内去重文章数 ≥ min_articles 且源数 ≥ min_sources
  （单桶独立成簇时行为与 v0 一致）

已知局限（如实标注）：
- 仅同日合并（"时间近邻"取同日近似）：跨日演化链留待后续版本
- shingle Jaccard 为词面相似：跨语言同事件不合并（crosslang 归 Phase 7 门禁）
- 实体命中靠别名子串匹配，误报会带入事件
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from oh_contracts.schemas import BronzeRecord, EventRecord

from oh_pipeline.entities import EntityRegistry

EventId = str

#: 词级 5-shingle Jaccard 合并阈值（同日跨桶；0.30 由全量数据调参选定，
#: 实测 211 簇 / 8 多实体簇 / 最大 3 实体，无巨簇塌缩）
MERGE_JACCARD_TAU = 0.30
_SHINGLE_K = 5
#: 词数不足（中文未分词/短文本）时退化为字符级 n-gram
_CHAR_SHINGLE_K = 6
#: 参与相似度计算的文本窗口（title + body 前缀，全文会稀释 Jaccard）
_TEXT_WINDOW = 500


@dataclass(frozen=True)
class BuiltEvent:
    """聚合出的候选事件及其覆盖统计。

    cluster_key：所属同日语义簇（多实体桶合并后共享；None 仅当记录未过门？——
    合格输出必属某簇，字段恒非空，保留 Optional 以对齐 EventRecord 契约）。
    """

    event: EventRecord
    n_articles: int
    n_sources: int
    cluster_key: str | None = None


def _utc_day(ts: datetime) -> date:
    return ts.astimezone(UTC).date()


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


def _shingles(text: str, k: int = _SHINGLE_K) -> set[str]:
    words = text.split()
    if len(words) < k + 2:
        # 词级 shingle 失效（CJK 未分词 / 短文本）：字符级 n-gram 兜底
        dense = "".join(words)
        if len(dense) < _CHAR_SHINGLE_K:
            return {dense} if dense else set()
        return {dense[i : i + _CHAR_SHINGLE_K] for i in range(len(dense) - _CHAR_SHINGLE_K + 1)}
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / (len(a) + len(b) - inter)


def _cluster_key(day: date, item_keys: Iterable[str]) -> str:
    digest = hashlib.sha1(
        (f"{day:%Y%m%d}|" + "\x00".join(sorted(set(item_keys)))).encode("utf-8")
    ).hexdigest()
    return f"evt-{digest[:8]}"


class _UnionFind:
    """小规模桶并查集（同日桶数有限，路径压缩即可）。"""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[max(ra, rb)] = min(ra, rb)


class EventBuilder:
    """实体×日桶 + 同日跨实体语义聚类（规则层，无 LLM 参与，可复现）。"""

    def __init__(
        self, registry: EntityRegistry | None = None, *, tau: float = MERGE_JACCARD_TAU
    ) -> None:
        self._registry = registry or EntityRegistry()
        self._tau = tau

    def build(
        self,
        records: Iterable[BronzeRecord],
        *,
        min_articles: int = 3,
        min_sources: int = 2,
    ) -> list[BuiltEvent]:
        """聚类合格簇并展开为成员事件；输出按 (day, entity_id) 确定性排序。"""
        # 1) 建桶（v0 语义）：(day, entity) -> item_key -> (published, title, shingles)
        groups: dict[tuple[date, str], dict[str, tuple[datetime, str, frozenset[str]]]] = (
            defaultdict(dict)
        )
        for rec in records:
            published = rec.published_at
            if published is None:
                continue  # PIT 锚缺失：不进事件（裁决 C 语义）
            title = str(rec.normalized.get("title") or "")
            body = str(rec.normalized.get("body") or "")
            full_text = " ".join((title, body))
            # 相似度窗口仅用于 shingle；实体匹配必须全文（截断会丢长文尾部实体，
            # 导致桶源数下降、事件过不了门——迁移实测 61→9 行丢失的根因）
            window_text = full_text[:_TEXT_WINDOW]
            sh = frozenset(_shingles(window_text))
            for entity_id in self._registry.match(full_text):
                groups[(_utc_day(published), entity_id)].setdefault(
                    rec.item_key, (published, title, sh)
                )

        # 2) 同日跨桶合并：桶 shingle Jaccard ≥ τ（无交集分支，见模块 docstring）
        built: list[BuiltEvent] = []
        by_day: dict[date, list[tuple[str, dict[str, tuple[datetime, str, frozenset[str]]]]]] = (
            defaultdict(list)
        )
        for (day, entity_id), articles in groups.items():
            by_day[day].append((entity_id, articles))

        for day in sorted(by_day):
            buckets = sorted(by_day[day], key=lambda kv: kv[0])
            uf = _UnionFind(len(buckets))
            shingle_cache = [
                frozenset().union(*(sh for _, _, sh in arts.values())) for _, arts in buckets
            ]
            key_sets = [frozenset(arts) for _, arts in buckets]
            for i in range(len(buckets)):
                for j in range(i + 1, len(buckets)):
                    if _jaccard(shingle_cache[i], shingle_cache[j]) >= self._tau:
                        uf.union(i, j)
            clusters: dict[int, list[int]] = defaultdict(list)
            for i in range(len(buckets)):
                clusters[uf.find(i)].append(i)

            # 3) 簇级合格门 + 展开为成员事件
            for members in clusters.values():
                member_keys: set[str] = set()
                for i in members:
                    member_keys |= key_sets[i]
                if len(member_keys) < min_articles:
                    continue
                n_sources = len({k.split(":", 1)[0] for k in member_keys})
                if n_sources < min_sources:
                    continue
                ck = _cluster_key(day, member_keys)
                for i in sorted(members):
                    entity_id, arts = buckets[i]
                    ordered = sorted(arts.items(), key=lambda kv: (kv[1][0], kv[0]))
                    built.append(
                        BuiltEvent(
                            event=EventRecord(
                                event_id=f"ev-{entity_id}-{day:%Y%m%d}",
                                title=ordered[0][1][1] or f"{entity_id} @ {day}",
                                entities=[entity_id],
                                as_of=_day_end(day),
                                cluster_key=ck,
                            ),
                            n_articles=len(arts),
                            n_sources=len({k.split(":", 1)[0] for k in arts}),
                            cluster_key=ck,
                        )
                    )
        built.sort(key=lambda b: (b.event.as_of, b.event.entities[0]))
        return built
