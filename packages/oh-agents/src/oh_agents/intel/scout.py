"""Scout 侦查员：信息流异常检测（OSINT 巡逻，超越 TradingAgents 的被动分析）。

三个检测器（纯统计零 IO，供 intel_graph 节点与每日巡逻复用）：
- 量级突刺：滚动窗口 z-score（源/实体日产出突增）
- 新实体涌现：首见实体进入高量级区间（议程生成信号）
- 节奏突变：CUSUM 均值漂移（信源发文节奏异常=失联前兆或立场转向）

产出 ScoutFinding 列表，交由研究总监立案（IntelCase）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "ScoutFinding",
    "detect_cadence_shift",
    "detect_new_entities",
    "detect_volume_spike",
    "volume_zscores",
]


@dataclass(frozen=True)
class ScoutFinding:
    """巡逻发现（研究立案的输入）。"""

    kind: Literal["volume_spike", "new_entity", "cadence_shift"]
    target: str  # 源 id 或实体 id
    score: float  # 异常强度：z 分数 / CUSUM 累积量
    detail: str


def volume_zscores(
    counts: Sequence[int],
    *,
    window: int = 14,
    min_history: int = 7,
) -> list[float | None]:
    """逐日产出量相对前一 window 日的 z 分数（前 min_history 日不足返回 None）。"""
    out: list[float | None] = []
    for i in range(len(counts)):
        lo = max(0, i - window)
        history = counts[lo:i]
        if len(history) < min_history:
            out.append(None)
            continue
        mean = sum(history) / len(history)
        var = sum((c - mean) ** 2 for c in history) / len(history)
        std = math.sqrt(var)
        out.append(None if std == 0 else (counts[i] - mean) / std)
    return out


def detect_volume_spike(
    target: str,
    counts: Sequence[int],
    *,
    threshold: float = 3.0,
    window: int = 14,
    min_history: int = 7,
) -> ScoutFinding | None:
    """最近一日产出量突刺（z ≥ threshold）。"""
    zs = volume_zscores(counts, window=window, min_history=min_history)
    z = zs[-1] if zs else None
    if z is None or z < threshold:
        return None
    return ScoutFinding(
        kind="volume_spike",
        target=target,
        score=round(z, 2),
        detail=f"近 1 日产出 {counts[-1]}，基线 z={z:.2f}（阈值 {threshold}）",
    )


def detect_new_entities(
    known: Mapping[str, float],
    fresh: Mapping[str, float],
    *,
    min_volume: int = 3,
) -> list[ScoutFinding]:
    """首见实体涌现（今日量 ≥ min_volume 且此前从未出现）。

    known/fresh：实体 → 累计出现量（known=巡逻前快照，fresh=当前）。
    """
    out = []
    for entity, vol in sorted(fresh.items(), key=lambda kv: -kv[1]):
        if entity in known:
            continue
        if vol < min_volume:
            continue
        out.append(
            ScoutFinding(
                kind="new_entity",
                target=entity,
                score=float(vol),
                detail=f"新实体首见，当前量 {vol:g}（≥{min_volume}）",
            )
        )
    return out


def detect_cadence_shift(
    target: str,
    intervals_hours: Sequence[float],
    *,
    threshold: float = 5.0,
    drift: float = 0.5,
) -> ScoutFinding | None:
    """发文间隔序列的 CUSUM 均值上移检测（节奏变慢=失联前兆/立场转向）。

    intervals_hours：相邻发文间隔（小时）。CUSUM 高和累积超过 threshold 触发。
    """
    if len(intervals_hours) < 6:
        return None
    baseline = intervals_hours[: len(intervals_hours) // 2]
    mean = sum(baseline) / len(baseline)
    s = 0.0
    peak = 0.0
    for x in intervals_hours[len(baseline) :]:
        s = max(0.0, s + (x - mean) / max(mean, 1e-9) - drift)
        peak = max(peak, s)
    if peak < threshold:
        return None
    return ScoutFinding(
        kind="cadence_shift",
        target=target,
        score=round(peak, 2),
        detail=f"发文间隔 CUSUM={peak:.2f}（基线均值 {mean:.1f}h，阈值 {threshold}）",
    )
