"""E3 首页图表组聚合器（纯函数，前端只渲染不拼图）。

G1 信息流密度：bronze 日计数分语言；G3 实体分歧榜：ndi_all 最新点 Top-N；
G4 情绪密度：S1 annotations emotions.expressed 日均值时序。
G2 叙事场复用 /api/change-field（build_change_field），不在本模块重复。
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any


def _lang_of(rec: Any, lang_by_source: dict[str, str]) -> str:
    return lang_by_source.get(rec.source_id, "other")


def build_flow_daily(
    records: list[Any],
    *,
    lang_by_source: dict[str, str],
    now: datetime,
    days: int = 30,
) -> list[dict[str, Any]]:
    """G1：每日文章量按语言分列（仅统计 published_at 已知记录，PIT ts≤now）。"""
    d = max(1, min(days, 120))
    lo = now - timedelta(days=d)
    buckets: dict[str, Counter[str]] = {}
    for r in records:
        ts = r.published_at
        if ts is None or ts > now or ts < lo:
            continue
        day = ts.date().isoformat()
        buckets.setdefault(day, Counter())[_lang_of(r, lang_by_source)] += 1
    return [
        {"date": day, **dict(cnt), "total": sum(cnt.values())}
        for day, cnt in sorted(buckets.items())
    ]


def build_ndi_rank(
    points: list[Any],
    *,
    registry: Any,
    now: datetime,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """G3：实体分歧榜——每实体取最新可测 NDI 点，降序 Top-N（弃权点不计）。"""
    latest: dict[str, Any] = {}
    for p in points:
        if p.status == "abstain" or p.ndi is None or p.ts > now:
            continue
        ev = p.event_id
        cur = latest.get(ev)
        if cur is None or p.ts > cur.ts:
            latest[ev] = p
    rows: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for ev, p in sorted(latest.items(), key=lambda kv: (-kv[1].ndi, kv[0])):
        entity = ev.removeprefix("ev-").rsplit("-", 1)[0]
        if entity in seen_entities:
            continue
        spec = registry.get(entity) if entity else None
        aliases = spec.aliases if spec else []
        label = next(
            (a for a in aliases if any("\u4e00" <= ch <= "\u9fff" for ch in a)),
            entity,
        )
        rows.append(
            {
                "entity": entity,
                "label": label or entity,
                "ndi": round(p.ndi, 4),
                "event_id": ev,
                "ts": p.ts.isoformat(),
                "n_sources": p.n_sources,
            }
        )
        seen_entities.add(entity)
        if len(rows) >= limit:
            break
    return rows


EMOTION_KEYS = (
    "fear",
    "anger",
    "optimism",
    "uncertainty",
    "confidence",
    "urgency",
    "concern",
    "relief",
)


def build_emotion_density(
    annotations: list[dict[str, Any]],
    *,
    now: datetime,
    days: int = 30,
) -> list[dict[str, Any]]:
    """G4：每日情绪密度均值时序（emotions.expressed 每 100 字符命中密度）。"""
    d = max(1, min(days, 120))
    lo = now - timedelta(days=d)
    sums: dict[str, dict[str, float]] = defaultdict(dict)
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    for ann in annotations:
        ts_raw = ann.get("annotated_at")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=now.tzinfo)
        if ts > now or ts < lo:
            continue
        emo = ann.get("emotions") or {}
        expressed = emo.get("expressed") if isinstance(emo, dict) else None
        if not isinstance(expressed, dict):
            continue
        day = ts.date().isoformat()
        agg = sums.setdefault(day, {})
        for k, v in expressed.items():
            if k in EMOTION_KEYS and isinstance(v, (int, float)):
                agg[k] = agg.get(k, 0.0) + float(v)
                day_counts = counts[day]
                day_counts[k] = day_counts.get(k, 0) + 1
    # 日期连续化（用户反馈：缺测日在图上被压缩导致日期轴错位）——
    # 窗口内每日都产出点位，无标注日各情绪键为 None（前端跳线留白，日期对齐日历）。
    out: list[dict[str, Any]] = []
    seen = {day: agg for day, agg in sums.items()}
    cur = (now - timedelta(days=d)).date()
    end = now.date()
    while cur <= end:
        day = cur.isoformat()
        agg = seen.get(day)
        if agg is None:
            out.append({"date": day, **{k: None for k in EMOTION_KEYS}})
        else:
            out.append(
                {
                    "date": day,
                    **{k: round(v / max(1, counts[day].get(k, 0)), 4) for k, v in agg.items()},
                }
            )
        cur += timedelta(days=1)
    # 缺测日补值（用户裁决：不留白断线）——上一有效值 carry-forward；
    # 窗口开头的缺口用下一有效值回填；全窗无读数的键保持 None（诚实）。
    filled: list[dict[str, Any]] = []
    last: dict[str, float] = {}
    for row in out:
        r = dict(row)
        for k in EMOTION_KEYS:
            v = r.get(k)
            if v is None and k in last:
                r[k] = last[k]
            elif v is not None:
                last[k] = v
        filled.append(r)
    nxt: dict[str, float] = {}
    for row in reversed(filled):
        for k in EMOTION_KEYS:
            v = row.get(k)
            if v is None and k in nxt:
                row[k] = nxt[k]
            elif v is not None:
                nxt[k] = v
    return filled


__all__ = ["EMOTION_KEYS", "build_emotion_density", "build_flow_daily", "build_ndi_rank"]
